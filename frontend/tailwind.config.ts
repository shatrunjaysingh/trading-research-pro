import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        sidebar: 'var(--color-sidebar)',
        canvas:  'var(--color-canvas)',
        primary: {
          // space-separated RGB so opacity modifiers (bg-primary/5) work
          DEFAULT: 'rgb(var(--color-primary) / <alpha-value>)',
          hover:   'rgb(var(--color-primary-hover) / <alpha-value>)',
          light:   'var(--color-primary-light)',
        },
        surface: {
          DEFAULT: 'var(--color-surface)',
          muted:   'var(--color-surface-muted)',
          border:  'var(--color-surface-border)',
        },
        ink: {
          DEFAULT: 'var(--color-ink)',
          muted:   'var(--color-ink-muted)',
          faint:   'var(--color-ink-faint)',
        },
        signal: {
          buy:       '#15803D',
          'buy-bg':  '#DCFCE7',
          watch:     '#1D4ED8',
          'watch-bg':'#DBEAFE',
          hold:      '#92400E',
          'hold-bg': '#FEF9C3',
          sell:      '#DC2626',
          'sell-bg': '#FEE2E2',
        },
        tier: {
          free:         '#475569',
          professional: '#2563EB',
          enterprise:   '#7C3AED',
        },
        role: {
          admin:   '#DC2626',
          analyst: '#2563EB',
          trader:  '#059669',
          viewer:  '#6B7280',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
      boxShadow: {
        card:       '0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)',
        'card-hover':'0 4px 16px rgba(0,0,0,0.10)',
      },
      borderRadius: {
        card: '12px',
      },
    },
  },
  plugins: [],
} satisfies Config
