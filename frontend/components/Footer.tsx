import Link from 'next/link';
import { ContactCta } from '@/components/ContactCta';
import { Logo } from '@/components/Logo';
import { RepositoryLink } from '@/components/RepositoryLink';
import { DEMO_NOTICE, TRADEMARK_NOTICE, hasRepository, mailto, siteConfig } from '@/lib/site';

/**
 * The footer link columns.
 *
 * A function rather than a constant because one link is conditional: the
 * Services entry follows `SERVICES_PAGE_ENABLED`, the same switch the primary
 * navigation reads, so the two cannot disagree about whether the page exists.
 */
function footerSections(servicesPageEnabled: boolean) {
  return [
    {
      heading: 'Project',
      links: [
        { href: '/platform', label: 'Platform overview' },
        { href: '/tools', label: 'All ten tools' },
        { href: '/how-it-works', label: 'How it works' },
        { href: '/architecture', label: 'Architecture' },
        { href: '/about', label: 'About' },
      ],
    },
    {
      heading: 'Using it',
      links: [
        ...(servicesPageEnabled
          ? [{ href: '/services', label: 'Consulting services' }]
          : []),
        { href: '/contact', label: 'Contact' },
        { href: '/demo-disclaimer', label: 'Demonstration disclaimer' },
      ],
    },
    {
      heading: 'Legal',
      links: [
        { href: '/privacy', label: 'Privacy' },
        { href: '/terms', label: 'Terms and disclaimer' },
      ],
    },
  ];
}

export function Footer() {
  const sections = footerSections(siteConfig.servicesPageEnabled);

  return (
    <footer className="mt-24 border-t border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-900">
      <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6">
        <div className="grid gap-10 md:grid-cols-2 lg:grid-cols-5">
          <div className="lg:col-span-2">
            <Logo className="text-lg" withProductName />
            <p className="mt-3 max-w-sm text-sm text-slate-600 dark:text-slate-400">
              {siteConfig.shortDescription}
            </p>
            <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-sm">
              <a
                href={mailto(`${siteConfig.name} enquiry`)}
                className="font-medium text-sky-700 underline underline-offset-4 hover:text-sky-900 dark:text-sky-400 dark:hover:text-sky-300"
              >
                {siteConfig.contactEmail}
              </a>
              {/* Renders nothing at all while the repository is private. The
                  gap-based layout above collapses with it rather than leaving
                  a hole where a link used to be. */}
              <RepositoryLink>Source on GitHub</RepositoryLink>
            </div>
            <div className="mt-6">
              <ContactCta className="px-4 py-2 text-sm" />
            </div>
          </div>

          {sections.map((section) => (
            <nav key={section.heading} aria-label={section.heading}>
              <h2 className="text-sm font-semibold text-slate-900 dark:text-white">
                {section.heading}
              </h2>
              <ul className="mt-3 space-y-2">
                {section.links.map((link) => (
                  <li key={link.href}>
                    <Link
                      href={link.href}
                      className="text-sm text-slate-600 hover:text-slate-900 hover:underline dark:text-slate-400 dark:hover:text-white"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
          ))}
        </div>

        <div className="mt-10 space-y-3 border-t border-slate-200 pt-6 text-xs leading-relaxed text-slate-500 dark:border-slate-800 dark:text-slate-500">
          <p>{DEMO_NOTICE}</p>
          <p>{TRADEMARK_NOTICE}</p>
          <p>
            © {new Date().getFullYear()} {siteConfig.parentBrand}
            {siteConfig.locationLabel ? ` · ${siteConfig.locationLabel}` : ''}
            {hasRepository ? '' : ' · Source available on request'}
          </p>
        </div>
      </div>
    </footer>
  );
}
