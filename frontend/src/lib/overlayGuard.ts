/**
 * `vue-stream-markdown` 的弹层（外链确认、图片放大等）会 teleport 到 body 下的 `#stream-markdown-overlay`，
 * 不在 reka-ui 模态内容之内：模态打开时 body 是 `pointer-events: none`，且在弹层上的点击会被判定为「外部交互」
 * 而关掉抽屉/对话框，导致弹层里的按钮点不动。模态内容用这个函数忽略落在弹层里的外部交互。
 */
const OVERLAY_SELECTOR = '#stream-markdown-overlay'

export function ignoreMarkdownOverlay(event: { target?: EventTarget | null, detail?: { originalEvent?: Event }, preventDefault: () => void }): void {
  const target = event.detail?.originalEvent?.target ?? event.target
  if (target instanceof Element && target.closest(OVERLAY_SELECTOR) !== null)
    event.preventDefault()
}
