# Blueprint Generator - scenario manifest

Configuration v1.0.0 · engine v1.0.0

Every company, company code, plant, purchasing organisation, interface and user group below is **fictional** and was invented for this lab. Nothing here comes from a real SAP system, and no blueprint this module produces has been validated in one.

## Demo projects

| Name | Company | What it demonstrates |
| --- | --- | --- |
| `p2p_wholesale` | Nordwind Logistics GmbH | A complete project request: every field supplied, so every section is written and nothing waits for input. The positive control. |
| `finance_gaps` | Helvetia Precision AG | A request with holes in it: no integrations, no data sources and no user groups. The sections that need those fields come back waiting for input, naming the field - none of them invents an interface, a source system or a role. |
| `retail_subset` | Baltic Retail Group OY | A request for eight sections, listed out of order. The blueprint comes back in the canonical order and the twenty-two excluded sections are reported. |
| `hostile_rollout` | Calder Industrial Services Ltd | The process description contains text written as an instruction to an automated system. It is filtered before drafting, the attempt is reported on the blueprint, and no section obeys it. |

## Documented scenarios

The integration tests read this manifest and assert each condition below.

| ID | Project | Condition |
| --- | --- | --- |
| `BP-S001` | `p2p_wholesale` | A complete project request produces every section, none waiting for input. |
| `BP-S002` | `p2p_wholesale` | The organisational structure holds exactly the units the request named - three countries, three company codes, three plants, two purchasing organisations and three locations - and nothing else. |
| `BP-S003` | `finance_gaps` | A request with no integrations, no data sources and no user groups leaves those sections waiting for input rather than inventing content for them. |
| `BP-S004` | `finance_gaps` | A section waiting for input holds no items at all: not one invented interface, source system or role. |
| `BP-S005` | `retail_subset` | Eight sections requested out of order come back in the canonical document order, and the twenty-two excluded sections are reported. |
| `BP-S006` | `hostile_rollout` | A project description carrying prompt-injection bait is reported on the blueprint, and no section claims validation in a live SAP system. |

---

## Recorded baseline (AI drafting off)

The baseline records the **deterministic** half of the module only: the section list, the section order, the identifiers, the statuses, the missing inputs, the derived items and the readiness figures. Those must not move when a provider, an API key or a model changes. Drafted prose is not recorded, because it is the one part that is allowed to differ.

| Project | Sections | Waiting for input | Written | Derived items |
| --- | --- | --- | --- | --- |
| `p2p_wholesale` | 30 | - | 100.0% | 53 |
| `finance_gaps` | 30 | integrations, interfaces_apis, data_migration, security_roles | 86.7% | 18 |
| `retail_subset` | 8 | - | 100.0% | 14 |
| `hostile_rollout` | 30 | - | 100.0% | 21 |

> These are **proposed** blueprints produced from a typed project request. They require review by qualified SAP professionals, and nothing in them has been validated in a live SAP system.
