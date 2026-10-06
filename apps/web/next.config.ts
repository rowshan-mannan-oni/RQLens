import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // `next build` writes a self-contained server to .next/standalone (used by the Dockerfile).
  output: "standalone",
};

export default nextConfig;
