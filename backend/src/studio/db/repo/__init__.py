"""仓储层：只暴露领域操作，返回值对象（dataclass），不泄露 ORM 实例。

本任务（T2）只实现 T3–T8 会用到的函数：`projects`（项目创建/查询）、
`profiles`（模型配置种子与查询）。`stages`/`sessions`/`turns`/`snapshots`
留给对应任务在需要时新增文件（ARCHITECTURE §2 规则 5）。
"""

from __future__ import annotations
