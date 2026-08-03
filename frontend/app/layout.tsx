import type { Metadata, Viewport } from 'next';
import { Footer } from '@/components/Footer';
import { Nav } from '@/components/Nav';
import { TITLE_SEPARATOR, canonicalOrigin } from '@/lib/metadata';
import { getNavItems } from '@/lib/navigation';
import { siteConfig } from '@/lib/site';
import './globals.css';

/**
 * The defaults every page inherits, and deliberately **no canonical**.
 *
 * This object used to carry `alternates: { canonical: '/' }`. Next resolves
 * metadata by merging a segment's object over its parents', so any page that
 * did not set its own canonical inherited that one - and the pages that do not
 * set their own are exactly the ones that must not claim to be the home page:
 * the 404, and an unknown `/tools/<slug>`. Every real page now gets its
 * canonical from `pageMetadata()`, and the absence of one here is what makes a
 * missing canonical visible instead of silently wrong.
 *
 * `metadataBase` is the public origin rather than the configured one, resolved
 * through `lib/metadata.ts`. Every relative URL in a page's metadata - the
 * social image most of all - is made absolute against it, so a debug build
 * pointed at `127.0.0.1` would otherwise publish an `og:image` no crawler can
 * fetch.
 */
export const metadata: Metadata = {
  metadataBase: new URL(canonicalOrigin),
  title: {
    default: siteConfig.title,
    template: `%s${TITLE_SEPARATOR}${siteConfig.name}`,
  },
  description: siteConfig.description,
  applicationName: siteConfig.name,
  authors: [{ name: siteConfig.parentBrand }],
  creator: siteConfig.parentBrand,
  publisher: siteConfig.parentBrand,
  keywords: [
    'procurement intelligence',
    'SAP demonstration',
    'procurement analytics',
    'supply chain analytics',
    'purchase order risk',
    'spend analytics',
    'invoice validation',
    'supplier risk',
    'SAP consulting portfolio',
  ],
  robots: {
    index: true,
    follow: true,
  },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="flex min-h-screen flex-col">
        {/* The first focusable element on every page. Without it, a keyboard
            user tabs through the whole navigation on every single page before
            reaching the content they came for. */}
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-sky-600 focus:px-4 focus:py-2 focus:text-white"
        >
          Skip to main content
        </a>
        {/* Resolved here, in a server component, because SERVICES_PAGE_ENABLED
            is not a NEXT_PUBLIC_ variable and never reaches the browser. */}
        <Nav items={getNavItems(siteConfig.servicesPageEnabled)} />
        <main id="main" className="flex-1">
          {children}
        </main>
        <Footer />
      </body>
    </html>
  );
}
