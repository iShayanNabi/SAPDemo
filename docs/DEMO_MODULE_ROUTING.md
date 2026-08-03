# Module-specific demonstration links

How a public tool page on `https://solveaihub.com` opens *its own* module inside
the protected demonstration at `https://demo.solveaihub.com`, instead of sending
every visitor to the same home page and asking them to find it again.

```
Public tool page                         solveaihub.com/tools/invoice-validator
        │
        │  Launch interactive demo
        ▼
Module-specific demo URL                 demo.solveaihub.com/?module=invoice-validator
        │
        ▼
Cloudflare Access                        authenticates the visitor when required
        │
        ▼
Streamlit reads ?module=                 validates against a fixed allowlist
        │
        ▼
Invoice Validator page opens
```

---

## The URL format

| Destination | URL |
| --- | --- |
| The demonstration home page | `https://demo.solveaihub.com/` |
| One module | `https://demo.solveaihub.com/?module=<identifier>` |

Nothing else is added to the query string, and the parameter is dropped from the
address bar as soon as it has been used - see *What happens on a rerun* below.

## The ten identifiers

Stable public values. They appear in links people bookmark and paste, so they
are deliberately **not** the display name, the marketing slug, the API module id
or the Streamlit page file name - each of those is free to change for reasons
that have nothing to do with a link.

| Public tool page | `?module=` | Streamlit page |
| --- | --- | --- |
| `/tools/purchase-order-risk-checker` | `po-risk` | `pages/1_PO_Risk_Checker.py` |
| `/tools/spend-analytics-dashboard` | `spend-analytics` | `pages/2_Spend_Analytics.py` |
| `/tools/supplier-recommendation-engine` | `supplier-recommendation` | `pages/3_Supplier_Recommendations.py` |
| `/tools/invoice-validator` | `invoice-validator` | `pages/4_Invoice_Validator.py` |
| `/tools/supplier-risk-copilot` | `supplier-risk` | `pages/5_Supplier_Risk_Copilot.py` |
| `/tools/contract-assistant` | `contract-assistant` | `pages/6_Contract_Assistant.py` |
| `/tools/inventory-predictor` | `inventory-predictor` | `pages/7_Inventory_Predictor.py` |
| `/tools/sap-test-case-generator` | `test-case-generator` | `pages/8_Test_Case_Generator.py` |
| `/tools/sap-blueprint-generator` | `blueprint-generator` | `pages/9_SAP_Blueprint_Generator.py` |
| `/tools/sap-interview-coach` | `interview-coach` | `pages/10_SAP_Interview_Coach.py` |

---

## Where the list lives, and why there are two of them

| Side | File |
| --- | --- |
| Website | `frontend/lib/demo.ts` - the identifiers, and `buildDemoUrl()` |
| Website content | `frontend/content/modules.ts` - which tool carries which identifier |
| Application | `streamlit_app/components/routing.py` - identifier to page |

One shared JSON file read by both languages would be the obvious arrangement,
and it does not fit this repository. The website image is built with
`context: ./frontend` (`docker-compose.selfhosted.yml`), so a file at the
repository root is not in the build context and `next build` cannot import it;
putting it under `frontend/` would mean the Python application reads its routing
table out of the website's source tree, and the two are separate containers.

So each side owns a typed list, and
`tests/integration/test_demo_module_contract.py` is the seam: it parses the
TypeScript, compares it with the Python, and fails on a missing identifier, an
extra one, or one that resolves to the wrong page.

## The website helper

`buildDemoUrl()` in `frontend/lib/demo.ts` is the only place a demonstration
address is built.

- `buildDemoUrl()` - the general demonstration home page.
- `buildDemoUrl('po-risk')` - one module.

It reads `NEXT_PUBLIC_DEMO_URL`, which already existed and whose Docker and
environment mapping is unchanged.

**The default protected-demonstration origin is `https://demo.solveaihub.com/`.**
Missing, blank, whitespace-only, malformed, credential-carrying and
unsupported-protocol values all fall back to it. That is a deliberate exception
to this repository's rule that address defaults are placeholders, and the reason
is that the usual argument does not hold here: a placeholder is meant to be a
link somebody can see is unconfigured, and `http://localhost:8501` on a public
page is not that. It is a link to *the visitor's own computer*, which either
refuses the connection or opens whatever they happen to be running on that port.
A deployment that forgot one variable must still reach the real demonstration.

**Local development configures localhost explicitly.** `http://localhost:8501`
and `http://127.0.0.1:8501` are accepted when they are supplied through
`NEXT_PUBLIC_DEMO_URL` - `frontend/.env.example` supplies one - and are never
reached by default. Localhost is a destination somebody asked for, never one the
code falls back to. There is no `NODE_ENV` branch anywhere in this decision.

Beyond the default, the value is **validated rather than trusted**, because it is
a build argument and a build argument is one mis-set environment file away from
putting a scheme of somebody's choosing in an `href` on every page:

- anything that is not `https:` is refused, except `http:` on `localhost` and
  `127.0.0.1`, which is what `npm run dev` really uses. `javascript:`, `data:`
  and `file:` fail this, and so does `http://` to a public hostname;
- a URL carrying credentials is refused;
- a fragment is dropped, repeated slashes are collapsed and the path always ends
  in exactly one `/`, so a value given with a trailing slash and one given
  without produce the same link;
- an identifier that is not one of the ten is dropped rather than appended, so
  the visitor reaches the demonstration home page - a working destination -
  rather than a link the application will refuse;
- a value that cannot be used at all falls back to `https://demo.solveaihub.com/`
  as above, so an unusable configuration fails towards the public demonstration
  rather than towards the visitor's own machine.

**Which links are module-specific:** only the two Launch Interactive Demo buttons
on each of the ten `/tools/<slug>` pages. The header button, the home page hero,
the tools overview, the contact page and every other page-level call to action
stay general. The home page's compact tool cards continue to link to the public
tool pages, not to the demonstration.

## The application router

`streamlit_app/components/routing.py`, called once at the top of
`streamlit_app/Home.py`.

The application is a `pages/` directory multipage app on **Streamlit 1.60.0**,
and the routing uses `st.query_params` and `st.switch_page` - the supported APIs
for that architecture in that version. No `st.navigation`, no `st.Page`, and no
JavaScript.

What the value is allowed to do is deliberately narrow: it is compared against a
fixed dictionary, and that is all. It is never imported, executed, formatted
into a path, joined onto a directory or written to disk. `resolve_module_route`
is a pure function, so every refusal below is asserted in
`tests/unit/test_demo_routing.py` without a browser.

| Input | Result |
| --- | --- |
| One of the ten | That module opens |
| Same value with whitespace or in capitals | Trimmed, lower-cased, then matched |
| No parameter | Demonstration home page, nothing said |
| Blank or whitespace-only | Demonstration home page, nothing said |
| Unknown identifier | Home page, with *"The requested module was not recognized. Showing the demo homepage."* |
| A path, a file name, a Python import path, a URL, a scheme, an encoded traversal | Same as unknown |
| Longer than 64 characters | Same as unknown, refused before it is normalised |
| The parameter given more than once | Same as unknown - two modules in one link has no correct answer, and guessing at intent is worse than the home page |

The message is fixed wording. It does not repeat the value that was asked for -
that would put a stranger's string on the page - and it names no file, no page
and no Python module.

## What happens on a rerun, a refresh and a back button

`st.switch_page` clears the query string as it navigates, so the address bar
shows the module's own page (`/PO_Risk_Checker`) rather than `/?module=po-risk`
once the link has been honoured. The routing runs **once per browser session**,
guarded by a flag in `st.session_state`.

| Action | Behaviour |
| --- | --- |
| Ordinary widget interaction (a rerun) | Nothing moves. The router only runs on `Home.py`, and only once |
| Refreshing after arriving at a module | The module page reloads - it is the page the browser is on |
| Refreshing the original `?module=` link, or opening it in a new tab | A new session, so the module opens again |
| Browser back from the module | Returns to the demonstration home page and **stays there** |
| Navigating manually to another module | Ordinary Streamlit navigation. The router has no opinion about it |

The back-button row is the one worth understanding. The browser's history entry
still carries `?module=`, so going back re-runs `Home.py` with the parameter
present. Without the once-per-session flag that would switch straight forward
again and the back button would be dead. With it, the visitor gets the home page
- which is what "back" means.

**The limitation, stated accurately:** because the parameter is cleared on
navigation, the address that opened the module is not the address the browser
ends up on. Sharing the resulting URL shares the module page inside the
protected application; sharing the `?module=` link is what reproduces the whole
flow. This is what the `pages/` architecture and `st.switch_page` support in
Streamlit 1.60.0, and the alternative - re-writing history from the browser -
would be a fragile JavaScript workaround and is not implemented.

---

## Security position

**The module parameter is navigation. It is not authentication and it is not
authorisation.**

- It says which page to open. It says nothing about who is asking, and no code
  on either side treats it as evidence of anything.
- **Cloudflare Access still protects the entire demonstration origin.** Every
  request to `demo.solveaihub.com` - with or without a query string, to the home
  page or to any module - passes the Access policy at the network edge before it
  reaches Streamlit. Nothing in this change touches Access policies, the
  one-time-PIN flow, or `cloudflared` configuration.
- Adding a module identifier to a URL grants nothing. An unapproved visitor sees
  the Cloudflare Access challenge and never reaches the application.
- **Application-level verification of the signed Access assertion is not
  implemented here.** The application does not yet read or verify the
  `Cf-Access-Jwt-Assertion` header; that is PR 5. Until then the protection is
  the edge policy plus the fact that the API has no public hostname - the
  position `docs/DEMO_SECURITY_CHECKLIST.md` already describes.
- Uploads remain disabled in demonstration mode, refused server-side. Routing
  changes nothing about that.

---

## Manual test matrix

Everything below needs a browser and, for most of it, the deployed stack behind
the real Cloudflare Access policy. **None of these has been performed** - they
are written here to be worked through after deployment, and the results belong
next to them.

Automated coverage exists for the routing logic and the rendered links
(`tests/unit/test_demo_routing.py`, `tests/integration/test_streamlit_pages.py`,
`tests/integration/test_demo_module_contract.py`,
`frontend/tests/demo-modules.test.tsx`). What no test in this repository can
cover is whether **Cloudflare Access preserves the query string across the
one-time-PIN redirect**, which is the single assumption this whole feature rests
on. Row 1 is therefore the one to run first: if the query string does not
survive the login redirect, every logged-out visitor lands on the demonstration
home page instead of the module they asked for, and the fix belongs in this
document rather than in the code.

| # | Scenario | Expected | Result |
| --- | --- | --- | --- |
| 1 | Logged-out visitor clicks Launch interactive demo on each of the ten tool pages | Cloudflare Access challenge appears; after login, the requested module opens | Not tested |
| 2 | The Cloudflare one-time-PIN page appears | The email prompt is shown on `demo.solveaihub.com` | Not tested |
| 3 | An approved visitor completes the one-time PIN | Access grants, the request continues to Streamlit | Not tested |
| 4 | The requested Streamlit module opens after authentication | The module page, not the home page | Not tested |
| 5 | An already-authenticated visitor opens a `?module=` URL directly | The module opens with no challenge | Not tested |
| 6 | `https://demo.solveaihub.com/` with no parameter | The demonstration home page, no message | Not tested |
| 7 | `?module=unknown-module` | Home page with *"The requested module was not recognized. Showing the demo homepage."* | Not tested |
| 8 | `?module=` (blank) | Home page, no message | Not tested |
| 9 | `?module=../../etc/passwd`, `?module=javascript:alert(1)`, `?module=pages/1_PO_Risk_Checker.py` | Home page with the same fixed message; no stack trace, no file name, no redirect off the origin | Not tested |
| 10 | Browser refresh after a module has opened | The same module page reloads | Not tested |
| 11 | Browser back button from the module | The demonstration home page; it does not bounce forward | Not tested |
| 12 | Manual navigation to another module in the sidebar | That module opens and stays open | Not tested |
| 13 | The same ten links on a mobile browser | The module opens; the sidebar is reachable | Not tested |
| 14 | An unapproved visitor follows a `?module=` link | Cloudflare Access refuses; Streamlit is never reached | Not tested |
| 15 | An expired Access session follows a `?module=` link | Re-authentication is required first; then as row 1 | Not tested |

---

## Related

- `docs/PUBLIC_DEMO_DEPLOYMENT.md` - what demonstration mode changes
- `docs/DEMO_SECURITY_CHECKLIST.md` - what protects the deployment
- `docs/CLOUDFLARE_TUNNEL_SETUP.md` - the hostnames and the tunnel
- `docs/API_AUTHENTICATION_PLAN.md` - the identity model that does not exist yet
