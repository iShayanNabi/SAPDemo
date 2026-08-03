/**
 * The ten modules, as the website describes them.
 *
 * `id`, `number` and `name` mirror `app/services/demo/catalog.py` and
 * `app/main.py::MODULES`. A Python test asserts the three agree, so the site
 * cannot claim a module the platform does not have, or number them differently
 * from the API. Everything else here is website copy.
 *
 * The wording rules this file follows, because they are easy to break by
 * accident and expensive to break in public:
 *
 * - No client, testimonial, certification, partnership, customer count,
 *   deployment or business outcome is named. None exist.
 * - A saving is always "estimated" and always attached to the assumption it
 *   rests on. It is never presented as money already saved.
 * - `computed` and `aiWrites` are separate fields because they are separate
 *   claims, and conflating them is the single most misleading thing this site
 *   could do.
 * - `limitation` is per-module rather than one shared sentence, because the
 *   thing each tool must not be mistaken for is different: the contract module
 *   must not read as legal review, the forecaster must not read as certainty,
 *   the interview coach must not read as a hiring prediction, and the two
 *   supplier modules must not imply an external news, financial or ESG feed
 *   that is not connected. A single generic caveat would cover none of them.
 */

import type { DemoModuleId } from '@/lib/demo';

export type OutputOrigin =
  | 'rule_based'
  | 'forecast'
  | 'ai_generated'
  | 'mock_ai'
  | 'demo_data';

/**
 * The three short phrases a card shows at a glance.
 *
 * Separate fields rather than an excerpt of `problem` or `demoInput`, because
 * the home page has to answer three questions about ten tools in a space where
 * a paragraph does not fit, and truncating a paragraph produces a fragment that
 * reads as a different claim than the sentence it came from.
 *
 * What must **not** go in here is as much the point as what does: no test
 * counts, no endpoint counts, no table names, no framework names, no row
 * counts. A card is read by somebody deciding whether a tool is about their
 * problem, and none of those help them decide.
 */
export interface ModuleOverview {
  /** What the user gives it. */
  input: string;
  /** What comes back. */
  output: string;
  /** Why somebody in procurement would want it. */
  purpose: string;
}

export interface ModuleContent {
  /** Matches the module id used by the API. */
  id: string;
  /** URL segment under /tools/. */
  slug: string;
  /**
   * The identifier this module is opened by in the protected demonstration.
   *
   * A fourth identifier on purpose, and none of the other three would do:
   * `id` is the API's (`po_risk`), `slug` is this site's URL segment
   * (`purchase-order-risk-checker`), and `name` is prose. This one appears in
   * a link a visitor may keep - `demo.solveaihub.com/?module=po-risk` - so it
   * has to be free to stay the same while the other three change.
   *
   * The type is the ten-value union from `lib/demo.ts`, so a typo here is a
   * compile error rather than a button that opens the wrong page.
   */
  demoModule: DemoModuleId;
  number: number;
  name: string;
  /** One line, used on the card. */
  tagline: string;
  /** The compact three-line summary, for the home page overview. */
  overview: ModuleOverview;
  /** The business problem, in the words of somebody who has it. */
  problem: string;
  /** What the fictional demonstration input actually is. */
  demoInput: string;
  /** The deterministic calculations. This is the load-bearing claim. */
  computed: string[];
  /** What AI does here - and, where it matters, what it cannot do. */
  aiWrites: string[];
  /** What a user gets out. */
  outputs: string[];
  /** The guided demonstration, step by step. */
  steps: string[];
  /**
   * What this specific tool must not be mistaken for. Rendered on the module
   * page next to the demonstration-data warning.
   */
  limitation: string;
  /** Origins a result from this module can carry. */
  origins: OutputOrigin[];
  /** Export formats the module already supports. Empty where it has none. */
  exports: string[];
}

export const modules: readonly ModuleContent[] = [
  {
    id: 'po_risk',
    slug: 'purchase-order-risk-checker',
    demoModule: 'po-risk',
    number: 1,
    name: 'Purchase Order Risk Checker',
    tagline: 'Twenty transparent rules over a purchase order export.',
    overview: {
      input: 'A purchase order export',
      output: 'Ranked findings with the evidence behind each one',
      purpose: 'Catch duplicates, split orders and off-contract prices before release',
    },
    problem:
      'A buyer releasing hundreds of purchase order lines a week cannot read all of them. ' +
      'The ones that matter - a duplicate, an order split to stay under a release threshold, ' +
      'a price well off the contract - look exactly like the ones that do not until somebody ' +
      'checks.',
    demoInput:
      'A fictional SAP-style purchase order export of 1,238 line items across 25 fields, with ' +
      'a documented set of deliberately planted anomalies recorded in a manifest so the ' +
      'results can be checked against known expectations.',
    computed: [
      'Twenty rules covering duplicates, split purchases, threshold avoidance, price anomalies, contract compliance, missing approvals, delivery dates, data quality and supplier concentration.',
      'A severity and a confidence for every finding, from the evidence the rule actually saw.',
      'An estimated financial exposure per finding, converted to a base currency before any comparison so orders in different currencies are comparable.',
      'A risk score whose method is reported next to it.',
    ],
    aiWrites: [
      'An optional executive summary restating the findings in business language.',
      'Optionally, a plain-language rewrite of the most severe findings.',
      'It cannot add, remove, reweight or reclassify a finding. AI text lives in separate fields and is labelled wherever it appears.',
    ],
    outputs: [
      'A ranked findings table with the rule, the evidence and a recommended action.',
      'Supplier-level risk aggregation and data-quality warnings.',
      'A downloadable report.',
    ],
    steps: [
      'Load the bundled fictional purchase order export.',
      'Review the column mapping the reader inferred from the SAP field names.',
      'Run the analysis.',
      'Filter the findings by severity, rule or supplier, and download the report.',
    ],
    limitation:
      'The findings are rule outputs over a fictional export, not an audit and not a guarantee ' +
      'that a flagged order is wrong or an unflagged one is right. A buyer still has to review ' +
      'each one.',
    origins: ['rule_based', 'ai_generated', 'mock_ai', 'demo_data'],
    exports: ['XLSX', 'CSV', 'JSON'],
  },
  {
    id: 'spend_analytics',
    slug: 'spend-analytics-dashboard',
    demoModule: 'spend-analytics',
    number: 2,
    name: 'Spend Analytics Dashboard',
    tagline: 'Where the money went, and which patterns look like leakage.',
    overview: {
      input: 'A procurement transaction file',
      output: 'Spend and leakage figures you can drill into',
      purpose: 'See where the money actually goes, and where it leaks',
    },
    problem:
      'Category managers are asked where the money goes and answer with a spreadsheet that ' +
      'took a week. The questions underneath - how much spend is under contract, how ' +
      'concentrated it is, which of it went around the agreed supplier - need the same data ' +
      'cut four different ways.',
    demoInput:
      'A fictional procurement transaction file of 3,640 rows, with documented scenarios ' +
      'covering maverick spend, contract leakage, tail spend and price variance.',
    computed: [
      'Spend aggregation by category, supplier, plant, cost centre and period.',
      'Spend under management, maverick spend, contract leakage, tail-spend share and supplier concentration.',
      'Price variance across suppliers for comparable material.',
      'Estimated savings opportunities, each stating the assumption it rests on.',
      'Reported averages summed in decimal arithmetic, so the same input always produces the same published figure.',
    ],
    aiWrites: [
      'A narrative summary of the picture the numbers show.',
      'Every number on the dashboard exists before any provider is contacted.',
    ],
    outputs: [
      'A dashboard with drill-down to the exact transactions behind any figure.',
      'A ranked list of estimated savings opportunities, labelled as estimates.',
      'A downloadable report.',
    ],
    steps: [
      'Load the bundled fictional transaction file.',
      'Run the analysis.',
      'Read the KPI row, then drill into a category or a supplier.',
      'Open an opportunity and inspect the transactions it was derived from.',
    ],
    limitation:
      'Every savings figure is an estimate stating the assumption it rests on, not money saved, ' +
      'and the transactions underneath it are fictional. Acting on one is a decision for somebody ' +
      'who knows the category.',
    origins: ['rule_based', 'ai_generated', 'mock_ai', 'demo_data'],
    exports: ['XLSX', 'CSV', 'JSON'],
  },
  {
    id: 'supplier_recommendation',
    slug: 'supplier-recommendation-engine',
    demoModule: 'supplier-recommendation',
    number: 3,
    name: 'Supplier Recommendation Engine',
    tagline: 'Rank the suppliers that can actually serve a requirement.',
    overview: {
      input: 'A requirement and a supplier catalogue',
      output: 'A ranked shortlist with every score broken down',
      purpose: 'Make a sourcing choice somebody else can reproduce',
    },
    problem:
      'Choosing a supplier for a specific requirement mixes price, delivery reliability, ' +
      'quality history, capacity, risk and whether a contract exists. Done in a meeting, the ' +
      'weighting is whatever the loudest person believes it is, and nobody can reproduce it ' +
      'a month later.',
    demoInput:
      'A fictional supplier catalogue of 55 suppliers with delivery, quality, capacity, ' +
      'certification, region and contract fields, including suppliers with deliberately ' +
      'missing data.',
    computed: [
      'Hard eligibility filters applied before ranking, so an ineligible supplier is never ranked and always says why it was excluded.',
      'Nine normalised sub-scores combined by configurable weights into one ranking.',
      'A score breakdown per supplier showing every component that produced it.',
      'A sensitivity view showing how far the weights can move before the order changes.',
    ],
    aiWrites: [
      'An explanation of why the leading supplier ranked where it did.',
      'The ranking is arithmetic. Nothing a provider returns changes a position.',
    ],
    outputs: [
      'The eligible suppliers in rank order with score breakdowns.',
      'The reasons behind every exclusion.',
      'A downloadable comparison.',
    ],
    steps: [
      'Load the bundled fictional supplier catalogue.',
      'Describe a requirement: material, quantity, plant, delivery date, target price.',
      'Rank the suppliers and open a score breakdown.',
      'Change a weight and watch the ranking respond.',
    ],
    limitation:
      'The ranking reflects the configured weights and the bundled fictional catalogue. No ' +
      'external supplier, financial, credit or news data source is connected, so this is a ' +
      'method demonstration rather than a sourcing decision.',
    origins: ['rule_based', 'ai_generated', 'mock_ai', 'demo_data'],
    exports: ['XLSX', 'CSV', 'JSON'],
  },
  {
    id: 'invoice_validator',
    slug: 'invoice-validator',
    demoModule: 'invoice-validator',
    number: 4,
    name: 'Invoice Validator',
    tagline: 'Three-way matching with configurable tolerances.',
    overview: {
      input: 'Invoices, purchase orders and goods receipts',
      output: 'Exceptions with a pay, hold or investigate suggestion',
      purpose: 'Stop paying for what was never ordered or received',
    },
    problem:
      'Accounts payable pays what it is billed unless somebody proves otherwise. Proving ' +
      'otherwise means comparing three documents per line - the invoice, the purchase order ' +
      'and the goods receipt - and most teams sample rather than check.',
    demoInput:
      'Three linked fictional datasets: 420 invoices, 418 purchase order lines and 417 goods ' +
      'receipts, with documented mismatches, duplicates and over-billing scenarios.',
    computed: [
      'A three-way match across invoice, purchase order and goods receipt with configurable quantity and price tolerances.',
      'Seventeen exception rules, each with a distinct trigger so one problem raises one exception rather than three.',
      'Duplicate invoice detection across supplier, amount, date and reference.',
      'Cumulative over-billing against the quantity actually ordered, separate from a single-line price mismatch.',
    ],
    aiWrites: [
      'The explanation a clerk would send to the supplier.',
      'The exception, the amount and the recommendation are computed.',
    ],
    outputs: [
      'Per-invoice exceptions with severity and the documents that disagreed.',
      'A pay, hold or investigate recommendation per invoice.',
      'A downloadable exception report.',
    ],
    steps: [
      'Load the three bundled fictional datasets.',
      'Set the matching tolerances, or keep the configured defaults.',
      'Run the validation.',
      'Open an exception and read the three documents side by side.',
    ],
    limitation:
      'The exceptions are matching results over fictional documents. A pay, hold or investigate ' +
      'recommendation is a suggestion for a person to approve, not an approval, and no payment ' +
      'system is connected to it.',
    origins: ['rule_based', 'ai_generated', 'mock_ai', 'demo_data'],
    exports: ['XLSX', 'CSV', 'JSON'],
  },
  {
    id: 'supplier_risk_copilot',
    slug: 'supplier-risk-copilot',
    demoModule: 'supplier-risk',
    number: 5,
    name: 'Supplier Risk Copilot',
    tagline: 'Ten risk categories, scored transparently, answerable in prose.',
    overview: {
      input: 'Supplier profiles and dated risk events',
      output: 'Category scores, and the events that moved them',
      purpose: 'Answer why a supplier is high risk, specifically',
    },
    problem:
      'Supplier risk is usually a spreadsheet updated once a year and a set of opinions held ' +
      'by whoever has been there longest. Neither survives the question "why is this supplier ' +
      'high risk, specifically?"',
    demoInput:
      'A fictional portfolio of 55 supplier risk profiles and 179 dated internal risk events, ' +
      'including one supplier with deliberately missing data.',
    computed: [
      'A weighted score across ten risk categories - financial, delivery, quality, compliance, geographic, concentration, contractual, operational, reputational and cyber.',
      'An overall band per supplier, from the profile fields and the dated events.',
      'Missing data reported as missing rather than scored as zero.',
      'A trend built from the events, with each event traceable to the score it moved.',
    ],
    aiWrites: [
      'Answers to questions asked in plain language, grounded in the loaded records and carrying citations back to them.',
      'A question the data cannot answer is refused with a reason, not guessed.',
    ],
    outputs: [
      'A scored supplier list with per-category breakdowns.',
      'The events behind every score.',
      'A cited question-and-answer panel, and a downloadable report.',
    ],
    steps: [
      'Load the bundled fictional profiles and risk events.',
      'Calculate the scores.',
      'Open a supplier and read the category breakdown.',
      'Ask the copilot a question and follow its citations back to the records.',
    ],
    limitation:
      'Scores come from the bundled fictional profiles and internal event records only. No live ' +
      'news, financial, credit, sanctions or ESG feed is connected, so nothing here reflects the ' +
      'real standing of any real supplier.',
    origins: ['rule_based', 'ai_generated', 'mock_ai', 'demo_data'],
    exports: ['XLSX', 'CSV', 'JSON'],
  },
  {
    id: 'contract_assistant',
    slug: 'contract-assistant',
    demoModule: 'contract-assistant',
    number: 6,
    name: 'Contract Assistant',
    tagline: 'Every extracted claim cites the page it came from.',
    overview: {
      input: 'Contract documents in PDF, DOCX or TXT',
      output: 'Clauses, dates and obligations, each citing its page',
      purpose: 'Know what was committed to without rereading the contract',
    },
    problem:
      'Somebody has to know when the contract renews, what the notice period is, whether ' +
      'liability is capped and what was actually committed to. That answer usually lives in a ' +
      'PDF nobody has opened since signature.',
    demoInput:
      'Six fictional contracts - a master services agreement, an NDA, a SaaS agreement, a ' +
      'services agreement and a supply agreement - in PDF, DOCX and TXT. One of them contains ' +
      'a deliberate prompt-injection attempt so the handling of untrusted document text can be ' +
      'seen working.',
    computed: [
      'Clause detection, key dates, obligations and risk flags from per-page extracted text.',
      'A page number, section heading and excerpt for every extracted claim.',
      'A confidence score built from the evidence actually seen - heading match, primary phrase, supporting phrases, a parsed value - never guessed.',
      'Negation handling, so a clause saying an agreement does not renew automatically is not read as one that does.',
    ],
    aiWrites: [
      'Answers to questions about the contract, and an optional summary.',
      'It never supplies a date, a party or a value that extraction did not find.',
      'A document with no extractable text is reported as needing OCR rather than analysed as an empty contract.',
    ],
    outputs: [
      'Extracted clauses, dates, obligations and risks, each citing its page.',
      'A cited question-and-answer panel.',
      'A downloadable summary.',
    ],
    steps: [
      'Load the bundled fictional contracts.',
      'Analyse one and read the extracted clauses.',
      'Follow a citation to the page and excerpt it came from.',
      'Ask a question about the contract.',
    ],
    limitation:
      'Extraction is not legal advice and does not replace review by a qualified lawyer. OCR is ' +
      'not enabled here, so a scanned or image-only document is reported as needing it rather ' +
      'than analysed.',
    origins: ['rule_based', 'ai_generated', 'mock_ai', 'demo_data'],
    exports: ['XLSX', 'CSV', 'JSON'],
  },
  {
    id: 'inventory_predictor',
    slug: 'inventory-predictor',
    demoModule: 'inventory-predictor',
    number: 7,
    name: 'Inventory Predictor',
    tagline: 'Five statistical models, chosen by backtesting. No AI touches a number.',
    overview: {
      input: 'Demand history by material and plant',
      output: 'Forecasts, shortage dates and reorder timing',
      purpose: 'Order early enough for the lead time to matter',
    },
    problem:
      'Planners are asked which materials will run short and when. The honest answer needs a ' +
      'forecast, a stock projection and a lead time - and a forecast that fits last year ' +
      'beautifully is not the same thing as one that works.',
    demoInput:
      'A fictional demand history of 450 rows across material and plant series, with ' +
      'documented seasonality, trend, intermittent demand and deliberately missing periods.',
    computed: [
      'The period granularity inferred from the data rather than assumed, by matching the median gap between rows.',
      'A complete period grid, so a missing month is recorded as missing rather than shifting every later period by one.',
      'Five explainable models backtested on identical held-out periods, with a complexity margin a flexible model has to beat before it wins.',
      'A stock projection walking real calendar days, so a shortage lands on a date rather than in a month.',
      'A reorder trigger compared against the demand expected over the lead time from each day forward, not from today.',
    ],
    aiWrites: [
      'An explanation of the forecast and the recommendation in planning language.',
      'No AI produces any number in this module - not the forecast, not the shortage date, not the model choice.',
    ],
    outputs: [
      'Per-material forecasts with the model chosen and why it won.',
      'Projected stock levels, shortage dates and reorder recommendations.',
      'Stock classifications, and a downloadable plan.',
    ],
    steps: [
      'Load the bundled fictional demand history.',
      'Run the forecast over the suggested horizon.',
      'Open a material and read which model was selected and on what evidence.',
      'Check the projected shortage date against the reorder trigger.',
    ],
    limitation:
      'A forecast is a projection from history with error attached, not a statement of what will ' +
      'happen. The shortage dates and reorder recommendations follow from that projection, so ' +
      'they inherit its uncertainty rather than resolving it.',
    origins: ['forecast', 'rule_based', 'ai_generated', 'mock_ai', 'demo_data'],
    exports: ['XLSX', 'CSV', 'JSON'],
  },
  {
    id: 'test_case_generator',
    slug: 'sap-test-case-generator',
    demoModule: 'test-case-generator',
    number: 8,
    name: 'SAP Test Case Generator',
    tagline: 'AI writes the wording. Code writes the skeleton.',
    overview: {
      input: 'A description of a business process',
      output: 'A structured test suite across eight test types',
      purpose: 'Start SAP testing from a draft rather than a blank page',
    },
    problem:
      'Writing a test suite for an SAP process is days of work that mostly produces structure: ' +
      'how many cases, of which types, covering which steps, at which priority. The structure ' +
      'is the part a model is least trustworthy with and the part most easily computed.',
    demoInput:
      'Bundled fictional SAP business processes - procure to pay, order to cash and a data ' +
      'migration - each with preconditions, business rules, systems, integrations and roles.',
    computed: [
      'How many cases each requested test type receives, decided before a provider is contacted.',
      'The identifier, the covered aspect and the priority of every case.',
      'Step renumbering: the order steps arrive in is trusted, the numbers they carry are not.',
      'Type allocation that respects the order the caller listed the types in, so a migration process keeps its migration tests.',
    ],
    aiWrites: [
      'The wording of each test case against that skeleton.',
      'A failure, a wrong shape or a blank field falls back to the configured template for that one case, and the repair is recorded on it. One bad case never costs the others.',
      'The same request produces the same suite structure with a real model, with the mock, or with AI switched off entirely.',
    ],
    outputs: [
      'An editable suite across eight test types, each case labelled with what produced it.',
      'Approval and execution tracking, with an execution result flagged as stale if the script it was recorded against has since changed.',
      'Export to CSV, XLSX, JSON or PDF.',
    ],
    steps: [
      'Start from a bundled fictional process, or describe one.',
      'Choose the test types and the case count.',
      'Generate the suite.',
      'Edit a case, approve it, record a result, and export.',
    ],
    limitation:
      'The suite is a drafting aid built from a fictional process description. It has not been ' +
      'executed against any SAP system, and a tester still has to review and adapt it before it ' +
      'is used.',
    origins: ['rule_based', 'ai_generated', 'mock_ai', 'demo_data'],
    exports: ['CSV', 'XLSX', 'JSON', 'PDF'],
  },
  {
    id: 'blueprint_generator',
    slug: 'sap-blueprint-generator',
    demoModule: 'blueprint-generator',
    number: 9,
    name: 'SAP Blueprint Generator',
    tagline: 'Thirty sections, versioned, with staleness tracked across them.',
    overview: {
      input: 'A project request and its constraints',
      output: 'A versioned blueprint, with stale sections flagged',
      purpose: 'Keep a long document honest as its scope changes',
    },
    problem:
      'An implementation blueprint is a long document whose sections describe each other. ' +
      'Edit the scope and the executive summary that described it is now describing something ' +
      'that no longer exists - and it still reads as approved.',
    demoInput:
      'Bundled fictional implementation projects with company codes, plants, modules, ' +
      'integrations, migration sources, timelines and constraints. One is deliberately ' +
      'hostile, carrying an injection attempt inside the document text.',
    computed: [
      'The section list, organisational structure, module list, integration register, interface list, migration sources and security roles, all derived from the project request.',
      'A dependency graph between sections, validated at load time, so an edit marks every section that described the edited one.',
      'Item identifiers renumbered on every edit; section identifiers never reissued, so a review comment keeps meaning what it meant.',
      'A section with no input reports which field to fill in and holds zero items, rather than being invented.',
    ],
    aiWrites: [
      'The prose of the sections that are not computed, drafted in small batches so one failed batch costs six sections their wording and nothing else.',
      'A section whose inputs are missing is never sent to a provider at all - there is nothing to draft it from.',
    ],
    outputs: [
      'An editable, versioned blueprint with per-section approval.',
      'A stale-approval flag and count when a section changed after it was approved.',
      'Version comparison, and export to Markdown, JSON, DOCX or PDF.',
    ],
    steps: [
      'Start from a bundled fictional project, or describe one.',
      'Generate the blueprint.',
      'Edit the scope section and watch the sections that depended on it flag as stale.',
      'Save a version, compare it with the previous one, and export.',
    ],
    limitation:
      'The document is a drafted starting point derived from a fictional project request, not a ' +
      'validated implementation design. No part of it has been reviewed or approved by SAP, and ' +
      'it needs a consultant to check it against the real project.',
    origins: ['rule_based', 'ai_generated', 'mock_ai', 'demo_data'],
    exports: ['Markdown', 'JSON', 'DOCX', 'PDF'],
  },
  {
    id: 'interview_coach',
    slug: 'sap-interview-coach',
    demoModule: 'interview-coach',
    number: 10,
    name: 'SAP Interview Coach',
    tagline: 'The rubric marks the answer. A model only writes the prose around it.',
    overview: {
      input: 'Your own answer to a practice question',
      output: 'A rubric score, with the concepts you missed',
      purpose: 'Practise SAP interviews with feedback that does not move',
    },
    problem:
      'Practising for an SAP interview without feedback teaches you to repeat your own gaps. ' +
      'Feedback from a model that scores as well as it writes gives a different mark on a ' +
      'different afternoon, which is worse than none.',
    demoInput:
      'A bundled bank of 104 fictional questions across nine tracks and six interview modes, ' +
      'each with an explicit rubric, a reference answer and known-wrong statements.',
    computed: [
      'Every score - overall, technical accuracy, completeness, clarity, business understanding and architecture where relevant - calculated from the rubric by Python.',
      'The keyword that credited each concept, printed next to it.',
      'A dimension the question does not test reported as not applicable, its weight shared among the dimensions that do apply, rather than dragging the score down.',
      'An unanswered question counted as pending, never averaged in as a zero.',
      'A stored score flagged as stale when the rubric it was computed against has since changed.',
    ],
    aiWrites: [
      'The coaching prose around a finished verdict.',
      'It is shown which concepts were missed, never the keyword list that decides them - a model that knows the marking scheme can write an answer that games it.',
      'The score exists before a provider is contacted, so the same answer scores identically with a real model, with the mock, or with no AI at all.',
    ],
    outputs: [
      'Per-answer scores with the evidence for each dimension.',
      'Session summaries and timing, recorded and reported but never applied to a mark.',
      'A performance dashboard with weak areas and a study plan derived from the answers themselves.',
    ],
    steps: [
      'Start a session on one or more tracks.',
      'Answer a question in your own words.',
      'Read the score, the matched keywords and the missing concepts.',
      'Complete the session and open the performance dashboard.',
    ],
    limitation:
      'Marking is keyword matching against a written rubric, which has a ceiling - the keyword ' +
      'that credited each concept is printed so you can see it. Scores are practice feedback on ' +
      'fictional questions and do not predict how any interview will go.',
    origins: ['rule_based', 'ai_generated', 'mock_ai', 'demo_data'],
    exports: ['CSV', 'XLSX', 'JSON', 'PDF'],
  },
] as const;

export function moduleBySlug(slug: string): ModuleContent | undefined {
  return modules.find((module) => module.slug === slug);
}

/**
 * A module by its API id.
 *
 * Throws rather than returning `undefined`, because the only caller is
 * `content/problems.ts`, where an id that resolves to nothing means a problem
 * area silently lists one tool fewer than it claims. Failing at render time is
 * how that gets noticed.
 */
export function moduleById(id: string): ModuleContent {
  const found = modules.find((module) => module.id === id);
  if (!found) {
    throw new Error(`Unknown module id: ${id}`);
  }
  return found;
}

export const moduleSlugs = modules.map((module) => module.slug);
