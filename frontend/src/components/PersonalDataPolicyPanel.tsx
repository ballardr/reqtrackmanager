/**
 * Module: components/PersonalDataPolicyPanel
 *
 * The personal-data policy for record export and import, at both tiers it is set:
 * - `server`: the deployment-wide default per sensitivity tag (everything excluded until allowed).
 * - `organization`: the organisation's own decision per tag, shown beside the server default it
 *   overrides, with a way back to following the server.
 *
 * Design decisions:
 * - One component for both scopes, so a tag reads and behaves the same at either tier; rows are the
 *   shared `ModuleSettingsList` (name, description, hint, one control).
 * - Every change saves at once and ends in a toast (style guide, feedback on every mutation). Widening
 *   the policy (a tag becoming allowed) is a Tier 1 confirm; excluding a tag is not, because it can only
 *   reduce what leaves the application.
 * - An organisation row that would equal the server default is saved as "follows the server" rather than
 *   as an override equal to it, so the pill never claims a custom value that changes nothing.
 * - Tag names come from `RECORD_SENSITIVITY_TAG_LABEL`; the backend never sends display text.
 *
 * Dependencies: `GET/PUT /api/v1/system/record-sensitivity-policy` and
 * `GET/PUT /api/v1/orgs/{id}/record-sensitivity-policy`.
 */
import { useEffect, useState } from "react";

import { api } from "../api/client";
import {
  RECORD_SENSITIVITY_TAG_LABEL,
  type OrgRecordSensitivity,
  type RecordSensitivityTag,
  type ServerRecordSensitivity,
} from "../api/types";
import { useOrgLabel } from "../context/BrandingContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { t } from "../i18n/strings";
import { ConfirmDialog } from "./ConfirmDialog";
import { ModuleSettingsList } from "./ModuleSettingsList";
import { OverridePill } from "./OverridePill";
import { Spinner } from "./Spinner";
import { ToggleSwitch } from "./ToggleSwitch";

const strings = t().personalDataPolicy;
const commonStrings = t().common;

/** Which tier the panel edits. */
export type PersonalDataPolicyScope = { kind: "server" } | { kind: "organization"; organizationId: string };

/** One tag as the panel shows it, whichever tier it came from. */
interface PolicyRow {
  tag: RecordSensitivityTag;
  serverAllowed: boolean;
  /** `null` while following the server (always `null` at the server tier). */
  override: boolean | null;
  effective: boolean;
}

function fromServer(row: ServerRecordSensitivity): PolicyRow {
  return { tag: row.tag, serverAllowed: row.allowed, override: null, effective: row.allowed };
}

function fromOrg(row: OrgRecordSensitivity): PolicyRow {
  return { tag: row.tag, serverAllowed: row.server_allowed, override: row.override, effective: row.effective };
}

/**
 * Renders the policy for one tier.
 *
 * @param scope `{ kind: "server" }` for the deployment default, or the organisation to edit.
 */
export function PersonalDataPolicyPanel({ scope }: { scope: PersonalDataPolicyScope }) {
  const { showToast } = useToast();
  const orgLabel = useOrgLabel();
  const isServer = scope.kind === "server";
  const base = isServer
    ? "/api/v1/system/record-sensitivity-policy"
    : `/api/v1/orgs/${scope.organizationId}/record-sensitivity-policy`;
  const [rows, setRows] = useState<PolicyRow[] | null>(null);
  const [pending, setPending] = useState<{ row: PolicyRow; next: boolean } | null>(null);

  useEffect(() => {
    let current = true;
    const load = isServer
      ? api.get<ServerRecordSensitivity[]>(base).then((items) => items.map(fromServer))
      : api.get<OrgRecordSensitivity[]>(base).then((items) => items.map(fromOrg));
    load
      .then((items) => current && setRows(items))
      .catch((err) => showToast(toErrorMessage(err, strings.loadError), "error"));
    return () => {
      current = false;
    };
  }, [base, isServer, showToast]);

  function replace(updated: PolicyRow) {
    setRows((prev) => prev && prev.map((row) => (row.tag === updated.tag ? updated : row)));
  }

  /** Saves the wanted effective value; at the organisation tier a value equal to the server's clears the override. */
  async function save(row: PolicyRow, next: boolean) {
    setPending(null);
    try {
      if (isServer) {
        replace(fromServer(await api.put<ServerRecordSensitivity>(`${base}/${row.tag}`, { allowed: next })));
      } else {
        const override = next === row.serverAllowed ? null : next;
        replace(fromOrg(await api.put<OrgRecordSensitivity>(`${base}/${row.tag}`, { allowed: override })));
      }
      showToast(strings.saved(RECORD_SENSITIVITY_TAG_LABEL[row.tag], next));
    } catch (err) {
      showToast(toErrorMessage(err, commonStrings.error), "error");
    }
  }

  /** Widening the policy asks first (this includes following a server default that allows the tag); narrowing saves straight away. */
  function change(row: PolicyRow, next: boolean) {
    if (next && !row.effective) setPending({ row, next });
    else void save(row, next);
  }

  if (rows === null) return <Spinner />;
  return (
    <div className="stack">
      <p className="text-muted" style={{ margin: 0 }}>
        {isServer ? strings.serverHint : strings.orgHint(orgLabel)}
      </p>
      <ModuleSettingsList
        items={rows.map((row) => {
          const label = RECORD_SENSITIVITY_TAG_LABEL[row.tag];
          return {
            key: row.tag,
            name: label,
            description: strings.tagDescription[row.tag],
            hint: isServer ? strings.serverStateHint(row.effective) : strings.orgStateHint(row.serverAllowed, row.effective),
            control: (
              <span className="row" style={{ gap: "var(--space-3)", display: "inline-flex", alignItems: "center" }}>
                {!isServer && (
                  <OverridePill
                    custom={row.override !== null}
                    defaultLabel={strings.followsServer}
                    resetLabel={strings.resetToServer}
                    onReset={() => change(row, row.serverAllowed)}
                  />
                )}
                <ToggleSwitch checked={row.effective} label={strings.allowedLabel(label.toLowerCase())} onChange={(next) => change(row, next)} />
              </span>
            ),
          };
        })}
      />
      {pending && (
        <ConfirmDialog
          title={strings.widenTitle(RECORD_SENSITIVITY_TAG_LABEL[pending.row.tag])}
          message={strings.widenMessage(RECORD_SENSITIVITY_TAG_LABEL[pending.row.tag])}
          confirmLabel={strings.widenConfirm}
          onConfirm={() => void save(pending.row, pending.next)}
          onCancel={() => setPending(null)}
        />
      )}
    </div>
  );
}
