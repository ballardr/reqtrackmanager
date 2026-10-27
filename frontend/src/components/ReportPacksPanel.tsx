/**
 * Module: components/ReportPacksPanel
 *
 * The list of an organisation's or a project's report packs (Org Admin and Project Admin, Report setup): one
 * component for both tiers over `ReportPackApi`, the sibling of `ReportLayoutsPanel`.
 *
 * Responsibilities:
 * - List the packs the scope can reach, with where an inherited one is shared from; the name opens the editor
 *   (`reportPackPath`), where a pack shared from elsewhere is read-only apart from overriding its saved sets.
 * - Create a pack (`ReportPackFormModal`), edit its details, make a copy (the way to customise a shared pack, since it
 *   is changed only where it lives), delete an own pack.
 * - In a project, hide a shared pack and restore it (style guide, "Pattern: organisation defaults in a project").
 * - Follow the confirmation tiers: delete is Tier 2 (type the name); hiding is Tier 1. Every change ends in a toast.
 *
 * Design decisions: access is enforced by the server (a 403 shows the load failure); the panel does not guess
 * permissions. Hidden packs are listed by the API only to a manager, so the restore button appears for them.
 */
import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";

import { LAYOUT_ORIGIN_LABEL } from "../api/reportLayouts";
import { reportPackPath, type ReportPackApi, type ReportPackSummary } from "../api/reportPacks";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { ActionMenu, type ActionMenuItem } from "./ActionMenu";
import { Badge } from "./Badge";
import { ConfirmDialog } from "./ConfirmDialog";
import { DirectoryTable, type DirectoryColumn } from "./DirectoryTable";
import { ReportPackFormModal } from "./ReportPackFormModal";
import { RestoreOrgDefaultsButton } from "./RestoreOrgDefaultsButton";
import { Spinner } from "./Spinner";

type Dialog =
  | { kind: "create" }
  | { kind: "edit"; pack: ReportPackSummary }
  | { kind: "delete"; pack: ReportPackSummary }
  | { kind: "hide"; pack: ReportPackSummary };

/** @param api The calls, bound to an organisation or a project. */
export function ReportPacksPanel({ api }: { api: ReportPackApi }) {
  const strings = useStrings();
  const text = strings.reportPacks;
  const { showToast } = useToast();
  const navigate = useNavigate();
  const [packs, setPacks] = useState<ReportPackSummary[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const inProject = api.scope.kind === "project";

  const reload = useCallback(async () => {
    try {
      setPacks(await api.list());
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [api]);

  useLoadOnChange(reload, [api.scope.kind, api.scope.id]);

  /** Runs a change, toasts its outcome and reloads; an error is toasted and leaves the list as it was. */
  async function run(action: () => Promise<string>) {
    try {
      showToast(await action());
      await reload();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  if (failed && !packs) return <p className="text-muted" role="alert">{text.loadFailed}</p>;
  if (!packs) return <Spinner />;

  const visible = packs.filter((pack) => !pack.hidden);
  const hidden = packs.filter((pack) => pack.hidden);

  async function copy(pack: ReportPackSummary) {
    await run(async () => {
      const detail = await api.get(pack.id);
      const created = await api.create({
        name: text.copyName(pack.name), description: pack.description, definition: detail.current.definition,
      });
      navigate(reportPackPath(api.scope, created.id));
      return text.copied;
    });
  }

  function menuFor(pack: ReportPackSummary): ActionMenuItem[] {
    const open: ActionMenuItem = {
      key: "open", label: pack.editable ? text.open : text.view, onSelect: () => navigate(reportPackPath(api.scope, pack.id)),
    };
    const makeCopy: ActionMenuItem = { key: "copy", label: text.makeCopy, onSelect: () => void copy(pack) };
    if (!pack.editable) {
      return [open, makeCopy, { key: "hide", label: text.hide, danger: true, onSelect: () => setDialog({ kind: "hide", pack }) }];
    }
    return [
      open,
      { key: "edit", label: text.editDetails, onSelect: () => setDialog({ kind: "edit", pack }) },
      makeCopy,
      { key: "delete", label: text.delete, danger: true, onSelect: () => setDialog({ kind: "delete", pack }) },
    ];
  }

  const columns: DirectoryColumn<ReportPackSummary>[] = [
    {
      key: "name",
      label: text.nameHeading,
      render: (pack) => (
        <span className="stack" style={{ gap: 0 }}>
          <span>{pack.name}</span>
          {pack.description && <span className="text-muted" style={{ fontSize: "0.85rem" }}>{pack.description}</span>}
        </span>
      ),
    },
    { key: "reports", label: text.reportsHeading, render: (pack) => text.reportCount(pack.entries) },
    ...(inProject
      ? [{
        key: "shared",
        label: text.sharedHeading,
        render: (pack: ReportPackSummary) => (pack.origin === "project" ? null : <Badge>{LAYOUT_ORIGIN_LABEL[pack.origin]}</Badge>),
      }]
      : []),
    { key: "version", label: text.versionHeading, render: (pack) => pack.current_version },
    { key: "updated", label: text.updatedHeading, render: (pack) => new Date(pack.updated_at).toLocaleDateString() },
    {
      key: "actions",
      label: <span className="sr-only">{strings.common.moreOptions}</span>,
      render: (pack) => <ActionMenu triggerLabel={text.actionsFor(pack.name)} items={menuFor(pack)} />,
    },
  ];

  return (
    <div className="stack">
      <p className="text-muted" style={{ margin: 0 }}>{text.description} {inProject ? text.projectDescription : text.orgDescription}</p>
      <div className="row">
        <button type="button" className="btn btn-primary" onClick={() => setDialog({ kind: "create" })}>{text.newPack}</button>
        {inProject && api.restore && (
          <RestoreOrgDefaultsButton
            hidden={hidden.map((pack) => ({ id: pack.id, name: pack.name }))}
            noun={text.restoreNoun}
            onRestore={async (ids) => {
              await api.restore?.(ids);
              showToast(text.restored);
              await reload();
            }}
          />
        )}
      </div>
      <DirectoryTable
        ariaLabel={text.listLabel}
        columns={columns}
        rows={visible}
        rowKey={(pack) => pack.id}
        rowHref={(pack) => reportPackPath(api.scope, pack.id)}
        emptyState={<p className="text-muted">{text.empty}</p>}
      />

      {dialog?.kind === "create" && (
        <ReportPackFormModal
          api={api}
          onClose={() => setDialog(null)}
          onSaved={(saved) => {
            showToast(text.created);
            navigate(reportPackPath(api.scope, saved.id));
          }}
        />
      )}
      {dialog?.kind === "edit" && (
        <ReportPackFormModal
          api={api}
          pack={dialog.pack}
          onClose={() => setDialog(null)}
          onSaved={() => {
            showToast(text.detailsSaved);
            void reload();
          }}
        />
      )}
      {dialog?.kind === "delete" && (
        <ConfirmDialog
          title={text.deleteTitle(dialog.pack.name)}
          message={text.deleteMessage(dialog.pack.current_version)}
          confirmLabel={text.delete}
          requireTypedText={dialog.pack.name}
          onCancel={() => setDialog(null)}
          onConfirm={() => {
            const pack = dialog.pack;
            setDialog(null);
            void run(async () => {
              await api.remove(pack.id);
              return text.deleted;
            });
          }}
        />
      )}
      {dialog?.kind === "hide" && (
        <ConfirmDialog
          title={text.hideTitle(dialog.pack.name)}
          message={text.hideMessage}
          confirmLabel={text.hideConfirm}
          onCancel={() => setDialog(null)}
          onConfirm={() => {
            const pack = dialog.pack;
            setDialog(null);
            void run(async () => {
              await api.setHidden?.(pack.id, true);
              return text.hidden;
            });
          }}
        />
      )}
    </div>
  );
}
