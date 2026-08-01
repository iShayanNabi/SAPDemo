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

afterEach(() => {
  cleanup();
});
