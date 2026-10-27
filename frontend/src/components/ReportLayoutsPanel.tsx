/**
 * Module: components/ReportLayoutsPanel
 *
 * The list of an organisation's or a project's report layouts (Org Admin and Project Admin, Report setup):
 * one component for both tiers over `ReportLayoutApi`.
 *
 * Responsibilities:
 * - List the layouts the scope can reach, with where an inherited one is shared from; the name opens the
 *   designer (`reportLayoutPath`), where a layout shared from elsewhere is read-only.
 * - Create a layout (`ReportLayoutFormModal`), add the starter layouts an organisation lacks, edit its details, make a copy (the way to customise a shared
 *   layout, since it is changed only where it lives), delete an own layout.
 * - In a project, hide a shared layout and restore it (style guide, "Pattern: organisation defaults in a
 *   project": delete on a shared row hides it, `RestoreOrgDefaultsButton` shows it again).
 * - Follow the confirmation tiers: delete is Tier 2 (type the name); hiding is Tier 1. Every change ends in a toast.
 *
 * Design decisions: access is enforced by the server (403 shows the load failure); the panel does not guess
 * permissions. Hidden layouts are listed by the API only to a manager, so the restore button appears for them.
 */
import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";

import type { ReportLayoutApi, ReportLayoutSummary } from "../api/reportLayouts";
import { copyReportLayout, LAYOUT_FAMILY_LABEL, LAYOUT_ORIGIN_LABEL, reportLayoutPath } from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { ActionMenu, type ActionMenuItem } from "./ActionMenu";
import { Badge } from "./Badge";
import { ConfirmDialog } from "./ConfirmDialog";
import { DirectoryTable, type DirectoryColumn } from "./DirectoryTable";
import { ReportLayoutFormModal } from "./ReportLayoutFormModal";
import { RestoreOrgDefaultsButton } from "./RestoreOrgDefaultsButton";
import { Spinner } from "./Spinner";

type Dialog =
  | { kind: "create" }
  | { kind: "edit"; layout: ReportLayoutSummary }
  | { kind: "delete"; layout: ReportLayoutSummary }
  | { kind: "hide"; layout: ReportLayoutSummary };

/** @param api The calls, bound to an organisation or a project. */
export function ReportLayoutsPanel({ api }: { api: ReportLayoutApi }) {
  const strings = useStrings();
  const text = strings.reportLayouts;
  const { showToast } = useToast();
  const navigate = useNavigate();
  const [layouts, setLayouts] = useState<ReportLayoutSummary[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const inProject = api.scope.kind === "project";

  const reload = useCallback(async () => {
    try {
      setLayouts(await api.list());
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

  if (failed && !layouts) return <p className="text-muted" role="alert">{text.loadFailed}</p>;
  if (!layouts) return <Spinner />;

  const visible = layouts.filter((layout) => !layout.hidden);
  const hidden = layouts.filter((layout) => layout.hidden);

  async function copy(layout: ReportLayoutSummary) {
    await run(async () => {
      const created = await copyReportLayout(api, layout, text.copyName(layout.name));
      navigate(reportLayoutPath(api.scope, created.id));
      return text.copied;
    });
  }

  function menuFor(layout: ReportLayoutSummary): ActionMenuItem[] {
    const open: ActionMenuItem = {
      key: "open", label: layout.editable ? text.open : text.view, onSelect: () => navigate(reportLayoutPath(api.scope, layout.id)),
    };
    const makeCopy: ActionMenuItem = { key: "copy", label: text.makeCopy, onSelect: () => void copy(layout) };
    if (!layout.editable) {
      return [open, makeCopy, { key: "hide", label: text.hide, danger: true, onSelect: () => setDialog({ kind: "hide", layout }) }];
    }
    return [
      open,
      { key: "edit", label: text.editDetails, onSelect: () => setDialog({ kind: "edit", layout }) },
      makeCopy,
      { key: "delete", label: text.delete, danger: true, onSelect: () => setDialog({ kind: "delete", layout }) },
    ];
  }

  const columns: DirectoryColumn<ReportLayoutSummary>[] = [
    {
      key: "name",
      label: text.nameHeading,
      render: (layout) => (
        <span className="stack" style={{ gap: 0 }}>
          <span>{layout.name}</span>
          {layout.description && <span className="text-muted" style={{ fontSize: "0.85rem" }}>{layout.description}</span>}
        </span>
      ),
    },
    { key: "kind", label: text.kindHeading, render: (layout) => <Badge>{LAYOUT_FAMILY_LABEL[layout.family]}</Badge> },
    ...(inProject
      ? [{
        key: "shared",
        label: text.sharedHeading,
        render: (layout: ReportLayoutSummary) => (layout.origin === "project" ? null : <Badge>{LAYOUT_ORIGIN_LABEL[layout.origin]}</Badge>),
      }]
      : []),
    { key: "version", label: text.versionHeading, render: (layout) => layout.current_version },
    { key: "updated", label: text.updatedHeading, render: (layout) => new Date(layout.updated_at).toLocaleDateString() },
    {
      key: "actions",
      label: <span className="sr-only">{strings.common.moreOptions}</span>,
      render: (layout) => <ActionMenu triggerLabel={text.actionsFor(layout.name)} items={menuFor(layout)} />,
    },
  ];

  return (
    <div className="stack">
      <p className="text-muted" style={{ margin: 0 }}>{inProject ? text.projectDescription : text.orgDescription}</p>
      <div className="row">
        <button type="button" className="btn btn-primary" onClick={() => setDialog({ kind: "create" })}>{text.newLayout}</button>
        {api.addStarters && (
          <button
            type="button"
            className="btn"
            onClick={() => void run(async () => {
              const added = (await api.addStarters?.()) ?? [];
              return added.length > 0 ? text.startersAdded(added) : text.startersNone;
            })}
          >
            {text.addStarters}
          </button>
        )}
        {inProject && api.restore && (
          <RestoreOrgDefaultsButton
            hidden={hidden.map((layout) => ({ id: layout.id, name: layout.name }))}
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
        rowKey={(layout) => layout.id}
        rowHref={(layout) => reportLayoutPath(api.scope, layout.id)}
        emptyState={<p className="text-muted">{text.empty}</p>}
      />

      {dialog?.kind === "create" && (
        <ReportLayoutFormModal
          api={api}
          onClose={() => setDialog(null)}
          onSaved={(saved) => {
            showToast(text.created);
            navigate(reportLayoutPath(api.scope, saved.id));
          }}
        />
      )}
      {dialog?.kind === "edit" && (
        <ReportLayoutFormModal
          api={api}
          layout={dialog.layout}
          onClose={() => setDialog(null)}
          onSaved={() => {
            showToast(text.detailsSaved);
            void reload();
          }}
        />
      )}
      {dialog?.kind === "delete" && (
        <ConfirmDialog
          title={text.deleteTitle(dialog.layout.name)}
          message={text.deleteMessage(dialog.layout.current_version)}
          confirmLabel={text.delete}
          requireTypedText={dialog.layout.name}
          onCancel={() => setDialog(null)}
          onConfirm={() => {
            const layout = dialog.layout;
            setDialog(null);
            void run(async () => {
              await api.remove(layout.id);
              return text.deleted;
            });
          }}
        />
      )}
      {dialog?.kind === "hide" && (
        <ConfirmDialog
          title={text.hideTitle(dialog.layout.name)}
          message={text.hideMessage}
          confirmLabel={text.hideConfirm}
          onCancel={() => setDialog(null)}
          onConfirm={() => {
            const layout = dialog.layout;
            setDialog(null);
            void run(async () => {
              await api.setHidden?.(layout.id, true);
              return text.hidden;
            });
          }}
        />
      )}
    </div>
  );
}
