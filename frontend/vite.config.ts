import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

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
        target: 'http://127.0.0.1:8000',
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
