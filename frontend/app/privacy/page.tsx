import { Callout, ClaimList, Container, PageHeader, Section, TextLink } from '@/components/ui';
import { isContactFormAvailable } from '@/lib/contact/config';
import { pageMetadata } from '@/lib/metadata';
import { ACCESS_NOTICE, POLICY_LAST_UPDATED, UPLOAD_NOTICE, mailto, siteConfig } from '@/lib/site';

export const metadata = pageMetadata('/privacy');

/**
 * Rendered per request so the policy describes the deployment it is served
 * from.
 *
 * This page makes a factual claim about whether a submission endpoint exists,
 * and `CONTACT_FORM_ENABLED` decides the answer at run time. Statically
 * pre-rendering it would freeze that claim at build time, so an operator could
 * switch the form on and leave a privacy policy behind saying there isn't one.
 */
export const dynamic = 'force-dynamic';

export default function PrivacyPage() {
  const formEnabled = isContactFormAvailable();

  return (
    <>
      <PageHeader
        eyebrow="Privacy"
        title="Privacy"
        lede="A plain statement of what this website and the interactive demonstration do with information, written to describe what is deployed rather than what would sound reassuring."
      />

      <Container>
        <Section title="Scope of this page">
          <p className="max-w-3xl text-slate-700 dark:text-slate-300">
            Last updated: {POLICY_LAST_UPDATED}
          </p>
          <div className="mt-6 max-w-3xl space-y-4 text-slate-700 dark:text-slate-300">
            <p>
              This page covers two separate things: the public marketing website you are reading
              now, and the interactive demonstration hosted separately behind Cloudflare Access.
              They are different systems with different behaviour, and the sections below keep them
              apart.
            </p>
            <p>
              It describes a personal demonstration project in plain language. It has not been
              drafted or reviewed by a lawyer, it claims no compliance certification, and it will
              be revised when the behaviour it describes changes.
            </p>
          </div>
        </Section>

        <Section title="The public website">
          <div className="max-w-3xl">
            <ClaimList
              variant="plain"
              items={[
                'This public marketing website is accessible to anyone, requires no login and asks for no account.',
                formEnabled
                  ? 'No page calls the platform API from your browser. The contact form is the only place on this site that accepts anything you submit; there is no comment system or other submission endpoint, and what the form does with a message is set out under “Contacting the project” below.'
                  : 'Its pages are compiled at build time. No page calls the platform API from your browser, and there is no contact form, comment system or other submission endpoint on it.',
                'It embeds no advertising network, no third-party analytics and no social widgets, and sets no advertising or tracking cookies of its own.',
                'Cloudflare sits in front of the site and terminates the connection. Cloudflare operates its own logging, caching and protection, and may use cookies or similar technologies as part of that; what it retains is governed by Cloudflare’s own documentation and policies rather than by this project.',
                'Ordinary operational logging exists as it does for any web server - address, timestamp, path, response status, user agent - and is used to operate, secure and troubleshoot the service rather than to build a profile of you.',
              ]}
            />
          </div>
        </Section>

        <Section title="The interactive demonstration">
          <div className="max-w-3xl">
            <p className="text-slate-700 dark:text-slate-300">
              The demonstration is a separate application on its own hostname. {ACCESS_NOTICE}
            </p>
            <div className="mt-6">
              <ClaimList
                variant="plain"
                items={[
                  'Reaching it requires passing Cloudflare Access, whose policy is an explicit allow list of addresses. Approved visitors authenticate through the configured Cloudflare Access method, so the operator of that access layer processes the address used to sign in.',
                  'Cloudflare Access is currently the perimeter control. Verification of the Cloudflare access token inside the application itself has not been deployed, and the application does not yet provide internal role-based access control or tenant administration.',
                  'Signing in involves a session established by Cloudflare Access, and the demonstration interface maintains a browser session while you use it. This page does not claim that no cookies or session technologies are involved, because they are.',
                  'Anything you type into the demonstration is stored in a shared demonstration database that is not partitioned by visitor. Records created by one visitor may be visible to another.',
                  'The demonstration database holds fictional sample data and may be reset without notice. Nothing in it should be treated as durable.',
                  'The demonstration is configured to use a local mock AI provider, checked before any provider key is consulted, so text entered into it is not sent to Anthropic, OpenAI or any other AI provider.',
                ]}
              />
            </div>
          </div>
        </Section>

        <Section title="Uploads">
          <div className="max-w-3xl space-y-4 text-slate-700 dark:text-slate-300">
            <p>{UPLOAD_NOTICE}</p>
            <p>
              Upload requests are refused server-side in the public demonstration rather than
              hidden, so there is currently no route by which a file of yours reaches this project
              through the public demonstration. The repository does contain upload-handling code
              used when the project is run privately on a laptop; it is not reachable from the
              public demonstration. If secure uploads for approved users are enabled in future,
              this page will be updated before that happens rather than after.
            </p>
          </div>
        </Section>

        <Section title={formEnabled ? 'Contacting the project' : 'Contacting the project by email'}>
          <div className="max-w-3xl space-y-4 text-slate-700 dark:text-slate-300">
            {formEnabled ? (
              <>
                <p>
                  There are two ways to get in touch, and both reach the same mailbox: the{' '}
                  <TextLink href="/contact">contact form</TextLink>, or email directly to{' '}
                  <a
                    href={mailto(`${siteConfig.name} — privacy`)}
                    className="font-medium text-sky-700 underline underline-offset-4 dark:text-sky-400"
                  >
                    {siteConfig.contactEmail}
                  </a>
                  .
                </p>
                <p>
                  When you submit the form, the name, email address, subject and message you type
                  are used for one thing: composing an email that is sent immediately to that
                  mailbox. This website writes no copy of them - not to a database, not to a file,
                  and not to its logs, which record only that a submission succeeded or failed and
                  why.
                </p>
                <p>
                  Two things are handled and then discarded rather than stored. Cloudflare Turnstile
                  runs an anti-spam check, so your browser sends Cloudflare a token that this server
                  verifies with Cloudflare and then drops. To limit how often the form can be used
                  from one place, your network address and the email address you typed are each
                  converted into an unreadable keyed fingerprint held in memory, which is used only
                  for counting, is never written to disk or included in the email, and is lost when
                  the server restarts. The address itself is not retained.
                </p>
                <p>
                  What the form produces is an ordinary email. It is not loaded into this platform,
                  not stored in its database and not sent to an AI provider. It does pass through
                  Cloudflare, which fronts this site and performs the anti-spam check, and it is
                  then handled by the email providers on both sides and delivered into a Gmail
                  mailbox, where the message remains until it is deleted there. Cloudflare&rsquo;s
                  and Google&rsquo;s own processing and retention are governed by their policies
                  rather than by this project, which does not control them and does not claim to.
                </p>
              </>
            ) : (
              <>
                <p>
                  There is no contact form on this site. Contact is by email, to{' '}
                  <a
                    href={mailto(`${siteConfig.name} — privacy`)}
                    className="font-medium text-sky-700 underline underline-offset-4 dark:text-sky-400"
                  >
                    {siteConfig.contactEmail}
                  </a>
                  , which means nothing is posted to or stored by this website when you get in
                  touch.
                </p>
                <p>
                  A message you send arrives in an ordinary mailbox and is read by a person. It is
                  not loaded into this platform, not stored in its database and not sent to an AI
                  provider. It does pass through and rest with the email providers involved on both
                  sides, whose own retention and processing this project does not control and does
                  not claim to.
                </p>
              </>
            )}
            <p>
              Contact information you send voluntarily is not sold, and is not passed to anyone for
              advertising or marketing purposes.
            </p>
          </div>
        </Section>

        <Section title="How long information is kept">
          <p className="max-w-3xl text-slate-700 dark:text-slate-300">
            Information may be retained for as long as reasonably necessary to operate, secure,
            troubleshoot and respond through the service, subject to the behaviour of the
            infrastructure and service providers involved. Where a specific retention period is set
            by Cloudflare, by an email provider or by another third party, that period is theirs
            rather than this project’s, and this page does not restate it as though it were.
          </p>
        </Section>

        <Section>
          <Callout title="Do not send confidential or sensitive information" tone="warning">
            <p>
              Please do not enter confidential, personal, medical, financial, regulated,
              credential, production SAP, customer or otherwise proprietary information into the
              demonstration, and do not email it either. The demonstration is a shared environment
              running on fictional data, and email is an ordinary mailbox.
            </p>
            <p>
              The full list of what not to enter is on the{' '}
              <TextLink href="/demo-disclaimer">demonstration disclaimer</TextLink>.
            </p>
          </Callout>
        </Section>

        <Section title="Questions or a request about your information">
          <p className="max-w-3xl text-slate-700 dark:text-slate-300">
            Write to{' '}
            <a
              href={mailto(`${siteConfig.name} — data request`)}
              className="font-medium text-sky-700 underline underline-offset-4 dark:text-sky-400"
            >
              {siteConfig.contactEmail}
            </a>
            . A request to delete correspondence held in the project’s own mailbox will be actioned;
            what a third-party provider retains in its own logs and backups is outside this
            project’s control, so no promise is made here on its behalf.
          </p>
        </Section>
      </Container>
    </>
  );
}
