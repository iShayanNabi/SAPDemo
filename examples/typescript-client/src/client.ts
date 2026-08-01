/**
 * A small, dependency-free client for the SAP AI Application Lab API.
 *
 * Everything here works in a browser and in Node 18+ (both have `fetch`,
 * `FormData` and `AbortController`). There is no build step and no runtime
 * dependency, because the point of this file is to be *read*: it is the
 * reference for how the envelope, the errors, the uploads and the downloads are
 * meant to be handled, not a package to depend on.
 *
 * Copy it into your app and change it. It is an example, not a library.
 */

import type {
  AnalysisLike,
  ApiErrorPayload,
  ApiResponse,
  DownloadedFile,
  HealthStatus,
  Paginated,
} from './types';

/** Options for constructing a client. */
export interface ClientOptions {
  /** Where the API lives. Defaults to the local dev server. */
  baseUrl?: string;
  /**
   * Bearer token. Ignored by the API today - no endpoint requires one - and
   * accepted here so the seam exists in your app from the start.
   * See docs/API_AUTHENTICATION_PLAN.md.
   */
  token?: string | (() => string | null | Promise<string | null>);
  /** Per-request timeout in milliseconds. Analyses are synchronous and can be slow. */
  timeoutMs?: number;
  /** Injectable for tests. Defaults to the global `fetch`. */
  fetchImpl?: typeof fetch;
}

/**
 * An error carrying everything the API told us.
 *
 * `code` is stable and safe to branch on; `message` is safe to show a user (the
 * API never puts a path or a stack trace in it). `requestId` is the value to
 * quote in a support request - it is in the server log.
 */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;
  readonly requestId: string | null;

  constructor(
    message: string,
    options: {
      code?: string;
      status?: number;
      details?: Record<string, unknown>;
      requestId?: string | null;
    } = {},
  ) {
    super(message);
    this.name = 'ApiError';
    this.code = options.code ?? 'api_error';
    this.status = options.status ?? 0;
    this.details = options.details ?? {};
    this.requestId = options.requestId ?? null;
  }

  /** True when retrying the same request might work. */
  get isRetryable(): boolean {
    return this.status === 0 || this.status === 429 || this.status >= 500;
  }

  /** True when the *input* was the problem, so retrying will not help. */
  get isUserFixable(): boolean {
    return this.status === 400 || this.status === 422;
  }
}

const DEFAULT_BASE_URL = 'http://127.0.0.1:8000';
const DEFAULT_TIMEOUT_MS = 120_000;

export class SapAiLabClient {
  private readonly baseUrl: string;
  private readonly token: ClientOptions['token'];
  private readonly timeoutMs: number;
  private readonly fetchImpl: typeof fetch;

  constructor(options: ClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? DEFAULT_BASE_URL).replace(/\/+$/, '');
    this.token = options.token;
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  }

  // ---------------------------------------------------------------------
  // Plumbing
  // ---------------------------------------------------------------------

  private async authHeader(): Promise<Record<string, string>> {
    const value = typeof this.token === 'function' ? await this.token() : this.token;
    return value ? { Authorization: `Bearer ${value}` } : {};
  }

  private url(path: string, query?: Record<string, unknown>): string {
    const url = new URL(`${this.baseUrl}/api/v1${path}`);
    for (const [key, value] of Object.entries(query ?? {})) {
      if (value === undefined || value === null) continue;
      // Repeated keys are how this API takes a multi-valued filter, e.g.
      // ?severity=high&severity=critical.
      if (Array.isArray(value)) {
        for (const item of value) url.searchParams.append(key, String(item));
      } else {
        url.searchParams.set(key, String(value));
      }
    }
    return url.toString();
  }

  /**
   * Send a request and unwrap the envelope.
   *
   * Every failure - a network error, a non-JSON body, an HTTP error, an error
   * envelope - arrives as an `ApiError`. There is exactly one place in your app
   * that has to know the envelope exists, and this is it.
   */
  private async request<T>(
    method: string,
    path: string,
    options: { query?: Record<string, unknown>; body?: unknown; signal?: AbortSignal } = {},
  ): Promise<T> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    // Respect a caller's own cancellation as well as our timeout.
    options.signal?.addEventListener('abort', () => controller.abort(), { once: true });

    let response: Response;
    try {
      response = await this.fetchImpl(this.url(path, options.query), {
        method,
        headers: {
          Accept: 'application/json',
          ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
          ...(await this.authHeader()),
        },
        body:
          options.body === undefined
            ? undefined
            : options.body instanceof FormData
              ? options.body
              : JSON.stringify(options.body),
        signal: controller.signal,
      });
    } catch (cause) {
      const aborted = cause instanceof Error && cause.name === 'AbortError';
      throw new ApiError(
        aborted
          ? `The request timed out after ${this.timeoutMs / 1000}s.`
          : 'The API could not be reached. Is it running?',
        { code: aborted ? 'timeout' : 'network_error' },
      );
    } finally {
      clearTimeout(timeout);
    }

    const requestId = response.headers.get('X-Request-ID');

    let body: ApiResponse<T>;
    try {
      body = (await response.json()) as ApiResponse<T>;
    } catch {
      throw new ApiError(`The API returned a non-JSON response (HTTP ${response.status}).`, {
        code: 'invalid_response',
        status: response.status,
        requestId,
      });
    }

    if (!body.success) {
      const error: ApiErrorPayload = body.error;
      throw new ApiError(error.message, {
        code: error.code,
        status: response.status,
        details: error.details,
        requestId: body.meta.request_id ?? requestId,
      });
    }

    return body.data;
  }

  /**
   * Download a file.
   *
   * Exports do *not* use the JSON envelope - they return the file itself, so a
   * browser can stream it straight to disk. The filename comes from
   * `Content-Disposition`, which the API exposes to cross-origin callers; a
   * `fetch` cannot read that header otherwise.
   */
  private async download(
    path: string,
    query?: Record<string, unknown>,
  ): Promise<DownloadedFile> {
    const response = await this.fetchImpl(this.url(path, query), {
      method: 'GET',
      headers: await this.authHeader(),
    });

    if (!response.ok) {
      // A failed download still answers with the JSON envelope.
      let message = `The download failed (HTTP ${response.status}).`;
      let code = 'download_failed';
      try {
        const body = (await response.json()) as ApiResponse<never>;
        if (!body.success) {
          message = body.error.message;
          code = body.error.code;
        }
      } catch {
        /* keep the generic message */
      }
      throw new ApiError(message, {
        code,
        status: response.status,
        requestId: response.headers.get('X-Request-ID'),
      });
    }

    return {
      blob: await response.blob(),
      filename: filenameFromDisposition(response.headers.get('Content-Disposition')),
      contentType: response.headers.get('Content-Type') ?? 'application/octet-stream',
    };
  }

  // ---------------------------------------------------------------------
  // 1. Health check
  // ---------------------------------------------------------------------

  /** Is the API up, is the database reachable, and which AI provider is active? */
  health(): Promise<HealthStatus> {
    return this.request<HealthStatus>('GET', '/health');
  }

  /** How authentication is configured. Reports "off" today, and says so honestly. */
  authStatus(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>('GET', '/auth-status');
  }

  // ---------------------------------------------------------------------
  // 2. File upload
  // ---------------------------------------------------------------------

  /**
   * Upload a file to a module's `/upload` endpoint.
   *
   * `extraFields` carries the form fields some modules need - the invoice
   * validator wants `dataset`, the supplier risk module wants `dataset` and an
   * optional `dataset_id`.
   *
   * ```ts
   * const upload = await client.upload('/po-risk/upload', file);
   * const invoices = await client.upload('/invoices/upload', file, { dataset: 'invoices' });
   * ```
   */
  upload<T = unknown>(
    path: string,
    file: File | Blob,
    extraFields: Record<string, string> = {},
    filename?: string,
  ): Promise<T> {
    const form = new FormData();
    form.append('file', file, filename ?? (file instanceof File ? file.name : 'upload'));
    for (const [key, value] of Object.entries(extraFields)) form.append(key, value);
    return this.request<T>('POST', path, { body: form });
  }

  // ---------------------------------------------------------------------
  // 3. Starting an analysis
  // ---------------------------------------------------------------------

  /**
   * Start an analysis and get the finished result.
   *
   * Analyses are **synchronous** today: this promise resolves with a completed
   * analysis. It can take a while on a large file - hence the generous default
   * timeout - so show a spinner, not a progress bar you cannot fill in.
   *
   * ```ts
   * const analysis = await client.analyze('/po-risk/analyze', {
   *   upload_id: upload.upload_id,
   *   generate_ai_summary: true,
   * });
   * ```
   */
  analyze<T = unknown>(path: string, body: Record<string, unknown>): Promise<T> {
    return this.request<T>('POST', path, { body });
  }

  // ---------------------------------------------------------------------
  // 4. Polling an analysis status
  // ---------------------------------------------------------------------

  /**
   * Poll a resource until it reaches a terminal state.
   *
   * Not needed today - `analyze()` already returns a completed analysis - and
   * written now because that is the part of the contract most likely to change:
   * when large uploads move to a background worker, `analyze()` will return
   * `pending` and this is the loop that copes. Writing your UI against this from
   * the start means the change is a one-line switch rather than a rewrite.
   *
   * ```ts
   * const done = await client.pollUntilComplete(
   *   () => client.get(`/po-risk/analyses/${id}`),
   *   { onProgress: (a) => setStatus(a.status) },
   * );
   * ```
   */
  async pollUntilComplete<T extends AnalysisLike>(
    fetchOnce: () => Promise<T>,
    options: {
      intervalMs?: number;
      timeoutMs?: number;
      onProgress?: (current: T) => void;
      signal?: AbortSignal;
    } = {},
  ): Promise<T> {
    const interval = options.intervalMs ?? 1_000;
    const deadline = Date.now() + (options.timeoutMs ?? 5 * 60_000);

    for (;;) {
      if (options.signal?.aborted) throw new ApiError('Polling was cancelled.', { code: 'aborted' });

      const current = await fetchOnce();
      options.onProgress?.(current);

      if (current.status === 'completed') return current;
      if (current.status === 'failed') {
        throw new ApiError(current.error_message ?? 'The analysis failed.', {
          code: 'analysis_failed',
        });
      }
      if (Date.now() > deadline) {
        throw new ApiError('The analysis did not finish in time.', { code: 'timeout' });
      }
      await sleep(interval);
    }
  }

  // ---------------------------------------------------------------------
  // 5. Retrieving findings (and any other paged list)
  // ---------------------------------------------------------------------

  /** GET any endpoint that returns the JSON envelope. */
  get<T = unknown>(path: string, query?: Record<string, unknown>): Promise<T> {
    return this.request<T>('GET', path, { query });
  }

  /** POST any endpoint that returns the JSON envelope. */
  post<T = unknown>(path: string, body?: Record<string, unknown>): Promise<T> {
    return this.request<T>('POST', path, { body: body ?? {} });
  }

  /** PUT any endpoint that returns the JSON envelope. */
  put<T = unknown>(path: string, body: Record<string, unknown>): Promise<T> {
    return this.request<T>('PUT', path, { body });
  }

  /**
   * Read every page of a list endpoint.
   *
   * The API caps `limit`, so "give me everything" is several requests. This
   * walks them, and stops on `total` rather than on an empty page - a list that
   * grows while you page through it would otherwise never end.
   *
   * ```ts
   * const findings = await client.listAll<Finding>(
   *   `/po-risk/analyses/${id}/findings`, 'findings', { severity: ['high', 'critical'] },
   * );
   * ```
   */
  async listAll<TItem>(
    path: string,
    itemsKey: string,
    query: Record<string, unknown> = {},
    pageSize = 200,
  ): Promise<TItem[]> {
    const collected: TItem[] = [];
    let offset = 0;

    for (;;) {
      const page = await this.get<Paginated & Record<string, unknown>>(path, {
        ...query,
        limit: pageSize,
        offset,
      });
      const items = (page[itemsKey] ?? []) as TItem[];
      collected.push(...items);

      offset += pageSize;
      if (items.length === 0 || collected.length >= page.total) return collected;
    }
  }

  // ---------------------------------------------------------------------
  // 6. Downloading an export
  // ---------------------------------------------------------------------

  /**
   * Download a report.
   *
   * ```ts
   * const report = await client.downloadExport(
   *   `/po-risk/analyses/${id}/export`, 'xlsx',
   * );
   * saveToDisk(report);
   * ```
   */
  downloadExport(path: string, format: string): Promise<DownloadedFile> {
    return this.download(path, { format });
  }

  /** Download a bundled demo dataset, to try a module without a file of your own. */
  downloadSample(path: string, format?: string): Promise<DownloadedFile> {
    return this.download(path, format ? { format } : undefined);
  }

  // ---------------------------------------------------------------------
  // 7. Asking the copilot a question
  // ---------------------------------------------------------------------

  /**
   * Ask the Supplier Risk Copilot a question.
   *
   * The answer is built from the loaded records and carries citations. When the
   * data cannot answer, `data_available` is false and `unavailable_reason` says
   * why - **render that instead of the answer**, rather than showing a confident
   * sentence that was never backed by anything.
   */
  askSupplierRiskCopilot(body: {
    question: string;
    supplier_id?: string;
    assessment_id?: string;
    generate_ai_summary?: boolean;
  }): Promise<{
    answer: string;
    data_available: boolean;
    unavailable_reason: string | null;
    citations: unknown[];
    output_origin: string;
    follow_up_suggestions: string[];
  }> {
    return this.post('/supplier-risk/chat', body);
  }

  /** Ask a question about an analysed contract. Answers cite the page they came from. */
  askContract(
    contractId: string,
    body: { question: string; generate_ai_summary?: boolean },
  ): Promise<{
    answer: string;
    answered: boolean;
    unavailable_reason: string | null;
    citations: unknown[];
    output_origin: string;
  }> {
    return this.post(`/contracts/${encodeURIComponent(contractId)}/questions`, body);
  }
}

// -------------------------------------------------------------------------
// Helpers
// -------------------------------------------------------------------------

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Pull the filename out of a `Content-Disposition` header.
 *
 * Handles the RFC 5987 `filename*=UTF-8''...` form as well as the plain one,
 * because a contract report named after a German supplier will use it.
 */
export function filenameFromDisposition(header: string | null): string {
  if (!header) return 'download';

  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(header)?.[1];
  if (encoded) {
    try {
      return decodeURIComponent(encoded);
    } catch {
      /* fall through to the plain form */
    }
  }

  const plain = /filename="?([^";]+)"?/i.exec(header)?.[1];
  return plain ? plain.trim() : 'download';
}

/**
 * Save a downloaded file in a browser.
 *
 * Not part of the client because it touches the DOM; here because every app
 * needs it and gets the object-URL lifetime wrong the first time.
 */
export function saveToDisk(file: DownloadedFile): void {
  const url = URL.createObjectURL(file.blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = file.filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Revoke on the next tick: revoking synchronously can cancel the download in
  // some browsers before it has started.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export default SapAiLabClient;
