# SAP Interview Coach - scenario manifest

Every question, scenario, company and reference answer in this bank is fictional. Nothing here is an SAP certification question, and no answer has been reviewed by SAP.

- **Bank version:** 1.0.0
- **Questions:** 104
- **Tracks:** 9
- **Topics:** 104

## Coverage

| Track | Questions |
| --- | --- |
| sap_mm | 12 |
| sap_ariba | 12 |
| sap_s4hana | 12 |
| sap_business_network | 11 |
| sap_integration | 12 |
| sap_architecture | 11 |
| procurement | 11 |
| supply_chain | 11 |
| sap_consulting | 12 |

| Difficulty | Questions |
| --- | --- |
| foundational | 13 |
| intermediate | 35 |
| advanced | 47 |
| expert | 9 |

| Interview mode | Questions available |
| --- | --- |
| practice | 104 |
| timed | 100 |
| technical | 67 |
| architecture | 25 |
| behavioral | 17 |
| rapid_fire | 15 |

## What the anchors prove

| ID | Condition | Why it matters |
| --- | --- | --- |
| IC-A01 | Every reference answer covers every concept of its own rubric. | The reference answer is the bank's own model answer. If it does not match its own keyword list, a candidate writing the perfect answer loses marks for it. |
| IC-A02 | A reference answer scores strictly higher than a partial answer. | A rubric that cannot separate a full answer from a vague one is not a rubric. |
| IC-A03 | A configured non-answer scores zero on every dimension and is reported as a non-answer rather than as a very low answer. | Silence and a wrong answer are different things and are coached differently. |
| IC-A04 | Adding a known-wrong statement to a complete answer lowers technical accuracy and leaves completeness unchanged. | Saying something incorrect does not make an answer less complete. Spreading the penalty would make the same mistake cost different amounts on different questions. |
| IC-A05 | Scores are identical with use_ai=true (mock provider) and use_ai=false. | The rubric scores; the provider only ever writes prose. |

## Anchor questions

Each anchor below is scored four ways: the bank's own reference answer, a partial answer, an answer with a known-wrong statement appended, and a configured non-answer. The recorded numbers live in `expected_interview_baseline.json`.

| Question | Mode | Track | Difficulty | Topic |
| --- | --- | --- | --- | --- |
| IQ-MM-003 | technical | sap_mm | intermediate | Three-way match |
| IQ-IN-002 | technical | sap_integration | advanced | Interface troubleshooting |
| IQ-AC-002 | architecture | sap_architecture | advanced | Clean core |
| IQ-CO-002 | behavioral | sap_consulting | advanced | Scope management |
| IQ-SC-001 | practice | supply_chain | intermediate | Safety stock |
| IQ-PR-003 | practice | procurement | foundational | Savings measurement |
| IQ-BN-001 | rapid_fire | sap_business_network | foundational | Network fundamentals |

## How an answer is marked

Concept coverage drives technical accuracy, completeness, business understanding and architecture. The shape of the answer - length, sentence length, signposting, filler - drives clarity. A known-wrong statement costs technical accuracy points and nothing else. Every threshold is in `app/modules/interview_coach/config/interview_rules.json`.

No score on this page was produced by a language model.
