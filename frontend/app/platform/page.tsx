import type { Metadata } from 'next';
import { DemoCta } from '@/components/DemoCta';
import { Card, ClaimList, Container, PageHeader, Section, TextLink } from '@/components/ui';
import { modules } from '@/content/modules';
import { UPLOAD_NOTICE, siteConfig } from '@/lib/site';

export const metadata: Metadata = {
  title: 'Platform overview',
  description:
    'How Procurement Intelligence Demo is built: a FastAPI backend of ten modules with deterministic business logic, a shared services layer, labelled output origins, and an interface that holds no business logic of its own.',
  alternates: { canonical: '/platform' },
};

export default function PlatformPage() {
  return (
    <>
      <PageHeader
        eyebrow="Platform"
        title="One backend, ten modules, no hidden arithmetic"
        lede={`${siteConfig.name} is a single FastAPI application. Each module owns its rules, its configuration and its data model; everything they share - file reading, column mapping, document extraction, exports, AI providers - lives in one services layer rather than being rewritten ten times.`}
      >
        <DemoCta />
      </PageHeader>

      <Container>
        <Section
          title="The layers, and the rule that keeps them honest"
          lede="Each layer may call downward and never upward. The practical consequence is the one that matters: no business logic lives in an interface, so the interface can be replaced without rewriting anything."
        >
          <div className="overflow-x-auto">
            <table className="w-full min-w-[36rem] border-collapse text-left text-sm">
              <caption className="sr-only">Application layers and their responsibilities</caption>
              <thead>
                <tr className="border-b border-slate-300 dark:border-slate-700">
                  <th scope="col" className="py-3 pr-4 font-semibold text-slate-900 dark:text-white">
                    Layer
                  </th>
                  <th scope="col" className="py-3 pr-4 font-semibold text-slate-900 dark:text-white">
                    Holds
                  </th>
                  <th scope="col" className="py-3 font-semibold text-slate-900 dark:text-white">
                    Never holds
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
                {[
                  ['Presentation', 'HTTP calls to the API, formatting, charts', 'Any business rule'],
                  ['API', 'Routes, status codes, the response envelope', 'Calculations'],
                  ['Module logic', 'Rules, engines, scoring, forecasting, orchestration', 'HTTP concerns'],
                  ['Shared services', 'File reading, mapping, extraction, exports, AI providers', 'Module-specific rules'],
                  ['Data', 'Models, schemas, migrations', 'Presentation decisions'],
                  ['Core', 'Configuration, logging, exceptions, security', 'Anything module-specific'],
                ].map(([layer, holds, never]) => (
                  <tr key={layer}>
                    <th scope="row" className="py-3 pr-4 font-medium text-slate-900 dark:text-white">
                      {layer}
                    </th>
                    <td className="py-3 pr-4 text-slate-600 dark:text-slate-400">{holds}</td>
                    <td className="py-3 text-slate-600 dark:text-slate-400">{never}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>

        <Section
          title="Configuration, not constants"
          lede="Every threshold that decides an outcome lives in a validated JSON file next to the module that reads it."
        >
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
                What that buys
              </h3>
              <div className="mt-4">
                <ClaimList
                  variant="computed"
                  items={[
                    'Changing what counts as risky is an edit to a configuration file, not a code change and not a deployment.',
                    'The thresholds a result was produced under are reported next to it, along with the configuration version.',
                    'Each module has a test proving a configuration edit changes the outcome with no code change - so the mechanism cannot quietly stop working.',
                  ]}
                />
              </div>
            </Card>
            <Card>
              <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
                Failure is isolated
              </h3>
              <div className="mt-4">
                <ClaimList
                  variant="computed"
                  items={[
                    'Each rule runs inside its own error boundary. One rule failing is reported on the response; the other nineteen still produce results.',
                    'An AI failure never fails an analysis - the computed results are complete without it, and the failure is reported rather than hidden.',
                    'A document that yields no text is reported as needing OCR rather than analysed as an empty contract.',
                  ]}
                />
              </div>
            </Card>
          </div>
        </Section>

        <Section
          title="Fictional data with deliberate, documented flaws"
          lede="Every dataset in the project is generated by a seeded script, and every anomaly in it is written down."
        >
          <div className="max-w-3xl">
            <ClaimList
              variant="plain"
              items={[
                'Each dataset ships with a manifest describing every planted anomaly, so a result can be checked against a known expectation rather than eyeballed.',
                'Generators are seeded and reproducible: regenerating a dataset produces the same file byte for byte.',
                'Each module also ships a recorded baseline of what the current engine produces, and integration tests read the manifest and assert every documented condition is still detected.',
                'The datasets deliberately include missing values, blank cells and awkward encodings, because a dataset with a hole in it finds bugs a clean one never will.',
              ]}
            />
            <p className="mt-6 text-slate-600 dark:text-slate-400">
              None of it came from a real company. See the{' '}
              <TextLink href="/demo-disclaimer">demonstration disclaimer</TextLink>.
            </p>
          </div>
        </Section>

        <Section title="Scope" lede={`${modules.length} modules are implemented and exercised by the test suite.`}>
          <div className="max-w-3xl">
            <p className="text-slate-600 dark:text-slate-400">
              What is deliberately <em>not</em> here is as informative as what is: no internal user
              accounts, roles or tenant administration, no live SAP connection, no billing, and no
              claim that any recommendation has been validated in a production SAP system. Access to
              the interactive demonstration is controlled at the network edge by Cloudflare Access
              rather than by anything inside the application. Those absences are stated in the API
              itself and on the <TextLink href="/architecture">architecture page</TextLink>.
            </p>
            <p className="mt-4 text-slate-600 dark:text-slate-400">{UPLOAD_NOTICE}</p>
          </div>
        </Section>
      </Container>
    </>
  );
}
