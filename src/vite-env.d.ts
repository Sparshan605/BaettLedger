/// <reference types="vite/client" />

interface ImportMetaEnv {
  // Base URL of the deployed Function App. Optional — when unset the client
  // falls back to the production API, never to mock data. See src/api/client.ts.
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
