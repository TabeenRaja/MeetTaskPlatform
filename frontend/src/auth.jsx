import { createContext, useContext, useEffect, useState } from 'react'
import { api } from './api'

const Ctx = createContext(null)
export const useAuth = () => useContext(Ctx)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(!!localStorage.getItem('access'))

  useEffect(() => {
    if (!localStorage.getItem('access')) return
    api
      .get('/auth/me/')
      .then((r) => setUser(r.data))
      .catch(() => localStorage.clear())
      .finally(() => setLoading(false))
  }, [])

  const login = async (username, password) => {
    const { data } = await api.post('/auth/login/', { username, password })
    localStorage.setItem('access', data.access)
    localStorage.setItem('refresh', data.refresh)
    setUser(data.user)
  }

  const logout = () => {
    localStorage.clear()
    setUser(null)
  }

  return <Ctx.Provider value={{ user, loading, login, logout }}>{children}</Ctx.Provider>
}