import { defineConfig, mergeConfig } from 'vite'
import { defineConfig as defineVitestConfig } from 'vitest/config'
import viteConfig from './vite.config.ts'

export default mergeConfig(
  defineConfig(viteConfig),
  defineVitestConfig({
    test: {
      environment: 'jsdom',
      globals: false,
      setupFiles: ['src/test/setup.ts'],
      include: ['src/**/*.spec.ts'],
    },
  }),
)
