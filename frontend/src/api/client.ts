/**
 * Thin REST client wrapping fetch(): attaches the bearer token, resolves
 * the API base URL from the environment (I-A-01: loosely coupled to the
 * backend), and normalises error handling.
 */

const BASE_URL =
  window.__ENV__?.VITE_API_BASE_URL ??
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
  "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let authToken: string | null = null;

export function setAuthToken(token: string | null): void {
  authToken = token;
  if (token) {
    localStorage.setItem("reqtrack_token", token);
  } else {
    localStorage.removeItem("reqtrack_token");
  }
}

export function loadStoredToken(): string | null {
  authToken = localStorage.getItem("reqtrack_token");
  return authToken;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(options.headers as Record<string, string>) };
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  if (authToken) {
    headers["Authorization"] = `Bearer ${authToken}`;
  }

  const response = await fetch(`${BASE_URL}${path}`, { ...options, headers });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = await response.json();
      message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      // response had no JSON body; fall back to statusText
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return (await response.json()) as T;
  }
  return (await response.blob()) as unknown as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body !== undefined ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body !== undefined ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  postFile: <T>(path: string, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return request<T>(path, { method: "POST", body: formData });
  },
  postForBlob: async (path: string, body?: unknown): Promise<Blob> => {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (authToken) headers["Authorization"] = `Bearer ${authToken}`;
    const response = await fetch(`${BASE_URL}${path}`, {
      method: "POST",
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (!response.ok) throw new ApiError(response.status, response.statusText);
    return response.blob();
  },
};

export function wsBaseUrl(): string {
  return BASE_URL.replace(/^http/, "ws");
}

/** Builds a viewable/downloadable URL for a stored file, e.g. for <img src>,
 * which cannot send an Authorization header, so the token travels as a
 * query param instead (backend/app/deps.py::get_current_user_header_or_query). */
export function fileUrl(fileId: string): string {
  return `${BASE_URL}/api/v1/files/${fileId}?token=${encodeURIComponent(authToken ?? "")}`;
}

export function getAuthToken(): string | null {
  return authToken;
}
