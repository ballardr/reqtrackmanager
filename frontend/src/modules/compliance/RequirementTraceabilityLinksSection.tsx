/**
 * Module: modules/compliance/RequirementTraceabilityLinksSection
 *
 * The Compliance module's contribution to `pages/RequirementDetailPage.tsx`'s
 * aside (below the shared Links panel), via the `requirementDetailSections`
 * extension point (`modules/types.ts`): this core requirement's links to compliance
 * standard requirements, with an "Add" dialog and remove behind `ConfirmDialog`.
 *
 * It stays a module-owned section rather than moving into the shared panel because
 * these links are a different kind of record: a row in
 * `ComplianceRequirementTraceabilityLink` pointing at an organisation-level standard
 * requirement (picked standard -> version -> requirement, there is no search
 * endpoint over them), not an `ArtefactLink` between two project records.
 *
 * Its own accent colour (the left-border stripe below) comes from this
 * module's own `module.ts` registration (`entityAccentColor`) via
 * `useEntityAccentColor("compliance")`, not a core `ENTITY_ACCENT_COLOR`
 * map entry — see `modules/entityAccentColor.ts`'s own docstring.
 */
import { useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";

import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Modal } from "../../components/Modal";
import { useStrings } from "../../context/TerminologyContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useEntityAccentColor } from "../entityAccentColor";
import * as complianceApi from "./api";
import { ComplianceRequirementLinkPickerTab } from "./ComplianceRequirementLinkPickerTab";
import type { ComplianceRequirementTraceabilityLink } from "./types";

interface Props {
  projectId: string;
  requirementId: string;
  organizationId: string;
  refreshToken: number;
}

export function RequirementTraceabilityLinksSection({ projectId, requirementId, organizationId, refreshToken }: Props) {
  const strings = useStrings();
  const { showToast } = useToast();
  const accentColor = useEntityAccentColor("compliance");
  const [links, setLinks] = useState<ComplianceRequirementTraceabilityLink[]>([]);
  const [linkToRemove, setLinkToRemove] = useState<ComplianceRequirementTraceabilityLink | null>(null);
  const [adding, setAdding] = useState(false);

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
    <section className="card stack" aria-label={strings.compliance.requirementLinksTitle}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.compliance.requirementLinksTitle}</h2>
        <button className="btn" onClick={() => setAdding(true)}>
          <Plus size={14} /> {strings.requirements.addLink}
        </button>
      </div>
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
      {adding && (
        <Modal title={strings.compliance.requirementLinksTitle} onClose={() => setAdding(false)}>
          <ComplianceRequirementLinkPickerTab
            projectId={projectId}
            requirementId={requirementId}
            organizationId={organizationId}
            onLinked={() => {
              setAdding(false);
              void reload();
            }}
          />
        </Modal>
      )}
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
    </section>
  );
}
