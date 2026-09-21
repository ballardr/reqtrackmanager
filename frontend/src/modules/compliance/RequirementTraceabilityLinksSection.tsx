/**
 * Module: modules/compliance/RequirementTraceabilityLinksSection
 *
 * The Compliance module's contribution to `pages/RequirementDetailPage
 * .tsx`'s own "Links" card (compliance-module-plan.md Phase 34), via the
 * `requirementDetailSections` extension point (`modules/types.ts`) — lists
 * this core requirement's own links to compliance standard requirements,
 * with remove/`ConfirmDialog` behaviour.
 *
 * Platform-review-2026-09 Phase 7 split this component in two: this half
 * keeps the list/remove responsibility; the "add a link" picker (three
 * cascading selects, standard -> version -> requirement) moved into
 * `ComplianceRequirementLinkPickerTab.tsx`, registered as a
 * `requirementLinkPickerTabs` contribution to the shared
 * `RequirementLinkPickerModal` instead of owning its own button+`Popover`
 * here. Because that picker is now a different component instance, this
 * list has no direct way to learn a new link was just added from it — it
 * re-fetches on `refreshToken` changing instead (a generic plumbing signal
 * `RequirementDetailPage.tsx` bumps whenever any link involving this
 * requirement changes, core-to-core or module-contributed).
 *
 * Its own accent colour (the left-border stripe below) comes from this
 * module's own `module.ts` registration (`entityAccentColor`) via
 * `useEntityAccentColor("compliance")`, not a core `ENTITY_ACCENT_COLOR`
 * map entry — see `modules/entityAccentColor.ts`'s own docstring for why a
 * `"compliance"` entry briefly lived in that core map and was corrected
 * back out.
 */
import { useEffect, useState } from "react";
import { Trash2 } from "lucide-react";

import { ConfirmDialog } from "../../components/ConfirmDialog";
import { useStrings } from "../../context/TerminologyContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useEntityAccentColor } from "../entityAccentColor";
import * as complianceApi from "./api";
import type { ComplianceRequirementTraceabilityLink } from "./types";

interface Props {
  projectId: string;
  requirementId: string;
  organizationId: string;
  refreshToken: number;
}

export function RequirementTraceabilityLinksSection({ projectId, requirementId, refreshToken }: Props) {
  const strings = useStrings();
  const { showToast } = useToast();
  const accentColor = useEntityAccentColor("compliance");
  const [links, setLinks] = useState<ComplianceRequirementTraceabilityLink[]>([]);
  const [linkToRemove, setLinkToRemove] = useState<ComplianceRequirementTraceabilityLink | null>(null);

  async function reload() {
    try {
      setLinks(await complianceApi.listRequirementTraceabilityLinks(projectId, requirementId));
    } catch (err) {
      showToast(toErrorMessage(err, "Could not load compliance requirement links."), "error");
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, requirementId, refreshToken]);

  async function removeLink(linkId: string) {
    await complianceApi.deleteRequirementTraceabilityLink(projectId, requirementId, linkId);
    await reload();
  }

  return (
    <div className="stack" style={{ borderTop: "1px solid var(--color-border)", paddingTop: "0.75rem", marginTop: "0.25rem" }}>
      <h3 style={{ margin: 0, fontSize: "0.95rem" }}>{strings.compliance.requirementLinksTitle}</h3>
      {links.length === 0 && <p className="text-muted" style={{ margin: 0 }}>{strings.compliance.noRequirementLinksYet}</p>}
      {links.map((link) => (
        <div
          key={link.id}
          className="row entity-accent-card"
          style={{
            justifyContent: "space-between",
            paddingLeft: "0.5rem",
            ["--entity-accent-color" as string]: accentColor,
          }}
        >
          <span>
            <span className="badge">{link.display_name}</span>{" "}
            {link.standard_reference} — {link.compliance_requirement_reference ? `${link.compliance_requirement_reference} ` : ""}
            {link.compliance_requirement_name}
            <span className="text-muted"> ({link.standard_name}, v{link.standard_version_label})</span>
          </span>
          <button
            className="btn btn-danger"
            title={strings.compliance.removeLink}
            aria-label={strings.compliance.removeLink}
            onClick={() => setLinkToRemove(link)}
          >
            <Trash2 size={14} />
          </button>
        </div>
      ))}
      {linkToRemove && (
        <ConfirmDialog
          title={strings.compliance.removeLinkTitle}
          message={strings.compliance.removeLinkConfirm}
          confirmLabel={strings.compliance.removeLink}
          onConfirm={async () => {
            const id = linkToRemove.id;
            setLinkToRemove(null);
            await removeLink(id);
          }}
          onCancel={() => setLinkToRemove(null)}
        />
      )}
    </div>
  );
}
