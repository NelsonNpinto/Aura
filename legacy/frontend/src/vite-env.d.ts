/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Milliseconds before a request is abandoned. Must stay under the platform's
   * function timeout when deployed; local Docker allows much longer generation. */
  readonly VITE_API_TIMEOUT_MS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
