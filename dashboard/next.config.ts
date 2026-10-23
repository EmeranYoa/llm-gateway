import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // A self-contained server (`.next/standalone/server.js`) for the Docker image.
  output: "standalone",
  poweredByHeader: false,
  experimental: {
    serverActions: {
      // Next.js runs a server action only when the host of the request's
      // `Origin` header matches its own host (`X-Forwarded-Host`, or `Host`).
      // No extra origin is trusted. Behind a reverse proxy that does not
      // forward `X-Forwarded-Host`, add the public host here and rebuild.
      allowedOrigins: [],
    },
  },
};

export default nextConfig;
