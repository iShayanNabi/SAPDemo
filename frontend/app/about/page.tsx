import { DemoCta } from '@/components/DemoCta';
import { RepositoryLink } from '@/components/RepositoryLink';
import { Card, ClaimList, Container, PageHeader, Section, TextLink } from '@/components/ui';
import { modules } from '@/content/modules';
import { pageMetadata } from '@/lib/metadata';
import { hasRepository, siteConfig } from '@/lib/site';

export const metadata = pageMetadata('/about');

export default function AboutPage() {
  return (
    <>
      <PageHeader
        eyebrow="About"
        title={`What ${siteConfig.name} is`}
        lede={`A working demonstration of ${modules.length} SAP-focused procurement and supply-chain tools, built to show how the analysis is done rather than to assert that it works.`}
      >
        <DemoCta />
      </PageHeader>

      <Container>
        <Section title="Why it exists">
          <div className="max-w-3xl space-y-4 leading-relaxed text-slate-700 dark:text-slate-300">
            <p>
              Software that analyses procurement data is easy to demonstrate and hard to trust.
              A dashboard showing a number is not evidence that the number is right, and a
              summary written by a language model reads identically whether the analysis
              underneath it is sound or absent.
            </p>
            <p>
              This project takes the opposite approach: the calculations are ordinary code, the
              thresholds are configuration you can read, the data has documented flaws planted in
              it so results can be checked against known expectations, and every value shown
              carries a label saying how it was produced.
            </p>
            <p>
              It is an educational, technical and portfolio project. It runs on a single machine,
              on fictional data, with no internal user accounts and no SAP connection - and it says
              so on every page rather than in a footnote. It is not an official SAP product, and
              everything it produces needs review by a qualified person before it is acted on.
            </p>
          </div>
        </Section>

        <Section title="The principles it is built on">
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
                About the software
              </h3>
              <div className="mt-4">
                <ClaimList
                  variant="computed"
                  items={[
                    'Never use a language model for a calculation that code can do reliably.',
                    'Label every output with how it was produced.',
                    'Keep thresholds in configuration, not in code.',
                    'Isolate failure: one broken rule must not cost the other nineteen.',
                    'Treat every uploaded document as untrusted data, and never execute instructions found inside one.',
                    'Report an error safely - the detail goes to the log, never to the caller.',
                  ]}
                />
              </div>
            </Card>
            <Card>
              <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
                About what is claimed
              </h3>
              <div className="mt-4">
                <ClaimList
                  variant="plain"
                  items={[
                    'No non-functional buttons, fake integrations or empty pages.',
                    'No hardcoded analysis results.',
                    'No claim that demonstration data comes from a live SAP system.',
                    'No claim that a generated SAP recommendation has been validated in a live SAP environment.',
                    'No estimated saving presented as a guaranteed one.',
                    'No invented clients, testimonials, certifications, partnerships or customer counts.',
                  ]}
                />
              </div>
            </Card>
          </div>
        </Section>

        <Section title="How it was tested">
          <div className="max-w-3xl space-y-4 leading-relaxed text-slate-700 dark:text-slate-300">
            <p>
              The repository carries a substantial automated test suite - unit, API, integration
              and end-to-end - and it is the second most useful thing in the project. The most
              useful is the written record of the bugs that suite did not catch.
            </p>
            <p>
              Several of the most serious defects in this project passed a fully green test run
              and only appeared when the API was driven by hand: a reorder recommendation that
              contradicted the same engine&apos;s own shortage prediction, a summary reporting a
              test failure against steps that no longer existed, a study plan recommending topics
              the candidate had scored 98 on. Each one was a pair of fields that were individually
              correct and jointly a lie.
            </p>
            <p>
              Those are written down in the repository, with what changed to catch the next one.
              A project that only records its successes is a project telling you less than it
              could.
            </p>
          </div>
        </Section>

        <Section title="Relationship to SAP">
          <div className="max-w-3xl space-y-4 leading-relaxed text-slate-700 dark:text-slate-300">
            <p>
              None. {siteConfig.name} is an independent demonstration project. SAP and SAP product
              names are trademarks of SAP SE or its affiliates, used here only to describe the
              domain this project works in. There is no endorsement, certification, sponsorship,
              partnership or affiliation of any kind, and no SAP logo, trademark, proprietary
              graphic or brand asset is reproduced anywhere in it.
            </p>
            <p>
              The tools read SAP-<em>style</em> data - fictional exports shaped the way a real one
              would be. Nothing connects to an SAP system.
            </p>
          </div>
        </Section>

        <Section title="The source">
          <p className="max-w-3xl text-slate-700 dark:text-slate-300">
            {hasRepository ? (
              <>
                The whole project is open for inspection at <RepositoryLink />, including every
                rule, threshold, sample-data generator and manifest. If a number in the
                demonstration looks wrong, the code that produced it is readable.{' '}
              </>
            ) : (
              <>
                The source repository is private. Every rule, threshold, sample-data generator and
                manifest exists and is documented, and a walkthrough of the code behind any number
                in the demonstration can be arranged -{' '}
                <TextLink href="/contact">ask</TextLink>. What the platform does and does not
                calculate is described here rather than left to be inferred from a repository you
                cannot open.{' '}
              </>
            )}
            See also <TextLink href="/architecture">architecture</TextLink> and{' '}
            <TextLink href="/how-it-works">how it works</TextLink>.
          </p>
        </Section>
      </Container>
    </>
  );
}
