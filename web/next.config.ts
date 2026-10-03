import path from "node:path";
import type { NextConfig } from "next";

/**
 * The browser only ever calls relative /api/* URLs. In "api" mode they are
 * proxied to the FastAPI service. API_BASE_URL is read when the config is
 * loaded (next dev / next build), so for the standalone Docker image pass it
 * as a build argument. Either the origin ("http://localhost:8080") or the API
 * prefix ("http://localhost:8080/api") is accepted.
 */
const apiBaseUrl = (process.env.API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8080")
  .replace(/\/+$/, "")
  // Accept both "http://host:8080" and "http://host:8080/api"; the rewrite adds /api itself.
  .replace(/\/api$/, "");

const nextConfig: NextConfig = {
  output: "standalone",
  // The repository root also holds the API and the deck; keep tracing and Turbopack scoped to this folder.
  outputFileTracingRoot: path.join(__dirname),
  turbopack: { root: path.join(__dirname) },
  reactStrictMode: true,
  // Do not let `next dev` write AGENTS.md / CLAUDE.md into the project.
  agentRules: false,
  devIndicators: false,
  poweredByHeader: false,
  // Gzip would buffer the proxied Server-Sent Events stream.
  compress: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiBaseUrl}/api/:path*` }];
  },
};

export default nextConfig;
