"""FastAPI 依赖：从 `request.app.state` 取出 `main._lifespan` 组装好的单例。

控制者裁定 1：`main` 在 lifespan 里创建 `engine`/`blobs`/`registry`/
`runtime_factory`/`bus`/`turn_runner`，存在 `app.state` 上；这里只是薄薄
一层取值函数，供各路由用 `Depends(...)` 注入，也方便 T8（会话/SSE）复用。
"""

from __future__ import annotations

from fastapi import Request
from sqlalchemy import Engine

from studio.agent.bus import SessionBus
from studio.agent.probe import Probe
from studio.agent.runner import TurnRunner
from studio.agent.runtime import RuntimeFactory
from studio.agent.stage import StageRegistry
from studio.config import Settings
from studio.workspace import BlobStore


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_engine(request: Request) -> Engine:
    return request.app.state.engine


def get_blobs(request: Request) -> BlobStore:
    return request.app.state.blobs


def get_registry(request: Request) -> StageRegistry:
    return request.app.state.registry


def get_runtime_factory(request: Request) -> RuntimeFactory:
    return request.app.state.runtime_factory


def get_bus(request: Request) -> SessionBus:
    return request.app.state.bus


def get_turn_runner(request: Request) -> TurnRunner:
    return request.app.state.turn_runner


def get_probe(request: Request) -> Probe:
    return request.app.state.probe
