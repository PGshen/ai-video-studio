/** 本机文件管理器的名字，用在「在 X 中打开」按钮上（后端和浏览器在同一台机器上）。 */
export function fileManagerName(platform: string = navigator.userAgent): string {
  if (/Mac/i.test(platform)) return 'Finder'
  if (/Win/i.test(platform)) return '资源管理器'
  return '文件管理器'
}
