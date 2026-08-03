import type { MetadataRoute } from 'next';
import { canonicalUrl } from '@/lib/metadata';

/**
 * Every marketing page is crawlable; the route handlers are not offered as
 * destinations.
 *
 * `/api/` is disallowed because there is nothing there for a crawler - the one
 * route is the contact endpoint, which accepts a POST and returns JSON. It is
 * **not** disallowed as a protection: `robots.txt` is a request, it is public,
 * and naming a path in it advertises the path. What actually guards that
 * endpoint is the feature flag, the Turnstile challenge and the two rate-limit
 * buckets in `lib/contact/`.
 *
 * The `allow` is written first and deliberately kept: a rule file whose only
 * entry is a `Disallow` is one edit away from `Disallow: /`, which removes the
 * whole site from every index and produces no error anywhere.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: '*',
      allow: '/',
      disallow: ['/api/'],
    },
    sitemap: canonicalUrl('/sitemap.xml'),
    // No `host:` directive. It is a Yandex extension that most crawlers ignore,
    // Next emits it as a full URL rather than the bare hostname it is specified
    // as, and the question it answers - which of www and non-www is the real
    // one - is answered properly by the canonical link on every page.
  };
}
