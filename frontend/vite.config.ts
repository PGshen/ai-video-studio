import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// scripts/dev.sh 从 `python -m studio.config` 读出实际绑定端口后，导出
// STUDIO_BIND_PORT 给这个进程；单独跑 `pnpm run dev`（没有这个环境变量）
// 时回退到默认的 8000，和 Settings.port 的缺省值一致（TD-2 复核发现：
// 之前这里写死 8000，改 STUDIO_PORT 对前端代理不生效）。
const backendPort = process.env.STUDIO_BIND_PORT ?? '8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      // 后端 SSE 接口经由代理直连转发，不缓冲响应体（vite 的 http-proxy 默认按块转发）。
      '/api': {
        target: `http://127.0.0.1:${backendPort}`,
        changeOrigin: true,
        // 后端进程被杀（或重启）时，http-proxy 不会结束已经在转发的 SSE 响应，
        // 浏览器侧的流一直挂着、永远不触发重连（M1 最终审查 L3 实测发现）。
        // 上游响应一断就销毁对浏览器的响应，让 openStream 走重连逻辑。
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes, _req, res) => {
            proxyRes.on('close', () => {
              if (!res.writableEnded) res.destroy()
            })
          })
        },
      },
    },
  },
})
