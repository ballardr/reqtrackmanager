/**
 * Module: modules/stakeholders/CreateLinkedRecordDialogs
 *
 * The "Create new" dialogs the Links panel shows for this module's records (registered as
 * `TierAModuleDefinition.linkedRecordCreators`): a Persona, Stakeholder, Stakeholder Group, Stakeholder Need,
 * Engagement and research Finding. Each is the type's own form modal, the one its list or page uses, so every field the
 * edit form has is present, together with quick links and tags; `useLinkedRecordSave` creates the record and reports
 * its id. A Finding belongs to an engagement, which the person chooses (the page record when that is an engagement).
 */
import { useEffect, useState } from "react";

import { useLinkedRecordSave } from "../../hooks/useLinkedRecordSave";
import type { LinkedRecordCreatorProps } from "../types";
import {
  projectEngagementApi, projectNeedApi, projectPersonaApi, projectResearchApi, projectStakeholderApi, projectStakeholderGroupApi,
} from "./api";
import { createStakeholderWithGroups } from "./createStakeholder";
import { EngagementFormModal } from "./EngagementFormModal";
import { FindingFormModal } from "./FindingFormModal";
import { NeedFormModal } from "./NeedFormModal";
import { PersonaFormModal } from "./PersonaFormModal";
import { StakeholderFormModal } from "./StakeholderFormModal";
import { StakeholderGroupFormModal } from "./StakeholderGroupFormModal";
import type { EffectivePersonaType, StakeholderGroup } from "./types";
import { useStakeholderScheme } from "./useStakeholderScheme";

/** The enabled types of a vocabulary, as select options. */
const typeOptions = (types: EffectivePersonaType[]) => types.filter((t) => t.is_enabled).map((t) => ({ value: t.id, label: t.name }));

/** Loads a list once for the dialog; `null` until it resolves, `[]` when it cannot be read. */
function useLoaded<T>(load: () => Promise<T[]>, key: string): T[] | null {
  const [rows, setRows] = useState<T[] | null>(null);
  useEffect(() => {
    let live = true;
    load().then((result) => { if (live) setRows(result); }).catch(() => { if (live) setRows([]); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` identifies the load; `load` is a new closure each render.
  }, [key]);
  return rows;
}

/** A new Persona. */
export function CreatePersonaDialog({ projectId, onCreated, onCancel }: LinkedRecordCreatorProps) {
  const { error, save } = useLinkedRecordSave(projectId, "persona", "Persona", onCreated);
  const types = useLoaded(() => projectPersonaApi.listTypes(projectId), projectId);
  if (types === null) return null;
  return (
    <PersonaFormModal
      scopeLabel="project" projectId={projectId} typeOptions={typeOptions(types)} error={error} onCancel={onCancel}
      onSave={(values, quickLinks, tags) => save(() => projectPersonaApi.create(projectId, values), quickLinks, tags)}
    />
  );
}

/** A new Stakeholder, with the groups chosen on the form. */
export function CreateStakeholderDialog({ projectId, onCreated, onCancel }: LinkedRecordCreatorProps) {
  const { error, save } = useLinkedRecordSave(projectId, "stakeholder", "Stakeholder", onCreated);
  const scheme = useStakeholderScheme({ projectId });
  const types = useLoaded(() => projectStakeholderApi.listTypes(projectId), projectId);
  const groups = useLoaded(() => projectStakeholderGroupApi.list(projectId), projectId);
  if (types === null || groups === null) return null;
  // Group pickers offer this project's own groups, not those of related projects.
  const ownGroups = groups.filter((g: StakeholderGroup) => !g.from_project_id);
  return (
    <StakeholderFormModal
      scopeLabel="project" projectId={projectId} typeOptions={typeOptions(types)} scheme={scheme} groups={ownGroups} groupTier="project"
      loadHint={(influence, interest) => projectStakeholderApi.cadenceHint(projectId, influence, interest)}
      error={error} onCancel={onCancel}
      onSave={({ group_ids: groupIds = [], ...values }, quickLinks, tags) =>
        save(async () => {
          let id = "";
          const warning = await createStakeholderWithGroups(
            async (v) => { const created = await projectStakeholderApi.create(projectId, v); id = created.id; return created; },
            (stakeholderId, ids) => projectStakeholderGroupApi.setStakeholderGroups(projectId, stakeholderId, ids),
            values, groupIds,
          );
          return { id, warning };
        }, quickLinks, tags)}
    />
  );
}

/** A new Stakeholder Group. */
export function CreateStakeholderGroupDialog({ projectId, onCreated, onCancel }: LinkedRecordCreatorProps) {
  const { error, save } = useLinkedRecordSave(projectId, "stakeholder_group", "Stakeholder Group", onCreated);
  const groups = useLoaded(() => projectStakeholderGroupApi.list(projectId), projectId);
  if (groups === null) return null;
  return (
    <StakeholderGroupFormModal
      groups={groups.filter((g) => !g.from_project_id)} projectId={projectId} error={error} onCancel={onCancel}
      onSave={(values, quickLinks, tags) => save(() => projectStakeholderGroupApi.create(projectId, values), quickLinks, tags)}
    />
  );
}

/** A new Stakeholder Need. */
export function CreateNeedDialog({ projectId, onCreated, onCancel }: LinkedRecordCreatorProps) {
  const { error, save } = useLinkedRecordSave(projectId, "stakeholder_need", "Stakeholder Need", onCreated);
  return (
    <NeedFormModal
      projectId={projectId} error={error} onCancel={onCancel}
      onSave={(values, quickLinks, tags) => save(() => projectNeedApi.create(projectId, values), quickLinks, tags)}
    />
  );
}

/** A new Engagement. */
export function CreateEngagementDialog({ projectId, onCreated, onCancel }: LinkedRecordCreatorProps) {
  const { error, save } = useLinkedRecordSave(projectId, "engagement", "Engagement", onCreated);
  return (
    <EngagementFormModal
      projectId={projectId} error={error} onCancel={onCancel}
      onSave={(values, quickLinks, tags) => save(() => projectEngagementApi.create(projectId, values), quickLinks, tags)}
    />
  );
}

/** A new research Finding; the engagement is chosen, and is the page record when that is an engagement. */
export function CreateFindingDialog({ projectId, pageRecord, onCreated, onCancel }: LinkedRecordCreatorProps) {
  const { error, save } = useLinkedRecordSave(projectId, "research_finding", "Finding", onCreated);
  const engagements = useLoaded(() => projectEngagementApi.list(projectId), projectId);
  if (engagements === null) return null;
  return (
    <FindingFormModal
      projectId={projectId} error={error} onCancel={onCancel}
      engagementOptions={engagements.map((e) => ({ value: e.id, label: `${e.unique_code} ${e.title}` }))}
      defaultEngagementId={pageRecord.type === "engagement" ? pageRecord.id : ""}
      onSave={(values, extras) => save(() => projectResearchApi.addFinding(projectId, extras.engagementId, values), extras.quickLinks, extras.tags)}
    />
  );
}
