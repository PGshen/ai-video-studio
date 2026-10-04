"""风格库的磁盘目录存储（ADR 0019；计划 style-library）。

纯能力层（ARCHITECTURE §2 规则 4）：只依赖 `config`，不访问数据库，不知道项目和阶段的存在。
一套风格是 skill 形态的目录——入口 `STYLE.md`（frontmatter 里有 name/description/category）、
`references/*.md`、`exemplars/*.json|md`；正式版本在 `data/styles/<id>/`，草稿在
`data/style-drafts/<id>/`。
"""
