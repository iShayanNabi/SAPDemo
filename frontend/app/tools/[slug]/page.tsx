import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { DemoCta } from '@/components/DemoCta';
import {
  Callout,
  Card,
  ClaimList,
  Container,
  OriginBadge,
  PageHeader,
  Section,
  Steps,
  TextLink,
} from '@/components/ui';
import { moduleBySlug, modules } from '@/content/modules';
import { siteConfig } from '@/lib/site';

interface PageProps {
  params: Promise<{ slug: string }>;
}

/**
 * Every module page is generated at build time from the content module. There
 * is no runtime data source, so the site needs no API and no database.
 */
export function generateStaticParams() {
  return modules.map((module) => ({ slug: module.slug }));
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const module = moduleBySlug(slug);
  if (!module) {
    return { title: 'Tool not found' };
  }
  return {
    title: module.name,
    description: `${module.tagline} ${module.problem}`.slice(0, 300),
    alternates: { canonical: `/tools/${module.slug}` },
    openGraph: {
      title: `${module.name} — ${siteConfig.name}`,
      description: module.tagline,
    },
  };
}

export default async function ModulePage({ params }: PageProps) {
  const { slug } = await params;
  const module = moduleBySlug(slug);
  if (!module) {
    notFound();
  }

  const index = modules.findIndex((entry) => entry.id === module.id);
  const previous = index > 0 ? modules[index - 1] : undefined;
  const next = index < modules.length - 1 ? modules[index + 1] : undefined;

  return (
    <>
      <PageHeader
        eyebrow={`Module ${module.number} of ${modules.length}`}
        title={module.name}
        lede={module.tagline}
      >
        <DemoCta />
        <Link
          href="/tools"
          className="inline-flex items-center justify-center rounded-lg bg-white px-5 py-3 text-base font-semibold text-slate-900 ring-1 ring-slate-300 hover:bg-slate-50 dark:bg-slate-800 dark:text-white dark:ring-slate-600 dark:hover:bg-slate-700"
        >
          All tools
        </Link>
      </PageHeader>

      <Container>
        <Section title="The business problem" as="h2">
          <p className="max-w-3xl text-lg leading-relaxed text-slate-700 dark:text-slate-300">
            {module.problem}
          </p>
        </Section>

        <Section title="The demonstration input" as="h2">
          <Card className="max-w-3xl">
            <div className="flex flex-wrap items-center gap-2">
              <OriginBadge origin="demo_data" />
            </div>
            <p className="mt-3 leading-relaxed text-slate-700 dark:text-slate-300">
              {module.demoInput}
            </p>
          </Card>
        </Section>

        <Section
          title="What the code calculates"
          as="h2"
          lede="Deterministic Python. The same input always produces the same output, and every threshold is configuration rather than a number buried in code."
        >
          <div className="max-w-3xl">
            <ClaimList variant="computed" items={module.computed} />
          </div>
        </Section>

        <Section
          title="What AI writes — and what it cannot touch"
          as="h2"
          lede="Language-model output lives in its own fields, is labelled wherever it appears, and never changes a computed result."
        >
          <div className="max-w-3xl">
            <ClaimList variant="ai" items={module.aiWrites} />
          </div>
        </Section>

        <Section title="What you get" as="h2">
          <div className="grid max-w-4xl gap-6 lg:grid-cols-2">
            <Card>
              <h3 className="text-base font-semibold text-slate-900 dark:text-white">Outputs</h3>
              <div className="mt-4">
                <ClaimList variant="plain" items={module.outputs} />
              </div>
            </Card>
            <Card>
              <h3 className="text-base font-semibold text-slate-900 dark:text-white">
                Result labels used here
              </h3>
              <div className="mt-4 flex flex-wrap gap-2">
                {module.origins.map((origin) => (
                  <OriginBadge key={origin} origin={origin} />
                ))}
              </div>
              {module.exports.length > 0 ? (
                <>
                  <h3 className="mt-6 text-base font-semibold text-slate-900 dark:text-white">
                    Export formats
                  </h3>
                  <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
                    {module.exports.join(' · ')}
                  </p>
                </>
              ) : null}
            </Card>
          </div>
        </Section>

        <Section title="The guided demonstration" as="h2">
          <div className="max-w-3xl">
            <Steps items={module.steps} />
            <div className="mt-8">
              <DemoCta />
            </div>
          </div>
        </Section>

        <Section>
          <Callout title="Demonstration data only" tone="warning">
            <p>
              Everything this module analyses in the demonstration is fictional sample data.
              Uploads are disabled in the public demonstration, and no output has been validated
              in a live SAP environment. See the{' '}
              <TextLink href="/demo-disclaimer">demonstration disclaimer</TextLink>.
            </p>
          </Callout>
        </Section>

        <nav aria-label="Other tools" className="border-t border-slate-200 py-10 dark:border-slate-800">
          <div className="flex flex-col justify-between gap-4 sm:flex-row">
            {previous ? (
              <Link
                href={`/tools/${previous.slug}`}
                className="text-sm font-medium text-sky-700 hover:underline dark:text-sky-400"
              >
                ← Module {previous.number}: {previous.name}
              </Link>
            ) : (
              <span />
            )}
            {next ? (
              <Link
                href={`/tools/${next.slug}`}
                className="text-sm font-medium text-sky-700 hover:underline sm:text-right dark:text-sky-400"
              >
                Module {next.number}: {next.name} →
              </Link>
            ) : (
              <span />
            )}
          </div>
        </nav>
      </Container>
    </>
  );
}
