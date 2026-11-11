/**
 * Module: hooks/useOrgResources
 *
 * Loads an organisation's shared resources and whether the person may manage them, and uploads or deletes one.
 *
 * Responsibilities:
 * - Read the list (`GET /orgs/{id}/resources`) and the server's answer (`GET /orgs/{id}/resources/access`); the page
 *   shows the upload and delete controls only when the server says `can_manage`, never from a role name.
 * - Upload and delete through the shared mutation helper (toast on success and failure), then reload.
 *
 * Design decisions: nothing is read until `enabled`, so the Files page's first tab costs no request for the second.
 * External dependencies: `api`, `useMutation`, `useLoadOnChange`.
 */
import { useState } from "react";

import { api } from "../api/client";
import type { OrgResource } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { useLoadOnChange } from "./useLoadOnChange";
import { useMutation } from "./useMutation";

/**
 * @param orgId The organisation whose resources to manage.
 * @param enabled False until the resources are needed (the tab is open).
 * @returns `resources` (null until loaded), `failed` (the last read failed), `canManage`, and `upload` / `remove`, which resolve once the list has reloaded.
 */
export function useOrgResources(orgId: string | undefined, enabled: boolean) {
  const strings = useStrings();
  const run = useMutation();
  const [resources, setResources] = useState<OrgResource[] | null>(null);
  const [canManage, setCanManage] = useState(false);
  const [failed, setFailed] = useState(false);

  async function load() {
    if (!orgId || !enabled) return;
    try {
      const [rows, access] = await Promise.all([
        api.get<OrgResource[]>(`/api/v1/orgs/${orgId}/resources`),
        api.get<{ can_manage: boolean }>(`/api/v1/orgs/${orgId}/resources/access`),
      ]);
      setResources(rows);
      setCanManage(access.can_manage);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }
  useLoadOnChange(load, [orgId, enabled]);

  async function upload(file: File) {
    if (await run(() => api.postFile(`/api/v1/orgs/${orgId}/resources`, file), "upload", strings.files.resources.noun)) await load();
  }

  async function remove(fileId: string) {
    if (await run(() => api.delete(`/api/v1/orgs/${orgId}/resources/${fileId}`), "delete", strings.files.resources.noun)) await load();
  }

  return { resources, failed, canManage, upload, remove };
}
