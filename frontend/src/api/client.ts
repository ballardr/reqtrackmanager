/**
 * Thin REST client wrapping fetch(): attaches the bearer token, resolves
 * the API base URL from the environment (I-A-01: loosely coupled to the
 * backend), and normalises error handling.
 */

import { localToday } from "../utils/localDate";

const BASE_URL =
  window.__ENV__?.VITE_API_BASE_URL ??
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
  "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  /** The response's `detail` when it was structured (an object), else `undefined`; a plain message is in `message`. */
  detail?: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

let authToken: string | null = null;

export function setAuthToken(token: string | null): void {
  authToken = token;
  if (token) {
    localStorage.setItem("reqtrack_token", token);
  } else {
    localStorage.removeItem("reqtrack_token");
    clearMediaToken();
  }
}

/** The short-lived credential file URLs carry (see `fileUrl`); never the session token. */
let mediaToken: string | null = null;
let mediaRefreshTimer: ReturnType<typeof setTimeout> | undefined;
/** Renewed well inside the server's 15-minute lifetime so a URL built at any moment still has minutes left. */
const MEDIA_TOKEN_REFRESH_MS = 10 * 60 * 1000;

function clearMediaToken(): void {
  mediaToken = null;
  if (mediaRefreshTimer !== undefined) clearTimeout(mediaRefreshTimer);
  mediaRefreshTimer = undefined;
}

/**
 * Fetches the media token for the current session and schedules its renewal. Awaited before the signed-in
 * UI first renders (`AuthContext`), so no `<img>` is built with an empty credential. A failure leaves file
 * URLs without a token (they 401 until the next renewal) and never breaks the session itself.
 */
export async function ensureMediaToken(): Promise<void> {
  if (mediaRefreshTimer !== undefined) clearTimeout(mediaRefreshTimer);
  mediaRefreshTimer = undefined;
  if (!authToken) {
    mediaToken = null;
    return;
  }
  try {
    const result = await request<{ token: string }>("/api/v1/auth/media-token", { method: "POST" });
    mediaToken = result.token;
  } catch {
    mediaToken = null;
  }
  if (authToken) mediaRefreshTimer = setTimeout(() => void ensureMediaToken(), MEDIA_TOKEN_REFRESH_MS);
}

export function loadStoredToken(): string | null {
  authToken = localStorage.getItem("reqtrack_token");
  return authToken;
}

/**
 * Fired whenever any request gets a 401 (expired/invalidated token — e.g.
 * the 12h access token lapsing, or a password change bumping
 * `User.token_version` server-side). `AuthContext` listens for this and
 * clears the session immediately, rather than leaving stale UI state up
 * until a hard reload re-runs the mount-time `/auth/me` check — this was
 * the actual cause of "the UI looks broken until I force-refresh, then I'm
 * at the login page": every fetch after expiry was 401ing silently, with
 * nothing reacting to it in place.
 */
export const AUTH_UNAUTHORIZED_EVENT = "reqtrack:unauthorized";

/** No request in this client carries a timeout by default — a plain `fetch()`
 * with no `signal` waits indefinitely, so a genuinely slow backend call has
 * always surfaced as a spinner that never resolves, not a distinct "timed
 * out" error. `timeoutMs` opts a specific call into an explicit ceiling
 * (login uses this — see AuthContext.tsx — since a bcrypt-verify under
 * concurrent login load can legitimately take longer than this app's other,
 * cheap requests; see docs/decisions.md, "bcrypt login cost under
 * concurrent load"). */
async function rawRequest(path: string, options: RequestInit = {}, timeoutMs?: number): Promise<Response> {
  const headers: Record<string, string> = { ...(options.headers as Record<string, string>), "X-Client-Date": localToday() };
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  if (authToken) {
    headers["Authorization"] = `Bearer ${authToken}`;
  }

  const controller = timeoutMs !== undefined ? new AbortController() : undefined;
  const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : undefined;
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, { ...options, headers, signal: controller?.signal ?? options.signal });
  } catch (err) {
    if (controller?.signal.aborted) {
      throw new ApiError(0, "The server is taking longer than expected to respond. Please try again.");
    }
    throw err;
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
  if (!response.ok) {
    // The backend raises 401 for two different reasons: the bearer token
    // itself being missing/invalid/expired (`deps.py`'s shared
    // `_UNAUTHORIZED`, always sent with a `WWW-Authenticate: Bearer`
    // header — the standard signal for "your credentials are bad"), vs. an
    // ordinary business-logic 401 with a valid token attached (wrong
    // current password, bad 2FA code). Only the former means the session
    // itself is dead and should force a logout; treating every 401 the
    // same would log the user out just for mistyping their current
    // password on the change-password form.
    if (response.status === 401 && authToken && response.headers.get("www-authenticate")) {
      window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
    }
    let message = response.statusText;
    let detail: unknown;
    try {
      const body = await response.json();
      message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
      if (body.detail && typeof body.detail === "object" && !Array.isArray(body.detail)) {
        detail = body.detail;
        if (typeof body.detail.message === "string") message = body.detail.message;
      }
    } catch {
      // response had no JSON body; fall back to statusText
    }
    throw new ApiError(response.status, message, detail);
  }
  return response;
}

async function request<T>(path: string, options: RequestInit = {}, timeoutMs?: number): Promise<T> {
  const response = await rawRequest(path, options, timeoutMs);
  if (response.status === 204) {
    return undefined as T;
  }
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return (await response.json()) as T;
  }
  return (await response.blob()) as unknown as T;
}

/** A page of results from a `limit`/`offset`-paginated list endpoint (U-P-06).
 * `totalUnfiltered` is optional — only the requirements/change-requests/projects
 * list endpoints send the `X-Total-Unfiltered-Count` header it comes from;
 * every other paginated endpoint (and every existing test/story mock built
 * before this field existed) simply omits it, and callers that care fall
 * back to `total` themselves (see `ResultCount`'s callers). */
export interface Page<T> {
  items: T[];
  total: number;
  totalUnfiltered?: number;
}

async function requestPage<T>(path: string): Promise<Page<T>> {
  const response = await rawRequest(path);
  const items = (await response.json()) as T[];
  const totalHeader = response.headers.get("x-total-count");
  const totalUnfilteredHeader = response.headers.get("x-total-unfiltered-count");
  return {
    items,
    total: totalHeader ? Number(totalHeader) : items.length,
    totalUnfiltered: totalUnfilteredHeader ? Number(totalUnfilteredHeader) : undefined,
  };
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  getPage: <T>(path: string) => requestPage<T>(path),
  /** `signal` lets the caller cancel the request (a superseded search); `timeoutMs` takes precedence when both are given. */
  post: <T>(path: string, body?: unknown, timeoutMs?: number, signal?: AbortSignal) =>
    request<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined, signal }, timeoutMs),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body !== undefined ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body !== undefined ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "DELETE", body: body !== undefined ? JSON.stringify(body) : undefined }),
  postFile: <T>(path: string, file: File, fields?: Record<string, string>) => {
    const formData = new FormData();
    formData.append("file", file);
    for (const [key, value] of Object.entries(fields ?? {})) formData.append(key, value);
    return request<T>(path, { method: "POST", body: formData });
  },
  postForBlob: async (path: string, body?: unknown): Promise<Blob> => {
    const headers: Record<string, string> = { "Content-Type": "application/json", "X-Client-Date": localToday() };
    if (authToken) headers["Authorization"] = `Bearer ${authToken}`;
    const response = await fetch(`${BASE_URL}${path}`, {
      method: "POST",
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (!response.ok) throw new ApiError(response.status, response.statusText);
    return response.blob();
  },
  getForBlob: async (path: string): Promise<Blob> => {
    const headers: Record<string, string> = { "X-Client-Date": localToday() };
    if (authToken) headers["Authorization"] = `Bearer ${authToken}`;
    const response = await fetch(`${BASE_URL}${path}`, { headers });
    if (!response.ok) throw new ApiError(response.status, response.statusText);
    return response.blob();
  },
};

export function wsBaseUrl(): string {
  return BASE_URL.replace(/^http/, "ws");
}

/** Builds a viewable/downloadable URL for a stored file, e.g. for <img src>,
 * which cannot send an Authorization header, so a credential travels as a
 * query param instead (backend/app/deps.py::get_current_user_header_or_query).
 * That credential is the short-lived media token (`ensureMediaToken`), never the
 * session token: a URL is written to server logs and browser history. */
export function fileUrl(fileId: string): string {
  return `${BASE_URL}/api/v1/files/${fileId}?token=${encodeURIComponent(mediaToken ?? "")}`;
}

export function getAuthToken(): string | null {
  return authToken;
}

/** Builds an absolute backend URL for endpoints the browser must navigate to
 * directly (full-page redirects) rather than call via fetch, e.g. the OIDC
 * login entry point (E-U-01), which itself issues a 302 to the identity
 * provider. */
export function apiUrl(path: string): string {
  return `${BASE_URL}${path}`;
}
