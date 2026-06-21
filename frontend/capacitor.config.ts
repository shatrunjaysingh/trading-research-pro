import type { CapacitorConfig } from '@capacitor/cli'

const isDev = process.env.NODE_ENV !== 'production'

// In production, set CAPACITOR_BACKEND_URL to your deployed backend URL
// e.g. export CAPACITOR_BACKEND_URL=https://api.yourdomain.com
// For local development, set it to your machine's LAN IP, e.g.:
// export CAPACITOR_BACKEND_URL=http://192.168.1.42:8000
const backendUrl = process.env.CAPACITOR_BACKEND_URL || 'http://localhost:8000'

const config: CapacitorConfig = {
  // ── App identity ──────────────────────────────────────────────────────────
  appId:   'com.tradingresearch.pro',
  appName: 'TradingResearch Pro',
  webDir:  'dist',

  // ── Server / API proxy ────────────────────────────────────────────────────
  server: {
    androidScheme: 'https',
    // Uncomment during development to live-reload from your dev server:
    // url: 'http://192.168.1.42:5173',
    // cleartext: true,
  },

  // ── Plugin configuration ──────────────────────────────────────────────────
  plugins: {
    SplashScreen: {
      launchShowDuration:    2000,
      launchAutoHide:        true,
      backgroundColor:       '#0F172A',
      androidSplashResourceName: 'splash',
      androidScaleType:      'CENTER_CROP',
      showSpinner:           false,
      splashFullScreen:      true,
      splashImmersive:       true,
    },
    StatusBar: {
      style:           'Dark',
      backgroundColor: '#0F172A',
    },
  },
}

export default config
