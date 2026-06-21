import axios from 'axios'

// VITE_API_URL controls the backend host for both native and web prod builds.
// Leave it unset in dev — the Vite proxy forwards /api/* to localhost:8000.
// Set it to https://your-api.onrender.com for Vercel / mobile deploys.
const apiHost = import.meta.env.VITE_API_URL?.replace(/\/$/, '') ?? ''
const baseURL = apiHost ? `${apiHost}/api/v1` : '/api/v1'

const client = axios.create({ baseURL })

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

client.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('access_token')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  },
)

export default client
