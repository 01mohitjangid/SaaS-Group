/** One HTTP client for both apps.
 *
 * The API answers every failure with the same envelope, so unwrapping it here means no
 * screen has to reinvent "what went wrong" — and `problems` survives all the way to the
 * form field that caused it.
 */

export interface ApiProblem {
  field: string | null;
  message: string;
  hint?: string;
  code?: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly problems: ApiProblem[];

  constructor(status: number, code: string, message: string, problems: ApiProblem[] = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.problems = problems;
  }

  /** 401/403 are a different kind of dead end: no amount of retrying fixes them. */
  get isPermission(): boolean {
    return this.status === 401 || this.status === 403;
  }

  problemFor(field: string): ApiProblem | undefined {
    return this.problems.find((problem) => problem.field === field);
  }
}

export const API_BASE: string =
  (import.meta.env?.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000";

function authHeaders(token?: string): HeadersInit {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function unwrap(response: Response): Promise<never> {
  let code = "http_error";
  let message = `${response.status} ${response.statusText}`;
  let problems: ApiProblem[] = [];
  try {
    const body = await response.json();
    if (body?.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
      problems = body.error.problems ?? [];
    }
  } catch {
    // A non-JSON failure (a proxy, a dead server) — keep the status line.
  }
  throw new ApiError(response.status, code, message, problems);
}

export interface RequestOptions {
  token?: string;
  method?: string;
  body?: unknown;
  form?: FormData;
  signal?: AbortSignal;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { token, method = "GET", body, form, signal } = options;
  const init: RequestInit = { method, signal, headers: { ...authHeaders(token) } };

  if (form) {
    init.body = form;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { ...init.headers, "Content-Type": "application/json" };
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch (cause) {
    // fetch only rejects when the network itself failed, which needs its own message:
    // "500" and "the API is not running" are very different problems for the reader.
    throw new ApiError(0, "network_error", "Cannot reach the API. Is the server running?", [
      { field: null, message: String(cause), hint: `Tried ${API_BASE}${path}` },
    ]);
  }

  if (!response.ok) await unwrap(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function query(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const rendered = search.toString();
  return rendered ? `?${rendered}` : "";
}
