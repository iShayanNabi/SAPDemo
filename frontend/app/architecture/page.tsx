import type { Metadata } from 'next';
import { DemoCta } from '@/components/DemoCta';
import { Callout, Card, ClaimList, Container, PageHeader, Section, TextLink } from '@/components/ui';
import { ACCESS_NOTICE, UPLOAD_NOTICE } from '@/lib/site';

export const metadata: Metadata = {
  title: 'Architecture',
  description:
    'How Procurement Intelligence Demo is deployed: a public Next.js website and a Streamlit demonstration behind Cloudflare Access, reached through an outbound Cloudflare Tunnel, with a FastAPI backend and PostgreSQL that are never published.',
  alternates: { canonical: '/architecture' },
};

export default function ArchitecturePage() {
  return (
    <>
      <PageHeader
        eyebrow="Architecture"
        title="An API-driven platform, and a deployment with nothing published"
        lede="The backend is the product; the interfaces are clients of it. That separation is what lets a Streamlit demonstration and a Next.js website coexist without either owning a business rule - and it is what makes it possible to expose neither the API nor the database to the internet."
      >
        <DemoCta />
      </PageHeader>

      <Container>
        <Section
          title="The deployment"
          lede="Five containers on one machine, on two private networks, with no inbound port open on the router."
        >
          <div className="overflow-x-auto rounded-xl border border-slate-200 bg-slate-50 p-4 sm:p-6 dark:border-slate-800 dark:bg-slate-900">
            <pre className="min-w-[34rem] text-xs leading-relaxed text-slate-700 sm:text-sm dark:text-slate-300">
{`  visitor
     │  https
     ▼
  ┌──────────────────────┐
  │  edge network        │        outbound connection only -
  │  ┌────────────────┐  │        nothing listens on the router
  │  │ Cloudflare     │──┼───────▶  (cloudflared dials out to Cloudflare)
  │  │ Tunnel client  │  │
  │  └───────┬────────┘  │
  │          │           │
  │   ┌──────▼──────┐  ┌─▼───────────┐
  │   │  website    │  │  streamlit  │
  │   │  Next.js    │  │  demo UI    │
  │   │  :3000      │  │  :8501      │
  │   └─────────────┘  └─────┬───────┘
  └──────────────────────────┼──────┘
                             │  http://api:8000
  ┌──────────────────────────┼──────┐
  │  internal network        ▼      │  no route to the internet
  │                    ┌──────────┐ │
  │                    │  api     │ │
  │                    │  FastAPI │ │
  │                    └────┬─────┘ │
  │                         │       │
  │                    ┌────▼─────┐ │
  │                    │ postgres │ │
  │                    └──────────┘ │
  └─────────────────────────────────┘`}
            </pre>
          </div>
          <p className="mt-6 max-w-3xl text-slate-600 dark:text-slate-400">
            The website is on the edge network so the tunnel can reach it, and on nothing else -
            it has no route to the API or the database, because it never calls them. The
            demonstration UI is on both, because it is the only thing that talks to the API.
          </p>
          <p className="mt-4 max-w-3xl text-slate-600 dark:text-slate-400">
            Reading it from the outside in: a public Next.js website, a Streamlit demonstration
            interface behind Cloudflare Access, a FastAPI backend holding every rule and
            calculation, and a PostgreSQL database. The two hostnames are served by the same
            outbound Cloudflare Tunnel; nothing about the tunnel, its credentials or the host it
            runs on is published here or anywhere else on this site.
          </p>
        </Section>

        <Section title="What is reachable, and what is not">
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
                Reachable from the internet
              </h3>
              <div className="mt-4">
                <ClaimList
                  variant="plain"
                  items={[
                    'The public marketing website, which requires no authentication and asks for no account.',
                    'The interactive demonstration, on its own hostname, behind Cloudflare Access with a policy that is an explicit allow list.',
                  ]}
                />
              </div>
            </Card>
            <Card>
              <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
                Not reachable at all
              </h3>
              <div className="mt-4">
                <ClaimList
                  variant="plain"
                  items={[
                    'The API. It has no public hostname and publishes no port.',
                    'The database. It publishes no port and sits on a network with no internet route.',
                    'The host machine, its administration interfaces and its backups.',
                  ]}
                />
              </div>
            </Card>
          </div>
        </Section>

        <Section
          title="Why the website never calls the API"
          lede="It is the single decision that removes the largest attack surface."
        >
          <div className="max-w-3xl space-y-4 text-slate-700 dark:text-slate-300">
            <p>
              Everything the website says is content about the platform, compiled into the pages
              at build time. No page fetches anything at runtime, so there is no browser-facing
              API endpoint, no public API hostname, no CORS policy to get wrong and no key to
              leak into a JavaScript bundle.
            </p>
            <p>
              The interactive demonstration does call the API - over a private container network,
              by service name, on a port that is never published. A visitor&apos;s browser talks to
              the demonstration UI; the demonstration UI talks to the API. Nothing crosses that
              boundary in the other direction.
            </p>
          </div>
        </Section>

        <Section
          title="The API contract"
          lede="Built so a different front end could replace the demonstration UI without touching a line of business logic."
        >
          <div className="max-w-3xl">
            <ClaimList
              variant="computed"
              items={[
                'One response envelope for every endpoint: success, data, error, meta - including on errors, so a client writes one error path rather than two.',
                'A request identifier on every response and in every log line, so a report of "it failed" can be traced to the exact request.',
                'An OpenAPI document generated from the code, with the error shapes documented per module.',
                'Errors that never carry a filesystem path, a stack trace, a database URL or a provider payload. The detail goes to the log; the caller gets a safe message.',
                'Authentication declared as a seam - a principal, roles and a tenant scope - and honestly reported as not enforced inside the application, because there are no internal accounts behind it yet.',
              ]}
            />
          </div>
        </Section>

        <Section
          title="How the demonstration is protected, and how far that goes"
          lede="Worth stating precisely, because the perimeter and the application are two different questions and only one of them is answered today."
        >
          <div className="max-w-3xl space-y-4 text-slate-700 dark:text-slate-300">
            <p>{ACCESS_NOTICE}</p>
            <p>
              Cloudflare Access is currently the perimeter control: it decides who reaches the
              demonstration hostname at all. Verification of the Cloudflare access token
              <em> inside</em> the Streamlit application has not been deployed, so the application
              itself does not independently check who a request came from. The public marketing
              website is deliberately not behind Access and requires no authentication.
            </p>
          </div>
        </Section>

        <Section title="What runs behind the demonstration">
          <div className="max-w-3xl">
            <ClaimList
              variant="plain"
              items={[
                'Deterministic Python does every calculation: rules, thresholds, matching, weighted scoring, aggregation and rubric marking.',
                'Statistical models produce the forecasts and stock projections, selected by backtesting and reported with the model that won.',
                'The AI provider is an abstraction over Anthropic, OpenAI and a local mock. The public demonstration is configured to use the mock, and that is checked before any provider key is consulted.',
                'Each module runs on its bundled fictional dataset, generated by a seeded script with its planted anomalies documented in a manifest.',
              ]}
            />
            <p className="mt-6 text-slate-700 dark:text-slate-300">{UPLOAD_NOTICE}</p>
          </div>
        </Section>

        <Section>
          <Callout title="Stated limitations" tone="warning">
            <p>
              The application does not maintain internal user accounts, roles, organisations or
              tenant administration, so records created by one visitor to the demonstration are
              visible to another through the API. Cloudflare Access in front of the hostname and
              session-scoped views reduce that exposure; they do not replace per-user ownership,
              and this project does not claim they do.
            </p>
            <p>
              The deployment runs on a single machine. It is a demonstration, not a
              high-availability service, and it is not offered as commercially
              production-ready. See <TextLink href="/terms">terms and disclaimer</TextLink>.
            </p>
          </Callout>
        </Section>
      </Container>
    </>
  );
}
