import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Allow Tailscale IP and HTTPS domain for dev access
  allowedDevOrigins: [
    "http://100.123.58.46:3000",
    "http://100.123.58.46",
    "100.123.58.46",
    "https://zima11.taild5de64.ts.net:3000",
    "https://zima11.taild5de64.ts.net",
    "zima11.taild5de64.ts.net",
  ],
  // Proxy /api and /static to backend - enables same-origin access
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8000/api/:path*",
      },
      {
        source: "/static/:path*",
        destination: "http://127.0.0.1:8000/static/:path*",
      },
      // Nero server proxy
      {
        source: "/nero/:path*",
        destination: "http://127.0.0.1:8001/nero/:path*",
      },
    ];
  },
};

export default nextConfig;

