import type { Metadata } from 'next';
import { DemoCta } from '@/components/DemoCta';
import { Callout, Card, ClaimList, Container, PageHeader, Section, Steps, TextLink } from '@/components/ui';
import { origins } from '@/content/origins';
import { UPLOAD_NOTICE } from '@/lib/site';

export const metadata: Metadata = {
  title: 'How it works',
  description:
    'How Procurement Intelligence Demo separates deterministic calculation from AI-generated text, how data moves from an uploaded file to a labelled result, and what each of the five result origins means.',
  alternates: { canonical: '/how-it-works' },
};

export default function HowItWorksPage() {
  return (
    <>
      <PageHeader
        eyebrow="How it works"
        title="The line between calculation and language"
        lede="Everything in this project follows from one decision: use ordinary code for anything that could be wrong in a way that costs money, and use a language model only for text about results that already exist."
      >
        <DemoCta />
      </PageHeader>

      <Container>
        <Section
          title="How data moves"
          lede="The path a dataset takes from arriving to being a labelled result. In the public demonstration the file that arrives is always a bundled fictional one."
        >
          <div className="max-w-3xl">
            <Steps
              items={[
                'A file arrives. Its extension is checked against an allow list, its size against a limit read in chunks rather than after the fact, and its leading bytes against what the extension claims - so a PDF renamed to .csv is refused before anything parses it.',
                'Columns are mapped onto a canonical field model. SAP technical names are matched first, then tokens, then fuzzy similarity, and every suggestion reports which strategy produced it and how confident it is. Nothing is silently guessed.',
                'Types are coerced, and the problems found doing it - a blank required field, an unparseable date, a negative quantity - are collected as data-quality issues rather than thrown away.',
                'The module engine runs. Each rule is isolated, so one failure is reported and the rest still produce results.',
                'Results are assembled with a label saying how each was produced, and persisted.',
                'Optionally, a language model is given the finished results and asked for prose. Its text goes into separate fields. If it fails, the analysis is still complete and the failure is reported.',
              ]}
            />
            <p className="mt-6 text-slate-700 dark:text-slate-300">
              {UPLOAD_NOTICE} The validation and mapping described in the first three steps is the
              code that runs when the project is used privately with a dataset of your own; in the
              public demonstration it runs against the bundled files.
            </p>
          </div>
        </Section>

        <Section
          title="Where code is used, and why"
          lede="Not a stylistic preference. Each of these has a property a language model cannot offer: the same input gives the same answer, and the reason for the answer can be shown."
        >
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
                Always ordinary Python
              </h3>
              <div className="mt-4">
                <ClaimList
                  variant="computed"
                  items={[
                    'Arithmetic, aggregation and currency conversion',
                    'Data validation and duplicate detection',
                    'Risk thresholds and weighted scoring',
                    'Invoice matching and tolerance checks',
                    'Statistical analysis and demand forecasting',
                    'Date arithmetic, ranking and classification',
                    'Marking an interview answer against a rubric',
                  ]}
                />
              </div>
            </Card>
            <Card>
              <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
                Only ever a language model
              </h3>
              <div className="mt-4">
                <ClaimList
                  variant="ai"
                  items={[
                    'Explaining and summarising computed results',
                    'Extracting meaning from contract prose - with a page citation attached to every claim',
                    'Answering questions from records that are supplied to it',
                    'Drafting test-case and blueprint wording inside a structure code decided first',
                    'Writing coaching feedback around a score that already exists',
                  ]}
                />
              </div>
            </Card>
          </div>
        </Section>

        <Section
          title="The five result origins"
          lede="Every value shown carries one. This is what makes the distinction above visible rather than something you have to take on trust."
        >
          <dl className="space-y-6">
            {origins.map((entry) => (
              <div
                key={entry.origin}
                className="rounded-xl border border-slate-200 p-6 dark:border-slate-800"
              >
                <dt className="flex flex-wrap items-center gap-3">
                  <span
                    className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${entry.className}`}
                  >
                    {entry.label}
                  </span>
                  <span className="font-medium text-slate-900 dark:text-white">
                    {entry.summary}
                  </span>
                </dt>
                <dd className="mt-2 leading-relaxed text-slate-600 dark:text-slate-400">
                  {entry.detail}
                </dd>
              </div>
            ))}
          </dl>
        </Section>

        <Section title="Running without an AI key">
          <div className="max-w-3xl space-y-4 text-slate-700 dark:text-slate-300">
            <p>
              The default AI provider is a mock. With no key configured, narrative text is
              composed locally from the computed results and labelled{' '}
              <strong>Mock AI</strong>. Every module works end to end this way - which is why the
              public demonstration needs no provider credential, incurs no API cost, and sends
              nothing to a third party.
            </p>
            <p>
              Anthropic and OpenAI are supported for anyone running the project themselves. Keys
              are read from environment variables only and never appear in source, logs, API
              responses or the browser.
            </p>
          </div>
        </Section>

        <Section>
          <Callout title="What this is not">
            <p>
              This is a demonstration platform on fictional data. It is not an official SAP
              product, it is not connected to any SAP system, none of its output has been validated
              in a live SAP environment, and no estimated saving it produces is a guarantee. Every
              result it produces needs review by a qualified person before it is acted on. Read the{' '}
              <TextLink href="/demo-disclaimer">demonstration disclaimer</TextLink> before drawing
              conclusions from anything you see in it.
            </p>
          </Callout>
        </Section>
      </Container>
    </>
  );
}
