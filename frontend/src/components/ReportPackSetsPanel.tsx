/**
 * Module: components/ReportPackSetsPanel
 *
 * The "Saved sets" tab of the pack editor: named choices for the pack's variables ("Team Alpha: categories A and
 * B") so a repeat download is one click, and, in a project, what that project overrides.
 *
 * Responsibilities:
 * - List the sets the scope sees, each with its variables' values; where a project overrides a shared set, show the
 *   shared value beside the project's own with a reset (style guide, "Pattern: organisation defaults in a project").
 * - Create, edit and delete the sets the scope owns (`ReportPackSetFormModal`); in a project, add its own set beside
 *   an inherited pack's, and override an inherited pack's set, variable by variable.
 * - Flag a stored value that is no longer one of the variable's options (the server's warning), never hide it.
 * - Every change ends in a toast; delete is Tier 1 (confirm).
 *
 * Design decisions: access is the server's (a refused write shows its message); the panel only offers the actions the
 * server says the scope may take (`editable`, `overridable`).
 */
import { useCallback, useState } from "react";

import type { PackValues, ReportPackApi, ReportPackSet } from "../api/reportPacks";
import { reportPackRunApi } from "../api/reportPacks";
import type { ReportVariable } from "../api/reports";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { ActionMenu, type ActionMenuItem } from "./ActionMenu";
import { Badge } from "./Badge";
import { ConfirmDialog } from "./ConfirmDialog";
import { ReportPackSetFormModal } from "./ReportPackSetFormModal";
import { Spinner } from "./Spinner";

type Dialog =
  | { kind: "create" }
  | { kind: "edit"; set: ReportPackSet }
  | { kind: "override"; set: ReportPackSet }
  | { kind: "delete"; set: ReportPackSet };

/** A value as the table shows it. */
function show(value: PackValues[string] | undefined, notSet: string): string {
  if (value === undefined) return notSet;
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

/**
 * @param api The pack calls bound to the scope.
 * @param packId The pack.
 */
export function ReportPackSetsPanel({ api, packId }: { api: ReportPackApi; packId: string }) {
  const strings = useStrings();
  const text = strings.reportPacks;
  const { showToast } = useToast();
  const [sets, setSets] = useState<ReportPackSet[] | null>(null);
  const [variables, setVariables] = useState<ReportVariable[]>([]);
  const [failed, setFailed] = useState(false);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const inProject = api.scope.kind === "project";

  const reload = useCallback(async () => {
    try {
      const [loadedSets, form] = await Promise.all([api.sets(packId), reportPackRunApi(api.scope, packId).form()]);
      setSets(loadedSets);
      setVariables(form.variables);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [api, packId]);

  useLoadOnChange(reload, [api.scope.kind, api.scope.id, packId]);

  async function run(action: () => Promise<string>) {
    try {
      showToast(await action());
      await reload();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  if (failed && !sets) return <p className="text-muted" role="alert">{text.loadFailed}</p>;
  if (!sets) return <Spinner />;

  const labelOf = (name: string) => variables.find((v) => v.name === name)?.label ?? name;

  function menuFor(set: ReportPackSet): ActionMenuItem[] {
    const items: ActionMenuItem[] = [];
    if (set.editable) items.push({ key: "edit", label: text.setEdit, onSelect: () => setDialog({ kind: "edit", set }) });
    if (set.overridable && api.putOverride) {
      items.push({ key: "override", label: text.setOverride, onSelect: () => setDialog({ kind: "override", set }) });
    }
    if (set.override && api.resetOverride) {
      items.push({
        key: "reset", label: text.setResetOverride,
        onSelect: () => void run(async () => {
          await api.resetOverride?.(packId, set.id);
          return text.setOverrideReset;
        }),
      });
    }
    if (set.editable) items.push({ key: "delete", label: text.setDelete, danger: true, onSelect: () => setDialog({ kind: "delete", set }) });
    return items;
  }

  return (
    <div className="stack">
      <p className="text-muted" style={{ margin: 0 }}>{inProject ? text.setsIntroProject : text.setsIntro}</p>
      <div className="row">
        <button type="button" className="btn btn-primary" disabled={variables.length === 0} onClick={() => setDialog({ kind: "create" })}>
          {text.newSet}
        </button>
        {variables.length === 0 && <span className="text-muted">{text.setsNeedVariables}</span>}
      </div>
      {sets.length === 0 && <p className="text-muted">{text.noSets}</p>}
      {sets.map((set) => {
        const names = [...new Set([...Object.keys(set.base), ...Object.keys(set.effective)])];
        const items = menuFor(set);
        return (
          <section key={set.id} className="card stack" aria-label={set.name}>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
              <span className="row" style={{ alignItems: "center" }}>
                <strong>{set.name}</strong>
                <Badge>{set.origin === "pack" ? text.setOriginPack : text.setOriginProject}</Badge>
                {set.override && <Badge tone="info">{text.setOverridden}</Badge>}
              </span>
              {items.length > 0 && <ActionMenu triggerLabel={text.actionsFor(set.name)} items={items} />}
            </div>
            {names.length > 0 && (
              <table aria-label={set.name}>
                <thead>
                  <tr>
                    <th>{text.setValuesHeading}</th>
                    <th>{inProject && set.origin === "pack" ? text.setSharedHeading : text.setHereHeading}</th>
                    {inProject && set.origin === "pack" && <th>{text.setHereHeading}</th>}
                  </tr>
                </thead>
                <tbody>
                  {names.map((name) => (
                    <tr key={name}>
                      <td>{labelOf(name)}</td>
                      <td>{show(set.base[name], text.setNotSet)}</td>
                      {inProject && set.origin === "pack" && (
                        <td>{set.effective[name] !== undefined && JSON.stringify(set.effective[name]) !== JSON.stringify(set.base[name])
                          ? show(set.effective[name], text.setNotSet) : ""}</td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {set.warnings.map((warning) => (
              <p key={warning} role="status" className="text-muted" style={{ margin: 0 }}>{warning}</p>
            ))}
          </section>
        );
      })}

      {dialog?.kind === "create" && (
        <ReportPackSetFormModal
          title={text.setCreateTitle}
          variables={variables}
          initialName=""
          initialValues={{}}
          onClose={() => setDialog(null)}
          onSave={async (name, values) => {
            await api.createSet(packId, { name, values });
            showToast(text.setSaved);
            await reload();
          }}
        />
      )}
      {dialog?.kind === "edit" && (
        <ReportPackSetFormModal
          title={text.setEditTitle}
          variables={variables}
          initialName={dialog.set.name}
          initialValues={dialog.set.base}
          onClose={() => setDialog(null)}
          onSave={async (name, values) => {
            await api.updateSet(packId, dialog.set.id, { name, values });
            showToast(text.setSaved);
            await reload();
          }}
        />
      )}
      {dialog?.kind === "override" && (
        <ReportPackSetFormModal
          title={text.setOverrideTitle(dialog.set.name)}
          hint={text.setOverrideHint}
          variables={variables}
          initialName={null}
          initialValues={dialog.set.effective}
          sharedValues={dialog.set.base}
          onClose={() => setDialog(null)}
          onSave={async (_name, values) => {
            await api.putOverride?.(packId, dialog.set.id, values);
            showToast(text.setOverrideSaved);
            await reload();
          }}
        />
      )}
      {dialog?.kind === "delete" && (
        <ConfirmDialog
          title={text.setDeleteTitle(dialog.set.name)}
          message={text.setDeleteMessage}
          confirmLabel={text.setDelete}
          onCancel={() => setDialog(null)}
          onConfirm={() => {
            const set = dialog.set;
            setDialog(null);
            void run(async () => {
              await api.removeSet(packId, set.id);
              return text.setDeleted;
            });
          }}
        />
      )}
    </div>
  );
}
