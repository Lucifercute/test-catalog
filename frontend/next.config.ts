import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Self-contained server.js for a small Docker image.
  output: "standalone",
  // Images are plain <img> from /media; never run the optimizer (it caches on each replica's disk).
  images: { unoptimized: true },
  poweredByHeader: false,
};

export default nextConfig;
