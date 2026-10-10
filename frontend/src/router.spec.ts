import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { routes } from './router'

function makeRouter() {
  return createRouter({ history: createMemoryHistory(), routes })
}

// Each push lazily imports page components; the first transforms took over the default 5 s on
// Windows right after the backend suite (windows-native T9, T11), so the whole file gets 30 s.
describe('router', { timeout: 30_000 }, () => {
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

  it('redirects /settings to the model profiles sub page', async () => {
    const router = makeRouter()
    await router.push('/settings')
    expect(router.currentRoute.value.path).toBe('/settings/models')
    expect(router.currentRoute.value.name).toBe('settings-models')
  })

  it.each([
    ['/settings/models', 'settings-models'],
    ['/settings/voice', 'settings-voice'],
    ['/settings/general', 'settings-general'],
  ])('resolves %s to the %s sub page inside the settings shell', async (path, name) => {
    const router = makeRouter()
    await router.push(path)
    const route = router.currentRoute.value
    expect(route.name).toBe(name)
    expect(route.matched.map((r) => r.name)).toEqual(['settings', name])
    expect(route.meta.title).toBe('设置')
  })

  it('resolves /styles to the style library page', async () => {
    const router = makeRouter()
    await router.push('/styles')
    const route = router.currentRoute.value
    expect(route.name).toBe('styles')
    expect(route.meta.title).toBe('风格库')
  })

  it('keeps the drawer query when opening a style', async () => {
    const router = makeRouter()
    await router.push('/styles?style=abc&mode=edit')
    expect(router.currentRoute.value.query).toEqual({ style: 'abc', mode: 'edit' })
  })

  it('redirects the old /settings/styles address to /styles', async () => {
    const router = makeRouter()
    await router.push('/settings/styles')
    expect(router.currentRoute.value.path).toBe('/styles')
    expect(router.currentRoute.value.name).toBe('styles')
  })
})
