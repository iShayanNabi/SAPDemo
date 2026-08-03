import Link from 'next/link';
import { Container, PageHeader, Section, TextLink } from '@/components/ui';
import { NOT_FOUND_METADATA } from '@/lib/metadata';

/**
 * A useful title, `noindex`, and deliberately no canonical.
 *
 * The address a visitor mistyped is not a page, so there is nothing for a
 * canonical to point at - and the root layout no longer supplies one to
 * inherit, which is what used to make every 404 claim to be the home page.
 * This page is not in `content/pages.ts` and therefore not in the sitemap:
 * a 404 offered to a crawler as a destination is worse than no entry at all.
 */
export const metadata = NOT_FOUND_METADATA;

export default function NotFound() {
  return (
    <>
      <PageHeader
        eyebrow="404"
        title="That page does not exist"
        lede="The link may be out of date, or the address mistyped."
      >
        <Link
          href="/"
          className="inline-flex items-center justify-center rounded-lg bg-sky-600 px-5 py-3 text-base font-semibold text-white hover:bg-sky-700"
        >
          Back to the home page
        </Link>
      </PageHeader>
      <Container>
        <Section>
          <p className="text-slate-700 dark:text-slate-300">
            The <TextLink href="/tools">tools overview</TextLink> lists all ten modules, and{' '}
            <TextLink href="/contact">contact</TextLink> is the way to report a broken link.
          </p>
        </Section>
      </Container>
    </>
  );
}
