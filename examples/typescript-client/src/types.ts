/**
 * The shapes this API guarantees, hand-written and small.
 *
 * These are the *envelope* and the handful of cross-cutting types every module
 * shares. The per-module payload types are not here on purpose: generate them
 * from the OpenAPI document instead, so they cannot drift from the server.
 *
 *   npx openapi-typescript ../../docs/openapi.json -o src/schema.ts
 *
 * What is written by hand is what a generator cannot express: that `data` is
 * non-null exactly when `success` is true, and that a failure always carries an
 * error. Those two facts are what let `unwrap()` below be type-safe.
 */

/** How a value was produced. Shown next to every figure the UI renders. */
export type OutputOrigin =
  | 'rule_based'
  | 'ai_generated'
  | 'mock_ai'
  | 'forecast'
  | 'demo_data';

/**
 * Severity of a *finding about the data*: a risk, an invoice exception, a
 * contract risk. Ordered least to most serious.
 */
export type Severity = 'low' | 'medium' | 'high' | 'critical';

/**
 * Severity of a message about the *processing*: a data-quality note, a warning
 * on a forecast. Deliberately a different scale from `Severity` - colouring
 * "three rows had no delivery date" the same red as a fraud finding is wrong.
 */
export type IssueSeverity = 'info' | 'warning' | 'error';

/** The lifecycle of one analysis run. Synchronous today, so you will see `completed`. */
export type AnalysisStatus = 'pending' | 'running' | 'completed' | 'failed';

/** Metadata present on every response, success or failure. */
export interface ResponseMeta {
  /** ISO-8601, always UTC and always timezone-aware. Safe for `new Date()`. */
  timestamp: string;
  /** Matches the `X-Request-ID` header and the server log. Quote it in a bug report. */
  request_id: string | null;
  api_version: string;
}

/** Machine-readable error information. `message` is always safe to show a user. */
export interface ApiErrorPayload {
  code: string;
  message: string;
  details: Record<string, unknown>;
}

/**
 * The response envelope, as a discriminated union.
 *
 * Written as a union rather than as `{ data: T | null }` so TypeScript narrows:
 * after `if (body.success)`, `body.data` is `T`, not `T | null`. That is the
 * whole reason for hand-writing this file.
 */
export type ApiResponse<T> =
  | { success: true; data: T; error: null; meta: ResponseMeta }
  | { success: false; data: null; error: ApiErrorPayload; meta: ResponseMeta };

/** Every list endpoint echoes the window it served. */
export interface Paginated {
  total: number;
  limit: number;
  offset: number;
}

/** A non-fatal problem found while loading a file. Reported, never fatal. */
export interface DataQualityIssue {
  field: string;
  issue_type: string;
  message: string;
  affected_rows: number;
  sample_rows: number[];
  severity: IssueSeverity;
}

/** `GET /api/v1/health`. */
export interface HealthStatus {
  status: 'ok' | 'degraded';
  app_name: string;
  version: string;
  environment: string;
  database_connected: boolean;
  ai_provider: 'mock' | 'anthropic' | 'openai';
  ai_is_mock: boolean;
}

/** The subset of an upload response every module returns. */
export interface UploadResult {
  upload_id: string;
  row_count: number;
  column_count?: number;
  detected_columns?: string[];
  suggested_mapping?: Record<string, string>;
  missing_required_fields?: string[];
  is_analyzable?: boolean;
  data_quality_issues?: DataQualityIssue[];
}

/** The subset of an analysis response the polling helper needs. */
export interface AnalysisLike {
  status: AnalysisStatus;
  created_at: string;
  completed_at?: string | null;
  error_message?: string | null;
}

/** A downloaded report: the bytes plus the filename the API chose. */
export interface DownloadedFile {
  blob: Blob;
  filename: string;
  contentType: string;
}
