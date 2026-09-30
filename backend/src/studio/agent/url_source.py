"""联网的「URL 来源」规则（M4 决策 D3；`native` 模式的 WebFetch 复用，TD-39）。

模型不能凭空构造要抓取的 URL：只能抓**本会话搜索结果里出现过的**，或**用户消息里出现过的**。
被提示注入的网页因此没法诱导模型把工作区文本拼进攻击者的 URL 再抓取。

本模块只放与具体联网工具无关的部分：URL 规范化/提取、「地址本身不该抓」的检查、
搜索结果 URL 的进程内集合（按会话，最多保留 `MAX_TRACKED_SESSIONS` 个会话，最久未用的先淘汰，
TD-38），以及「本会话允许抓哪些 URL」的计算。自建工具 `web_search`/`fetch_url`
（`stages.common.web_tools`）和 Claude 原生 `WebFetch` 的 hook（`claude_scope`）都用它。
"""

from __future__ import annotations

import ipaddress
import re
from collections import OrderedDict
from collections.abc import Iterable
from urllib.parse import urlsplit

from sqlalchemy import Engine

from studio.db.repo import turns as turns_repo

MAX_TRACKED_SESSIONS = 200
"""进程内最多记住多少个会话的搜索结果 URL；超出时淘汰最久没用的会话。"""

_URL_RE = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+", re.IGNORECASE)
_TRAILING_PUNCT = ".,;:!?)]}>，。；：！？、）】》」』"
_LOCAL_SUFFIXES = (".local", ".internal", ".localhost", ".lan", ".home")


def normalize_url(raw: str) -> str | None:
    """规范化 URL 用于比较：小写协议和主机、去 fragment、去路径末尾的 `/`；
    不是带主机的 http(s) URL 时返回 `None`。"""
    try:
        parts = urlsplit(raw.strip())
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not host:
        return None
    netloc = host if ":" not in host else f"[{host}]"
    if parts.port is not None:
        netloc += f":{parts.port}"
    path = parts.path.rstrip("/")
    query = f"?{parts.query}" if parts.query else ""
    return f"{parts.scheme.lower()}://{netloc}{path}{query}"


def refusal_reason(url: str) -> str | None:
    """URL 本身不该抓的原因；可以抓时返回 `None`。"""
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower()
    except ValueError:
        return "地址格式不合法"
    if parts.scheme.lower() not in ("http", "https") or not host:
        return "只能读取 http/https 网页地址"
    if parts.username or parts.password:
        return "地址里不能带账号密码"
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return "不能直接读取 IP 地址"
    if host == "localhost" or host.endswith(_LOCAL_SUFFIXES) or "." not in host:
        return "不能读取本机或内网地址"
    return None


def _trim_url(url: str) -> str:
    """去掉 URL 末尾的句读；末尾的 `)` 只在没有对应 `(` 时才去掉（保留 `Foo_(bar)`）。"""
    while url and url[-1] in _TRAILING_PUNCT:
        if url[-1] == ")" and url.count("(") >= url.count(")"):
            break
        url = url[:-1]
    return url


def urls_in(text: str) -> set[str]:
    """文本里出现的全部 http(s) URL（已规范化）。"""
    found: set[str] = set()
    for match in _URL_RE.findall(text):
        normalized = normalize_url(_trim_url(match))
        if normalized is not None:
            found.add(normalized)
    return found


_SEARCHED: OrderedDict[str, set[str]] = OrderedDict()
"""`session_id -> 本会话搜索返回过的（规范化）URL`，按最近使用排序。"""


def record_searched(session_id: str, urls: Iterable[str]) -> None:
    """记下本会话搜索结果里出现的 URL（入参可以是未规范化的）。"""
    seen = _SEARCHED.setdefault(session_id, set())
    _SEARCHED.move_to_end(session_id)
    for url in urls:
        normalized = normalize_url(url)
        if normalized is not None:
            seen.add(normalized)
    while len(_SEARCHED) > MAX_TRACKED_SESSIONS:
        _SEARCHED.popitem(last=False)


def searched_urls(session_id: str) -> set[str]:
    return set(_SEARCHED.get(session_id, set()))


def reset_searched() -> None:
    """清空进程内的搜索结果集合（测试用，模拟进程重启）。"""
    _SEARCHED.clear()


def allowed_urls(engine: Engine | None, session_id: str | None) -> set[str]:
    """本会话允许抓取的 URL：搜索结果里出现过的 ∪ 用户消息里出现过的。
    用户消息从数据库取，进程重启后仍成立；搜索结果只在内存里，重启后需要重新搜索。"""
    allowed: set[str] = set()
    if session_id is None:
        return allowed
    allowed |= searched_urls(session_id)
    if engine is not None:
        for turn in turns_repo.list_turns(engine, session_id):
            allowed |= urls_in(turn.user_message)
    return allowed
