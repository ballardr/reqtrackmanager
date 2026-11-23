/**
 * Module: components/RequirementCreateModal
 *
 * The "New requirement" dialog, shared by the Requirements page and the Links panel's "Create new"
 * (`CreateRequirementDialog`), so a field added to a requirement reaches both.
 *
 * Responsibilities:
 * - Load what the form needs (the project, its organisation's members, components, categories, target versions and the
 *   requirement custom fields) and show `RequirementFields`, the component and category pickers, custom fields, the
 *   quick-link field and the tag field.
 * - Create the requirement (with any further components, `RequirementAliasField`), then apply its quick links and tags.
 * - A project with no component or category yet: let a project manager create the first ones inline, else point to the
 *   project's settings.
 * - Optionally (`offerAttach`) a second step to attach files to the new requirement, which the create endpoints need an
 *   id for; the plain Create closes the dialog.
 *
 * Design decisions:
 * - Cancel and Create sit in the dialog header (`FormActions`); "Create and attach files" is the extra header control.
 */
import { useCallback, useState } from "react";
import { Link } from "react-router-dom";

import type { CollectedLink } from "../api/artefactLinks";
import { api } from "../api/client";
import type { PlacementPair } from "../api/placements";
import type { Category, Component, CustomFieldDefinition, FileAsset, ProjectStage, Requirement } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage } from "../context/ToastContext";
import { useCommitQuickLinks } from "../hooks/useCommitQuickLinks";
import { useCommitTags } from "../hooks/useCommitTags";
import { useCreatedToast } from "../hooks/useCreatedToast";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useMutation } from "../hooks/useMutation";
import { useProjectPeople } from "../hooks/useProjectPeople";
import { CustomFieldsForm } from "./CustomFieldsForm";
import { FileAttachmentList } from "./FileAttachmentList";
import { FormActions } from "./FormActions";
import { FormGrid, FormGridFull } from "./FormGrid";
import { InlineStructureForm } from "./InlineStructureForm";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";
import { PrimaryPlaceField } from "./PrimaryPlaceField";
import { QuickLinkField } from "./QuickLinkField";
import { RequirementAliasField } from "./RequirementAliasField";
import { RequirementFields } from "./RequirementFields";
import { EMPTY_REQUIREMENT_FIELDS, requirementPeopleAndReviewPayload, type RequirementFieldValues } from "./requirementFieldValues";
import { TagField } from "./TagField";

/**
 * @param projectId The project the requirement is created in.
 * @param canManageProject Whether the person may create the first component and category inline.
 * @param offerAttach Offer "Create and attach files" (a second step against the new id); the Links panel passes false.
 * @param onCreated Called with the new requirement once it exists (and its links and tags are applied), for the caller
 *   to reload or link it; the dialog stays open when a second step follows.
 * @param onClose Called when the dialog should close (dismissed, or finished).
 */
export function RequirementCreateModal({
  projectId, canManageProject, offerAttach, onCreated, onClose,
}: {
  projectId: string;
  canManageProject: boolean;
  offerAttach: boolean;
  onCreated: (requirement: Requirement) => void;
  onClose: () => void;
}) {
  const strings = useStrings();
  const run = useMutation();
  const commitQuickLinks = useCommitQuickLinks(projectId, "requirement");
  const commitTags = useCommitTags(projectId, "requirement");
  const announceCreated = useCreatedToast(projectId, "requirement");
  const { project, orgUsers } = useProjectPeople(projectId);

  const [components, setComponents] = useState<Component[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [stages, setStages] = useState<ProjectStage[]>([]);
  const [customFieldDefs, setCustomFieldDefs] = useState<CustomFieldDefinition[]>([]);
  // Both lists start empty before the first fetch resolves, which looks like "this project has none yet"; the inline
  // component and category form is for a genuinely empty project only, so nothing shows until the fetch completes.
  const [metaLoaded, setMetaLoaded] = useState(false);
  const [fields, setFields] = useState<RequirementFieldValues>(EMPTY_REQUIREMENT_FIELDS);
  const [componentId, setComponentId] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [customFieldValues, setCustomFieldValues] = useState<Record<string, unknown>>({});
  const [quickLinks, setQuickLinks] = useState<CollectedLink[]>([]);
  const [tags, setTags] = useState<string[]>([]);
  const [additionalPlaces, setAdditionalPlaces] = useState<PlacementPair[]>([]);
  const [error, setError] = useState<string | null>(null);
  // Step 2 (offerAttach): the requirement just created and the files attached to it.
  const [created, setCreated] = useState<Requirement | null>(null);
  const [createdFiles, setCreatedFiles] = useState<FileAsset[]>([]);

  const loadMeta = useCallback(async () => {
    const [comps, cats, stgs, defs] = await Promise.all([
      api.get<Component[]>(`/api/v1/projects/${projectId}/components`),
      api.get<Category[]>(`/api/v1/projects/${projectId}/categories`),
      api.get<ProjectStage[]>(`/api/v1/projects/${projectId}/stages`),
      api.get<CustomFieldDefinition[]>(`/api/v1/projects/${projectId}/custom-fields?entity_kind=requirement`),
    ]);
    setComponents(comps);
    setCategories(cats);
    setStages(stgs);
    setCustomFieldDefs(defs);
    // The target version is mandatory (it can never be left unset): the select always has a real one pre-filled, the
    // same default the create endpoint applies.
    setFields((f) => (f.targetStageId || !stgs[0] ? f : { ...f, targetStageId: stgs[0].id }));
    // The first place that can be chosen: the first category of the first component that has one.
    const firstCategory = cats.find((c) => c.component_id === comps.find((k) => cats.some((x) => x.component_id === k.id))?.id);
    setComponentId((current) => current || firstCategory?.component_id || comps[0]?.id || "");
    setCategoryId((current) => current || firstCategory?.id || "");
    setMetaLoaded(true);
  }, [projectId]);

  useLoadOnChange(async () => {
    try {
      await loadMeta();
    } catch (err) {
      setError(toErrorMessage(err, strings.common.error));
    }
  }, [projectId]);

  /** Creates the requirement; `andAttach` advances to the file step against its id instead of closing. */
  async function createRequirement(andAttach: boolean) {
    setError(null);
    try {
      const requirement = await api.post<Requirement>(`/api/v1/projects/${projectId}/requirements`, {
        name: fields.name,
        reasoning: fields.reasoning,
        clarification: fields.clarification,
        description: fields.description,
        component_id: componentId,
        category_id: categoryId,
        target_stage_id: fields.targetStageId,
        level: fields.level,
        ...requirementPeopleAndReviewPayload(fields),
        keywords: [],
        additional_places: additionalPlaces
          .filter((place) => place.category_id && place.category_id !== categoryId)
          .map((place) => ({ component_id: place.component_id, category_id: place.category_id })),
        custom_fields: customFieldValues,
      });
      announceCreated(strings.requirements.recordLabel, requirement);
      await commitQuickLinks(requirement.id, quickLinks);
      await commitTags(requirement.id, tags);
      onCreated(requirement);
      if (andAttach) {
        setCreated(requirement);
        setCreatedFiles([]);
      } else {
        onClose();
      }
    } catch (err) {
      setError(toErrorMessage(err, strings.common.error));
    }
  }

  async function reloadCreatedFiles(requirementId: string) {
    setCreatedFiles(await api.get<FileAsset[]>(`/api/v1/projects/${projectId}/requirements/${requirementId}/files`));
  }

  if (!metaLoaded || !project || orgUsers === null) return null;
  const valid = !!fields.name && !!componentId && !!categoryId && !!fields.targetStageId;
  const title = created ? `${created.unique_code} — ${strings.requirements.attachFilesAndLinks}` : strings.requirements.newRequirement;

  if (created) {
    return (
      <Modal title={title} onClose={onClose} size="lg">
        <div className="stack">
          <h3 style={{ margin: 0, fontSize: "1rem" }}>{strings.requirements.attachments}</h3>
          <FileAttachmentList
            files={createdFiles}
            onUpload={async (file) => {
              if (!(await run(() => api.postFile(`/api/v1/projects/${projectId}/requirements/${created.id}/files`, file), "upload", "file"))) return;
              await reloadCreatedFiles(created.id);
            }}
            onRemove={async (fileId) => {
              if (!(await run(() => api.delete(`/api/v1/projects/${projectId}/requirements/${created.id}/files/${fileId}`), "remove", "file"))) return;
              await reloadCreatedFiles(created.id);
            }}
          />
          <FormActions onCancel={onClose} onSave={onClose} saveLabel={strings.requirements.finish} />
        </div>
      </Modal>
    );
  }

  if (components.length === 0 || categories.length === 0) {
    return (
      <Modal title={title} onClose={onClose} size="lg">
        <div className="stack">
          <p style={{ margin: 0 }}>{strings.requirements.noComponentsOrCategories}</p>
          {canManageProject ? (
            <div className="stack">
              {components.length === 0 && <InlineStructureForm projectId={projectId} kind="component" onCreated={loadMeta} />}
              {categories.length === 0 && components.length > 0 && (
                <>
                  {components.length > 1 && (
                    <LabeledSelect help={strings.help.structureParentComponent}
                      label={strings.requirements.component} value={componentId} onChange={setComponentId}
                      options={components.map((c) => ({ value: c.id, label: c.name }))} placeholder={null}
                    />
                  )}
                  <InlineStructureForm projectId={projectId} kind="category" componentId={componentId} onCreated={loadMeta} />
                </>
              )}
            </div>
          ) : (
            <Link to={`/projects/${projectId}/admin`} className="btn btn-primary" style={{ alignSelf: "flex-start" }}>
              {strings.requirements.configureComponentsFirst}
            </Link>
          )}
        </div>
      </Modal>
    );
  }

  return (
    <Modal title={title} onClose={onClose} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <RequirementFields
            values={fields}
            onChange={setFields}
            stages={stages}
            orgUsers={orgUsers}
            organizationId={project.organization_id}
            projectId={projectId}
            ownerPlaceholder={strings.requirements.ownerDefaultsToYou}
            afterDescription={
              <>
                <PrimaryPlaceField
                  tree={{ components, categories }} categoryId={categoryId} help={strings.help.requirementPlace}
                  onChange={(place) => {
                    setComponentId(place.component_id);
                    setCategoryId(place.category_id ?? "");
                  }}
                />
                <FormGridFull>
                  <RequirementAliasField projectId={projectId} ownCategoryId={categoryId} value={additionalPlaces} onChange={setAdditionalPlaces} />
                </FormGridFull>
              </>
            }
          />
          <FormGridFull>
            <CustomFieldsForm
              definitions={customFieldDefs}
              values={customFieldValues}
              onChange={(fieldId, value) => setCustomFieldValues((v) => ({ ...v, [fieldId]: value }))}
            />
          </FormGridFull>
          <FormGridFull>
            <QuickLinkField projectId={projectId} artefactType="requirement" value={quickLinks} onChange={setQuickLinks} />
          </FormGridFull>
          <FormGridFull>
            <TagField projectId={projectId} artefactType="requirement" value={tags} onChange={setTags} />
          </FormGridFull>
        </FormGrid>
        <FormActions error={error} onCancel={onClose} onSave={() => createRequirement(false)} saveLabel={strings.common.create} saveDisabled={!valid}>
          {offerAttach && (
            <button className="btn" onClick={() => createRequirement(true)} disabled={!valid}>{strings.requirements.createAndAttach}</button>
          )}
        </FormActions>
      </div>
    </Modal>
  );
}
