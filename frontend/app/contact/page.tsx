import type { Metadata } from 'next';
import { Suspense } from 'react';
import { Callout, Container, PageHeader, Section, TextLink } from '@/components/ui';
import { ContactForm } from '@/components/ContactForm';
import { DemoCta } from '@/components/DemoCta';
import { EMAIL_CARD_LABEL, EmailCard, emailCardLabel } from '@/components/EmailCard';
import { isContactFormAvailable, turnstileSiteKey } from '@/lib/contact/config';
import { mailto, siteConfig } from '@/lib/site';

/**
 * Read at request time, on the server.
 *
 * `isContactFormAvailable()` is true only when the operator asked for the form
 * *and* every secret it needs is present. A deployment that sets
 * `CONTACT_FORM_ENABLED=true` and forgets `TURNSTILE_SECRET_KEY` therefore gets
 * this page exactly as it was before the form existed, rather than a form whose
 * submissions all fail - and the privacy page, reading the same function, keeps
 * describing what actually shipped.
 */
export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: 'Contact',
  description:
    'How to get in touch about Procurement Intelligence Demo: consulting enquiries, questions about the platform, and access to the interactive demonstration.',
  alternates: { canonical: '/contact' },
};

/**
 * The three things worth writing about, each a card that *is* the email action.
 *
 * `about` is the suffix on the accessible name. Three links reading "Email
 * Solve AI Hub at solveaihub@gmail.com" would be three identical entries in a
 * screen reader's link list, which is the same problem as three links called
 * "click here".
 */
const reasons = [
  {
    title: 'Consulting enquiry',
    body: 'Procurement or supply-chain analysis, rule engines, document extraction, or drawing the line between calculation and language models in a system you are building.',
    subject: `${siteConfig.name} — consulting enquiry`,
    about: 'a consulting enquiry',
  },
  {
    title: 'A question about the platform',
    body: 'How a module calculates something, why a result looks the way it does, or how the deployment is put together. Every threshold and weight is configuration rather than hidden behaviour, so a specific question usually has a specific answer.',
    subject: `${siteConfig.name} — question about the platform`,
    about: 'a question about the platform',
  },
  {
    title: 'Access to the demonstration',
    body: 'The interactive demonstration sits behind Cloudflare Access, whose policy is an explicit allow list. If you have been asked to review it and cannot get in, this is the address to use.',
    subject: `${siteConfig.name} — demonstration access`,
    about: 'access to the demonstration',
  },
] as const;

export default function ContactPage() {
  const formEnabled = isContactFormAvailable();
  const siteKey = turnstileSiteKey();

  return (
    <>
      <PageHeader
        eyebrow="Contact"
        title="Get in touch"
        lede={
          formEnabled
            ? 'Send a message with the form below, or email the same address directly - both reach the same inbox.'
            : 'Email is the only channel, and that is deliberate - see the note below about why there is no contact form.'
        }
      >
        {/*
          A direct-email action, labelled as one.

          The button used to print `solveaihub@gmail.com` as its own text,
          sitting beside Launch interactive demo - so the pair of buttons at the
          top of this page read as an address and a demo rather than as two
          actions, and on a machine with no mail client configured the first one
          appeared to do nothing when pressed. A button's label says what
          pressing it does; the address itself belongs in the cards below, which
          exist to print it, and in the footer.

          `aria-label` still names the action *and* the address, so a screen
          reader announces where the message is going before it is opened. The
          focus ring matches every other call to action, because a keyboard user
          has to be able to see where they are.
        */}
        <a
          href={mailto(`${siteConfig.name} enquiry`)}
          aria-label={EMAIL_CARD_LABEL}
          className="inline-flex items-center justify-center rounded-lg bg-sky-600 px-5 py-3 text-base font-semibold text-white transition-colors hover:bg-sky-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600"
        >
          Email us directly
        </a>
        <DemoCta variant="secondary" />
      </PageHeader>

      <Container>
        <Section title="What are you writing about?">
          <ul className="grid gap-6 lg:grid-cols-3">
            {reasons.map((reason) => (
              <li key={reason.title} className="h-full">
                <EmailCard
                  title={reason.title}
                  body={reason.body}
                  subject={reason.subject}
                  ariaLabel={emailCardLabel(reason.about)}
                />
              </li>
            ))}
          </ul>
        </Section>

        {formEnabled ? (
          <Section title="Send a message">
            <p className="mb-6 max-w-2xl text-slate-700 dark:text-slate-300">
              This form emails the same address as the links above. Nothing you type is stored by
              this website - see <TextLink href="/privacy">the privacy page</TextLink> for what
              happens to it afterwards.
            </p>
            {/*
              `ContactForm` reads `?service=` to preselect a topic, and
              `useSearchParams` requires a Suspense boundary for any page Next
              might try to prerender. This page is `force-dynamic` so it never
              is - the boundary is here anyway, because the failure without one
              is a build error naming neither the hook nor the file.
            */}
            <Suspense fallback={null}>
              <ContactForm siteKey={siteKey} />
            </Suspense>
          </Section>
        ) : (
          <Section>
            <Callout title="Why there is no contact form">
              <p>
                A form needs somewhere to post to. That means an endpoint on this machine accepting
                unauthenticated writes from anyone on the internet, and a place to keep what they
                send - which is a spam target, a storage obligation and a new class of vulnerability
                in exchange for saving you one click.
              </p>
              <p>
                A{' '}
                <code className="rounded bg-slate-200 px-1 py-0.5 text-xs dark:bg-slate-800">
                  mailto:
                </code>{' '}
                link posts nothing, stores nothing and reaches the same inbox. The{' '}
                <TextLink href="/architecture">architecture page</TextLink> explains the same
                reasoning applied to the API, which is also not publicly reachable.
              </p>
            </Callout>
          </Section>
        )}

        <Section title="What happens to what you send">
          <div className="max-w-3xl space-y-4 text-slate-700 dark:text-slate-300">
            {formEnabled ? (
              <p>
                A message sent through the form is checked by Cloudflare Turnstile, emailed
                straight to an ordinary inbox and read by a person. This website writes no copy of
                it: not to its database, not to a file, not to a log. It is not processed by the
                platform and not sent to a language model.
              </p>
            ) : (
              <p>
                An email you send arrives in an ordinary inbox and is read by a person. It is not
                processed by this platform, not stored in its database and not sent to a language
                model.
              </p>
            )}
            {formEnabled ? (
              <p>
                It does pass through Cloudflare, which fronts this site and runs the anti-spam
                check, and it then rests in a Gmail mailbox and with the email providers on both
                sides. Their own retention is outside this project&rsquo;s control, and a delivered
                message stays in that mailbox until it is deleted there.
              </p>
            ) : (
              <p>
                It does pass through and rest with the email providers on both sides, whose own
                retention this project does not control.
              </p>
            )}
            <p>
              Please do not send confidential data, personal data about other people, credentials,
              or real SAP exports. If a conversation needs real data, that is a conversation to
              have before any data moves. See the <TextLink href="/privacy">privacy page</TextLink>.
            </p>
          </div>
        </Section>
      </Container>
    </>
  );
}
