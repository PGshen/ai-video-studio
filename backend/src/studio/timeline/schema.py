"""时间轴数据结构（设计 §4.1、总设计 §4.3）。所有时间是全局秒。

子项目 2 只产出 `duration`、`sections`、`narration`；`grid`、`moments`、`music`、
`lyrics` 是为配乐与歌词预留的层，字段在这里一次定全。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Beat(BaseModel):
    start: float
    end: float
    cue_text: str


class NarrationScene(BaseModel):
    scene_id: str
    start: float
    end: float
    beats: list[Beat] = Field(default_factory=list)


class Section(BaseModel):
    id: str
    label: str
    start: float
    end: float


class Grid(BaseModel):
    bpm: float
    offset: float
    beats: list[float]
    downbeats: list[float]


class Moment(BaseModel):
    section_id: str
    at: str
    t: float
    visual_action: str


class MusicEvent(BaseModel):
    name: str
    kind: str
    start: float
    end: float


class Energy(BaseModel):
    hop: float
    values: list[float]


class LyricLine(BaseModel):
    """One lyric line (mv-lyrics design §3.1); `start`/`end` are seconds."""

    text: str
    start: float
    end: float


class Music(BaseModel):
    file: str
    events: list[MusicEvent] = Field(default_factory=list)
    energy: Energy


class Timeline(BaseModel):
    duration: float
    grid: Grid | None = None
    sections: list[Section] = Field(default_factory=list)
    narration: list[NarrationScene] = Field(default_factory=list)
    moments: list[Moment] = Field(default_factory=list)
    music: Music | None = None
    lyrics: list[Any] = Field(default_factory=list)
