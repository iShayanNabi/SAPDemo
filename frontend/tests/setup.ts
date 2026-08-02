import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

/**
 * `next/navigation` is a server/client boundary that has no meaning outside a
 * Next request. Components under test use `usePathname` only to decide which
 * navigation link is the current page, so a stub is enough - and stubbing it
 * here keeps every test file from repeating the same mock.
 */
vi.mock('next/navigation', () => ({
  usePathname: () => '/',
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

/**
 * Fail loudly on any un-stubbed network call.
 *
 * The contact endpoint talks to Cloudflare's `siteverify` and to an SMTP
 * server. Neither may ever be reached from the test suite: a test that quietly
 * makes a real request is slow, flaky, dependent on somebody's network, and -
 * with a real key in the environment - capable of sending real mail.
 *
 * Replacing the global with a thrower means forgetting to stub is a loud,
 * immediate failure naming the URL, rather than a silent outbound request.
 * Tests that need `fetch` stub it themselves with `vi.stubGlobal`, and
 * `vi.unstubAllGlobals()` restores this guard afterwards.
 */
vi.stubGlobal(
  'fetch',
  vi.fn((input: RequestInfo | URL) => {
    throw new Error(
      `Unstubbed network call in a test: ${String(input)}. ` +
        'Stub it with vi.stubGlobal("fetch", ...) or pass a fetch implementation.',
    );
  }),
);

afterEach(() => {
  cleanup();
});
