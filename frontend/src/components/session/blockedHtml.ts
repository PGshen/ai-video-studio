/**
 * 第二层防御：即使原始 HTML 漏过了 `escapeRawHtml`，也在渲染层把危险标签换成惰性占位。
 * `vue-stream-markdown` 的 `components` 属性按标签名映射到 Vue 组件，对任意标签名生效；
 * 占位组件**丢弃所有传入的属性**（`src`、`href`、`style`、`on*` 都不会落到占位元素上）。
 * 这是黑名单，覆盖会加载外部资源、导航、发起提交、改写页面或盖住整页的标签；
 * 第一层（源文本转义）才是主要防线。
 */
import { defineComponent, h, type Component } from 'vue'

const Blocked = defineComponent({
  name: 'BlockedHtml',
  inheritAttrs: false,
  setup() {
    return () => h('span', { 'data-blocked-html': '', class: 'text-muted-foreground' }, '[已屏蔽的 HTML]')
  },
})

const BLOCKED_TAGS = [
  // 加载外部资源 / 嵌入
  'iframe', 'frame', 'frameset', 'object', 'embed', 'applet', 'img', 'picture', 'video', 'audio',
  'source', 'track', 'canvas', 'svg', 'math', 'portal',
  // 导航 / 重定向 / 改写页面
  'meta', 'link', 'base', 'style', 'script', 'noscript', 'template',
  // 提交 / 交互
  'form', 'input', 'textarea', 'select', 'dialog',
  // 可以带 `style` 盖住整页的容器
  'div', 'section', 'article', 'aside', 'nav', 'header', 'footer', 'main', 'center', 'marquee',
  'font',
] as const

export const BLOCKED_COMPONENTS: Record<string, Component> = Object.fromEntries(
  BLOCKED_TAGS.map((tag) => [tag, Blocked]),
)
