import { ApiError, apiUrl, errorFrom, jsonInit, NetworkError } from "@/services/api/client";
import type { CurrentUser } from "@/types/document";

/** Only same-site relative paths, so `?next=` can't become an open redirect. */
export function safeNextPath(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\") ? next : "/";
}

// Sign-in pages call the API directly: a 401 here is an answer, not a reason to redirect.
async function authFetch(path: string, init: RequestInit = {}): Promise<Response> {
  try {
    return await fetch(apiUrl(path), { ...init, credentials: "include" });
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
  return authRequest("/auth/register", { email, password, fullName: fullName?.trim() || null });
}

export function login(email: string, password: string): Promise<CurrentUser> {
  return authRequest("/auth/login", { email, password });
}

/** Asks for a link to choose a new password (ACCT-002); resolves with what to tell the
 * user, the same whether or not the address has an account. */
export async function requestPasswordReset(email: string): Promise<string> {
  const res = await authFetch("/auth/password-reset", jsonInit("POST", { email }));
  if (res.status === 422) {
    const error = await errorFrom(res, "Invalid request");
    throw new ApiError(422, { code: error.code, message: "Enter a valid email address." }, "", error.requestId);
  }
  if (!res.ok) throw await errorFrom(res, "Couldn't ask for a link");
  return ((await res.json()) as { message: string }).message;
}

/** Sets a new password with a reset link's token; every browser signed in to the account is then signed out. */
export async function confirmPasswordReset(token: string, password: string): Promise<void> {
  const res = await authFetch("/auth/password-reset/confirm", jsonInit("POST", { token, password }));
  if (res.status === 422) {
    const error = await errorFrom(res, "Invalid request");
    throw new ApiError(422, { code: error.code, message: "Choose a password of at least 8 characters." }, "", error.requestId);
  }
  if (!res.ok) throw await errorFrom(res, "Couldn't set the new password");
}

/** Sends the signed-in user another link to confirm their address (ACCT-003); resolves with what to tell them. */
export async function requestEmailVerification(): Promise<string> {
  const res = await authFetch("/auth/verify-email", { method: "POST" });
  if (!res.ok) throw await errorFrom(res, "Couldn't send the link");
  return ((await res.json()) as { message: string }).message;
}

/** Confirms an address with the token of the link sent to it; works signed in or not. */
export async function confirmEmailVerification(token: string): Promise<void> {
  const res = await authFetch("/auth/verify-email/confirm", jsonInit("POST", { token }));
  if (!res.ok) throw await errorFrom(res, "Couldn't confirm the address");
}

/** Changes the signed-in user's password; every other browser signed in to the account is then signed out. */
export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  const res = await authFetch("/auth/password", jsonInit("PUT", { currentPassword, newPassword }));
  if (res.status === 422) {
    const error = await errorFrom(res, "Invalid request");
    throw new ApiError(422, { code: error.code, message: "Choose a new password of at least 8 characters." }, "", error.requestId);
  }
  if (!res.ok) throw await errorFrom(res, "Couldn't change the password");
}

export async function logout(): Promise<void> {
  await authFetch("/auth/logout", { method: "POST" });
}

/** null when nobody is signed in -- unlike the rest of the API, never redirects. */
export async function getCurrentUser(): Promise<CurrentUser | null> {
  const res = await authFetch("/auth/me", { cache: "no-store" });
  if (res.status === 401) return null;
  if (!res.ok) throw await errorFrom(res, "Failed to load the signed-in user");
  return res.json();
}
