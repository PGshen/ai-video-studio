# sse-starlette / httpx 流式测试

## ✅ 已验证：`httpx.AsyncClient` + `ASGITransport` 不支持真正的增量流式读取

日期：2026-09-27。来源：实测（`httpx` 0.28.1 源码 `httpx._transports.asgi.ASGITransport.handle_async_request`）+ 本地脚本验证。

`ASGITransport.handle_async_request` 会把整个 `await self.app(scope, receive, send)`
跑到完成（收集所有 `send()` 传来的 `body` 到一个列表里，直到某次
`more_body=False`）才返回 `Response`。也就是说：

- 对于一个**会自己结束**的 ASGI 响应（普通 REST 接口），`client.stream()`
  看起来能正常工作，因为整个响应本来就很快跑完。
- 对于一个**不会自己结束**的流（比如本项目 `GET /sessions/{id}/stream`：
  只要客户端不断开就会一直转发总线事件），`await self.app(...)` 永远不会
  返回，`client.stream()`/`client.get()` 会一直挂起，直到外部
  `asyncio.wait_for` 超时或者调用方取消对应的 `asyncio.Task`——**在此之前
  拿不到任何中间数据**，因为数据是在 transport 内部缓冲的，只有整个调用
  返回之后才会被封装成 `Response` 交还给上层。

实测脚本（简化版）：起一个每 50ms `yield` 一条事件的 `EventSourceResponse`，
用 `AsyncClient(transport=ASGITransport(app=app))` 读取，即使只想要前几条
消息也会阻塞满 `asyncio.wait_for` 的超时时间，取消后生成器的 `finally` 才
执行。

**影响**：测试"断线重连、不丢不重"这类需要中途拿到部分数据的场景，不能
指望通过 `httpx.AsyncClient` + `ASGITransport` 的 `client.stream()` 拿到
真正的增量数据。本项目的做法（`backend/tests/api/test_stream.py`）：

1. 回放、重放/实时交界处去重、瞬时事件转发等核心逻辑，直接调用 SSE 端点
   背后的异步生成器（`studio.api.sessions._stream_events`）来测试，绕开
   HTTP 层。
2. 断线时的清理（总线订阅是否被正确关闭），用真实 HTTP 请求包一层
   `asyncio.Task`，通过 `task.cancel()` 模拟客户端断开（`asyncio` 任务取消
   在等待点抛 `CancelledError`，效果等价于 ASGI 服务器检测到连接断开），
   验证走完整依赖注入链路后 `SessionBus.subscriber_count` 归零。

## ✅ 已验证：Python 异步生成器完全惰性，`aclose()` 对"从未 `__anext__`
过"的生成器是空操作

日期：2026-09-27。来源：实测（CPython 3.12 标准库行为）。

```python
async def gen():
    try:
        yield 1
    finally:
        print("cleanup")  # 只有生成器已经开始执行过（至少 __anext__ 一次）
                            # aclose() 才会触发这里；从未启动过的生成器上
                            # 调用 aclose() 什么都不会发生。
```

对 SSE 端点的影响：如果一次连接的全部数据都能靠"回放已落库事件"满足
（没有真正走到订阅总线拿实时事件那一步），那么代表总线订阅的内层异步
生成器可能从未被 `__anext__` 过；这时直接对它调用 `aclose()`
不会触发 `SessionBus._pump` 里"把订阅者从列表移除"的清理逻辑，订阅会
永久残留（正是评审关注点 2 要避免的订阅者泄漏）。

修复方式（`studio.api.sessions._stream_events`）：订阅总线后立刻用
`asyncio.ensure_future` 把"取下一条实时事件"这个协程包成任务并调度，再用
`await asyncio.wait_for(asyncio.shield(task), timeout=0)` 给它恰好一次
调度机会——足够让它推进到自己真正的挂起点（`_pump` 内部
`await _has_data.wait()`），但不会等它真的产出事件；`shield` 防止这次
`timeout=0` 的超时连带取消这个任务本身。这样无论回放阶段消费了几条就
断线，收尾时取消的都是一个已经真正开始执行的任务，取消才能正确传播到
`_pump` 的 `finally`。
