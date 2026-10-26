import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const devHeaders = {
  'X-User-Id': process.env.VITE_DEV_USER_ID || 'nv_001',
  'X-Department-Id': process.env.VITE_DEV_DEPT_ID || 'IT',
  'X-User-Role': process.env.VITE_DEV_USER_ROLE || 'user',
  'X-User-Name': process.env.VITE_DEV_USER_NAME || 'Nguyễn Văn A',
};

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: process.env.VITE_DEV_HOST || '127.0.0.1',
    proxy: {
      '/upload': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        headers: devHeaders,
      },
      '/files': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        headers: devHeaders,
      },
      '/chat': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        headers: devHeaders,
      },
      '/sessions': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        headers: devHeaders,
      },
      '/feedback': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        headers: devHeaders,
      },
      '/health': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/me': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        headers: devHeaders,
      },
    },
  },
})
