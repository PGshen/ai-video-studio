"""导入音乐（音乐 MV）的 api 部分（子项目 4B 设计 §3）。

- **上传** `POST /api/projects/{id}/music/source`：流式解析 multipart，边读边算哈希、边计数，超过
  `MAX_UPLOAD_BYTES` 立即中止；文件先落在 `.cache/tmp` 下的私有目录，`ffprobe` 确认是音频且时长合
  格后，才原子改名为 `music/source.<ext>` 并清掉别的扩展名的旧源文件。原文件名只用来取扩展名，不参
  与任何路径拼接。不触发分析（分析是 agent 工具的事）。
- 换歌不删 `analysis.*` 与 `range.json`：`analysis.json` 的 `source_hash` 与新文件对不上，
  定稿条件与预览已把这种状态当成 stale/阻塞。

- 歌曲和歌词是 `concept` 的输入：`concept` 定稿后三个端点（上传歌曲、上传/删除歌词）都回 409，
  要先重新打开（TD-81）。检查在碰磁盘之前。

`async def` 端点：忙碌检查与登记"上传中"之间不 `await`（同 `api.music` 的约定）。
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from python_multipart.multipart import MultipartParser, parse_options_header
from sqlalchemy import Engine
from starlette.datastructures import UploadFile

from studio.agent.runner import TurnRunner
from studio.api.deps import get_engine, get_settings, get_turn_runner
from studio.api.music import require_music_project
from studio.api.schemas import MusicLyricsOut, MusicSourceOut
from studio.config import Settings
from studio.db.repo.stages import get_stage
from studio.engines.audio.probe import AudioProbeError, probe_audio
from studio.engines.audio.song import MAX_SONG_SECONDS, MIN_SONG_SECONDS
from studio.stages.common.music_source import SOURCE_EXTENSIONS, find_source
from studio.timeline.lyrics import LYRICS_PATH, MAX_LRC_BYTES, LyricsError, parse_lrc
from studio.workspace import project_dir

if TYPE_CHECKING:
    from python_multipart.multipart import MultipartCallbacks

router = APIRouter(prefix="/api", tags=["music"])

MAX_UPLOAD_BYTES = 150 * 1024 * 1024


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=422, detail=detail)


class _Receiver:
    """multipart 的回调：只接收名为 `file` 的那一段，写入 `target_dir`。"""

    def __init__(self, target_dir: Path) -> None:
        self.target_dir = target_dir
        self.header_name = b""
        self.header_value = b""
        self.headers: dict[bytes, bytes] = {}
        self.ext: str | None = None
        self.path: Path | None = None
        self.size = 0
        self.complete = False
        self.digest = hashlib.sha256()
        self._writer = None
        self._skipping = False

    def on_part_begin(self) -> None:
        self.headers = {}
        self.header_name = b""
        self.header_value = b""
        self._skipping = False

    # A header name or value cut by a read-chunk boundary arrives in several calls: accumulate
    # them and commit the pair in `on_header_end`.
    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self.header_name += data[start:end].lower()

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self.header_value += data[start:end]

    def on_header_end(self) -> None:
        self.headers[self.header_name] = self.header_value
        self.header_name = b""
        self.header_value = b""

    def on_headers_finished(self) -> None:
        _, params = parse_options_header(self.headers.get(b"content-disposition", b""))
        if params.get(b"name") != b"file" or self.path is not None:
            self._skipping = True
            return
        filename = params.get(b"filename", b"").decode("utf-8", errors="replace")
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in SOURCE_EXTENSIONS:
            raise _unprocessable(f"不支持的音频格式，请上传 {' / '.join(SOURCE_EXTENSIONS)}")
        self.ext = ext
        self.path = self.target_dir / f"source.{ext}"
        self._writer = self.path.open("wb")

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        if self._skipping or self._writer is None:
            return
        chunk = data[start:end]
        self.size += len(chunk)
        if self.size > MAX_UPLOAD_BYTES:
            raise _unprocessable(f"文件大小超过上限 {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
        self.digest.update(chunk)
        self._writer.write(chunk)

    def on_part_end(self) -> None:
        if self._writer is not None:
            self.complete = True
        self.close()

    def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            self._writer = None


async def _receive(request: Request, receiver: _Receiver) -> None:
    _, params = parse_options_header(request.headers.get("content-type", ""))
    boundary = params.get(b"boundary")
    if not boundary:
        raise _unprocessable("请求必须是 multipart/form-data，字段名为 file")
    parser = MultipartParser(boundary, _callbacks(receiver))
    try:
        async for chunk in request.stream():
            parser.write(chunk)
        parser.finalize()
    except ValueError as exc:  # MultipartParseError is a ValueError
        raise _unprocessable("请求体不是合法的 multipart/form-data") from exc


def _callbacks(receiver: _Receiver) -> MultipartCallbacks:
    return {
        "on_part_begin": receiver.on_part_begin,
        "on_header_field": receiver.on_header_field,
        "on_header_value": receiver.on_header_value,
        "on_header_end": receiver.on_header_end,
        "on_headers_finished": receiver.on_headers_finished,
        "on_part_data": receiver.on_part_data,
        "on_part_end": receiver.on_part_end,
    }


_BUSY_DETAIL = {
    "song": "项目正在运行中的一轮，请等它结束再上传",
    "lyrics": "项目正在运行中的一轮，请等它结束再改歌词",
}
_FINALIZED_DETAIL = {
    "song": "创意与要求已定稿，请先重新打开再换歌曲",
    "lyrics": "创意与要求已定稿，请先重新打开再改歌词",
}


def _guard_song_request(
    request: Request,
    engine: Engine,
    project_id: str,
    turn_runner: TurnRunner,
    target: Literal["song", "lyrics"],
) -> None:
    """Shared pre-checks of the three song/lyrics endpoints, run before anything touches disk.

    The song and its lyrics are `concept` inputs: once `concept` is finalized they are frozen
    until the user reopens it (a missing `concept` row counts as not finalized)."""
    form, _ = require_music_project(engine, project_id)
    if form != "import":
        raise HTTPException(status_code=404, detail="这个项目没有导入音乐")
    if turn_runner.is_project_busy(project_id):
        raise HTTPException(status_code=409, detail=_BUSY_DETAIL[target])
    concept = get_stage(engine, project_id, "concept")
    if concept is not None and concept.status == "finalized":
        raise HTTPException(status_code=409, detail=_FINALIZED_DETAIL[target])
    if project_id in request.app.state.music_uploads:
        raise HTTPException(status_code=409, detail="这个项目正在上传音乐，请稍后再试")


@router.post("/projects/{project_id}/music/source", response_model=MusicSourceOut)
async def upload_music_source_endpoint(
    project_id: str,
    request: Request,
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
    turn_runner: TurnRunner = Depends(get_turn_runner),
) -> MusicSourceOut:
    _guard_song_request(request, engine, project_id, turn_runner, "song")
    uploading: set[str] = request.app.state.music_uploads
    uploading.add(project_id)
    workdir = project_dir(settings.data_dir, project_id)
    scratch = workdir / ".cache" / "tmp" / f"upload-{uuid4().hex[:8]}"
    receiver = _Receiver(scratch)
    try:
        scratch.mkdir(parents=True)
        try:
            await _receive(request, receiver)
        finally:
            receiver.close()
        if receiver.path is None or receiver.ext is None:
            raise _unprocessable("没有收到文件，字段名应为 file")
        if not receiver.complete:
            raise _unprocessable("上传的数据不完整，请重新上传")
        if receiver.size == 0:
            raise _unprocessable("文件是空的")
        try:
            probe = await probe_audio(receiver.path)
        except AudioProbeError as exc:
            raise _unprocessable(f"不是可用的音频文件：{exc}") from exc
        if not MIN_SONG_SECONDS <= probe.duration <= MAX_SONG_SECONDS:
            raise _unprocessable(
                f"音频时长 {probe.duration:.1f} 秒，"
                f"需要在 {MIN_SONG_SECONDS:g}–{MAX_SONG_SECONDS} 秒之间"
            )
        music = workdir / "music"
        music.mkdir(exist_ok=True)
        final = music / f"source.{receiver.ext}"
        os.replace(receiver.path, final)
        for other in SOURCE_EXTENSIONS:
            if other != receiver.ext:
                (music / f"source.{other}").unlink(missing_ok=True)
        return MusicSourceOut(
            filename=final.name,
            size=receiver.size,
            sha256=receiver.digest.hexdigest(),
            duration=probe.duration,
        )
    finally:
        uploading.discard(project_id)
        shutil.rmtree(scratch, ignore_errors=True)


@router.post("/projects/{project_id}/music/lyrics", response_model=MusicLyricsOut)
async def upload_music_lyrics_endpoint(
    project_id: str,
    request: Request,
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
    turn_runner: TurnRunner = Depends(get_turn_runner),
) -> MusicLyricsOut:
    """Validate an `.lrc` against the uploaded song, then atomically replace `music/lyrics.lrc`."""
    _guard_song_request(request, engine, project_id, turn_runner, "lyrics")
    uploading: set[str] = request.app.state.music_uploads
    uploading.add(project_id)
    workdir = project_dir(settings.data_dir, project_id)
    scratch = workdir / ".cache" / "tmp" / f"lyrics-{uuid4().hex[:8]}"
    try:
        if int(request.headers.get("content-length") or 0) > MAX_LRC_BYTES * 2:
            raise _unprocessable(f"歌词文件超过 {MAX_LRC_BYTES // 1000} KB")
        try:
            form = await request.form()
        except Exception as exc:  # malformed multipart bodies surface as several error types
            raise _unprocessable("请求体不是合法的 multipart/form-data") from exc
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise _unprocessable("没有收到文件，字段名应为 file")
        data = await upload.read(MAX_LRC_BYTES + 1)
        if not data:
            raise _unprocessable("没有收到文件，或者文件是空的")
        song = find_source(workdir / "music")
        if song is None:
            raise _unprocessable("先上传歌曲，再上传歌词")
        try:
            probe = await probe_audio(song)
        except AudioProbeError as exc:
            raise _unprocessable(f"歌曲不可用：{exc}") from exc
        try:
            lines = parse_lrc(data, probe.duration)
        except LyricsError as exc:
            raise _unprocessable(str(exc)) from exc
        stored = data.decode("utf-8-sig").encode("utf-8")
        scratch.mkdir(parents=True)
        staged = scratch / "lyrics.lrc"
        staged.write_bytes(stored)
        final = workdir / LYRICS_PATH
        final.parent.mkdir(exist_ok=True)
        os.replace(staged, final)
        return MusicLyricsOut(lines=len(lines), sha256=hashlib.sha256(stored).hexdigest())
    finally:
        uploading.discard(project_id)
        shutil.rmtree(scratch, ignore_errors=True)


@router.delete("/projects/{project_id}/music/lyrics", status_code=204)
async def delete_music_lyrics_endpoint(
    project_id: str,
    request: Request,
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
    turn_runner: TurnRunner = Depends(get_turn_runner),
) -> Response:
    """Idempotent: deleting lyrics that are not there succeeds too."""
    _guard_song_request(request, engine, project_id, turn_runner, "lyrics")
    (project_dir(settings.data_dir, project_id) / LYRICS_PATH).unlink(missing_ok=True)
    return Response(status_code=204)
