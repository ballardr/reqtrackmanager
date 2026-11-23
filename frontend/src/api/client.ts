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
  /** Set when this refusal ended the session: the person is being returned to sign-in, so nothing more is shown for it. */
  sessionEnded = false;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

let authToken: string | null = null;
/** The token whose refusal has already been reported, so requests refused together end the session once even before the listener clears it. */
let endedSessionToken: string | null = null;

export function setAuthToken(token: string | null): void {
  authToken = token;
  endedSessionToken = null;
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
  const sessionToken = authToken;
  try {
    const result = await request<{ token: string }>("/api/v1/auth/media-token", { method: "POST" });
    // A session that ended (or was replaced) while this was in flight is not given the old session's credential.
    if (authToken !== sessionToken) return;
    mediaToken = result.token;
  } catch {
    if (authToken !== sessionToken) return;
    mediaToken = null;
  }
  if (authToken) mediaRefreshTimer = setTimeout(() => void ensureMediaToken(), MEDIA_TOKEN_REFRESH_MS);
}

export function loadStoredToken(): string | null {
  authToken = localStorage.getItem("reqtrack_token");
  return authToken;
}

/**
 * Fired once when a request is refused because the session token is dead (expired, revoked or superseded by a
 * password change). `AuthContext` listens for this and clears the session at once, so the router returns the person
 * to the sign-in page instead of leaving stale UI up until a reload re-runs the mount-time `/auth/me` check.
 */
export const AUTH_UNAUTHORIZED_EVENT = "reqtrack:unauthorized";

/** The `code` of the body of a dead-token 401 (`app.deps.INVALID_TOKEN_CODE`). */
export const INVALID_TOKEN_CODE = "invalid_token";

/**
 * The ceiling an ordinary read (a GET, or a POST that only reads and is passed `READ_TIMEOUT_MS`) is given when the
 * caller names none: a response that never arrives would otherwise be a spinner that never ends. Generous on purpose
 * (a large list on a slow deployment); uploads, downloads, exports and report runs name their own limit or none.
 */
export const READ_TIMEOUT_MS = 120_000;

/** Message of the error raised when a request outlives its ceiling. */
export const REQUEST_TIMEOUT_MESSAGE = "The server is taking longer than expected to respond. Please try again.";

/** Message of the error raised when no response arrives at all (offline, refused, a proxy that is down). */
export const NETWORK_FAILURE_MESSAGE = "The server could not be reached. Check the connection and try again.";

/**
 * Whether a refused request means the session itself is over. The backend answers a missing, invalid, expired,
 * revoked or superseded token with `401` and `WWW-Authenticate: Bearer`, and puts `code: invalid_token` in the body;
 * either alone is enough, because a browser on another origin cannot read a header the server did not expose and a
 * proxy may remove one. An ordinary 401 (a wrong current password, a bad two-factor code) carries neither and never
 * ends a session.
 */
export function isDeadSessionResponse(status: number, wwwAuthenticate: string | null, body: unknown): boolean {
  if (status !== 401) return false;
  if (wwwAuthenticate) return true;
  return typeof body === "object" && body !== null && (body as { code?: unknown }).code === INVALID_TOKEN_CODE;
}

/** Whether a request with these options is an ordinary read that gets the default ceiling. */
function isPlainRead(options: RequestInit): boolean {
  return (options.method ?? "GET").toUpperCase() === "GET";
}

/**
 * `timeoutMs` opts a call into an explicit ceiling (login uses this, see AuthContext.tsx, since a bcrypt verify under
 * concurrent login load can legitimately take longer than this app's other, cheap requests; see docs/decisions.md,
 * "bcrypt login cost under concurrent load"). Left out, a plain GET gets `READ_TIMEOUT_MS` and everything else waits
 * (an upload or an export may legitimately take minutes); `null` means no ceiling for a GET too (a file download).
 */
async function rawRequest(path: string, options: RequestInit = {}, timeoutMs?: number | null): Promise<Response> {
  const headers: Record<string, string> = { ...(options.headers as Record<string, string>), "X-Client-Date": localToday() };
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  // The token this request is sent with: a refusal of it ends the session only while it is still the session's token,
  // so a late answer to a request of a session that already ended never signs out the one that replaced it.
  const sentToken = authToken;
  if (sentToken) {
    headers["Authorization"] = `Bearer ${sentToken}`;
  }

  const ceiling = timeoutMs === undefined ? (isPlainRead(options) ? READ_TIMEOUT_MS : undefined) : (timeoutMs ?? undefined);
  const controller = ceiling !== undefined ? new AbortController() : undefined;
  const timer = controller ? setTimeout(() => controller.abort(), ceiling) : undefined;
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, { ...options, headers, signal: controller?.signal ?? options.signal });
  } catch (err) {
    if (controller?.signal.aborted) throw new ApiError(0, REQUEST_TIMEOUT_MESSAGE);
    // A caller's own cancellation (a superseded search) is its own business and keeps its AbortError.
    if (err instanceof TypeError) throw new ApiError(0, NETWORK_FAILURE_MESSAGE);
    throw err;
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
  if (!response.ok) {
    let message = response.statusText;
    let detail: unknown;
    let body: unknown;
    try {
      body = await response.json();
      const parsed = body as { detail?: unknown };
      message = typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail ?? body);
      if (parsed.detail && typeof parsed.detail === "object" && !Array.isArray(parsed.detail)) {
        detail = parsed.detail;
        if (typeof (parsed.detail as { message?: unknown }).message === "string") message = (parsed.detail as { message: string }).message;
      }
    } catch {
      // response had no JSON body; fall back to statusText
    }
    // Checked after the body is read and against the live token: when several requests are refused together the first
    // ends the session (and clears the token), so the rest see a token that is no longer current and do nothing.
    const error = new ApiError(response.status, message, detail);
    if (isDeadSessionResponse(response.status, response.headers.get("www-authenticate"), body) && sentToken !== null) {
      // A refusal of an earlier session's token (sent before the current sign-in) is not this session's to end.
      error.sessionEnded = true;
      if (sentToken === authToken && sentToken !== endedSessionToken) {
        endedSessionToken = sentToken;
        window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
      }
    }
    throw error;
  }
  return response;
}

async function request<T>(path: string, options: RequestInit = {}, timeoutMs?: number | null): Promise<T> {
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
  /** Set when the server says the list was cut short (`X-Projects-Truncated`, the organisation Files list). */
  truncated?: boolean;
  /** Set by the project list: whether the caller administers an organisation, so the filter that adds projects they
   * are not a member of applies to them (`X-Can-Include-Unjoined`). */
  canIncludeUnjoined?: boolean;
}

async function requestPage<T>(path: string, options: RequestInit = {}, timeoutMs?: number): Promise<Page<T>> {
  const response = await rawRequest(path, options, timeoutMs);
  const items = (await response.json()) as T[];
  const totalHeader = response.headers.get("x-total-count");
  const totalUnfilteredHeader = response.headers.get("x-total-unfiltered-count");
  return {
    items,
    total: totalHeader ? Number(totalHeader) : items.length,
    totalUnfiltered: totalUnfilteredHeader ? Number(totalUnfilteredHeader) : undefined,
    truncated: response.headers.get("x-projects-truncated") === "true" ? true : undefined,
    canIncludeUnjoined: response.headers.has("x-can-include-unjoined")
      ? response.headers.get("x-can-include-unjoined") === "true"
      : undefined,
  };
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  getPage: <T>(path: string) => requestPage<T>(path),
  /** A paginated read whose filters travel in a POST body, so text a person typed is in no URL a server logs. */
  postPage: <T>(path: string, body: unknown) => requestPage<T>(path, { method: "POST", body: JSON.stringify(body) }, READ_TIMEOUT_MS),
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
  /** Posts JSON and returns the file in the response; a failed response throws the same `ApiError` (with its structured `detail`) as any other call. */
  postForBlob: async (path: string, body?: unknown): Promise<Blob> =>
    (await rawRequest(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined })).blob(),
  /**
   * Posts JSON and returns the file as a `File` named as the server named it (its `Content-Disposition`), so a download
   * keeps the name the server's rules produced; a response with no name yields a plain `Blob`.
   */
  postForFile: async (path: string, body?: unknown): Promise<Blob> => {
    const response = await rawRequest(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined });
    const blob = await response.blob();
    const name = dispositionFileName(response.headers.get("Content-Disposition"));
    return name ? new File([blob], name, { type: blob.type }) : blob;
  },
  /** Downloads a file (no ceiling: a large file may take minutes); a failed response throws the same `ApiError` (message and structured `detail`) as any other call. */
  getForBlob: async (path: string): Promise<Blob> => (await rawRequest(path, {}, null)).blob(),
};

/**
 * The file name the server chose in a `Content-Disposition` header (the RFC 5987 `filename*` form when present, else the
 * quoted `filename`), or `null` when there is none.
 */
export function dispositionFileName(header: string | null): string | null {
  if (!header) return null;
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (encoded) {
    try {
      return decodeURIComponent(encoded[1].trim());
    } catch {
      // A malformed escape: fall through to the plain form.
    }
  }
  return /filename="([^"]*)"/i.exec(header)?.[1] ?? null;
}

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
