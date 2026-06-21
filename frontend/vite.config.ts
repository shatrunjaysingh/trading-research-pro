import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icons/*.svg'],
      manifest: {
        name: 'Trading Research Pro',
        short_name: 'TRP',
        description: 'Institutional-grade stock research & market intelligence',
        theme_color: '#0F172A',
        background_color: '#0F172A',
        display: 'standalone',
        orientation: 'portrait-primary',
        start_url: '/',
        scope: '/',
        categories: ['finance', 'business'],
        icons: [
          {
            src: '/icons/icon.svg',
            sizes: 'any',
            type: 'image/svg+xml',
            purpose: 'any',
          },
          {
            src: '/icons/maskable-icon.svg',
            sizes: 'any',
            type: 'image/svg+xml',
            purpose: 'maskable',
          },
        ],
        shortcuts: [
          {
            name: 'Market Overview',
            short_name: 'Market',
            url: '/market',
            icons: [{ src: '/icons/icon.svg', sizes: 'any' }],
          },
          {
            name: 'Stock Analysis',
            short_name: 'Stocks',
            url: '/stocks',
            icons: [{ src: '/icons/icon.svg', sizes: 'any' }],
          },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,woff2}'],
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/api/],
        runtimeCaching: [
          {
            // Google Fonts — cache first, long TTL
            urlPattern: /^https:\/\/fonts\.(googleapis|gstatic)\.com\/.*/i,
            handler: 'CacheFirst',
            options: {
              cacheName: 'google-fonts',
              expiration: { maxEntries: 10, maxAgeSeconds: 60 * 60 * 24 * 365 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          {
            // Market overview — stale-while-revalidate (60s)
            urlPattern: /\/api\/v1\/market\/.*/i,
            handler: 'StaleWhileRevalidate',
            options: {
              cacheName: 'market-api',
              expiration: { maxEntries: 10, maxAgeSeconds: 60 },
            },
          },
          {
            // Price history charts — cache 5 min
            urlPattern: /\/api\/v1\/analysis\/history.*/i,
            handler: 'StaleWhileRevalidate',
            options: {
              cacheName: 'chart-history',
              expiration: { maxEntries: 50, maxAgeSeconds: 60 * 5 },
            },
          },
        ],
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
