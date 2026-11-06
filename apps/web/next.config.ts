import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";
import path from "node:path";

// Monorepo: also read the repo-root .env.local (Vercel injects env vars directly).
loadEnvConfig(
  path.resolve(process.cwd(), "../.."),
  process.env.NODE_ENV !== "production",
  { info: () => {}, error: console.error },
  true,
);

const apiOrigin = process.env.AURA_API_DEV_ORIGIN ?? "http://localhost:8010";

const isDev = process.env.NODE_ENV === "development";

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  {
    // img-src blocks external images (Markdown exfiltration, §B18). Turnstile needs its script + frame.
    key: "Content-Security-Policy",
    value: [
      "default-src 'self'",
      `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""} https://challenges.cloudflare.com`,
      "frame-src https://challenges.cloudflare.com",
      "img-src 'self' data:",
      "style-src 'self' 'unsafe-inline'",
      `connect-src 'self'${isDev ? " ws://localhost:* http://localhost:*" : ""}`,
      "font-src 'self' data:",
      "object-src 'none'",
      "base-uri 'self'",
      "form-action 'self'",
      "frame-ancestors 'none'",
    ].join("; "),
  },
];

const nextConfig: NextConfig = {
  poweredByHeader: false,
  // macOS writes AppleDouble (._*) files on exFAT drives, which corrupt Turbopack's on-disk cache.
  experimental: {
    turbopackFileSystemCacheForDev: false,
    turbopackFileSystemCacheForBuild: false,
    // Allow the local API's paced marketing comparison to finish before the dev proxy times out.
    proxyTimeout: isDev ? 250_000 : undefined,
  },
  turbopack: {
    rules: {
      "*.css": { loaders: ["@tailwindcss/turbopack"], as: "*.css" },
    },
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  async rewrites() {
    // Local dev only: on Vercel, Services routing sends /api/v1/* and /mcp* to the FastAPI service.
    if (process.env.NODE_ENV !== "development") return [];
    return [
      { source: "/api/v1/:path*", destination: `${apiOrigin}/api/v1/:path*` },
      { source: "/mcp/:path*", destination: `${apiOrigin}/mcp/:path*` },
    ];
  },
};

export default nextConfig;
