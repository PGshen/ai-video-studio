"""`GET /api/projects/{id}/blobs/{sha256}`（TD-21）。

工具结果里的图片（例如 `render_preview` 的关键帧）持久化时只把字节存进
`BlobStore`（内容寻址，天然去重），`turn_events` 表里的 `tool_result.images`
只留 `sha256` 引用——这个端点按需把字节读出来给前端渲染缩略图，不随
SSE/回放把图片字节内联发一遍。

`project_id` 只用来确认项目存在（和其它端点一致的检查），不是说这个 blob
"属于"这个项目：`BlobStore` 本身就是跨项目内容寻址、天然去重的存储（设计
§3.3），同一份图片字节多个项目引用到也只存一份。

Content-Type 从字节本身嗅探，不信任任何调用方传入的值：目前只有
`render_preview` 产出的 PNG 是已知来源，未识别的字节退回
`application/octet-stream`（浏览器仍然能按字节内容渲染 `<img>`）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import Engine

from studio.api.deps import get_blobs, get_engine
from studio.db.repo.projects import get_project
from studio.workspace import BlobStore

router = APIRouter(prefix="/api", tags=["blobs"])


def _sniff_media_type(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return "application/octet-stream"


@router.get("/projects/{project_id}/blobs/{sha256}")
def get_blob_endpoint(
    project_id: str,
    sha256: str,
    engine: Engine = Depends(get_engine),
    blobs: BlobStore = Depends(get_blobs),
) -> Response:
    if get_project(engine, project_id) is None:
        raise HTTPException(status_code=404, detail=f"项目不存在：{project_id}")
    if not blobs.exists(sha256):
        raise HTTPException(status_code=404, detail=f"blob 不存在：{sha256}")
    data = blobs.get(sha256)
    return Response(content=data, media_type=_sniff_media_type(data))
