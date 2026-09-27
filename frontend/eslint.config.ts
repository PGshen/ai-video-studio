import pluginVue from 'eslint-plugin-vue'
import { defineConfigWithVueTs, vueTsConfigs } from '@vue/eslint-config-typescript'

// 分层规则（对应 docs/ARCHITECTURE.md §3，控制者裁定 R3）：
// - features/* 互不 import
// - components/ 不 import features/ 或 pages/
// 用 no-restricted-imports 的 patterns 实现，不引入 eslint-plugin-boundaries。
//
// 审查发现：只匹配 `@/...` 别名的 patterns 挡不住相对路径（`../projects/X.vue` 能绕过分层
// 检查，已用临时违规文件验证）。修复：额外禁止任何"跳出当前目录向上"的相对 import（`..`
// 开头，覆盖到 5 层，本项目目录深度用不到这么深），强制跨目录一律走 `@/` 别名，上面基于别名
// 的规则就能接管边界检查；同目录/子目录的相对 import（`./Child.vue`、`./sub/Child.vue`，
// 不含 `..`）不受影响。注意：同一个文件集合上同名规则（`no-restricted-imports`）只有最后一个
// 匹配的配置块生效，所以"别名"和"相对路径"两组 pattern 必须写进同一个 `no-restricted-imports`
// 调用的 `patterns` 数组里，不能拆成两个各自独立的配置块（拆开会导致后写的块覆盖先写的块）。
const PARENT_RELATIVE_GLOBS = ['../*', '../*/*', '../*/*/*', '../*/*/*/*', '../*/*/*/*/*']

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
            {
              group: PARENT_RELATIVE_GLOBS,
              message: '不能用相对路径跳出当前目录向上 import；跨目录一律用 @/ 别名（同目录/子目录的相对 import 不受影响）。',
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
            {
              group: PARENT_RELATIVE_GLOBS,
              message: '不能用相对路径跳出当前目录向上 import；跨目录一律用 @/ 别名（同目录/子目录的相对 import 不受影响）。',
            },
          ],
        },
      ],
    },
  },
  {
    // composables/、api/、types/ 目前没有目录间互相禁止的规则，只需要禁止相对路径向上跳出
    // 当前目录（强制走 @/ 别名），方便以后按需加别名规则时统一生效。
    name: 'app/architecture-boundaries/no-parent-relative-imports',
    files: ['src/composables/**/*.{ts,vue}', 'src/api/**/*.{ts,vue}', 'src/types/**/*.{ts,vue}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: PARENT_RELATIVE_GLOBS,
              message: '不能用相对路径跳出当前目录向上 import；跨目录一律用 @/ 别名（同目录/子目录的相对 import 不受影响）。',
            },
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
