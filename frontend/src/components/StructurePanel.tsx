/**
 * Module: components/StructurePanel
 *
 * The Structure page of project administration: the project's components and the categories beneath each, drawn as the
 * same collapsible folder tree the report lists use (`FolderTreeList`), with each row's actions in a menu and create and
 * edit in a side panel (`StructureNodeForm`).
 *
 * Responsibilities: load the tree and counts and reload after every change (`onChanged` refreshes what else reads it);
 * keep each person's open components (`useOpenFolders`), opening every match while searching and the component just
 * edited; offer Add component and per row Edit, Move up, Move down, Add category, Move to another component and Delete
 * (a category in use opens the replacement dialog after a 409; a component is deleted only once it has no categories).
 *
 * Design decisions: component and category order is manual (the server's `sort_order`), so no header sorts. Every action
 * is a `StructureApi` call; the panel holds no rule of its own. Injectable `api` keeps stories off the network.
 */
import { Boxes, Layers, Plus } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import type { PlacementTree } from "../api/placements";
import { ApiError } from "../api/client";
import { structureApi, type StructureApi, type StructureCounts } from "../api/structure";
import type { Category, Component } from "../api/types";
import { useToast, toErrorMessage } from "../context/ToastContext";
import { useStrings } from "../context/TerminologyContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useOpenFolders } from "../hooks/useOpenFolders";
import { buildStructureNodes } from "../utils/structureTree";
import { componentNodeId } from "./placementTree";
import { ActionMenu, type ActionMenuItem } from "./ActionMenu";
import { ConfirmDialog } from "./ConfirmDialog";
import { DeleteInUseDialog } from "./DeleteInUseDialog";
import { FilterPanel } from "./FilterPanel";
import { FolderTreeList, type FolderTreeColumn } from "./FolderTreeList";
import { FormActions } from "./FormActions";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";
import { StructureNodeForm, type StructureNodeTarget } from "./StructureNodeForm";
import type { FolderNode } from "../utils/reportFolders";
import { Spinner } from "./Spinner";

/** What the person is deleting or moving, by id. */
type Pending =
  | { kind: "delete-component"; component: Component }
  | { kind: "delete-category"; category: Category }
  | { kind: "in-use"; category: Category; message: string }
  | { kind: "move"; category: Category };

/**
 * @param projectId The project whose structure is edited.
 * @param api The structure calls (injectable for stories).
 * @param onChanged Called after any change, so the page can reload what else shows components and categories.
 */
export function StructurePanel({
  projectId, api = structureApi, onChanged,
}: { projectId: string; api?: StructureApi; onChanged?: () => void }) {
  const strings = useStrings();
  const text = strings.structure;
  const { showToast } = useToast();
  const [data, setData] = useState<{ tree: PlacementTree; counts: StructureCounts } | null>(null);
  const [failed, setFailed] = useState(false);
  const [search, setSearch] = useState("");
  const [form, setForm] = useState<StructureNodeTarget | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [openIds, setFolderOpen] = useOpenFolders(`structure-${projectId}`);

  const reload = useCallback(async () => {
    try {
      const [tree, counts] = await Promise.all([api.tree(projectId), api.counts(projectId)]);
      setData({ tree, counts });
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [api, projectId]);
  useLoadOnChange(reload, [projectId]);

  const searching = search.trim() !== "";
  const built = useMemo(() => (data ? buildStructureNodes(data.tree, search) : null), [data, search]);
  const expanded = searching ? built?.opened ?? new Set<string>() : openIds;
  const components = useMemo(() => data?.tree.components ?? [], [data]);
  const categories = useMemo(() => data?.tree.categories ?? [], [data]);
  const componentById = useMemo(() => new Map(components.map((c) => [c.id, c])), [components]);

  async function changed() {
    await reload();
    onChanged?.();
  }

  async function act(action: () => Promise<unknown>, success?: string) {
    try {
      await action();
      if (success) showToast(success);
      await changed();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  const move = (kind: "component" | "category", id: string, direction: "up" | "down") =>
    act(() => api.move(projectId, kind, id, direction));

  /** Deletes a category; a category in use opens the replacement dialog with the server's own counts. */
  async function deleteCategory(category: Category) {
    try {
      await api.remove(projectId, "category", category.id);
      showToast(strings.mutation.success("{category}", strings.mutation.past.delete));
      await changed();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) setPending({ kind: "in-use", category, message: err.message });
      else showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  const columns: FolderTreeColumn<Category>[] = [
    {
      id: "prefix", header: text.prefixColumn, width: "minmax(5rem, 8rem)",
      render: (category) => <code>{category.prefix}</code>,
      renderFolder: (node) => <code>{componentById.get(node.path)?.prefix}</code>,
    },
    {
      id: "requirements", header: text.requirementsColumn, width: "minmax(5rem, 8rem)", hideBelow: true,
      render: (category) => data?.counts.categories[category.id] ?? 0,
      renderFolder: (node) => data?.counts.components[node.path]?.requirements ?? 0,
    },
  ];

  function componentMenu(node: FolderNode<Category>): ActionMenuItem[] {
    const component = componentById.get(node.path);
    if (!component) return [];
    const index = components.findIndex((c) => c.id === component.id);
    const hasCategories = (data?.counts.components[component.id]?.categories ?? 0) > 0;
    return [
      { label: text.edit, onSelect: () => setForm({ kind: "component", node: component }) },
      { label: text.addCategory(component.name), onSelect: () => setForm({ kind: "category", component }) },
      { label: text.moveUp, disabled: index <= 0, onSelect: () => void move("component", component.id, "up") },
      { label: text.moveDown, disabled: index === components.length - 1, onSelect: () => void move("component", component.id, "down") },
      {
        label: text.delete, danger: true, disabled: hasCategories, title: hasCategories ? text.deleteComponentBlocked : undefined,
        onSelect: () => setPending({ kind: "delete-component", component }),
      },
    ];
  }

  function categoryMenu(category: Category): ActionMenuItem[] {
    const siblings = categories.filter((c) => c.component_id === category.component_id);
    const index = siblings.findIndex((c) => c.id === category.id);
    const noOther = components.length < 2;
    return [
      { label: text.edit, onSelect: () => openCategory(category) },
      { label: text.moveUp, disabled: index <= 0, onSelect: () => void move("category", category.id, "up") },
      { label: text.moveDown, disabled: index === siblings.length - 1, onSelect: () => void move("category", category.id, "down") },
      {
        label: text.moveToComponent, disabled: noOther, title: noOther ? text.noOtherComponent : undefined,
        onSelect: () => setPending({ kind: "move", category }),
      },
      { label: text.delete, danger: true, onSelect: () => setPending({ kind: "delete-category", category }) },
    ];
  }

  function openCategory(category: Category) {
    const component = componentById.get(category.component_id);
    if (component) setForm({ kind: "category", component, node: category });
  }

  /** Keeps the component a node was saved in open, so the person sees the result. */
  function saved(target: StructureNodeTarget) {
    const id = target.kind === "component" ? target.node?.id : target.component.id;
    if (id) setFolderOpen(componentNodeId(id), true);
    void changed();
  }

  if (failed) return <p className="text-muted">{strings.common.error}</p>;
  if (!data || !built) return <Spinner />;

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button type="button" className="btn btn-primary" onClick={() => setForm({ kind: "component" })}>
          <Plus /> {text.addComponent}
        </button>
      </div>
      <FilterPanel
        sectionKey="projectAdmin.structure" layout="top" matching={built.nodes.length} total={components.length}
        search={search} onSearchChange={setSearch} searchPlaceholder={text.searchPlaceholder} searchAriaLabel={text.searchLabel}
      >
        {null}
      </FilterPanel>
      <FolderTreeList
        nodes={built.nodes}
        order="given"
        label={text.treeLabel}
        expanded={expanded}
        onToggle={(id, open) => {
          if (!searching) setFolderOpen(id, open);
        }}
        folderIcon={() => <Boxes aria-hidden="true" />}
        itemView={() => ({ icon: <Layers aria-hidden="true" />, iconLabel: strings.requirements.category })}
        onOpenItem={openCategory}
        columns={columns}
        folderBadge={(node) => text.categoryCount(node.count)}
        emptyFolderText={text.emptyFolder}
        emptyText={components.length > 0 ? text.noMatch : text.emptyTree}
        renderFolderActions={(node) => <ActionMenu triggerLabel={text.actionsFor(node.name)} items={componentMenu(node)} />}
        renderItemActions={(category) => <ActionMenu triggerLabel={text.actionsFor(category.name)} items={categoryMenu(category)} />}
      />

      {form && (
        <StructureNodeForm
          api={api} projectId={projectId} target={form} onSaved={() => saved(form)} onClose={() => setForm(null)}
        />
      )}
      {pending?.kind === "delete-component" && (
        <ConfirmDialog
          title={text.deleteComponentTitle} message={strings.admin.deleteComponentConfirm(pending.component.name)}
          confirmLabel={strings.admin.confirmDelete}
          onConfirm={() => {
            const { component } = pending;
            setPending(null);
            void act(() => api.remove(projectId, "component", component.id), strings.mutation.success("{component}", strings.mutation.past.delete));
          }}
          onCancel={() => setPending(null)}
        />
      )}
      {pending?.kind === "delete-category" && (
        <ConfirmDialog
          title={text.deleteCategoryTitle} message={strings.admin.deleteCategoryConfirm(pending.category.name)}
          confirmLabel={strings.admin.confirmDelete}
          onConfirm={() => {
            const { category } = pending;
            setPending(null);
            void deleteCategory(category);
          }}
          onCancel={() => setPending(null)}
        />
      )}
      {pending?.kind === "in-use" && (
        <DeleteInUseDialog
          title={strings.admin.deleteInUseTitle(pending.category.name)}
          summary={pending.message}
          candidates={categories.filter((other) => other.id !== pending.category.id).map((other) => ({
            id: other.id, label: `${componentById.get(other.component_id)?.name ?? ""} / ${other.name}`,
          }))}
          onMove={async (replacementId) => {
            await api.remove(projectId, "category", pending.category.id, replacementId);
            showToast(strings.mutation.success("{category}", strings.mutation.past.delete));
            await changed();
          }}
          onClose={() => setPending(null)}
        />
      )}
      {pending?.kind === "move" && (
        <MoveCategoryDialog
          category={pending.category} components={components} requirementCount={data.counts.categories[pending.category.id] ?? 0}
          onMove={async (componentId) => {
            await api.moveCategoryTo(projectId, pending.category.id, componentId);
            showToast(text.moved);
            setFolderOpen(componentNodeId(componentId), true);
            await changed();
          }}
          onClose={() => setPending(null)}
        />
      )}
    </div>
  );
}

/**
 * The dialog that moves a category under another component.
 *
 * @param category The category to move.
 * @param components Every component of the project (its own is left out of the choice).
 * @param requirementCount How many requirements move with it, named in the explanation.
 * @param onMove Makes the move; a refusal (a prefix already in use there) is shown in the dialog.
 * @param onClose Closes the dialog.
 */
function MoveCategoryDialog({
  category, components, requirementCount, onMove, onClose,
}: {
  category: Category;
  components: Component[];
  requirementCount: number;
  onMove: (componentId: string) => Promise<void>;
  onClose: () => void;
}) {
  const strings = useStrings();
  const text = strings.structure;
  const [target, setTarget] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await onMove(target);
      onClose();
    } catch (err) {
      setError(toErrorMessage(err, strings.common.error));
      setBusy(false);
    }
  }

  return (
    <Modal title={text.moveTitle(category.name)} onClose={onClose}>
      <div className="stack">
        <LabeledSelect
          label={text.moveTarget} required help={strings.help.structureMoveTarget} value={target} onChange={setTarget}
          placeholder={text.moveChoose}
          options={components.filter((c) => c.id !== category.component_id).map((c) => ({ value: c.id, label: `${c.name} (${c.prefix})` }))}
        />
        <p style={{ margin: 0 }}>{text.moveEffect(category.name, requirementCount)}</p>
        <FormActions error={error} onCancel={onClose} onSave={() => void submit()} saveLabel={text.moveConfirm} saveDisabled={target === "" || busy} />
      </div>
    </Modal>
  );
}
