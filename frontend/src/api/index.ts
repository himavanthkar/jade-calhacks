import { createHttpApi } from './client'
import { createMockApi, type MockScenario } from './mock'

const mode = import.meta.env.VITE_API_MODE ?? 'mock'
if (mode !== 'mock' && mode !== 'http') throw new Error('VITE_API_MODE must be mock or http.')
const scenario = (import.meta.env.VITE_MOCK_SCENARIO ?? 'inbox') as MockScenario
if (scenario !== 'inbox' && scenario !== 'moment') throw new Error('VITE_MOCK_SCENARIO must be inbox or moment.')
export const apiMode = mode
export const api = mode === 'mock' ? createMockApi(scenario) : createHttpApi(import.meta.env.VITE_API_BASE_URL ?? '/api')
export { ApiError, createHttpApi, errorKind } from './client'
export { ACTORS } from './actors'
export type * from './types'
