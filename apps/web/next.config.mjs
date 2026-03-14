const apiOrigin = process.env.NOVAREEL_API_ORIGIN?.replace(/\/$/, '');

/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: '**'
      }
    ]
  },
  async rewrites() {
    if (!apiOrigin) {
      return [];
    }

    return [
      { source: '/v1/:path*', destination: `${apiOrigin}/v1/:path*` },
      { source: '/docs', destination: `${apiOrigin}/docs` },
      { source: '/docs/:path*', destination: `${apiOrigin}/docs/:path*` },
      { source: '/openapi.json', destination: `${apiOrigin}/openapi.json` },
      { source: '/healthz', destination: `${apiOrigin}/healthz` },
      { source: '/files/:path*', destination: `${apiOrigin}/files/:path*` }
    ];
  }
};

export default nextConfig;
