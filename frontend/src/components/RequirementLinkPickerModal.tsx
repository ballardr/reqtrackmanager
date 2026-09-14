/**
 * Module: components/RequirementLinkPickerModal
 *
 * Replaces `pages/RequirementDetailPage.tsx`'s old flat-`<select>` "Add
 * link" `Popover` (platform-review-2026-09 Phase 7) with a `Modal` offering
 * three ways to find a target: a plain text **Search**, a cascading
 * **Requirements** browse (component → category → requirement, mirroring
 * `RequirementsPage.tsx`'s own create-form cascade — component and category
 * form a genuine two-level tree, not two independent filters), and any
 * further tabs installed modules contribute (`RequirementLinkPickerTabDef`,
 * `modules/types.ts`) — today, Compliance's own standard → version →
 * requirement cascade for linking to a `ComplianceRequirement`. This page
 * never imports a specific module's own entity: the Compliance tab arrives
 * pre-rendered as `extraTabs`, computed by the caller the same way
 * `contributedLinkSections` already is (see `modules/registry.ts`'s
 * `getInstalledModule`).
 *
 * The Search/Requirements tabs both end in the same link-type select + Add
 * button and call `onAddCoreLink`, which the caller wires to the same
 * `POST .../links` endpoint the old popover used — this phase changes how a
 * target is found, not how a core-to-core link is created. Platform review
 * 2026-09 Phase 8: when `linksLocked` is true (this requirement is approved
 * and the project/org requires a change request for link changes), both
 * built-in tabs additionally show a "Reason for change" field and disable
 * Add until it's filled — `onAddCoreLink`'s caller (`RequirementDetailPage
 * .tsx`) branches on the same condition to submit an `add_link` change
 * request instead of calling the direct endpoint, the same
 * change-request-only-once-locked pattern item 514 already established for
 * actions. Module-contributed tabs are unaffected — `linksLocked` only ever
 * gates core-to-core `RequirementLink`s, never a module's own kind of link.
 * A module-contributed tab owns its own target-picker UI *and* its own link-creation
 * call (it links to its own kind of entity via its own module's API); it
 * signals success by calling `onLinked()`, which the caller treats the same
 * as `onAddCoreLink` resolving — close the modal, bump the shared refresh
 * signal (`RequirementDetailSectionDef`'s `refreshToken`) so any section
 * displaying links re-fetches. This is the first `Modal`+`Tabs` combination
 * in the codebase — see `docs/ux-style-guide.md`'s "Pattern: tabbed picker
 * modal."
 */
import { useState, type ReactNode } from "react";

import type { Category, Component, LinkTypeDefinition, Requirement } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";
import { Tabs, tabPanelProps, type TabDef } from "./Tabs";

const ID_PREFIX = "requirement-link-picker";

interface ContributedTab {
  key: string;
  label: string;
  node: ReactNode;
}

export function RequirementLinkPickerModal({
  eligibleTargets,
  components,
  categories,
  linkTypes,
  extraTabs,
  linksLocked,
  onAddCoreLink,
  onClose,
}: {
  eligibleTargets: Requirement[];
  components: Component[];
  categories: Category[];
  linkTypes: LinkTypeDefinition[];
  /** Module-contributed tabs, already rendered by the caller (each
   * `render()` call already supplied `onLinked`) — this modal has no
   * knowledge of what a contributed tab links to. */
  extraTabs: ContributedTab[];
  /** Platform review 2026-09, Phase 8 — true once this requirement is
   * approved and the project/org requires a change request for link
   * changes (`services.requirements.requires_change_request_for_links`,
   * mirrored client-side by the caller). Only affects the two built-in
   * tabs, below — a module-contributed tab's own kind of link is never
   * gated by this. */
  linksLocked: boolean;
  onAddCoreLink: (targetRequirementId: string, linkTypeId: string, reason?: string) => Promise<void>;
  onClose: () => void;
}) {
  const strings = useStrings();
  type TabKey = "search" | "requirements" | (string & {});
  const [activeTab, setActiveTab] = useState<TabKey>("search");

  const builtInTabs: TabDef<TabKey>[] = [
    { key: "search", label: strings.requirements.linkPickerSearchTab },
    { key: "requirements", label: strings.requirements.linkPickerRequirementsTab },
  ];
  const tabs: TabDef<TabKey>[] = [...builtInTabs, ...extraTabs.map((t) => ({ key: t.key, label: t.label }))];

  return (
    <Modal title={strings.requirements.addLink} onClose={onClose} size="lg">
      <div className="stack">
        {linksLocked && <p className="text-muted" style={{ margin: 0 }}>{strings.requirements.linkChangeRequestNotice}</p>}
        <Tabs idPrefix={ID_PREFIX} tabs={tabs} active={activeTab} onChange={setActiveTab} />
        {activeTab === "search" && (
          <div {...tabPanelProps(ID_PREFIX, "search")}>
            <SearchLinkTab
              eligibleTargets={eligibleTargets}
              linkTypes={linkTypes}
              linksLocked={linksLocked}
              onAddCoreLink={onAddCoreLink}
            />
          </div>
        )}
        {activeTab === "requirements" && (
          <div {...tabPanelProps(ID_PREFIX, "requirements")}>
            <RequirementsBrowseLinkTab
              eligibleTargets={eligibleTargets}
              components={components}
              categories={categories}
              linkTypes={linkTypes}
              linksLocked={linksLocked}
              onAddCoreLink={onAddCoreLink}
            />
          </div>
        )}
        {extraTabs.map(
          (t) =>
            activeTab === t.key && (
              <div key={t.key} {...tabPanelProps(ID_PREFIX, t.key)}>
                {t.node}
              </div>
            )
        )}
      </div>
    </Modal>
  );
}

function SearchLinkTab({
  eligibleTargets,
  linkTypes,
  linksLocked,
  onAddCoreLink,
}: {
  eligibleTargets: Requirement[];
  linkTypes: LinkTypeDefinition[];
  linksLocked: boolean;
  onAddCoreLink: (targetRequirementId: string, linkTypeId: string, reason?: string) => Promise<void>;
}) {
  const strings = useStrings();
  const [query, setQuery] = useState("");
  const [targetId, setTargetId] = useState("");
  const [linkTypeId, setLinkTypeId] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const matches = eligibleTargets.filter((r) => {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return r.unique_code.toLowerCase().includes(q) || r.name.toLowerCase().includes(q);
  });

  async function handleAdd() {
    if (!targetId || !linkTypeId || (linksLocked && !reason.trim())) return;
    setError(null);
    try {
      await onAddCoreLink(targetId, linkTypeId, linksLocked ? reason : undefined);
    } catch (err) {
      setError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  return (
    <div className="stack">
      <label className="stack" style={{ gap: "0.25rem" }}>
        <span>{strings.requirements.linkPickerSearchTab}</span>
        <input
          className="input"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setTargetId("");
          }}
          placeholder={strings.requirements.linkPickerSearchPlaceholder}
        />
      </label>
      <LabeledSelect
        label={strings.requirements.targetRequirement}
        value={targetId}
        onChange={setTargetId}
        options={matches.map((r) => ({ value: r.id, label: `${r.unique_code} — ${r.name}` }))}
        placeholder={
          matches.length === 0 ? strings.requirements.linkPickerNoMatches : strings.requirements.selectARequirementToLink
        }
        disabled={matches.length === 0}
      />
      <LabeledSelect
        label={strings.requirements.linkType}
        value={linkTypeId}
        onChange={setLinkTypeId}
        options={linkTypes.map((lt) => ({ value: lt.id, label: lt.forward_name }))}
      />
      {linksLocked && (
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.changeRequests.reason}
          <textarea
            className="input" rows={2} aria-label={strings.changeRequests.reason}
            value={reason} onChange={(e) => setReason(e.target.value)}
          />
        </label>
      )}
      {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button
          className="btn btn-primary" onClick={handleAdd}
          disabled={!targetId || !linkTypeId || (linksLocked && !reason.trim())}
        >
          {strings.requirements.addLink}
        </button>
      </div>
    </div>
  );
}

function RequirementsBrowseLinkTab({
  eligibleTargets,
  components,
  categories,
  linkTypes,
  linksLocked,
  onAddCoreLink,
}: {
  eligibleTargets: Requirement[];
  components: Component[];
  categories: Category[];
  linkTypes: LinkTypeDefinition[];
  linksLocked: boolean;
  onAddCoreLink: (targetRequirementId: string, linkTypeId: string, reason?: string) => Promise<void>;
}) {
  const strings = useStrings();
  const [componentId, setComponentId] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [targetId, setTargetId] = useState("");
  const [linkTypeId, setLinkTypeId] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Category is nested under one component (the tree) — a category
  // belonging to a different component is never valid, so changing the
  // component resets both the category and the leaf selection, mirroring
  // `RequirementsPage.tsx`'s own create-form cascade. When the new
  // component has exactly one category, auto-select it rather than
  // leaving the user to pick from a dropdown with only one real option.
  function handleComponentChange(value: string) {
    setComponentId(value);
    const ownCategories = categories.filter((c) => c.component_id === value);
    setCategoryId(ownCategories.length === 1 ? ownCategories[0].id : "");
    setTargetId("");
  }
  function handleCategoryChange(value: string) {
    setCategoryId(value);
    setTargetId("");
  }

  const categoriesForComponent = categories.filter((c) => c.component_id === componentId);
  const requirementsForSelection = eligibleTargets.filter(
    (r) => r.component_id === componentId && (categoryId === "" || r.category_id === categoryId)
  );

  async function handleAdd() {
    if (!targetId || !linkTypeId || (linksLocked && !reason.trim())) return;
    setError(null);
    try {
      await onAddCoreLink(targetId, linkTypeId, linksLocked ? reason : undefined);
    } catch (err) {
      setError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  return (
    <div className="stack">
      <LabeledSelect
        label={strings.requirements.component}
        value={componentId}
        onChange={handleComponentChange}
        options={components.map((c) => ({ value: c.id, label: `${c.name} (${c.prefix})` }))}
      />
      <LabeledSelect
        label={strings.requirements.category}
        value={categoryId}
        onChange={handleCategoryChange}
        options={categoriesForComponent.map((c) => ({ value: c.id, label: `${c.name} (${c.prefix})` }))}
        disabled={!componentId}
        placeholder={
          componentId && categoriesForComponent.length === 0
            ? strings.requirements.noCategoriesForComponent
            : "Select…"
        }
      />
      <LabeledSelect
        label={strings.requirements.targetRequirement}
        value={targetId}
        onChange={setTargetId}
        options={requirementsForSelection.map((r) => ({ value: r.id, label: `${r.unique_code} — ${r.name}` }))}
        disabled={!componentId}
        placeholder={
          componentId && requirementsForSelection.length === 0
            ? strings.requirements.linkPickerNoMatches
            : strings.requirements.selectARequirementToLink
        }
      />
      <LabeledSelect
        label={strings.requirements.linkType}
        value={linkTypeId}
        onChange={setLinkTypeId}
        options={linkTypes.map((lt) => ({ value: lt.id, label: lt.forward_name }))}
      />
      {linksLocked && (
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.changeRequests.reason}
          <textarea
            className="input" rows={2} aria-label={strings.changeRequests.reason}
            value={reason} onChange={(e) => setReason(e.target.value)}
          />
        </label>
      )}
      {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button
          className="btn btn-primary" onClick={handleAdd}
          disabled={!targetId || !linkTypeId || (linksLocked && !reason.trim())}
        >
          {strings.requirements.addLink}
        </button>
      </div>
    </div>
  );
}
