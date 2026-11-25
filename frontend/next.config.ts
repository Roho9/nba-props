import type { NextConfig } from "next";

// The browser talks to the FastAPI backend through these rewrites, so no backend URL
// or credential is ever embedded in client code.
const BACKEND = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

const config: NextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND}/api/:path*` }];
  },
};

export default config;
