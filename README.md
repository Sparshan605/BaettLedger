# BaettLedger

Dashboard spec lives in [docs/dashboard.md](docs/dashboard.md); API contract in [docs/api.md](docs/api.md);
infra in [docs/azure-setup.md](docs/azure-setup.md).

## Dashboard app

Vite + React + TypeScript + Tailwind, in the repo root (`src/`, `index.html`, `package.json`).

```bash
npm install
npm run dev
```

Runs against the static fixtures in `public/mocks/*.json` by default. Point it at the real
Function App by setting `VITE_API_BASE` (e.g. in a `.env.local` file):

```
VITE_API_BASE=https://func-baettledger.azurewebsites.net
```

```bash
npm run build   # type-checks + production build to dist/
```