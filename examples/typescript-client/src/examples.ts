/**
 * The seven calls a front end has to get right, written out end to end.
 *
 * Each function here is one of the operations named in the integration brief:
 * health check, file upload, starting an analysis, polling its status,
 * retrieving findings, downloading an export, and asking a copilot question.
 * They are runnable against a local API (`npm run demo`) and are meant to be
 * copied into a real component and edited.
 *
 * Nothing here is clever. What it is, is *complete*: the error handling, the
 * origin labels and the "we could not answer that" paths are all in, because
 * those are the parts a first draft leaves out and a user notices first.
 */

import SapAiLabClient, { ApiError, saveToDisk } from './client';
import type {
  AnalysisStatus,
  DataQualityIssue,
  DownloadedFile,
  HealthStatus,
  OutputOrigin,
  Severity,
} from './types';

const client = new SapAiLabClient({ baseUrl: process.env.API_BASE_URL ?? 'http://127.0.0.1:8000' });

// ---------------------------------------------------------------------------
// 1. Health check
// ---------------------------------------------------------------------------

/**
 * Check the API before doing anything else.
 *
 * Worth calling on app start: "the API is not running" and "your file was
 * rejected" are different problems and a user should never see the second
 * message for the first cause.
 */
export async function checkHealth(): Promise<HealthStatus | null> {
  try {
    const health = await client.health();
    console.log(
      `${health.app_name} v${health.version} - ${health.status}`,
      `| database: ${health.database_connected ? 'connected' : 'unavailable'}`,
      `| AI: ${health.ai_provider}${health.ai_is_mock ? ' (mock, no key needed)' : ''}`,
    );
    return health;
  } catch (error) {
    if (error instanceof ApiError && error.code === 'network_error') {
      console.error('The API is not reachable. Start it with: uvicorn app.main:app --reload');
      return null;
    }
    throw error;
  }
}

// ---------------------------------------------------------------------------
// 2. File upload
// ---------------------------------------------------------------------------

interface UploadResponse {
  upload_id: string;
  row_count: number;
  detected_columns: string[];
  suggested_mapping: Record<string, string>;
  unmapped_columns: string[];
  missing_required_fields: string[];
  is_analyzable: boolean;
  data_quality_issues?: DataQualityIssue[];
}

/**
 * Upload a purchase order file.
 *
 * Two things to render that a first draft skips:
 *
 * - `suggested_mapping` is a *suggestion*. Show it and let the user correct it;
 *   the analyse call takes `column_mapping_overrides` for exactly that.
 * - `is_analyzable: false` with `missing_required_fields` is not an error, it is
 *   a form to fill in. Do not show it as a failure.
 */
export async function uploadPurchaseOrders(file: File): Promise<UploadResponse> {
  try {
    const upload = await client.upload<UploadResponse>('/po-risk/upload', file);

    if (!upload.is_analyzable) {
      console.warn(
        'This file cannot be analysed yet. Map these fields first:',
        upload.missing_required_fields.join(', '),
      );
    }
    for (const issue of upload.data_quality_issues ?? []) {
      console.log(`[${issue.severity}] ${issue.field}: ${issue.message}`);
    }
    return upload;
  } catch (error) {
    if (error instanceof ApiError && error.isUserFixable) {
      // The message is written to be shown: "File type '.pdf' is not supported.
      // Allowed types: .csv, .json, .xlsx"
      console.error(error.message);
    }
    throw error;
  }
}

// ---------------------------------------------------------------------------
// 3. Starting an analysis
// ---------------------------------------------------------------------------

interface Analysis {
  analysis_id: string;
  status: AnalysisStatus;
  created_at: string;
  completed_at: string | null;
  record_count: number;
  findings_count: number;
  critical_count: number;
  high_count: number;
  risk_score: number;
  ai_narrative: { available: boolean; summary: string | null; error: string | null };
  ai_output_origin: OutputOrigin | null;
  rule_errors: Array<{ rule_id: string; message: string }>;
  error_message?: string | null;
}

/**
 * Run the risk analysis.
 *
 * `rule_errors` is worth surfacing rather than ignoring: one rule failing does
 * not stop the others, so a result can be complete-looking and short by one
 * rule. Saying which one is the difference between a caveat and a lie.
 */
export async function runRiskAnalysis(uploadId: string): Promise<Analysis> {
  const analysis = await client.analyze<Analysis>('/po-risk/analyze', {
    upload_id: uploadId,
    generate_ai_summary: true,
  });

  console.log(
    `${analysis.findings_count} findings over ${analysis.record_count} lines`,
    `(${analysis.critical_count} critical, ${analysis.high_count} high)`,
  );

  if (analysis.rule_errors.length > 0) {
    console.warn(
      `${analysis.rule_errors.length} rule(s) could not run:`,
      analysis.rule_errors.map((e) => e.rule_id).join(', '),
    );
  }

  // The narrative is optional enrichment and is labelled. It never decides a
  // number, so a UI shows it *next to* the figures, never instead of them.
  if (analysis.ai_narrative.available) {
    console.log(`Summary (${analysis.ai_output_origin}): ${analysis.ai_narrative.summary}`);
  } else if (analysis.ai_narrative.error) {
    console.log(`No AI summary (${analysis.ai_narrative.error}). The findings are unaffected.`);
  }

  return analysis;
}

// ---------------------------------------------------------------------------
// 4. Polling analysis status
// ---------------------------------------------------------------------------

/**
 * Watch an analysis until it finishes.
 *
 * Analyses are synchronous today, so this returns on its first poll. Write your
 * UI against it anyway: when large uploads move to a background worker, the only
 * change is that `analyze()` starts returning `pending`.
 */
export async function watchAnalysis(
  analysisId: string,
  onStatus: (status: AnalysisStatus) => void,
): Promise<Analysis> {
  return client.pollUntilComplete<Analysis>(
    () => client.get<Analysis>(`/po-risk/analyses/${analysisId}`),
    { intervalMs: 1_000, timeoutMs: 5 * 60_000, onProgress: (a) => onStatus(a.status) },
  );
}

// ---------------------------------------------------------------------------
// 5. Retrieving findings
// ---------------------------------------------------------------------------

interface Finding {
  finding_id: string;
  rule_id: string;
  rule_name: string;
  severity: Severity;
  risk_category: string;
  explanation: string;
  recommended_action: string;
  evidence: Record<string, unknown>;
  confidence_score: number;
  estimated_financial_exposure: number | null;
  exposure_currency: string | null;
  output_origin: OutputOrigin;
  po_number: string | null;
  supplier_name: string | null;
}

interface FindingPage {
  analysis_id: string;
  total: number;
  limit: number;
  offset: number;
  findings: Finding[];
}

/**
 * One page of findings, filtered.
 *
 * Findings come back most serious first, then by exposure - a stable order, so
 * paging never shows the same row twice. Pass `severity` more than once to
 * filter on several levels.
 */
export async function getFindings(
  analysisId: string,
  options: { severity?: Severity[]; ruleId?: string; limit?: number; offset?: number } = {},
): Promise<FindingPage> {
  return client.get<FindingPage>(`/po-risk/analyses/${analysisId}/findings`, {
    severity: options.severity,
    rule_id: options.ruleId,
    limit: options.limit ?? 25,
    offset: options.offset ?? 0,
  });
}

/** Every critical and high finding, across as many pages as it takes. */
export async function getSeriousFindings(analysisId: string): Promise<Finding[]> {
  return client.listAll<Finding>(`/po-risk/analyses/${analysisId}/findings`, 'findings', {
    severity: ['critical', 'high'],
  });
}

// ---------------------------------------------------------------------------
// 6. Downloading an export
// ---------------------------------------------------------------------------

/**
 * Download the report.
 *
 * The filename comes from the API, not from the front end - a report called
 * `export.xlsx` in a downloads folder is indistinguishable from every other one.
 */
export async function downloadReport(
  analysisId: string,
  format: 'xlsx' | 'csv' | 'json' = 'xlsx',
): Promise<DownloadedFile> {
  const file = await client.downloadExport(`/po-risk/analyses/${analysisId}/export`, format);
  console.log(`Downloaded ${file.filename} (${file.blob.size} bytes, ${file.contentType})`);
  // In a browser:
  //   saveToDisk(file);
  return file;
}

// ---------------------------------------------------------------------------
// 7. Sending a copilot question
// ---------------------------------------------------------------------------

/**
 * Ask the Supplier Risk Copilot about a supplier.
 *
 * The important branch is the one where it *cannot* answer. The API tells you
 * so explicitly, and rendering `answer` regardless would turn "I do not have
 * that data" into what looks like a considered response.
 */
export async function askAboutSupplier(supplierId: string, question: string): Promise<string> {
  const reply = await client.askSupplierRiskCopilot({ question, supplier_id: supplierId });

  if (!reply.data_available) {
    return `Not answerable from the loaded records: ${reply.unavailable_reason}`;
  }

  const citations = reply.citations.length;
  return `${reply.answer}\n\n(${reply.output_origin}, ${citations} citation${
    citations === 1 ? '' : 's'
  })`;
}

// ---------------------------------------------------------------------------
// The whole journey, end to end
// ---------------------------------------------------------------------------

/**
 * What `npm run demo` runs: every step above, against a live local API.
 *
 * It uses the bundled demo dataset, so it needs no file of your own - which is
 * also the point of `/sample`: a front end can have something to show before
 * anybody has uploaded anything.
 */
export async function runFullJourney(): Promise<void> {
  const health = await checkHealth();
  if (!health) return;

  console.log('\n1. Fetching the bundled demo dataset...');
  const sample = await client.downloadSample('/po-risk/sample', 'csv');
  console.log(`   ${sample.filename} (${sample.blob.size} bytes)`);

  console.log('2. Uploading it...');
  const upload = await client.upload<UploadResponse>(
    '/po-risk/upload',
    sample.blob,
    {},
    sample.filename,
  );
  console.log(`   upload_id=${upload.upload_id}, ${upload.row_count} rows`);

  console.log('3. Running the analysis...');
  const analysis = await runRiskAnalysis(upload.upload_id);

  console.log('4. Polling until complete...');
  await watchAnalysis(analysis.analysis_id, (status) => console.log(`   status: ${status}`));

  console.log('5. Reading the most serious findings...');
  const serious = await getSeriousFindings(analysis.analysis_id);
  for (const finding of serious.slice(0, 3)) {
    console.log(`   [${finding.severity}] ${finding.rule_id} ${finding.rule_name}`);
    console.log(`      ${finding.explanation}`);
  }

  console.log('6. Downloading the report...');
  await downloadReport(analysis.analysis_id, 'xlsx');

  console.log('7. Asking the copilot...');
  // Needs a supplier risk dataset loaded first - see scripts/seed_database.py.
  try {
    console.log(`   ${await askAboutSupplier('0000390001', 'Why is this supplier risky?')}`);
  } catch (error) {
    if (error instanceof ApiError) {
      console.log(`   (skipped: ${error.message})`);
    } else {
      throw error;
    }
  }

  console.log('\nDone. Every figure above was computed by rules, not by a model.');
}

// `npm run demo`
if (typeof require !== 'undefined' && require.main === module) {
  runFullJourney().catch((error) => {
    console.error(error instanceof ApiError ? `${error.code}: ${error.message}` : error);
    process.exitCode = 1;
  });
}
