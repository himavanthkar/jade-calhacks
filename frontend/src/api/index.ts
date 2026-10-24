import { createHttpApi } from './client'
import { createMockApi } from './mock'

const mode = import.meta.env.VITE_API_MODE ?? 'mock'
if (mode !== 'mock' && mode !== 'http') throw new Error('VITE_API_MODE must be mock or http.')
export const apiMode = mode
export const api = mode === 'mock' ? createMockApi() : createHttpApi(import.meta.env.VITE_API_BASE_URL ?? '/api')
export { ApiError, createHttpApi } from './client'
export { createMockApi } from './mock'
export type * from './types'
