import type { Metadata } from 'next';
import { ContactCta } from '@/components/ContactCta';
import { DemoCta } from '@/components/DemoCta';
import { ModuleGrid } from '@/components/ModuleCard';
import { Callout, Card, ClaimList, Container, Section, TextLink } from '@/components/ui';
import { modules } from '@/content/modules';
import { origins } from '@/content/origins';
import { DEMO_NOTICE, siteConfig } from '@/lib/site';

export const metadata: Metadata = {
  title: siteConfig.title,
  description: siteConfig.description,
  alternates: { canonical: '/' },
};

export default function HomePage() {
  return (
    <>
      <section className="border-b border-slate-200 bg-gradient-to-b from-slate-50 to-white py-16 sm:py-24 dark:border-slate-800 dark:from-slate-900 dark:to-slate-950">
        <Container>
          <p className="text-sm font-semibold uppercase tracking-wider text-sky-700 dark:text-sky-400">
            SAP-focused demonstration platform
          </p>
          <h1 className="mt-3 max-w-4xl text-4xl font-bold tracking-tight text-slate-900 sm:text-5xl lg:text-6xl dark:text-white">
            Ten procurement and supply-chain tools, where every number is code you can read
          </h1>
          <p className="mt-6 max-w-3xl text-lg leading-relaxed text-slate-600 sm:text-xl dark:text-slate-300">
            {siteConfig.name} analyses SAP-style data with ordinary, deterministic Python.
            Risk thresholds, three-way matching, weighted scoring, statistical forecasting -
            all of it is arithmetic you can reproduce. Language models are used for one thing:
            explaining what the code found.
          </p>
          <div className="mt-9 flex flex-wrap gap-4">
            <DemoCta />
            <ContactCta variant="secondary" />
            <a
              href="/tools"
              className="inline-flex items-center justify-center rounded-lg bg-white px-5 py-3 text-base font-semibold text-slate-900 ring-1 ring-slate-300 transition-colors hover:bg-slate-50 dark:bg-slate-800 dark:text-white dark:ring-slate-600 dark:hover:bg-slate-700"
            >
              See the ten tools
            </a>
          </div>
          <p className="mt-6 max-w-3xl text-sm text-slate-500 dark:text-slate-400">{DEMO_NOTICE}</p>
        </Container>
      </section>

      <Container>
        <Section
          title="The decision this whole project is organised around"
          lede="Most of what procurement software is asked to do is arithmetic. Treating it as arithmetic is what makes an answer reproducible, auditable and cheap - and it is what makes the parts that genuinely need a language model obvious."
        >
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
                Code does the deciding
              </h3>
              <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
                Every value that could be wrong in a way that costs money.
              </p>
              <div className="mt-4">
                <ClaimList
                  variant="computed"
                  items={[
                    'Risk thresholds, duplicate detection and split-order logic',
                    'Three-way invoice matching and tolerance checks',
                    'Weighted supplier scoring and eligibility filters',
                    'Spend aggregation, concentration and variance',
                    'Demand forecasting, stock projection and reorder timing',
                    'Interview marking against an explicit rubric',
                  ]}
                />
              </div>
            </Card>
            <Card>
              <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
                AI does the explaining
              </h3>
              <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
                Prose about results that already exist, in fields of its own.
              </p>
              <div className="mt-4">
                <ClaimList
                  variant="ai"
                  items={[
                    'Executive summaries of computed findings',
                    'Plain-language rewrites of technical results',
                    'Answers to questions, with citations back to the source records',
                    'Drafting test-case and blueprint wording inside a skeleton code decided first',
                    'Coaching prose around a score the rubric already produced',
                  ]}
                />
              </div>
              <p className="mt-4 text-sm text-slate-600 dark:text-slate-400">
                No AI output ever overwrites a computed value, and every result carries a label
                saying which produced it.
              </p>
            </Card>
          </div>
        </Section>

        <Section
          title="Ten tools"
          lede="Each one addresses a specific procurement or supply-chain question, runs on documented fictional data, and shows the evidence behind its answer."
        >
          <ModuleGrid modules={modules} />
        </Section>

        <Section
          title="Every result says where it came from"
          lede="Five origins, printed next to the value they describe. This is the mechanism that stops a mock narrative from being mistaken for a validated SAP result."
        >
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {origins.map((entry) => (
              <li key={entry.origin}>
                <Card className="h-full">
                  <span
                    className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${entry.className}`}
                  >
                    {entry.label}
                  </span>
                  <p className="mt-3 text-sm font-medium text-slate-900 dark:text-white">
                    {entry.summary}
                  </p>
                  <p className="mt-2 text-sm leading-relaxed text-slate-600 dark:text-slate-400">
                    {entry.detail}
                  </p>
                </Card>
              </li>
            ))}
          </ul>
        </Section>

        <Section>
          <Callout title="What the interactive demonstration is" tone="warning">
            <p>
              The demonstration runs the real modules on bundled fictional data. File uploads
              are disabled, the AI runs in mock mode with no provider key, and nothing is
              connected to an SAP system.
            </p>
            <p>
              Please do not enter confidential information, personal information, or any real
              SAP, supplier, invoice or contract data. See the{' '}
              <TextLink href="/demo-disclaimer">demonstration disclaimer</TextLink> for the full
              statement.
            </p>
            <div className="pt-2">
              <DemoCta variant="secondary" className="px-4 py-2 text-sm" />
            </div>
          </Callout>
        </Section>
      </Container>
    </>
  );
}
