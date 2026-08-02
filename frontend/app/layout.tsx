import type { Metadata, Viewport } from 'next';
import { Footer } from '@/components/Footer';
import { Nav } from '@/components/Nav';
import { getNavItems } from '@/lib/navigation';
import { siteConfig } from '@/lib/site';
import './globals.css';

export const metadata: Metadata = {
  metadataBase: new URL(siteConfig.url),
  title: {
    default: siteConfig.title,
    template: `%s — ${siteConfig.name}`,
  },
  description: siteConfig.description,
  applicationName: siteConfig.name,
  keywords: [
    'SAP demonstration',
    'procurement analytics',
    'supply chain analytics',
    'purchase order risk',
    'spend analytics',
    'invoice validation',
    'supplier risk',
    'SAP consulting portfolio',
  ],
  openGraph: {
    type: 'website',
    siteName: siteConfig.name,
    title: siteConfig.title,
    description: siteConfig.description,
    url: siteConfig.url,
  },
  twitter: {
    card: 'summary',
    title: siteConfig.title,
    description: siteConfig.shortDescription,
  },
  robots: {
    index: true,
    follow: true,
  },
  alternates: {
    canonical: '/',
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
