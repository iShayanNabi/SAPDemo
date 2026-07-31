# Contract Assistant sample data manifest

Every contract in this folder is **fiction**. The companies, addresses, prices, dates and clause wording were invented for this lab by `scripts/generate_contract_sample_data.py`. Nothing here comes from a real agreement, a real company or an SAP system, and no external service is contacted by the generator or by the Contract Assistant.

- Contracts: 6
- Formats per contract: txt, pdf, docx (the PDF is a real, text-based PDF; the DOCX uses real heading styles and a table)
- Documented scenarios: 21
- Reference date (`as_of`): `2026-07-01`

The same contract exists in all three formats so the test suite can prove that PDF, DOCX and TXT extraction reach the same conclusions about the same agreement.

## Contracts

| File stem | Title | What it demonstrates |
| --- | --- | --- |
| `sample_contract_msa_nordwind` | MASTER SERVICES AGREEMENT | A maintenance MSA that renews itself, gives only 14 days' termination notice and carries liquidated damages. |
| `sample_contract_supply_ravenna` | SUPPLY AGREEMENT | A components supply agreement with unlimited liability, no data-privacy clause and free assignment. |
| `sample_contract_saas_helvetia` | SOFTWARE SUBSCRIPTION AGREEMENT | A SaaS subscription whose auto-renewal notice deadline has already passed at the reference date, with service levels and service credits. |
| `sample_contract_services_baltic` | PROFESSIONAL SERVICES AGREEMENT | A well-drafted agreement with every required clause present and no auto-renewal - the negative control for the rule set. |
| `sample_contract_nda_meridian` | MUTUAL NON-DISCLOSURE AGREEMENT | A short mutual NDA. Most clause types genuinely do not exist in it, which is what makes it the missing-clause test case. |
| `sample_contract_hostile_calder` | EQUIPMENT RENTAL AGREEMENT | An otherwise ordinary rental agreement whose text contains prompt-injection bait. The assistant must report it and must not obey it. |

## Documented scenarios

### msa_nordwind

**CA-S001 - Automatic renewal with a notice deadline**

- Clause: `auto_renewal`
- Expected effect: CA-R001 fires; the renewal term is twelve months and renewal_notice_days is 90.

**CA-S002 - Termination notice below policy**

- Clause: `termination`
- Expected effect: CA-R002 fires at critical severity; notice_period_days is 14.

**CA-S003 - Liquidated damages**

- Clause: `penalties`
- Expected effect: CA-R007 fires and the penalties clause is present.

**CA-S004 - Payment terms outside policy**

- Clause: `payment_terms`
- Expected effect: CA-R010 fires; net_days is 90 against a 60-day policy maximum.

### supply_ravenna

**CA-S005 - Missing data-privacy clause**

- Clause: `data_privacy`
- Expected effect: data_privacy is absent; CA-R004 raises a critical missing-clause finding.

**CA-S006 - Unlimited liability**

- Clause: `liability`
- Expected effect: CA-R005 fires at critical severity.

**CA-S007 - Assignment without consent**

- Clause: `assignment`
- Expected effect: CA-R013 fires.

**CA-S008 - Governing law outside the approved list**

- Clause: `governing_law`
- Expected effect: CA-R015 fires; the extracted jurisdiction is Singapore.

### saas_helvetia

**CA-S009 - Renewal notice deadline already passed**

- Clause: `auto_renewal`
- Expected effect: CA-R009 fires; notice_deadline is 2026-06-15, before the reference date 2026-07-01.

**CA-S010 - Contract expiring inside the warning window**

- Clause: `term`
- Expected effect: CA-R008 fires; expiration_date is 2026-09-15, inside the 90-day window.

**CA-S011 - Service levels with credits**

- Clause: `service_levels`
- Expected effect: service_levels and penalties are both present, so CA-R012 does NOT fire.

**CA-S012 - No audit rights**

- Clause: `audit_rights`
- Expected effect: audit_rights is absent and CA-R014 fires.

### services_baltic

**CA-S013 - Every required clause present**

- Clause: `all`
- Expected effect: missing_clauses is empty and CA-R004 does not fire.

**CA-S014 - No automatic renewal**

- Clause: `auto_renewal`
- Expected effect: auto_renewal is absent, so CA-R001 and CA-R009 do not fire.

**CA-S015 - Compliant termination notice and payment terms**

- Clause: `termination`
- Expected effect: notice_period_days is 90 and net_days is 30, so CA-R002 and CA-R010 do not fire.

### nda_meridian

**CA-S016 - Many required clauses genuinely absent**

- Clause: `multiple`
- Expected effect: payment_terms, pricing, liability, indemnification and dispute_resolution are absent, so CA-R004 raises several findings.

**CA-S017 - Confidentiality present with high confidence**

- Clause: `confidentiality`
- Expected effect: confidentiality is present with confidence above 0.55.

**CA-S018 - No termination clause**

- Clause: `termination`
- Expected effect: CA-R003 fires.

### hostile_calder

**CA-S019 - Prompt-injection bait inside the document**

- Clause: `security`
- Expected effect: CA-R016 fires, injection_detected is true, and the extracted clauses are unchanged by the bait.

**CA-S020 - Instruction text is neutralised before any AI call**

- Clause: `security`
- Expected effect: The injection markers are recorded on the analysis and the phrases are replaced with [filtered] in any prompt payload.

**CA-S021 - Ordinary clauses still extract correctly**

- Clause: `payment_terms`
- Expected effect: payment_terms is present with net_days 30, despite the bait.

## What the engine currently produces

Recorded in `expected_contract_baseline.json` by reading the written files back through the real extractor - not from the generator's in-memory strings. A value that survives in memory can still change on the round trip through a file, and a baseline recorded before that round trip disagrees with the API.

| Contract | Clauses found | Missing | Risks | Score | Band |
| --- | --- | --- | --- | --- | --- |
| `msa_nordwind` | 17/17 | none | 6 | 67 | high |
| `supply_ravenna` | 12/17 | data_privacy | 5 | 62 | high |
| `saas_helvetia` | 16/17 | none | 6 | 51 | high |
| `services_baltic` | 16/17 | none | 1 | 5 | low |
| `nda_meridian` | 4/17 | termination, payment_terms, pricing, liability, indemnification, dispute_resolution | 7 | 80 | critical |
| `hostile_calder` | 11/17 | none | 3 | 16 | low |

## The hostile document

`sample_contract_hostile_calder` deliberately contains text written as an instruction to an automated system, including an attempt to have the assistant reveal a system prompt and print an API key. It is here so the test suite can prove the assistant reports the attempt (`CA-R016`) and does not obey it: the extracted clauses, dates and risks for that contract are exactly what the text itself supports, and the instruction phrases are neutralised before any AI call.

## A note on the figures

Every clause, date, obligation and risk is produced by the deterministic engine in `app/modules/contract_assistant`, not by an AI model. Each carries a page number, a section heading, a supporting excerpt and a confidence score. This is an assistive review, not legal advice, and nothing here has been validated in a live SAP environment.
