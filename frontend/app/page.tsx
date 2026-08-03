import Link from 'next/link';
import { ContactCta } from '@/components/ContactCta';
import { DemoCta } from '@/components/DemoCta';
import { ExamplePanel } from '@/components/ExamplePanel';
import { CompactModuleGrid } from '@/components/ModuleCard';
import { Callout, Card, Container, Section, TextLink } from '@/components/ui';
import { examplePanels } from '@/content/examples';
import { moduleById, modules } from '@/content/modules';
import { methodOrigins } from '@/content/origins';
import { problemAreas } from '@/content/problems';
import { pageMetadata } from '@/lib/metadata';
import { CONTACT_CTA_HREF, CONTACT_CTA_LABEL } from '@/lib/navigation';
import { UPLOAD_NOTICE, siteConfig } from '@/lib/site';

export const metadata = pageMetadata('/');

/**
 * The home page.
 *
 * Its job is to answer, in one screenful each: what this is, which problems it
 * is about, what the ten tools are, roughly how it works, what an answer looks
 * like, which parts are arithmetic and which are a language model, and how to
 * see it or get in touch. Anything that takes longer than that to say belongs
 * on the page written for it - the layered architecture is on /architecture,
 * the five output origins and the path a file takes are on /how-it-works, and
 * the full description of each tool is on its own page.
 *
 * Two rules about the disclaimers, because they pull in opposite directions:
 *
 * * there is exactly **one** on this page. The previous version stated the
 *   fictional-data position in the hero and again in the callout, and a warning
 *   repeated twice on one page is read once and skipped thereafter;
 * * that one has to keep saying everything it said - what the demonstration
 *   runs on, that uploads are off, what must not be typed into it, and that a
 *   qualified person reviews the output. The footer carries the standing
 *   fictional-data and trademark notices on every page, so this callout does
 *   not repeat those.
 */
export default function HomePage() {
  return (
    <>
      {/* 1. Hero */}
      <section className="border-b border-slate-200 bg-gradient-to-b from-slate-50 to-white py-16 sm:py-20 dark:border-slate-800 dark:from-slate-900 dark:to-slate-950">
        <Container>
          <p className="text-sm font-semibold uppercase tracking-wider text-sky-700 dark:text-sky-400">
            A procurement intelligence portfolio demonstration
          </p>
          <h1 className="mt-3 text-4xl font-bold tracking-tight text-slate-900 sm:text-5xl lg:text-6xl dark:text-white">
            {siteConfig.name}
          </h1>
          {/*
            A real space between the product name and the attribution, and it is
            load-bearing for exactly the reason `components/Logo.tsx` documents.
            These are two block boxes, so the character is never painted - but
            JSX drops the whitespace-only line between two elements, and without
            this the full public name reads `Procurement Intelligence Demoby
            Solve AI Hub` to anything that takes the page as text: a copy and
            paste, a text-only client, a search snippet, a test looking for the
            combined name. Verified by reading the built HTML rather than by
            trusting the source - a `toContain('by Solve AI Hub')` assertion
            passes on the broken markup, because the `by` it finds is the one
            stuck to `Demo`.
          */}
          {' '}
          <p className="mt-2 text-xl font-medium text-slate-500 sm:text-2xl dark:text-slate-400">
            by {siteConfig.parentBrand}
          </p>
          <p className="mt-6 max-w-3xl text-lg leading-relaxed text-slate-600 sm:text-xl dark:text-slate-300">
            Ten procurement and supply-chain tools running on fictional SAP-style data. Rules
            and calculations decide; a language model only explains what they found - and every
            result on screen says which of the two produced it.
          </p>
          <div className="mt-9 flex flex-wrap gap-4">
            <DemoCta />
            {/*
              Beside Launch interactive demo, and visibly a different action:
              the demo is the filled button, this one is the outlined one, and
              it goes to the contact page rather than opening a compose window.
              The label is the site-wide one; it is passed rather than defaulted
              so this line says what the button says.
            */}
            <ContactCta href={CONTACT_CTA_HREF} variant="secondary">
              {CONTACT_CTA_LABEL}
            </ContactCta>
            <Link
              href="/tools"
              className="inline-flex items-center justify-center rounded-lg bg-white px-5 py-3 text-base font-semibold text-slate-900 ring-1 ring-slate-300 transition-colors hover:bg-slate-50 dark:bg-slate-800 dark:text-white dark:ring-slate-600 dark:hover:bg-slate-700"
            >
              See the ten tools
            </Link>
          </div>
        </Container>
      </section>

      <Container>
        {/* 2. The problems, before the tools that address them. */}
        <Section
          title="The problems it addresses"
          lede="Six questions a procurement team is asked repeatedly, and which the ten tools are organised around."
        >
          <ul className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {problemAreas.map((area) => (
              <li key={area.title}>
                <Card className="h-full">
                  <h3 className="text-base font-semibold text-slate-900 dark:text-white">
                    {area.title}
                  </h3>
                  <p className="mt-2 text-sm leading-relaxed text-slate-600 dark:text-slate-400">
                    {area.summary}
                  </p>
                  <p className="mt-3 text-xs text-slate-500 dark:text-slate-500">
                    {area.moduleIds.map((id) => moduleById(id).name).join(' · ')}
                  </p>
                </Card>
              </li>
            ))}
          </ul>
        </Section>

        {/* 3. All ten, compactly. */}
        <Section
          title="The ten tools"
          lede="Each one answers a specific question on documented fictional data. Open any of them for the calculations behind it, what AI does and does not do, and the guided demonstration."
        >
          <CompactModuleGrid modules={modules} />
        </Section>

        {/* 4. How it works, in four steps and a link. */}
        <Section
          title="How it works"
          lede="The same four stages in every module, whichever question it answers."
        >
          <ol className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {[
              {
                step: 'Input',
                body: 'A dataset or a document. In the public demonstration it is always one of the bundled fictional ones.',
              },
              {
                step: 'Validation and normalisation',
                body: 'File and type checks, SAP field names mapped to a shared contract, missing values reported rather than assumed.',
              },
              {
                step: 'Rules, models and AI',
                body: 'Configured rules and calculations first, a statistical model where a projection is needed, a language model only for the wording.',
              },
              {
                step: 'Explainable result and export',
                body: 'Every figure shown with the evidence behind it and a label saying what produced it, and downloadable.',
              },
            ].map((stage, index) => (
              <li key={stage.step}>
                <Card className="h-full">
                  <span
                    aria-hidden="true"
                    className="flex size-7 items-center justify-center rounded-full bg-sky-600 text-sm font-semibold text-white"
                  >
                    {index + 1}
                  </span>
                  <h3 className="mt-3 text-base font-semibold text-slate-900 dark:text-white">
                    {stage.step}
                  </h3>
                  <p className="mt-2 text-sm leading-relaxed text-slate-600 dark:text-slate-400">
                    {stage.body}
                  </p>
                </Card>
              </li>
            ))}
          </ol>
          <p className="mt-6 text-sm text-slate-600 dark:text-slate-400">
            In detail: <TextLink href="/how-it-works">how it works</TextLink> covers the path a
            dataset takes and the five result labels;{' '}
            <TextLink href="/architecture">architecture</TextLink> covers the deployment.
          </p>
        </Section>

        {/* 5. What an answer looks like. */}
        <Section
          title="What an answer looks like"
          lede="Two results in the shape the modules produce them: the computed finding, the evidence it rests on, and the written explanation beside it carrying its own label."
        >
          <div className="grid gap-6 lg:grid-cols-2">
            {examplePanels.map((panel) => (
              <ExamplePanel key={panel.title} panel={panel} />
            ))}
          </div>
          <p className="mt-4 text-sm text-slate-500 dark:text-slate-400">
            Illustrative examples, laid out with this site’s own components and invented values
            in the shape of the bundled fictional data. They are not screenshots, and no result
            here was produced for a customer.
          </p>
        </Section>

        {/* 6. Which parts are arithmetic, and which are a language model. */}
        <Section
          title="Four kinds of output, each labelled"
          lede="Not everything on a screen is produced the same way, so nothing here claims to be. These are the labels the application prints next to the values themselves."
        >
          <ul className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {methodOrigins.map((entry) => (
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
                  <ul className="mt-3 space-y-1 text-sm text-slate-600 dark:text-slate-400">
                    {entry.examples.map((example) => (
                      <li key={example}>{example}</li>
                    ))}
                  </ul>
                </Card>
              </li>
            ))}
          </ul>
          <p className="mt-6 max-w-3xl text-sm text-slate-600 dark:text-slate-400">
            No AI output ever overwrites a computed value, and nothing here decides a
            procurement approval, a legal question, a payment or an SAP governance matter.
          </p>
        </Section>

        {/* 7 and 8. The demonstration, and the one disclaimer on this page. */}
        <Section>
          <Callout title="Before you open the demonstration" tone="warning">
            <p>
              It runs the real modules with a local mock AI provider, on a separate hostname
              behind Cloudflare Access. {UPLOAD_NOTICE} Nothing is connected to a live SAP
              system, and every result needs review by a qualified person before it is acted on.
            </p>
            <p>
              Please do not enter confidential information, personal information, or any real
              SAP, supplier, invoice or contract data. The{' '}
              <TextLink href="/demo-disclaimer">demonstration disclaimer</TextLink> is the full
              statement.
            </p>
            <div className="flex flex-wrap gap-3 pt-2">
              <DemoCta variant="secondary" className="px-4 py-2 text-sm" />
            </div>
          </Callout>
        </Section>
      </Container>
    </>
  );
}
