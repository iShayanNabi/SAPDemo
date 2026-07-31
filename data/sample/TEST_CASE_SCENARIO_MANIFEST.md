# Test Case Generator - demo process manifest

Every process below is **fiction**. The company, plants, material and vendor numbers, roles and interface names were invented for this lab. Nothing here comes from a real SAP system, and no output has been validated in one.

Configuration version: `1.0.0` - engine version: `1.0.0`

Regenerate with:

```bash
python scripts/generate_test_case_sample_data.py
```

---

## Demo processes

| Name | Title | Types | Cases | Why it is here |
| --- | --- | --- | --- | --- |
| `p2p_standard_po` | Procure to Pay - standard purchase order | sit, uat, negative, integration, regression | 10 | The financially sensitive, heavily integrated process. Its description mentions invoices, goods receipts and payments, it names four integrations and four roles, so every configured priority escalation signal fires. |
| `pm_notification` | Plant maintenance - raise a maintenance notification | sit, uat, negative | 6 | The negative control. One role, no integration, no financial vocabulary, so no escalation rule fires and every test case keeps its test type's base priority. |
| `migration_vendor` | Vendor master migration - cutover load | data_migration, sit, negative, authorization, security, regression | 4 | A cutover load, deliberately requested with more test types than test cases so the uncovered-type path is exercised: the generator drops the lightest types and says so instead of silently ignoring them. |
| `fiori_approval` | Fiori purchase requisition approval | uat, authorization, security, negative | 8 | An approval app with six roles and no financial posting. Only the access-related test types escalate, which is what the role-count rule is for. |

---

## Documented scenarios

| ID | Process | Condition | Expectation |
| --- | --- | --- | --- |
| TCG-S001 | `p2p_standard_po` | All three priority escalation signals fire | The process description contains configured escalation keywords, four integrations are named (>= the threshold of 3) and four roles are named (>= the threshold of 4). |
| TCG-S002 | `p2p_standard_po` | System integration tests are escalated above their base priority | SIT has a base priority of high and the keyword rule applies to it, so every SIT case in this suite is critical. |
| TCG-S003 | `pm_notification` | Nothing escalates for a quiet process | No escalation keyword appears, no integration is named and one role is named, so every case keeps its test type's configured base priority. |
| TCG-S004 | `migration_vendor` | More test types requested than test cases | Six types are requested and four cases are asked for, so the two types listed last receive no case, are reported as uncovered and produce a note. The headline type of the process - data migration, listed first - is kept. |
| TCG-S005 | `fiori_approval` | Only the access test types escalate on role count | Six roles are named, so authorization and security escalate one level; the process description contains no financial keyword, so UAT does not. |
| TCG-S006 | `all` | Every planned case is complete without any AI | With drafting switched off, every case is built from the configured templates and still has at least the configured minimum number of steps. |
| TCG-S007 | `all` | Identifiers are unique and typed | Each identifier follows the configured template and carries its test type's id_code, numbered from 1 within the type. |

---

## Recorded baseline (AI drafting off)

The baseline records the **deterministic** half of the module only: identifiers, type allocation, priorities, focus areas, owners and step counts. Those must not move when a provider, an API key or a model changes. Drafted prose is not recorded, because it is the one part that is allowed to differ.

| Process | Cases | Allocation | Priorities |
| --- | --- | --- | --- |
| `p2p_standard_po` | 10 | integration 2, negative 2, regression 2, sit 2, uat 2 | critical 2, high 6, medium 2 |
| `pm_notification` | 6 | negative 2, sit 2, uat 2 | high 4, medium 2 |
| `migration_vendor` | 4 | authorization 1, data_migration 1, negative 1, sit 1 | critical 2, high 1, medium 1 |
| `fiori_approval` | 8 | authorization 2, negative 2, security 2, uat 2 | high 6, medium 2 |

> These are draft test cases produced from a typed process description. They have not been executed or validated in a live SAP system.
