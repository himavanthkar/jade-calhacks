# Trade Promotion — General Mills

React + TypeScript + Vite. Screens are owned by D; the current screen is a static grayscale wireframe. Frontend API scaffolding is ready for mock-based development.

```sh
bun install
bun run --bun dev
```

Default mode is mock; no backend is required. Copy `.env.example` to `.env.local` to configure HTTP mode.

```sh
bun run build
bun run lint
bun test
```

- `src/api/types.ts`: the real API's response shapes (`tpa/api.py`); amounts are decimal strings
- `src/api/client.ts`: HTTP adapter; errors carry the API's `detail` (a 403 with kind `segregation_of_duties` is the SoD throw)
- `src/api/mock.ts`: replays responses captured from the real API, so the mock and the backend can't drift
- `src/api/fixtures/`: those captures; regenerate with `uv run python scripts/frontend_fixtures.py` from the repo root
- `src/api/index.ts`: mode selection; import `api` from here in screens

Mock scenarios (`VITE_MOCK_SCENARIO`): `inbox` steps January and February with every card waiting for a person;
`moment` opens at month 8 after the AM-02 restatement, with February's two answers and the interrogation chain.
For the full year run the API (`make api` at the repo root) and set `VITE_API_MODE=http`.

Fixtures are seeded fiction (seed 1337), not real General Mills transactions.
