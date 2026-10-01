import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ThinkingBody from './ThinkingBody.vue'

describe('ThinkingBody', () => {
  it('次要色：外层给 text-muted-foreground，并让 Markdown 根节点继承它（根节点自带的前景色会盖掉传入的类）', () => {
    const wrapper = mount(ThinkingBody, { props: { text: '想一想' } })

    expect(wrapper.classes()).toContain('text-muted-foreground')
    expect(wrapper.get('.stream-markdown').classes()).toContain('text-inherit!')
  })
})
