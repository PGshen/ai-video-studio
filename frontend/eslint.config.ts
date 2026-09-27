import pluginVue from 'eslint-plugin-vue'
import { defineConfigWithVueTs, vueTsConfigs } from '@vue/eslint-config-typescript'

// 分层规则（对应 docs/ARCHITECTURE.md §3，控制者裁定 R3）：
// - features/* 互不 import
// - components/ 不 import features/ 或 pages/
// 用 no-restricted-imports 的 patterns 实现，不引入 eslint-plugin-boundaries。
export default defineConfigWithVueTs(
  {
    name: 'app/files-to-lint',
    files: ['src/**/*.{ts,mts,tsx,vue}'],
  },
  {
    name: 'app/ignores',
    ignores: ['**/dist/**', '**/node_modules/**', 'src/components/ui/**', 'src/components/ai-elements/**'],
  },
  ...pluginVue.configs['flat/recommended'],
  vueTsConfigs.recommended,
  {
    name: 'app/architecture-boundaries/features',
    files: ['src/features/**/*.{ts,vue}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/features/**'],
              message: 'features/* 之间互不 import；共用内容放进 components/ 或 composables/。',
            },
          ],
        },
      ],
    },
  },
  {
    name: 'app/architecture-boundaries/components',
    files: ['src/components/**/*.{ts,vue}'],
    ignores: ['src/components/ui/**', 'src/components/ai-elements/**'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            { group: ['@/features/**'], message: 'components/ 不能 import features/。' },
            { group: ['@/pages/**'], message: 'components/ 不能 import pages/。' },
          ],
        },
      ],
    },
  },
  {
    name: 'app/generated-code',
    files: ['src/components/ui/**/*.{ts,vue}', 'src/components/ai-elements/**/*.{ts,vue}'],
    rules: {
      // 生成的代码尽量不手改，格式规则放宽。
      'vue/multi-word-component-names': 'off',
      'vue/attributes-order': 'off',
      'vue/html-self-closing': 'off',
      '@typescript-eslint/no-explicit-any': 'off',
    },
  },
)
