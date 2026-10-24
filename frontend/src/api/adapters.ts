import type { Control, Metrics } from './types'

/** API spec calls this owner; the database column is owner_role. */
export function adaptControls(rows: (Omit<Control, 'owner'> & { owner?: string; owner_role?: string })[]): Control[] {
  return rows.map(row => {
    const owner = row.owner ?? row.owner_role
    if (!owner) throw new Error(`Control ${row.id} has no owner or owner_role`)
    // fired_count must be computed by the API; do not invent a zero.
    if (!Number.isInteger(row.fired_count) || row.fired_count < 0) throw new Error(`Control ${row.id} is missing a valid fired_count`)
    return { ...row, owner }
  })
}
export function adaptMetrics(value: Metrics): Metrics {
  for (const key of ['precision', 'recall', 'escalation_rate', 'autonomy'] as const) {
    const n = value[key]
    if (n !== null && (typeof n !== 'number' || !Number.isFinite(n) || n < 0 || n > 1)) throw new Error(`Invalid metric: ${key}`)
  }
  return value
}
