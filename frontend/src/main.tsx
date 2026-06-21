// Apply saved theme before first paint to prevent flash of wrong theme
try {
  const saved = localStorage.getItem('theme-pref')
  if (saved && JSON.parse(saved)?.state?.theme === 'dark') {
    document.documentElement.classList.add('dark')
  }
} catch {}

import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={queryClient}>
    <App />
  </QueryClientProvider>,
)
