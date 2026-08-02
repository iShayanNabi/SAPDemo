import type { Metadata } from 'next';
import { Callout, ClaimList, Container, PageHeader, Section, TextLink } from '@/components/ui';
import { mailto, siteConfig } from '@/lib/site';

export const metadata: Metadata = {
  title: 'Privacy',
  description:
    'What Procurement Intelligence Demo collects, what it does not, and how to get in touch about it. A placeholder statement pending a full policy.',
  alternates: { canonical: '/privacy' },
};

export default function PrivacyPage() {
  return (
    <>
      <PageHeader
        eyebrow="Privacy"
        title="Privacy"
        lede="A plain statement of what this site and demonstration do with data. It is a placeholder, not a lawyer-reviewed policy, and it says so."
      />

      <Container>
        <Section title="Status of this page">
          <Callout title="This is a placeholder" tone="warning">
            <p>
              This page describes the current behaviour of a personal demonstration project
              accurately, but it has not been reviewed by a lawyer and is not a compliance
              document. If you need a formal privacy policy before engaging, say so and one will
              be produced rather than improvised here.
            </p>
          </Callout>
        </Section>

        <Section title="This website">
          <div className="max-w-3xl">
            <ClaimList
              variant="plain"
              items={[
                'The website is static content. It has no accounts, no login, no contact form and no comment system.',
                'It sets no advertising or tracking cookies and embeds no third-party analytics, social widgets or fonts loaded from another host.',
                'It makes no requests to the platform API from your browser - every page is compiled at build time.',
                'Standard server request logs (address, timestamp, path, user agent) exist as they do for any web server, and are used for operation and troubleshooting rather than profiling.',
                'The network provider that serves the site operates its own logging and protection, described in that provider’s own documentation.',
              ]}
            />
          </div>
        </Section>

        <Section title="The interactive demonstration">
          <div className="max-w-3xl">
            <ClaimList
              variant="plain"
              items={[
                'It is protected by an access policy with an explicit allow list. Reaching it requires a one-time code sent to an address on that list, so the operator of the access layer processes that address.',
                'It has no user accounts. Anything you type into it is stored in a shared demonstration database that is not partitioned by visitor.',
                'File uploads are disabled and refused server-side.',
                'No text you enter is sent to an AI provider: the demonstration runs a local mock and has no provider key configured.',
                'The demonstration database holds fictional sample data and may be reset without notice. Do not put anything in it you would mind losing - or anyone else seeing.',
              ]}
            />
            <p className="mt-6 text-slate-700 dark:text-slate-300">
              The full list of what not to enter is on the{' '}
              <TextLink href="/demo-disclaimer">demonstration disclaimer</TextLink>.
            </p>
          </div>
        </Section>

        <Section title="Email">
          <p className="max-w-3xl text-slate-700 dark:text-slate-300">
            If you email{' '}
            <a
              href={mailto(`${siteConfig.name} — privacy`)}
              className="font-medium text-sky-700 underline underline-offset-4 dark:text-sky-400"
            >
              {siteConfig.contactEmail}
            </a>
            , the message arrives in an ordinary mailbox and is read by a person. It is kept for
            as long as the conversation is useful and is not fed into this platform or any AI
            provider. Ask and it will be deleted.
          </p>
        </Section>

        <Section title="Questions or a deletion request">
          <p className="max-w-3xl text-slate-700 dark:text-slate-300">
            Write to{' '}
            <a
              href={mailto(`${siteConfig.name} — data request`)}
              className="font-medium text-sky-700 underline underline-offset-4 dark:text-sky-400"
            >
              {siteConfig.contactEmail}
            </a>
            . Given the above there is unlikely to be much to delete, which is the intended
            design rather than an accident.
          </p>
        </Section>
      </Container>
    </>
  );
}
