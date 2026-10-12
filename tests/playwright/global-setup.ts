import { request } from "@playwright/test";

/**
 * Pre-flight check: asks the backend to probe its file storage (write, read back, delete) and aborts
 * the run with the cause when it is not writable. A full storage volume otherwise shows up as
 * unrelated upload specs failing (the branding logo upload, attachments, avatars), which is slow to
 * trace back; the Docker VM disk filling up with build cache is the usual reason
 * (`docker builder prune -af` frees it).
 *
 * Only a definite "not healthy" answer aborts. If the backend or login is unreachable the specs
 * report that themselves, so this stays quiet rather than hiding the real error.
 */
export default async function globalSetup(): Promise<void> {
  const api = await request.newContext({ baseURL: "http://localhost:8000" });
  try {
    const login = await api.post("/api/v1/auth/login", { data: { email: "admin@example.com", password: "ChangeMe123!" } });
    if (!login.ok()) return;
    const token = (await login.json()).access_token;
    const health = await api.get("/api/v1/system/storage-health", { headers: { Authorization: `Bearer ${token}` } });
    if (!health.ok()) return;
    const body = await health.json();
    if (body.healthy === false) {
      throw new Error(
        `File storage (${body.backend}) is not accepting writes: ${body.error}. Upload specs will fail. ` +
          "A full Docker disk is the usual cause; free it with `docker builder prune -af`.",
      );
    }
  } catch (err) {
    if (err instanceof Error && err.message.startsWith("File storage")) throw err;
  } finally {
    await api.dispose();
  }
}
