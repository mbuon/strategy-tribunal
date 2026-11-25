import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Single-file output: one JS bundle + one CSS file, inlined by dashboard.py
// into every page so run folders stay self-contained and readable offline.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: '../src/llm_council/static',
    emptyOutDir: true,
    rollupOptions: {
      input: 'src/main.jsx',
      output: {
        entryFileNames: 'dashboard.js',
        chunkFileNames: 'dashboard-[name].js',
        assetFileNames: 'dashboard.[ext]',
      },
    },
    cssCodeSplit: false,
  },
})
