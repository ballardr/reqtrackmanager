/**
 * Module: components/ApprovalSeparationSection
 *
 * The Approval section of the project Lifecycles group: for each record type with an approval step, whether the person
 * who created a record may approve it.
 *
 * Responsibilities:
 * - Read the project's rules and save one type's choice at a time (`ApprovalSeparationApi`); `api` is injectable for
 *   stories.
 * - Offer three choices per type (default, submitter may approve with a comment, separate approver required), shown
 *   locked with the reason when the organisation requires a separate approver and the project is not exempt.
 * - For a type whose self-approval only an organisation administrator may give, name the administrator in the choices and
 *   help, so they never read as letting any submitter approve.
 *
 * Design decisions: the default choice stores nothing, so a nested project follows its parent project until it sets its
 * own; a locked type still names the organisation as the reason rather than failing on save.
 */
import { useCallback, useState } from "react";

import { approvalSeparationApi, type ApprovalSeparationApi, type ProjectSeparation, type ProjectSeparations } from "../api/approvalSeparation";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { Badge } from "./Badge";
import { LabeledSelect } from "./LabeledSelect";
import { Spinner } from "./Spinner";

type Choice = "inherit" | "creator" | "separate";

/** The choice a type's own setting stands for. */
function choiceOf(type: ProjectSeparation): Choice {
  if (type.own === null) return "inherit";
  return type.own ? "separate" : "creator";
}

/**
 * @param projectId The project whose rules are configured.
 * @param api The calls (the live ones by default).
 */
export function ApprovalSeparationSection({ projectId, api = approvalSeparationApi }: { projectId: string; api?: ApprovalSeparationApi }) {
  const strings = useStrings();
  const text = strings.approvalSeparation;
  const { showToast } = useToast();
  const [data, setData] = useState<ProjectSeparations | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await api.project(projectId));
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [api, projectId]);
  useLoadOnChange(load, [api, projectId]);

  async function save(artefactType: string, choice: Choice) {
    try {
      setData(await api.setProject(projectId, artefactType, choice === "inherit" ? null : choice === "separate"));
      showToast(text.saved);
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  if (failed && !data) return <p className="text-muted" role="alert">{text.loadFailed}</p>;
  if (!data) return <Spinner />;
  const optionsFor = (type: ProjectSeparation) => [
    {
      value: "inherit",
      label: data.has_parent ? text.followParent : type.self_approval_org_admins_only ? text.byDefaultOrgAdmin : text.byDefault,
    },
    { value: "creator", label: type.self_approval_org_admins_only ? text.orgAdminWithComment : text.creatorWithComment },
    { value: "separate", label: text.separate },
  ];

  return (
    <section className="stack" aria-label={text.heading}>
      <h3 style={{ margin: 0 }}>{text.heading}</h3>
      {data.types.length === 0 && <p className="text-muted">{text.noTypes}</p>}
      {data.types.map((type) => {
        const locked = type.required;
        return (
          <div key={type.artefact_type} className="row" style={{ alignItems: "flex-end" }}>
            <LabeledSelect
              label={text.fieldLabel(type.label)}
              help={type.self_approval_org_admins_only ? strings.help.approvalSeparationProjectOrgAdmins : strings.help.approvalSeparationProject}
              placeholder={null} autoWidth value={locked ? "separate" : choiceOf(type)} options={optionsFor(type)}
              disabled={!data.can_manage || locked} onChange={(value) => void save(type.artefact_type, value as Choice)}
            />
            {locked && <Badge>{text.requiredByOrganisation}</Badge>}
            {type.exempt && <Badge tone="info">{text.exempt}</Badge>}
            {!locked && type.source === "parent_project" && type.own === null && <Badge>{text.inheritedParent}</Badge>}
          </div>
        );
      })}
    </section>
  );
}
