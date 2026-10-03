import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ReadinessIcon from './ReadinessIcon.vue'

type Props = InstanceType<typeof ReadinessIcon>['$props']

const mountIcon = (props: Props) => mount(ReadinessIcon, { props, attachTo: document.body })

const open = async (w: ReturnType<typeof mountIcon>) => {
  await w.get('[data-testid="readiness"]').trigger('focus')
  await new Promise((resolve) => setTimeout(resolve, 0))
  return document.body.querySelector('[data-slot="tooltip-content"]')
}

describe('ReadinessIcon', () => {
  it('满足定稿条件：绿色图标，aria-label 含镜头数和覆盖率', () => {
    const w = mountIcon({
      readiness: { ready: true, reasons: [] },
      sceneCount: 12,
      coverageLabel: '100%',
      timingError: null,
    })
    const button = w.get('[data-testid="readiness"]')
    expect(button.attributes('data-ready')).toBe('true')
    expect(button.attributes('aria-label')).toBe(
      '可以定稿：12 个镜头全部校验通过并已配音，对齐覆盖率 100%。',
    )
  })

  it('不满足：气泡列出原因和当前覆盖率', async () => {
    const w = mountIcon({
      readiness: { ready: false, reasons: ['2 个镜头还没有配音', '1 个镜头有校验问题'] },
      sceneCount: 5,
      coverageLabel: '70%',
      timingError: null,
    })
    expect(w.get('[data-testid="readiness"]').attributes('data-ready')).toBe('false')
    const tip = await open(w)
    expect(tip?.textContent).toContain('暂不满足定稿条件')
    expect(tip?.textContent).toContain('2 个镜头还没有配音')
    expect(tip?.textContent).toContain('1 个镜头有校验问题')
    expect(tip?.textContent).toContain('当前对齐覆盖率 70%')
  })

  it('timing.json 解析失败：气泡里带上错误', async () => {
    const w = mountIcon({
      readiness: { ready: false, reasons: ['1 个镜头还没有配音'] },
      sceneCount: 1,
      coverageLabel: null,
      timingError: 'bad json',
    })
    const tip = await open(w)
    expect(tip?.textContent).toContain('解析 timing.json 失败：bad json')
    expect(tip?.textContent).not.toContain('当前对齐覆盖率')
  })
})
