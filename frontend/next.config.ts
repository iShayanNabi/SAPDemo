import type { NextConfig } from 'next';

/**
 * `standalone` is what makes the production image small: Next traces the
 * modules the server actually needs and emits a self-contained `server.js`, so
 * the runtime stage copies that rather than a `node_modules` tree.
 *
 * There is deliberately no `rewrites`/`proxy` entry pointing at FastAPI. The
 * website is content about the platform, not a client of it - the browser never
 * calls the API, so the API needs no public hostname. Adding a proxy here would
 * quietly create one.
 */
const nextConfig: NextConfig = {
  output: 'standalone',
  reactStrictMode: true,
  poweredByHeader: false,
  productionBrowserSourceMaps: false,

  /**
   * The site ships no images - the logo is typography and the diagrams are
   * text. Disabling the optimizer therefore costs nothing and removes a real
   * exposure: Next bundles `sharp` for it, `sharp` currently carries four high
   * severity libvips advisories (GHSA-f88m-g3jw-g9cj), and the only offered fix
   * is downgrading Next by seven major versions.
   *
   * With `unoptimized`, the `/_next/image` route does no decoding, so the
   * vulnerable code has no reachable entry point. Re-enable this only together
   * with a `sharp` release that clears the advisory.
   */
  images: {
    unoptimized: true,
  },
};

// Linting is its own gate (`npm run lint`, using the flat config in
// eslint.config.mjs). Next 16 no longer runs ESLint during `next build`, so
// there is nothing to opt out of here - an `eslint` key would not type-check.

export default nextConfig;
