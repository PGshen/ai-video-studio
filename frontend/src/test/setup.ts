/**
 * vitest 全局准备：jsdom 没有 `ResizeObserver`，而 reka-ui 的 Tooltip / Splitter 等组件挂载时会用到它。
 * 这里只给一个什么都不做的桩（测试里不关心尺寸变化），不改被测代码。
 */
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = ResizeObserverStub
}
