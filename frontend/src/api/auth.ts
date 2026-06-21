import client from './client'
import type { User } from '../types'

export interface TokenResponse { access_token: string; token_type: string; user: User }

export const apiLogin = (email: string, password: string) =>
  client.post<TokenResponse>('/auth/login', { email, password }).then(r => r.data)

export const apiRegister = (data: {
  email: string; username: string; password: string; full_name: string; consent?: boolean
}) => client.post<TokenResponse>('/auth/register', data).then(r => r.data)

export const apiLogout = () => client.post('/auth/logout')

export const apiMe = () => client.get<User>('/auth/me').then(r => r.data)
