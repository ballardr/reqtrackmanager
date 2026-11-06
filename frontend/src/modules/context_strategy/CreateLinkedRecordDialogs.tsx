/**
 * Module: modules/context_strategy/CreateLinkedRecordDialogs
 *
 * The "Create new" dialogs the Links panel shows for this module's records other than a Pain Point (registered as
 * `TierAModuleDefinition.linkedRecordCreators`): a Strategy, Future State, Guiding Principle and Open Question. Each is
 * the type's own form modal, the one its list page uses, so every field the edit form has is present, together with
 * quick links and tags; `useLinkedRecordSave` creates the record and reports its id.
 */
import { useLinkedRecordSave } from "../../hooks/useLinkedRecordSave";
import type { LinkedRecordCreatorProps } from "../types";
import { projectFutureStateApi, projectGuidingPrincipleApi, projectOpenQuestionApi, projectStrategyApi } from "./api";
import { FutureStateFormModal } from "./FutureStateFormModal";
import { GuidingPrincipleFormModal } from "./GuidingPrincipleFormModal";
import { OpenQuestionFormModal } from "./OpenQuestionFormModal";
import { StrategyFormModal } from "./StrategyFormModal";

/** A new Strategy. */
export function CreateStrategyDialog({ projectId, onCreated, onCancel }: LinkedRecordCreatorProps) {
  const { error, save } = useLinkedRecordSave(projectId, "strategy", "Strategy", onCreated);
  return (
    <StrategyFormModal
      scopeLabel="project" projectId={projectId} error={error} onCancel={onCancel}
      onSave={(values, quickLinks, tags) => save(() => projectStrategyApi.create(projectId, values), quickLinks, tags)}
    />
  );
}

/** A new Future State. */
export function CreateFutureStateDialog({ projectId, onCreated, onCancel }: LinkedRecordCreatorProps) {
  const { error, save } = useLinkedRecordSave(projectId, "future_state", "Future State", onCreated);
  return (
    <FutureStateFormModal
      scopeLabel="project" projectId={projectId} error={error} onCancel={onCancel}
      onSave={(values, quickLinks, tags) => save(() => projectFutureStateApi.create(projectId, values), quickLinks, tags)}
    />
  );
}

/** A new Guiding Principle. */
export function CreateGuidingPrincipleDialog({ projectId, onCreated, onCancel }: LinkedRecordCreatorProps) {
  const { error, save } = useLinkedRecordSave(projectId, "guiding_principle", "Guiding Principle", onCreated);
  return (
    <GuidingPrincipleFormModal
      scopeLabel="project" projectId={projectId} error={error} onCancel={onCancel}
      onSave={(values, quickLinks, tags) => save(() => projectGuidingPrincipleApi.create(projectId, values), quickLinks, tags)}
    />
  );
}

/** A new Open Question. */
export function CreateOpenQuestionDialog({ projectId, onCreated, onCancel }: LinkedRecordCreatorProps) {
  const { error, save } = useLinkedRecordSave(projectId, "open_question", "Open Question", onCreated);
  return (
    <OpenQuestionFormModal
      projectId={projectId} error={error} onCancel={onCancel}
      onSave={(values, quickLinks, tags) => save(() => projectOpenQuestionApi.create(projectId, values), quickLinks, tags)}
    />
  );
}
