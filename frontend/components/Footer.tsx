import Link from 'next/link';
import { Logo } from '@/components/Logo';
import { DEMO_NOTICE, TRADEMARK_NOTICE, mailto, siteConfig } from '@/lib/site';

const footerSections = [
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
      { href: '/services', label: 'Consulting services' },
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
] as const;

export function Footer() {
  return (
    <footer className="mt-24 border-t border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-900">
      <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6">
        <div className="grid gap-10 md:grid-cols-2 lg:grid-cols-5">
          <div className="lg:col-span-2">
            <Logo className="text-lg" />
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
              <a
                href={siteConfig.repositoryUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-sky-700 underline underline-offset-4 hover:text-sky-900 dark:text-sky-400 dark:hover:text-sky-300"
              >
                Source on GitHub
              </a>
            </div>
          </div>

          {footerSections.map((section) => (
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
            © {new Date().getFullYear()} {siteConfig.name}
            {siteConfig.locationLabel ? ` · ${siteConfig.locationLabel}` : ''}
          </p>
        </div>
      </div>
    </footer>
  );
}
