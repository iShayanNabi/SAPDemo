import Link from 'next/link';
import { Container, PageHeader, Section, TextLink } from '@/components/ui';

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
