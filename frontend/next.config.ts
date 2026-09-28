import type { NextConfig } from "next";

/**
 * The browser only ever talks to our own origin (/api/*). Next.js forwards those
 * requests to the FastAPI backend, so no external weather API (and no API key)
 * is ever reachable from the frontend.
 */
const BACKEND_URL = (process.env.BACKEND_URL ?? "http://localhost:8000").trim().replace(/\/+$/, "");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` }];
  },
};

export default nextConfig;
