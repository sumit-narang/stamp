import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  // served under /stamp in production (set VITE_BASE=/stamp/ at build time)
  base: process.env.VITE_BASE ?? '/',
  plugins: [react()],
  server: { port: 5173 },
})
