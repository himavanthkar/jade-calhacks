import type { Actor } from './types'

/** tpa/seed/fiction.py ACTORS, less the agent and last year's people. The API decides who may answer what. */
export const ACTORS: Actor[] = [
  { id: 'controller', name: 'Controller', role: 'controller', customer_id: null },
  { id: 'close_reviewer', name: 'Close reviewer', role: 'close_reviewer', customer_id: null },
  { id: 'sales.walmart', name: 'Walmart sales lead', role: 'sales_lead', customer_id: 'WMT' },
  { id: 'sales.costco', name: 'Costco sales lead', role: 'sales_lead', customer_id: 'COST' },
  { id: 'sales.kroger', name: 'Kroger sales lead', role: 'sales_lead', customer_id: 'KR' },
  { id: 'team.walmart', name: 'Walmart customer team analyst', role: 'customer_team_analyst', customer_id: 'WMT' },
  { id: 'team.costco', name: 'Costco customer team analyst', role: 'customer_team_analyst', customer_id: 'COST' },
  { id: 'team.kroger', name: 'Kroger customer team analyst', role: 'customer_team_analyst', customer_id: 'KR' },
]
