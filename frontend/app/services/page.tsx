import { ContactCta } from '@/components/ContactCta';
import { DemoCta } from '@/components/DemoCta';
import { EmailCard } from '@/components/EmailCard';
import { Callout, Card, ClaimList, Container, PageHeader, Section, TextLink } from '@/components/ui';
import { pageMetadata } from '@/lib/metadata';
import {
  CONSULTING_CTA_HREF,
  CONSULTING_CTA_LABEL,
  CONTACT_CTA_HREF,
  CONTACT_CTA_LABEL,
} from '@/lib/navigation';
import { hasRepository, siteConfig } from '@/lib/site';

export const metadata = pageMetadata('/services');

const areas = [
  {
    title: 'Procurement and supply-chain analysis',
    body:
      'Turning an SAP export into answers: spend structure, supplier concentration, contract ' +
      'leakage, purchase order risk, invoice exceptions. The work is mostly deciding which ' +
      'question is actually being asked, then computing it in a way somebody can check.',
    points: [
      'Rule engines with configurable thresholds rather than numbers buried in code',
      'Three-way matching and exception handling',
      'Weighted scoring models where the weights are visible and adjustable',
      'Demand forecasting with model selection you can defend',
    ],
  },
  {
    title: 'Document and data extraction',
    body:
      'Getting structured facts out of contracts, specifications and exports - with a citation ' +
      'attached to each one, because an extracted value nobody can trace back is a value ' +
      'nobody should act on.',
    points: [
      'Clause, date and obligation extraction with page-level citations',
      'Confidence scores derived from evidence rather than assigned',
      'Handling for documents that cannot be read, instead of an empty result that looks like an answer',
    ],
  },
  {
    title: 'Using language models where they help',
    body:
      'The useful question is rarely "can AI do this" and usually "which part of this should ' +
      'it do". Drawing that line well is most of the value; drawing it badly produces a system ' +
      'that is confidently wrong and expensive.',
    points: [
      'Separating computed results from generated text, structurally rather than by convention',
      'Deterministic skeletons for generated artefacts, so structure survives a model failure',
      'Validation at the provider boundary, and repair with the failure recorded rather than hidden',
      'Prompt-injection handling for any pipeline that reads untrusted documents',
    ],
  },
  {
    title: 'Building it so it can be maintained',
    body:
      'A system nobody can change is a system that gets replaced. Layer separation, ' +
      'configuration over constants, honest error handling and tests that assert the ' +
      'relationships between fields rather than each field alone.',
    points: [
      'Clear layer boundaries, so an interface can be replaced without touching business logic',
      'Sample data with documented, deliberate flaws to test against',
      'Test suites that check pairs of fields agree, which is where the real bugs live',
      'Deployment that does not require exposing an API or a database to the internet',
    ],
  },
] as const;

/**
 * Three things a reader can check for themselves.
 *
 * Two of them used to say "read the source" and "the repository records...".
 * The repository is private, so with the link removed those sentences would
 * still be inviting somebody to open something they cannot open - which is the
 * claim, not the anchor, doing the damage. When there is no public repository
 * the same two points are made as an offer rather than an instruction.
 */
const evaluationSteps: readonly string[] = [
  'Open the interactive demonstration and run any module end to end on its bundled fictional data.',
  hasRepository
    ? 'Read the source. Every rule, threshold and scoring weight is in the repository, and each module states what it does not do as clearly as what it does.'
    : 'Ask about a specific calculation. Every rule, threshold and scoring weight is configuration rather than hidden behaviour, so a specific question has a specific answer - and a walkthrough of the code behind any number here can be arranged.',
  hasRepository
    ? 'Read the project notes. The repository records the bugs that a fully passing test suite did not catch, and what was changed to catch them next time - which is a more useful signal than a list of successes.'
    : 'Ask about the project notes. The bugs a fully passing test suite did not catch are written down, together with what changed to catch the next one - which is a more useful signal than a list of successes.',
];

export default function ServicesPage() {
  return (
    <>
      <PageHeader
        eyebrow="Consulting"
        title="SAP-focused analysis, built to be checked"
        lede="This site is a portfolio project. The tools in it are the working examples - every one of them runs, on data whose flaws are documented, with the calculations open to inspection."
      >
        <ContactCta href={CONTACT_CTA_HREF}>{CONTACT_CTA_LABEL}</ContactCta>
        <DemoCta variant="secondary" />
      </PageHeader>

      <Container>
        <Section title="Areas of work">
          <div className="grid gap-6 lg:grid-cols-2">
            {areas.map((area) => (
              <Card key={area.title} className="h-full">
                <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
                  {area.title}
                </h3>
                <p className="mt-3 leading-relaxed text-slate-600 dark:text-slate-400">
                  {area.body}
                </p>
                <div className="mt-5">
                  <ClaimList variant="computed" items={area.points} />
                </div>
              </Card>
            ))}
          </div>
        </Section>

        <Section
          title="How to evaluate this"
          lede="Rather than a list of claims, three things you can check yourself."
        >
          <div className="max-w-3xl">
            <ClaimList variant="plain" items={evaluationSteps} />
            <p className="mt-6 text-slate-600 dark:text-slate-400">
              The <TextLink href="/architecture">architecture page</TextLink> describes how it is
              deployed, and the <TextLink href="/platform">platform overview</TextLink> describes
              how it is built.
            </p>
          </div>
        </Section>

        <Section>
          <Callout title="What this page deliberately does not contain">
            <p>
              No client names, testimonials, certifications, partnerships, customer counts,
              production deployments or claimed savings. None of those exist for this project,
              and a portfolio that invents them is telling you something about how it would
              report your numbers too.
            </p>
            <p>
              Everything demonstrated here runs on fictional data. See the{' '}
              <TextLink href="/demo-disclaimer">demonstration disclaimer</TextLink>.
            </p>
          </Callout>
        </Section>

        <Section title="Get in touch">
          <div className="max-w-3xl space-y-6">
            <p className="text-slate-700 dark:text-slate-300">
              A short description of the data you have and the question you want answered is more
              useful than a specification.
            </p>
            {/*
              An internal link, not a `mailto:`. It carries the topic with it -
              `?service=consulting` opens the contact form with "Collaboration
              or consulting" already chosen - so the visitor lands somewhere
              that knows why they clicked, rather than in a blank compose
              window. The address is still one card below for anyone who would
              rather just write.
            */}
            <div>
              <ContactCta href={CONSULTING_CTA_HREF}>{CONSULTING_CTA_LABEL}</ContactCta>
            </div>
            <EmailCard
              title="Or email directly"
              body="Straight to the same inbox, read by a person. Nothing to fill in first."
              subject={`${siteConfig.name} — consulting enquiry`}
            />
          </div>
        </Section>
      </Container>
    </>
  );
}
