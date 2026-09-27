# sse-starlette / httpx 流式测试

## ✅ 已验证：`httpx.AsyncClient` + `ASGITransport` 不支持真正的增量流式读取，但直接驱动 ASGI app 可以

日期：2026-09-27（初次验证）／2026-09-27（复审后修正：HTTP 层其实可以测，
补充下面第二条）。来源：实测（`httpx` 0.28.1 源码
`httpx._transports.asgi.ASGITransport.handle_async_request`）+ 本地脚本验证。

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

**但这只是 `httpx.AsyncClient` + `ASGITransport` 这一种客户端实现的限制，
不是"HTTP 层没法测"**（复审指正了初版报告里过于宽泛的结论）：ASGI 的
`app(scope, receive, send)` 调用本身就是"服务端主动 `send()` 推流、随时
`await receive()` 查询客户端有没有断开"的协议，只要自己实现 `receive`/
`send` 两个回调直接驱动 `app`，就能拿到真正逐块到达的响应体，也能在任意
时刻模拟客户端断开——完全不需要额外依赖，`receive()` 在一个
`asyncio.Event` 被置位前一直挂起（模拟"还连着"），置位后返回
`{"type": "http.disconnect"}`。验证脚本：

```python
async def receive():
    await disconnect.wait()
    return {"type": "http.disconnect"}

async def send(message):
    if message["type"] == "http.response.body" and message.get("body"):
        chunks.append(message["body"])  # 每条 SSE 消息在这里就能立刻看到

task = asyncio.create_task(app(scope, receive, send))
await asyncio.wait_for(got_enough_chunks.wait(), 1)  # 真的能中途拿到数据
disconnect.set()
await asyncio.wait_for(task, 1)
```

实测（`EventSourceResponse`，每 10ms `yield` 一条）：`chunks` 在 `app(...)`
调用返回之前就能逐条追加，`disconnect.set()` 之后生成器的 `finally` 立刻
执行——和 `httpx.ASGITransport` 的"全量缓冲"行为完全不同。

**结论**：`backend/tests/api/test_stream.py` 分两层测试：

1. 回放、重放/实时交界处去重、瞬时事件转发、未知事件类型过滤这些核心逻辑，
   直接调用 SSE 端点背后的异步生成器（`studio.api.sessions._stream_events`）
   来测试，绕开 HTTP 层（这一层不需要真实网络协议，直接测生成器最直接）。
2. 响应头、SSE 帧的 `id`/`event`/`data` 格式、`Last-Event-ID`、非法
   `after_seq`/`Last-Event-ID` 的 400、真实断线时的清理、断线重连端到端
   不丢不重——这些需要走真实 ASGI 协议的场景，用上面这种自己驱动
   `app(scope, receive, send)` 的方式测，不经过 `httpx.ASGITransport`。

## ✅ 已验证：`sse_starlette.sse.AppStatus.should_exit_event` 是进程级单例，跨事件循环的测试套件里必须手动重置

日期：2026-09-27。来源：实测（`sse-starlette` 2.4.1 源码
`sse_starlette/sse.py`）。

`EventSourceResponse.__call__` 内部会起一个 `_listen_for_exit_signal` 协程，
第一次运行时惰性创建 `AppStatus.should_exit_event = anyio.Event()`（用来在
收到 uvicorn 的退出信号时唤醒所有还在跑的 SSE 连接）；这个 `Event` 是
**类属性**，创建之后会一直留着，不会随着某一次请求结束而清空。

本项目 `pytest-asyncio` 用 `asyncio_mode = "auto"`、没有单独设置
`asyncio_default_test_loop_scope`，默认是**每个测试函数一个新的事件循环**。
如果测试套件里有两个（或更多）测试各自真正跑到
`EventSourceResponse.__call__`（不是在建立连接前就被 404/400 短路掉），第一
个测试会把 `AppStatus.should_exit_event` 绑定到它自己的事件循环上；第二个
测试用的是一个新的事件循环，`await AppStatus.should_exit_event.wait()` 会
抛 `RuntimeError: <Event ...> is bound to a different event loop`（并且是在
`anyio.create_task_group()` 里，会被包成 `ExceptionGroup`，日志显示成
"Task exception was never retrieved"，容易被误判成别的 bug）。

修复：每个用到 `EventSourceResponse` 的测试前后重置这两个类属性
（`backend/tests/api/test_stream.py` 的 `_reset_sse_starlette_app_status`
自动夹具）：

```python
sse_starlette_sse.AppStatus.should_exit_event = None
sse_starlette_sse.AppStatus.should_exit = False
```

只有第一次真正调用 `_listen_for_exit_signal` 的测试才会创建它，所以只在
`test_stream.py` 里加这个夹具就够了，不需要动全局 `conftest.py`。

## ✅ 已验证：Python 异步生成器完全惰性，`aclose()` 对"从未 `__anext__` 过"的生成器是空操作——但这属于 `SessionBus` 内部实现细节，不需要在 SSE 端点里绕过

日期：2026-09-27（初版）／2026-09-27（控制者裁定后修正：不再用
"预热任务 + `wait_for(shield, timeout=0)`" 这种绕过写法，改成结构性修复，
见下）。来源：实测（CPython 3.12 标准库行为）。

```python
async def gen():
    try:
        yield 1
    finally:
        print("cleanup")  # 只有生成器已经开始执行过（至少 __anext__ 一次）
                            # aclose() 才会触发这里；从未启动过的生成器上
                            # 调用 aclose() 什么都不会发生。
```

这条 Python 行为本身是真的、也确实曾经导致一个真实的订阅者泄漏 bug：如果
一次 SSE 连接的全部数据都能靠"回放已落库事件"满足（没有真正走到订阅总线
拿实时事件那一步），早期实现里代表总线订阅的异步生成器就可能从未被
`__anext__` 过，这时对它调用 `aclose()` 不会触发"把订阅者从列表移除"的
`finally`，订阅永久残留（评审关注点 2 要防的问题）。

初版修复曾经试图用"订阅后立刻用 `ensure_future` + `wait_for(shield,
timeout=0)` 预热一次"绕过这条 Python 行为，但这个写法本身依赖调度顺序
（预热任务有没有真的被调度到第一次真正的挂起点），复审用
`t8probe.py`（脚本见 scratchpad）证明了在"任务被取消得足够早"的情况下预热
同样会失效，本质上只是把"生成器是不是冷的"这个问题往后挪了一层，没有真正
解决。

**结构性修复**（控制者裁定，见 `studio/agent/bus.py`）：`SessionBus.subscribe()`
不再返回裸的异步生成器，而是返回一个 `Subscription` 对象——它的 `close()`
是**同步、幂等**的方法，直接把订阅者从 `_subscribers` 列表里摘掉，完全不
经过任何生成器的 `aclose()`/`finally`，因此不管这个订阅有没有被迭代过、
迭代了几次，调用一次 `close()` 都能正确清理。`_stream_events` 相应地简化成：

```python
subscription = bus.subscribe(session_id)
try:
    ...  # 回放、`async for bus_event in subscription: ...`
finally:
    subscription.close()
```

不再需要任何预热/`shield`/`timeout=0` 之类的调度技巧。
