import type { Metadata } from 'next';
import { RepositoryLink } from '@/components/RepositoryLink';
import { Callout, ClaimList, Container, PageHeader, Section, TextLink } from '@/components/ui';
import { hasRepository, mailto, siteConfig } from '@/lib/site';

export const metadata: Metadata = {
  title: 'Terms and disclaimer',
  description:
    'Terms of use and disclaimer for the Procurement Intelligence Demo website and interactive demonstration. A placeholder statement pending formal terms.',
  alternates: { canonical: '/terms' },
};

export default function TermsPage() {
  return (
    <>
      <PageHeader
        eyebrow="Legal"
        title="Terms and disclaimer"
        lede="What you can expect from this site and demonstration, and what you cannot. A placeholder, stated plainly."
      />

      <Container>
        <Section title="Status of this page">
          <Callout title="This is a placeholder" tone="warning">
            <p>
              These are the honest working terms of a personal demonstration project. They have
              not been drafted or reviewed by a lawyer and are not a commercial agreement. Any
              engagement would be governed by a separate written contract, not by this page.
            </p>
          </Callout>
        </Section>

        <Section title="No warranty, and no production claim">
          <div className="max-w-3xl">
            <ClaimList
              variant="plain"
              items={[
                'This site and the demonstration are provided as-is, for demonstration and evaluation, with no warranty of any kind.',
                'They are not offered as a commercially production-ready product, and no claim of production readiness is made anywhere in this project.',
                'The demonstration runs on a single machine and may be unavailable, reset, changed or withdrawn at any time without notice.',
                'Nothing here constitutes professional, financial, legal or procurement advice.',
              ]}
            />
          </div>
        </Section>

        <Section title="What the outputs are, and are not">
          <div className="max-w-3xl">
            <ClaimList
              variant="plain"
              items={[
                'Every figure, supplier, purchase order, invoice, contract and material is fictional sample data generated for demonstration.',
                'No output has been validated in a live SAP environment, and nothing here is connected to any SAP system.',
                'Estimated savings are estimates that state the assumption behind them. They are not guaranteed savings and must not be reported as such.',
                'Forecasts are statistical projections from historical data, carrying error. They are not predictions of fact.',
                'AI-generated text is labelled wherever it appears and describes computed results. It must not be relied on as an independent statement of fact.',
                'Do not make a business decision on the basis of anything produced by this demonstration.',
              ]}
            />
          </div>
        </Section>

        <Section title="Acceptable use of the demonstration">
          <div className="max-w-3xl">
            <ClaimList
              variant="plain"
              items={[
                'Do not enter confidential information, personal information, real SAP data, real supplier, purchase order, invoice or contract data, or proprietary company data.',
                'Do not attempt to reach the platform API, the database or the host machine directly. Neither the API nor the database is published, and probing for them is not evaluation.',
                'Do not use the demonstration to store anything. It holds fictional data and may be reset without notice.',
                'Do not present output from this demonstration as a validated SAP result, an audited figure or a business outcome.',
              ]}
            />
            <p className="mt-6 text-slate-700 dark:text-slate-300">
              The full statement is on the{' '}
              <TextLink href="/demo-disclaimer">demonstration disclaimer</TextLink>.
            </p>
          </div>
        </Section>

        <Section title="Trademarks">
          <p className="max-w-3xl text-slate-700 dark:text-slate-300">
            SAP and SAP product names are trademarks of SAP SE or its affiliates and are used here
            only descriptively, to identify the domain this project works in. {siteConfig.name} is
            an independent demonstration project and is not endorsed by, certified by, sponsored
            by, partnered with or affiliated with SAP. No SAP logo, trademark, proprietary graphic,
            website layout or brand asset is reproduced in this project. Other trademarks belong
            to their respective owners.
          </p>
        </Section>

        <Section title="Intellectual property">
          <p className="max-w-3xl text-slate-700 dark:text-slate-300">
            {hasRepository ? (
              <>
                The source code and the fictional datasets are the work of this project and are
                published at <RepositoryLink />. Refer to the licence in that repository for what
                you may do with them.
              </>
            ) : (
              <>
                The source code and the fictional datasets are the work of this project and are
                not published. No licence to copy, redistribute or reuse them is granted by this
                site, and the pages here are provided for reading rather than reproduction.
              </>
            )}
          </p>
        </Section>

        <Section title="Questions">
          <p className="max-w-3xl text-slate-700 dark:text-slate-300">
            Write to{' '}
            <a
              href={mailto(`${siteConfig.name} — terms`)}
              className="font-medium text-sky-700 underline underline-offset-4 dark:text-sky-400"
            >
              {siteConfig.contactEmail}
            </a>
            .
          </p>
        </Section>
      </Container>
    </>
  );
}
