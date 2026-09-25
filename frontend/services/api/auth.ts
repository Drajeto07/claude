import { API_BASE_URL, ApiError, errorFrom, jsonInit, NetworkError } from "@/services/api/client";
import type { CurrentUser } from "@/types/document";

/** Only same-site relative paths, so `?next=` can't become an open redirect. */
export function safeNextPath(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\") ? next : "/";
}

// Sign-in pages call the API directly: a 401 here is an answer, not a reason to redirect.
async function authFetch(path: string, init: RequestInit = {}): Promise<Response> {
  try {
    return await fetch(`${API_BASE_URL}${path}`, { ...init, credentials: "include" });
  } catch {
    throw new NetworkError();
  }
}

async function authRequest(path: string, body: object): Promise<CurrentUser> {
  const res = await authFetch(path, jsonInit("POST", body));
  if (res.status === 422) {
    const error = await errorFrom(res, "Invalid request");
    throw new ApiError(422, { code: error.code, message: "Enter a valid email and a password of at least 8 characters." }, "", error.requestId);
  }
  if (!res.ok) throw await errorFrom(res, "Request failed");
  return res.json();
}

export function register(email: string, password: string, fullName?: string): Promise<CurrentUser> {
  return authRequest("/api/auth/register", { email, password, fullName: fullName?.trim() || null });
}

export function login(email: string, password: string): Promise<CurrentUser> {
  return authRequest("/api/auth/login", { email, password });
}

export async function logout(): Promise<void> {
  await authFetch("/api/auth/logout", { method: "POST" });
}

/** null when nobody is signed in -- unlike the rest of the API, never redirects. */
export async function getCurrentUser(): Promise<CurrentUser | null> {
  const res = await authFetch("/api/auth/me", { cache: "no-store" });
  if (res.status === 401) return null;
  if (!res.ok) throw await errorFrom(res, "Failed to load the signed-in user");
  return res.json();
}
