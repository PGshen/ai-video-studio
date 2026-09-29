/**
 * 会话事件里和选题池相关的判断（计划 M4 T10）。头脑风暴 agent 用 `create_idea`/`update_idea`
 * 写卡片；Claude 运行时里工具名带 `mcp__<server>__` 前缀。看到这两个工具的结果就让选题池
 * 查询失效，卡片网格不用手动刷新。
 */
export function isIdeaWriteTool(name: string): boolean {
  return /(^|__)(create|update)_idea$/.test(name)
}
