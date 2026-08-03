import type { MetadataRoute } from 'next';
import { modules } from '@/content/modules';
import { publishedPages } from '@/content/pages';
import { canonicalUrl } from '@/lib/metadata';
import { siteConfig } from '@/lib/site';

/**
 * The public marketing pages, generated from the same two registries the pages
 * themselves read.
 *
 * Nothing here is written out by hand, which is the point: a module added to
 * `content/modules.ts` appears without anybody remembering, and a page cannot
 * be listed unless it is in `content/pages.ts` and therefore actually exists.
 *
 * What is deliberately **absent** matters as much as what is present:
 *
 * * `/api/contact` and every other route handler. They accept a POST and
 *   return JSON; a crawler asked to fetch one gets a 405 at best.
 * * `https://demo.solveaihub.com` - the Streamlit demonstration. It is behind
 *   Cloudflare Access, it is not a marketing page, and it is not even on this
 *   origin, so `canonicalUrl` could not produce it if somebody tried.
 * * query-string variants. `/contact?service=consulting` is the Services
 *   page's call to action and is the same page as `/contact`; listing both
 *   splits one page into two. `canonicalUrl` drops the query for this reason.
 * * the 404. It is not a destination.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  const paths = [
    ...publishedPages(siteConfig.servicesPageEnabled).map((page) => page.path),
    ...modules.map((module) => `/tools/${module.slug}`),
  ];

  const lastModified = new Date();

  return paths.map((path) => ({
    url: canonicalUrl(path),
    lastModified,
    changeFrequency: path === '/' ? 'weekly' : 'monthly',
    priority: path === '/' ? 1 : path.startsWith('/tools') ? 0.8 : 0.6,
  }));
}
