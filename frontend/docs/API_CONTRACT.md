# Frontend integration with jade-calhacks

## Current status

The seven request paths below follow spec.md. At integration time (backend commit
8698046), this repository has no FastAPI app or route handlers. Therefore there is
no deployed HTTP response contract to verify yet. This frontend is aligned with
the concrete Python function results and SQL schema where available; it does not
claim an end-to-end backend connection. The initial screen is unchanged.

| Method | Request | Source / status |
| --- | --- | --- |
| getPeriod(period) | GET /api/period/{YYYY-MM} | spec envelope: state, postings, findings, gates, flux; aggregation not implemented |
| stepPeriod(period) | POST /api/period/{YYYY-MM}/step | cycle route not implemented |
| getControls() | GET /api/controls | schema fields plus API-computed fired_count |
| getEscalations() | GET /api/escalations?open=true | requires joining findings.evidence to escalations |
| answerEscalation(id, answer) | POST /api/escalations/{id}/answer with {answer} | judgment / authority route not implemented |
| explainEntry(id) | GET /api/explain/{entry_id} | typed to tpa.asof.entry_history output |
| getMetrics(period) | GET /api/metrics?as_of={YYYY-MM} | typed to tpa.evaluate.metrics output |

## Changes based on existing backend code

- Customer IDs are WMT, COST, KR (tpa/constants.py). Control IDs use CTL slugs.
- Ledger lines include customer_id, entry_type, program_id, reversal_of, restates,
  source_finding_id, deduction_id and approved_by. Memo may be null. Account names
  include account codes. valid_time is the activity period's last day.
- Money/decimal values accept number or string, preserving the wire value without
  lossy conversion. Frontend does not compute accounting entries.
- Gate results are {name, description, passed, violations[]} (tpa/gates.py), not
  {passed, message}. Violation evidence may contain decimal strings.
- Evidence is arbitrary JSON, not a fixed set of ID arrays (tpa/evaluate.py).
- Controls store owner_role. The adapter exposes owner for the spec's UI contract.
  threshold and threshold_unit can be null. fired_count is not a DB column: the
  route must derive it from findings, and the adapter rejects a missing count.
- Explanation is {line, journal, reverses_or_restates, reversed_by, restated_by,
  deduction, finding, approved_by}. approved_by is an actor object or null;
  restated_by is an array of ledger lines. No model narrative is implemented.
- Metrics are ratios 0–1 or null when no denominator exists. Render null as N/A,
  never as 0%. Evaluator counts, missed and false_positives are preserved.
- SQL TIMESTAMP values are timezone-naive. Preserve their strings; agree a timezone
  before local-time display rather than adding Z and changing their meaning.
- Escalation options are JSONB. The exact option schema is still unspecified;
  do not assume object options are strings. The answer payload is a string per spec.

## Remaining decisions with B/C

1. Periods are per (period, customer_id), while the spec has a single state and
   gates object. Define the HTTP aggregation or customer filter; do not infer that
   all customers are closed from one row. CustomerPeriod is separately typed.
2. sim_clock.current_period is the next period to run. Define Step's resulting
   active period and retry/conflict semantics. The mock only processes the
   requested period and does not advance a real clock.
3. Define actor authentication, role authorization, answer reasoning and SoD errors.
   The frontend never grants permissions itself.
4. Free-text interrogation, precedent detail and close signing are not among the
   seven specified routes. entry_history is a record lookup, not a question API.
5. Freeze HTTP serialization, option IDs, decimal handling and error schemas once
   the FastAPI handlers exist. Types do not runtime-validate all response bodies.

## Screen integration

```ts
import { api, apiMode, ApiError } from './api'

const controller = new AbortController()
const period = await api.getPeriod('2026-01', { signal: controller.signal })
const controls = await api.getControls()
await api.stepPeriod('2026-01')
const updated = await api.getPeriod('2026-01')
```

Refresh period, controls and inbox after answering. Disable pending mutation
buttons. Do not automatically retry a POST: an aborted request may still have
completed on the server. API errors retain status/details; network and abort
errors propagate. Screens own loading, error, empty and stale-request handling.

## Run modes

Default: mock. Each createMockApi() has an isolated in-memory session; reload resets
it. Fixtures are synthetic, metrics illustrative, flux empty. Answering simply
closes a sample card; it is not a real judgment engine or precedent matcher.
Display apiMode in the UI when screens are built.

For HTTP mode, copy .env.example to .env.local and set VITE_API_MODE=http.
/api is proxied to API_PROXY_TARGET (default http://127.0.0.1:8000) by Vite in dev.
Restart after env changes. Production needs an /api reverse proxy or an explicit
VITE_API_BASE_URL and backend CORS configuration. VITE variables are public:
never store secrets there. There is no backend launch command until an app exists.

## Verification

bun run build; bun run lint; bun test. Tests cover request encoding, empty mutation
responses, authority failures without retries, cancellation, fixture flow, nullable
metrics, owner_role mapping and ledger-history response preservation. They do not
exercise live HTTP routes or a Postgres instance.
