import type { MetadataRoute } from 'next';
import { modules } from '@/content/modules';
import { siteConfig } from '@/lib/site';

/**
 * Generated from the same content the pages render, so a module added to the
 * content module appears in the sitemap without anybody remembering to add it.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  const staticPaths = [
    '',
    '/platform',
    '/tools',
    '/how-it-works',
    '/architecture',
    // Follows the same switch the navigation and the footer read, so a page
    // that is not linked anywhere is not advertised to a crawler either.
    ...(siteConfig.servicesPageEnabled ? ['/services'] : []),
    '/about',
    '/contact',
    '/demo-disclaimer',
    '/privacy',
    '/terms',
  ];

  const modulePaths = modules.map((module) => `/tools/${module.slug}`);

  return [...staticPaths, ...modulePaths].map((path) => ({
    url: `${siteConfig.url}${path}`,
    lastModified: new Date(),
    changeFrequency: path === '' ? 'weekly' : 'monthly',
    priority: path === '' ? 1 : path.startsWith('/tools') ? 0.8 : 0.6,
  }));
}
