# GoDaddy nameserver change

Pointing your domain's nameservers at Cloudflare. This is a **manual step in
your own GoDaddy account**; nothing in this repository does it, and it has not
been done.

Do this after adding the domain to Cloudflare (step 1 of
[`CLOUDFLARE_TUNNEL_SETUP.md`](CLOUDFLARE_TUNNEL_SETUP.md)) and before anything
else, because propagation takes time.

---

## What actually changes

Changing nameservers moves **all** DNS authority for the domain to Cloudflare.
GoDaddy stops answering for it. Every record — mail, verification, subdomains —
now has to exist in Cloudflare, or it does not exist at all.

This is the step where email breaks, and it breaks quietly. Nothing bounces
loudly at you; messages just stop arriving, and somebody mentions it a week
later.

---

## 1. Write down what you have now

**Before touching anything.** Do this even though Cloudflare's scan usually
imports the records — *usually* is not a good enough basis for your mail.

GoDaddy: **My Products → Domain → DNS → Manage Zones**.

Export or screenshot the whole zone, then specifically record:

| Type | Why it matters |
| --- | --- |
| `MX` | Inbound mail. Missing → mail stops. |
| `TXT` starting `v=spf1` | Outbound mail passes SPF. Missing → your mail is spam. |
| `TXT` at `selector._domainkey` | DKIM signing. Missing → same. |
| `TXT` at `_dmarc` | DMARC policy. Missing → same, and you lose reporting. |
| `TXT` verification records | Google, Microsoft, Apple, anything that asked you to prove ownership. Missing → silently un-verified. |
| `CNAME` | Anything already pointing somewhere that should keep working. |
| `A` / `AAAA` | Anything currently hosted. |

Keep this list. You need it in step 3, and again if you ever roll back.

A quick capture from a terminal:

```bash
DOMAIN=example.com
for t in NS MX TXT A AAAA CNAME SOA; do echo "--- $t"; dig +short "$DOMAIN" "$t"; done
dig +short _dmarc."$DOMAIN" TXT
dig +short default._domainkey."$DOMAIN" TXT   # selector varies by provider
```

Save the output to a file outside the repository.

---

## 2. Check what Cloudflare imported

In Cloudflare, **DNS → Records**. Compare against your list from step 1.

Add anything missing **now**, while GoDaddy is still authoritative and nothing
has broken yet.

Two things to get right:

- **MX records and mail-related `TXT` records must be DNS-only** (grey cloud,
  not orange). Proxying an MX record breaks mail delivery.
- **`A`/`AAAA` records for services you host elsewhere** should usually stay
  DNS-only too, unless you specifically want Cloudflare in front of them.

---

## 3. Change the nameservers at GoDaddy

1. **My Products → Domain → DNS → Nameservers → Change**.
2. Choose **I'll use my own nameservers** (wording varies).
3. Enter the two Cloudflare gave you — they look like
   `xxx.ns.cloudflare.com`. Enter them exactly; a typo is a domain that stops
   resolving entirely.
4. Save. GoDaddy may ask you to confirm you understand DNS moves away.

If the domain has **domain protection** enabled you may need to unlock it first.

---

## 4. Wait, and verify

Propagation is usually 15 minutes to 2 hours, occasionally up to 48.

```bash
dig +short NS example.com          # expect the Cloudflare pair
dig +short MX example.com          # expect your mail records, unchanged
dig +short TXT example.com         # expect your SPF record, unchanged
```

Cloudflare's dashboard reports the domain **Active** when it has taken over.

### Test mail before you trust it

```bash
# Send yourself a message from an external address and confirm it arrives.
# Then send one FROM the domain to an external address and check the headers
# show spf=pass and dkim=pass.
```

Do this on the day you make the change. Finding out later is the failure mode
this page exists to prevent.

---

## 5. Then continue

Return to [`CLOUDFLARE_TUNNEL_SETUP.md`](CLOUDFLARE_TUNNEL_SETUP.md) step 2 and
create the tunnel.

---

## Rolling back

1. In GoDaddy, **Nameservers → Change → I'll use GoDaddy's nameservers**.
2. Restore every record from step 1 in GoDaddy's DNS editor. They will not come
   back on their own — this is why you wrote them down.
3. Wait for propagation and re-test mail.

Rolling back is slower than rolling forward. Keeping that record list is the
whole difference between a ten-minute rollback and an afternoon.

---

## What this repository does not do

It does not log in to GoDaddy, read your domain, change nameservers, create,
modify or delete any DNS record. Every step above is yours, in your own account,
in a browser.
