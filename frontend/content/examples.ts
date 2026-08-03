/**
 * Two illustrative result panels for the home page.
 *
 * **These are not screenshots, and the page says so where they are rendered.**
 * That sentence is the whole reason this file exists as typed content rather
 * than as an image: there is no sanitised screenshot of the application in this
 * repository, and the alternative to labelled mock-ups is a fabricated picture
 * of a dashboard - which is the single most common way a demonstration site
 * ends up making a claim nobody intended.
 *
 * The rules the values follow:
 *
 * - Every name, number, date and identifier is invented for this page, in the
 *   same shape as the bundled fictional datasets. None of it is a real
 *   supplier, a real order or a real result, and none of it came from a
 *   customer.
 * - No outcome is claimed. There is no "saved €48,200", no "prevented", no
 *   percentage improvement and no before-and-after. A finding is a finding.
 * - The origin label on each panel is the same one the application prints next
 *   to the same kind of value, so an illustration cannot show a computed figure
 *   dressed as an AI one or the reverse.
 */

import type { OutputOrigin } from './modules';

export interface ExampleField {
  label: string;
  value: string;
}

export interface ExamplePanel {
  /** Which module this is illustrating. */
  moduleName: string;
  /** The headline of the result. */
  title: string;
  /** The origin badge shown against the computed part of the panel. */
  origin: OutputOrigin;
  fields: readonly ExampleField[];
  /** The evidence sentence a rule or a model attaches to the result. */
  evidence: string;
  /** The narrative half, and the origin it carries. Always labelled separately. */
  narrative: {
    origin: OutputOrigin;
    text: string;
  };
}

export const examplePanels: readonly ExamplePanel[] = [
  {
    moduleName: 'Purchase Order Risk Checker',
    title: 'Split purchase order',
    origin: 'rule_based',
    fields: [
      { label: 'Supplier', value: 'Meridian Components GmbH' },
      { label: 'Orders', value: '4500018842, 4500018847, 4500018851' },
      { label: 'Severity', value: 'High' },
      { label: 'Estimated exposure', value: '€48,300' },
    ],
    evidence:
      'Three orders for the same material to the same supplier within 48 hours, each €16,100 ' +
      '- just under the €20,000 release threshold configured for this plant.',
    narrative: {
      origin: 'mock_ai',
      text:
        'These three orders look like one requirement split to stay below the approval limit. ' +
        'Worth confirming with the requisitioner before any of them is released.',
    },
  },
  {
    moduleName: 'Inventory Predictor',
    title: 'Projected shortage',
    origin: 'forecast',
    fields: [
      { label: 'Material', value: '100001 · Plant 1000' },
      { label: 'Model selected', value: 'Holt-Winters (seasonal)' },
      { label: 'Projected shortage', value: '15 November' },
      { label: 'Order by', value: '25 October (21-day lead time)' },
    ],
    evidence:
      'Chosen over four simpler models on identical held-out periods, and only because it beat ' +
      'the next-best by more than the configured margin for the extra parameters it fits.',
    narrative: {
      origin: 'mock_ai',
      text:
        'Demand for this material peaks in November, so the reorder point was calculated from ' +
        'November’s expected demand rather than today’s. A projection carries error; treat the ' +
        'date as a planning signal rather than a commitment.',
    },
  },
] as const;
