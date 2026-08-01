# Cloudflare Tunnel setup

Everything in this file is a **manual step you perform in your own account**.
Nothing here has been done for you: no tunnel exists, no DNS record has been
created, no token is stored anywhere in this repository, and the deployment has
never been published.

Do the GoDaddy nameserver change first —
[`GODADDY_NAMESERVER_SETUP.md`](GODADDY_NAMESERVER_SETUP.md) — because it takes
time to propagate and everything below depends on it.

---

## Why a tunnel rather than port forwarding

`cloudflared` makes an **outbound** connection to Cloudflare and traffic comes
back down it. Consequences worth being explicit about:

- **No router port forwarding.** Nothing listens on your public IP; there is no
  inbound rule to create and none to forget about later.
- **No inbound firewall hole.** The stack publishes no host port at all in the
  deployed configuration — `docker compose ps` shows no `->` mapping.
- **Your home IP address is not published.** Visitors resolve Cloudflare.
- **TLS is terminated by Cloudflare.** No certificate to obtain or renew on the
  Mac.

The trade is a dependency on Cloudflare and on your internet connection. Both
are stated in [`SELF_HOSTED_TROUBLESHOOTING.md`](SELF_HOSTED_TROUBLESHOOTING.md).

---

## The routes to create

| Public hostname | Service | Notes |
| --- | --- | --- |
| `[DOMAIN]` | `http://website:3000` | Public marketing site |
| `www.[DOMAIN]` | `http://website:3000` | Same site |
| `demo.[DOMAIN]` | `http://streamlit:8501` | **Behind Access** |

`website` and `streamlit` are Docker service names on the `sapdemo-edge`
network. `cloudflared` resolves them because it is on that network; it is on no
other.

### There is deliberately no `api.[DOMAIN]`

Do not create one, and do not add a route to `http://api:8000`.

The API has no public hostname by design. It publishes no port, sits on a
network declared `internal: true`, and the only thing that talks to it is the
demonstration UI over that private network. The website never calls it — every
page is compiled at build time — so there is nothing a public API hostname
would enable except exposure.

`cloudflared` is deliberately **not** attached to the internal network, so a
route to the API cannot work even if one is created by accident.

---

## 1. Add the domain to Cloudflare

1. Sign in to Cloudflare and choose **Add a site**.
2. Enter your domain, choose the **Free** plan.
3. Cloudflare scans the existing DNS records. **Read that list carefully before
   continuing.**

### Preserve these records

Cloudflare's scan usually finds them, and *usually* is not good enough — email
stops working quietly and you find out days later when somebody mentions they
never got a reply.

Write down, then confirm afterwards:

- **MX** — mail delivery. Miss these and inbound mail stops.
- **SPF** (`TXT` beginning `v=spf1`) — miss it and your outbound mail is spam.
- **DKIM** (`TXT`, often `selector._domainkey`) — same.
- **DMARC** (`TXT` at `_dmarc`) — same.
- **Domain verification records** — Google, Microsoft, Apple, anything else that
  asked you to prove ownership. Removing one silently un-verifies the service.
- **Existing CNAMEs** — anything already pointing somewhere that should keep
  working.

MX and mail-related `TXT` records must be **DNS-only** (grey cloud), not
proxied. Proxying an MX record breaks mail.

4. Cloudflare gives you two nameservers. Take them to
   [`GODADDY_NAMESERVER_SETUP.md`](GODADDY_NAMESERVER_SETUP.md).

Wait for Cloudflare to report the domain **Active** before continuing. Usually
minutes; allow up to 24 hours.

---

## 2. Create a remotely-managed tunnel

**Zero Trust → Networks → Tunnels → Create a tunnel → Cloudflared.**

Name it something you will recognise in a year: `sapdemo-macbook`.

Cloudflare shows an install command containing a long token. **You need only the
token**, not the command — the `cloudflared` container is already in the compose
file.

### Handling the token

The token authenticates a connector to your tunnel. Anyone holding it can serve
traffic as this deployment.

```bash
# On the MacBook, in the repository:
$ nano .env.selfhosted
CLOUDFLARE_TUNNEL_TOKEN=<paste it here>
```

- `.env.selfhosted` is git-ignored, and a test asserts no `.env` file except the
  examples is ever tracked.
- **Do not** paste it into a commit, an issue, a screenshot, a chat message or a
  terminal you are recording.
- **Do not** add it before the pull request has been reviewed and merged.
- If it is ever exposed, delete the tunnel in the dashboard and create a new
  one. Rotating is cheap; hoping is not.

Nothing in this repository prints the token. `status_selfhosted.sh` reports
`(set, N characters)`, and `verify_selfhosted.sh` greps the container logs for
the actual value and fails if it appears.

---

## 3. Add the public hostnames

In the tunnel's **Public Hostname** tab, add three:

| Subdomain | Domain | Type | URL |
| --- | --- | --- | --- |
| *(blank)* | `[DOMAIN]` | HTTP | `website:3000` |
| `www` | `[DOMAIN]` | HTTP | `website:3000` |
| `demo` | `[DOMAIN]` | HTTP | `streamlit:8501` |

`HTTP` rather than `HTTPS` is correct: the hop from Cloudflare's edge to your
Mac is the encrypted tunnel, and the hop from `cloudflared` to the container is
inside a private Docker network. There is no certificate on the container to
validate.

Cloudflare creates the proxied DNS records for these automatically.

---

## 4. Start the connector

```bash
./scripts/start_selfhosted.sh
./scripts/status_selfhosted.sh
```

`cloudflared` should be `running`. If it is `restarting`, the token is missing
or wrong — that is also the expected state *before* you add one, and both
`status_selfhosted.sh` and `verify_selfhosted.sh` say so rather than reporting a
fault.

```bash
./scripts/logs_selfhosted.sh cloudflared
```

`Registered tunnel connection` (usually four of them) means it is connected.

---

## 5. Protect the demonstration with Access

**Do this before the demonstration hostname resolves for anyone else.**

**Zero Trust → Access → Applications → Add an application → Self-hosted.**

| Setting | Value |
| --- | --- |
| Application name | `SAPDemo demonstration` |
| Session duration | `24 hours` |
| Subdomain / domain | `demo` / `[DOMAIN]` |

Then add a policy:

| Setting | Value |
| --- | --- |
| Policy name | `Invited reviewers` |
| Action | **Allow** |
| Include | **Emails** → the exact addresses, one per line |

Under **Login methods**, enable **One-time PIN** only.

### Configure this deliberately

- **Use `Emails`, not `Emails ending in`.** A domain rule lets everyone at that
  domain in, which is not what an invitation is.
- **Do not use `Everyone` with one-time PIN.** That is unrestricted access with
  an email prompt in front of it — anybody with any address gets in. It looks
  like a control and is not one.
- **Add a default-deny.** Access denies anything not explicitly allowed, but add
  an explicit **Block / Everyone** policy *below* the allow rule so the intent is
  visible to whoever reads it next.
- **24 hours** balances not re-authenticating constantly against a laptop left
  open in a café. Shorten it for a wider list.

The marketing site stays public — do not put an Access application in front of
`[DOMAIN]` or `www.[DOMAIN]`.

---

## 6. Test it

From a device on a **different network** — cellular data, not your wifi. On your
own wifi a DNS cache can make a broken setup look fine.

```
https://[DOMAIN]        -> the website, no login
https://www.[DOMAIN]    -> the website, no login
https://demo.[DOMAIN]   -> an Access login prompt
```

Then, on the demonstration:

1. Enter an allow-listed address, receive the PIN, enter it.
2. Confirm the `Public Demo — Fictional Data Only` banner is present.
3. Confirm no file-upload control appears anywhere.
4. Run a guided demonstration end to end and download a report.

And confirm these **fail**:

```
https://api.[DOMAIN]        -> must not resolve. If it does, delete the route.
https://[DOMAIN]:5432       -> must not connect.
```

Try the Access login with an address that is *not* on the list. It must be
refused. An allow list nobody has tested against a non-member is an assumption.

---

## Never expose through the tunnel

Adding any of these as a public hostname would undo the design:

- FastAPI (`api:8000`) — no public hostname, ever
- PostgreSQL (`database:5432`)
- The Docker socket or Docker Desktop
- SSH or macOS Screen Sharing
- Any host administration interface
- The backup directory
- A database management tool (pgAdmin, Adminer)
- Any development server

`cloudflared` is on the `edge` network only, which makes the first two
unreachable regardless of what is configured. The rest are on you.

---

## Rollback

Fastest to slowest:

1. **Stop serving:** `./scripts/stop_selfhosted.sh`. The tunnel has no connector
   and the hostnames return a Cloudflare error page.
2. **Remove the routes:** delete the public hostnames in the tunnel. DNS records
   go with them.
3. **Delete the tunnel:** invalidates the token.
4. **Revert DNS:** point the nameservers back at GoDaddy —
   [`GODADDY_NAMESERVER_SETUP.md`](GODADDY_NAMESERVER_SETUP.md) has the record
   list to restore first.

---

## What is still manual after a merge

Everything on this page. The repository contains the compose service, the
environment placeholder, the scripts and this document. It contains no token,
no tunnel, no DNS record and no Access policy, and running any script here
creates none of them.
