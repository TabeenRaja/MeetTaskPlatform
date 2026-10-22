import axios from 'axios'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api'
export const api = axios.create({ baseURL: API })

api.interceptors.request.use((cfg) => {
  const t = localStorage.getItem('access')
  if (t) cfg.headers.Authorization = `Bearer ${t}`
  return cfg
})

let refreshing = null

api.interceptors.response.use(
  (r) => r,
  async (err) => {
    const orig = err.config
    const canRetry =
      err.response?.status === 401 &&
      !orig._retry &&
      localStorage.getItem('refresh') &&
      !orig.url.includes('/auth/login')
    if (canRetry) {
      orig._retry = true
      try {
        refreshing = refreshing || axios.post(`${API}/auth/refresh/`, { refresh: localStorage.getItem('refresh') })
        const { data } = await refreshing
        refreshing = null
        localStorage.setItem('access', data.access)
        orig.headers.Authorization = `Bearer ${data.access}`
        return api(orig)
      } catch {
        refreshing = null
        localStorage.clear()
        window.location.href = '/login'
      }
    }
    return Promise.reject(err)
  }
)

// Turns any DRF error into one readable string
export function errMsg(e) {
  const d = e?.response?.data
  if (!d) return e?.message || 'Something went wrong'
  if (typeof d === 'string') return 'Server error. Check the backend terminal.'
  if (d.detail) return d.detail
  if (Array.isArray(d)) return d.join(' ')
  return Object.entries(d)
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(' ') : v}`)
    .join(' | ')
}