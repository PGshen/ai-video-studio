import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import EventTable from './EventTable.vue'

describe('EventTable', () => {
  it('lists the events and emits the start of the clicked one', async () => {
    const wrapper = mount(EventTable, {
      props: {
        events: [
          { name: 'kick', kind: 'onset', start: 1.5, end: 1.7 },
          { name: 'riser', kind: 'sweep', start: 5, end: 8 },
        ],
      },
    })
    const rows = wrapper.findAll('[data-testid="event-row"]')
    expect(rows).toHaveLength(2)
    expect(rows[0]!.text()).toContain('瞬发')
    expect(rows[1]!.text()).toContain('扫频')
    expect(rows[1]!.text()).toContain('0:08.0')
    await rows[1]!.trigger('click')
    expect(wrapper.emitted('seek')![0]).toEqual([5])
  })

  it('says so when there are no events', () => {
    const wrapper = mount(EventTable, { props: { events: [] } })
    expect(wrapper.find('[data-testid="events-empty"]').exists()).toBe(true)
    expect(wrapper.find('table').exists()).toBe(false)
  })
})
