import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'node:path'

// Backend port: the Electron shell launches the FastAPI sidecar on a stable
// port (47900+) and exports H3C_BACKEND_PORT before starting vite. Falls back
// to 8000 for plain `npm run dev` web development.
const BACKEND_PORT = process.env.H3C_BACKEND_PORT || '8000'
const BACKEND_TARGET = `http://localhost:${BACKEND_PORT}`

export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  build: {
    rollupOptions: {
      input: {
        main: path.resolve(__dirname, 'index.html'),
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: BACKEND_TARGET,
        changeOrigin: true,
        // SSE: disable any buffering on the proxy so chunks pass through immediately
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            proxyRes.headers['cache-control'] = 'no-cache, no-transform'
            // ensure no compression that would buffer
            delete proxyRes.headers['content-encoding']
          })
        },
      },
      // Scenic-spot mock backend serves images at :5001/images/*.jpg.
      // UI Schema CardList uses these relative URLs as <img src>; proxy
      // them so the browser doesn't 404 against the Vite dev server.
      '/images': {
        target: 'http://localhost:5001',
        changeOrigin: true,
      },
    },
  },
})
