/// <reference types="vite/client" />

interface ImportMetaEnv {
  // Base URL of the deployed Function App, e.g. "https://func-baettledger.azurewebsites.net".
  // Left unset during local development so the app falls back to the /mocks JSON files.
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
