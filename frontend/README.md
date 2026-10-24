# Trade Promotion — General Mills

React + TypeScript + Vite. Screens are owned by D; the current starter screen is unchanged. Frontend API scaffolding is ready for mock-based development.

```sh
bun install
bun run --bun dev
```

Default mode is mock; no backend is required. Copy `.env.example` to `.env.local` to configure HTTP mode. See [API contract](docs/API_CONTRACT.md) for endpoints, integration examples and items to confirm with B/C.

```sh
bun run build
bun run lint
bun test
```

- `src/api/types.ts`: shared proposed response types
- `src/api/client.ts`: HTTP adapter and API errors
- `src/api/mock.ts`: isolated synthetic fixture adapter
- `src/api/index.ts`: mode selection; import `api` from here in screens

Mock responses are for interface development, not real General Mills transactions or measured accounting results.
