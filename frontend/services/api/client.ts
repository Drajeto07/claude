import type { ApiErrorBody } from "@/types/document";

/**
 * The one place the frontend talks HTTP to the backend (корекции.docx §49):
 * every call sends the session cookie, a 401 in the browser goes to /login and
 * back, and every failure becomes an ApiError carrying the backend's
 * standard error body -- a message meant for people, a code, details and the
 * request id -- or a NetworkError when no answer came at all.
 */

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
export const SESSION_COOKIE = "smartdoc_session";

/** An error the API answered with (backend app/api/errors.py). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown> | null;
  /** Quote it when reporting a problem: the server's log is searchable by it. */
  readonly requestId: string | null;

  constructor(status: number, body: Partial<ApiErrorBody> | null, fallback: string, requestId: string | null) {
    super(body?.message || fallback);
    this.name = "ApiError";
    this.status = status;
    this.code = body?.code ?? "error";
    this.details = body?.details ?? null;
    this.requestId = body?.request_id ?? requestId;
  }
}

export class UnauthorizedError extends ApiError {
  constructor(requestId: string | null = null) {
    super(401, { code: "not_signed_in", message: "Not signed in" }, "Not signed in", requestId);
    this.name = "UnauthorizedError";
  }
}

/** No answer: the browser is offline or the server can't be reached. */
export class NetworkError extends Error {
  constructor() {
    super("Can't reach the server. Check your connection and try again.");
    this.name = "NetworkError";
  }
}

/** A person-readable message for anything a call can throw. */
export function errorMessage(error: unknown, fallback = "Something went wrong."): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, { ...init, credentials: "include" });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new NetworkError();
  }
  if (res.status === 401) {
    if (typeof window !== "undefined") {
      const next = window.location.pathname + window.location.search;
      // Plain module, no router hook available; a full load also drops any stale state.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign(`/login?next=${encodeURIComponent(next)}`);
    }
    throw new UnauthorizedError(res.headers.get("X-Request-ID"));
  }
  return res;
}

/** The ApiError a failed response stands for; `fallback` when its body says nothing. */
export async function errorFrom(res: Response, fallback: string): Promise<ApiError> {
  const body = (await res.json().catch(() => null)) as Partial<ApiErrorBody> | null;
  return new ApiError(res.status, body, `${fallback} (${res.status})`, res.headers.get("X-Request-ID"));
}

export async function jsonOrThrow<T>(res: Response, fallback: string): Promise<T> {
  if (!res.ok) throw await errorFrom(res, fallback);
  return res.json() as Promise<T>;
}

export async function okOrThrow(res: Response, fallback: string): Promise<void> {
  if (!res.ok) throw await errorFrom(res, fallback);
}

/** A JSON request; `ifMatch` is the version the change was based on (412 if it moved on). */
export function jsonInit(method: string, body: unknown, ifMatch?: number | null): RequestInit {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (ifMatch != null) headers["If-Match"] = String(ifMatch);
  return { method, headers, body: JSON.stringify(body) };
}
