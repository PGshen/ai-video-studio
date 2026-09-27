import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { routes } from './router'

function makeRouter() {
  return createRouter({ history: createMemoryHistory(), routes })
}

describe('router', () => {
  it('redirects / to /projects', async () => {
    const router = makeRouter()
    await router.push('/')
    expect(router.currentRoute.value.path).toBe('/projects')
  })

  it('resolves /projects to the projects page', async () => {
    const router = makeRouter()
    await router.push('/projects')
    const matched = router.currentRoute.value.matched
    expect(matched).toHaveLength(1)
    expect(matched[0]?.name).toBe('projects')
  })

  it('resolves /projects/:id/:stage with route params', async () => {
    const router = makeRouter()
    await router.push('/projects/proj-1/topic')
    const route = router.currentRoute.value
    expect(route.name).toBe('project-workbench')
    expect(route.params).toEqual({ id: 'proj-1', stage: 'topic' })
  })

  it('resolves /ideas to the ideas placeholder page', async () => {
    const router = makeRouter()
    await router.push('/ideas')
    expect(router.currentRoute.value.name).toBe('ideas')
  })

  it('resolves /settings to the settings placeholder page', async () => {
    const router = makeRouter()
    await router.push('/settings')
    expect(router.currentRoute.value.name).toBe('settings')
  })
})
