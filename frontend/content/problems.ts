/**
 * The procurement problems this project addresses, grouped.
 *
 * The home page used to open with an argument about software design, which is
 * the right thing to say to somebody who already knows what the project is and
 * the wrong thing to say to somebody who does not. Six problems a procurement
 * team recognises is the first thing on the page now, and the ten tools sit
 * underneath as the answers to them.
 *
 * Each area names the modules that address it, by id rather than by name, so a
 * renamed module cannot leave a group pointing at a tool that no longer exists.
 * The ids are checked against `content/modules.ts` by a test that also asserts
 * every module appears in exactly one area - a module in none is a tool nobody
 * can find from the home page, and a module in two makes the six counts add up
 * to more than ten.
 */

export interface ProblemArea {
  /** The problem, in the words somebody with it would use. */
  title: string;
  /** One sentence. Not two. */
  summary: string;
  /** Module ids from `content/modules.ts`, in the order they are listed there. */
  moduleIds: readonly string[];
}

export const problemAreas: readonly ProblemArea[] = [
  {
    title: 'Risk and compliance',
    summary:
      'Which of this week’s purchase orders is a duplicate, a split order, or priced well ' +
      'away from the contract - before any of them is released.',
    moduleIds: ['po_risk'],
  },
  {
    title: 'Spend visibility and savings analysis',
    summary:
      'Where the money went, how much of it is under contract, and which patterns are worth ' +
      'a category manager’s time.',
    moduleIds: ['spend_analytics'],
  },
  {
    title: 'Supplier selection and risk',
    summary:
      'Which suppliers can actually serve a requirement, in an order somebody can reproduce - ' +
      'and what is known about the risk each one carries.',
    moduleIds: ['supplier_recommendation', 'supplier_risk_copilot'],
  },
  {
    title: 'Invoice and contract review',
    summary:
      'Whether an invoice matches what was ordered and received, and what the contract behind ' +
      'it actually commits to.',
    moduleIds: ['invoice_validator', 'contract_assistant'],
  },
  {
    title: 'Inventory planning',
    summary:
      'Which materials run short, on which date, and how early an order has to be placed for ' +
      'the lead time to be survivable.',
    moduleIds: ['inventory_predictor'],
  },
  {
    title: 'SAP project delivery and training',
    summary:
      'The drafting work around an SAP project - test suites, implementation blueprints - and ' +
      'practice for the interviews that staff it.',
    moduleIds: ['test_case_generator', 'blueprint_generator', 'interview_coach'],
  },
] as const;
