/**
 * Module: components/ReportPackEditor
 *
 * The editor of one report pack: its reports, its variables, its saved sets and its version history. One component
 * for an organisation's and a project's packs over `ReportPackApi`.
 *
 * Responsibilities:
 * - Load a pack and edit its definition as structured parts (`ReportPackEntriesEditor`, `ReportPackVariablesEditor`)
 *   held as one draft; Save sends the whole definition with the version the author started from, so a concurrent
 *   save is reported (409) instead of overwritten, and the server's positioned problems are listed.
 * - Hold Save back while a JSON box is invalid or nothing has changed; warn before leaving with unsaved changes.
 * - Show a pack shared from elsewhere read-only (with "make a copy"), while its saved sets can still be overridden
 *   for this project (`ReportPackSetsPanel`).
 *
 * Design decisions: the server is the only validator of a definition, so the client holds no rules beyond what the
 * pickers offer; the draft's client-only ids are dropped on save. Saved sets belong to the pack, not a version, so
 * saving a new version does not touch them.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { LAYOUT_ORIGIN_LABEL, reportLayoutApi, type ReportFieldCatalogue } from "../api/reportLayouts";
import {
  packProblems,
  reportPackPath,
  type ReportPackApi,
  type ReportPackDefinition,
  type ReportPackDetail,
  type ReportPackVersionSummary,
} from "../api/reportPacks";
import { reportsApi } from "../api/reports";
import { conflictVersion } from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useReportTemplates } from "../hooks/useReportTemplates";
import { canonicalJson, newUid, type LayoutChoice } from "../utils/reportPackDraft";
import { Badge } from "./Badge";
import { ConfirmDialog } from "./ConfirmDialog";
import { LabeledSelect } from "./LabeledSelect";
import { RecordHeader } from "./RecordHeader";
import { ReportPackEntriesEditor, type DraftEntry, type ReportChoice } from "./ReportPackEntriesEditor";
import { ReportPackFormModal } from "./ReportPackFormModal";
import { ReportPackSetsPanel } from "./ReportPackSetsPanel";
import { ReportPackVariablesEditor, type DraftVariable } from "./ReportPackVariablesEditor";
import { SaveVersionButton } from "./SaveVersionButton";
import { Spinner } from "./Spinner";
import { Tabs, tabPanelProps, type TabDef } from "./Tabs";

type Tab = "reports" | "variables" | "sets" | "history";
type Dialog = "details" | "delete" | "reload" | "leave";

/** The definition a draft stands for (client ids dropped, empty parts left out). */
function definitionOf(entries: DraftEntry[], variables: DraftVariable[], template: string): ReportPackDefinition {
  const out: ReportPackDefinition = { schema_version: 1, entries: entries.map((d) => d.entry) };
  if (variables.length > 0) out.variables = variables.map((d) => d.variable);
  if (template) out.template = template;
  return out;
}

/** The comparable form of a definition (so key order never makes a pack look changed). */
function signature(definition: ReportPackDefinition): string {
  return canonicalJson({ ...definition, variables: definition.variables ?? [], template: definition.template ?? "" });
}

/**
 * @param api The calls bound to the scope the pack belongs to.
 * @param packId The pack.
 * @param backTo Where Back leads (Report setup of Project Admin, Templates & reports of Org Admin).
 */
export function ReportPackEditor({ api, packId, backTo }: { api: ReportPackApi; packId: string; backTo: string }) {
  const strings = useStrings();
  const text = strings.reportPacks;
  const { showToast } = useToast();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<ReportPackDetail | null>(null);
  const [loadFailed, setLoadFailed] = useState<string | null>(null);
  const [entries, setEntries] = useState<DraftEntry[]>([]);
  const [variables, setVariables] = useState<DraftVariable[]>([]);
  const [template, setTemplate] = useState("");
  const [tab, setTab] = useState<Tab>("reports");
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [problems, setProblems] = useState<string[]>([]);
  const [invalid, setInvalid] = useState<Set<string>>(new Set());
  const [layouts, setLayouts] = useState<LayoutChoice[]>([]);
  const [reports, setReports] = useState<ReportChoice[]>([]);
  const [catalogue, setCatalogue] = useState<ReportFieldCatalogue | null>(null);
  const [versions, setVersions] = useState<ReportPackVersionSummary[] | null>(null);
  const templates = useReportTemplates(detail?.organization_id);
  const inProject = api.scope.kind === "project";

  const load = useCallback(async () => {
    try {
      const loaded = await api.get(packId);
      const definition = loaded.current.definition;
      setDetail(loaded);
      setEntries(definition.entries.map((entry) => ({ uid: newUid(), entry })));
      setVariables((definition.variables ?? []).map((variable) => ({ uid: newUid(), variable })));
      setTemplate(definition.template ?? "");
      setConflict(false);
      setProblems([]);
      setInvalid(new Set());
      setLoadFailed(null);
      setVersions(null);
    } catch (err) {
      setLoadFailed(toErrorMessage(err, strings.common.error));
    }
  }, [api, packId, strings.common.error]);

  const loadTools = useCallback(async () => {
    const layoutCalls = reportLayoutApi(api.scope);
    const catalogueLoad = api.scope.kind === "project" ? reportsApi.projectCatalogue(api.scope.id) : reportsApi.orgCatalogue(api.scope.id);
    const [layoutList, entriesList, fields] = await Promise.allSettled([layoutCalls.list(), catalogueLoad, layoutCalls.fields()]);
    if (layoutList.status === "fulfilled") {
      setLayouts(layoutList.value.filter((l) => !l.hidden).map((l) => ({ name: l.name, family: l.family })));
    }
    if (entriesList.status === "fulfilled") {
      setReports(entriesList.value.filter((e) => e.module_key !== "custom_reports").map((e) => ({
        module_key: e.module_key, report: e.key, title: `${e.module_name}: ${e.title}`,
      })));
    }
    if (fields.status === "fulfilled") setCatalogue(fields.value);
  }, [api.scope]);

  useLoadOnChange(load, [api.scope.kind, api.scope.id, packId]);
  useLoadOnChange(loadTools, [api.scope.kind, api.scope.id]);

  const definition = useMemo(() => definitionOf(entries, variables, template), [entries, variables, template]);
  const dirty = detail !== null && signature(definition) !== signature(detail.current.definition);

  useEffect(() => {
    if (!dirty) return undefined;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  useEffect(() => {
    if (tab !== "history" || versions !== null) return;
    api.versions(packId).then(setVersions, () => setVersions([]));
  }, [tab, versions, api, packId]);

  if (loadFailed && !detail) return <p className="text-muted" role="alert">{loadFailed}</p>;
  if (!detail) return <Spinner />;

  const editable = detail.editable;
  const originLabel = LAYOUT_ORIGIN_LABEL[detail.origin];

  /** Saves the definition on screen as a new version with `note`; resolves to whether a version was stored. */
  async function save(note: string): Promise<boolean> {
    if (!detail) return false;
    setSaving(true);
    setProblems([]);
    try {
      const result = await api.save(packId, { definition, base_version: detail.current_version, comment: note });
      showToast(result.current_version === detail.current_version ? text.noChanges : text.saved(result.current_version));
      setDetail(result);
      setVersions(null);
      return true;
    } catch (err) {
      const newer = conflictVersion(err);
      const found = packProblems(err);
      if (newer !== null) setConflict(true);
      else if (found.length > 0) setProblems(found.map((p) => text.problem(p.path, p.message)));
      else showToast(toErrorMessage(err, text.saveFailed), "error");
      return false;
    } finally {
      setSaving(false);
    }
  }

  function leave() {
    if (dirty) setDialog("leave");
    else navigate(backTo);
  }

  async function makeCopy() {
    if (!detail) return;
    try {
      const created = await api.create({
        name: text.copyName(detail.name), description: detail.description, definition: detail.current.definition,
      });
      showToast(text.copied);
      navigate(reportPackPath(api.scope, created.id));
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  function setValidity(key: string, valid: boolean) {
    setInvalid((current) => {
      const next = new Set(current);
      if (valid) next.delete(key);
      else next.add(key);
      return next.size === current.size && [...next].every((k) => current.has(k)) ? current : next;
    });
  }

  const tabs: TabDef<Tab>[] = [
    { key: "reports", label: text.reportsTab },
    { key: "variables", label: text.variablesTab },
    { key: "sets", label: text.setsTab },
    { key: "history", label: text.historyTab },
  ];

  return (
    <div className="stack">
      <RecordHeader
        recordLabel={text.recordLabel}
        title={detail.name}
        subtitle={detail.description || undefined}
        badges={
          <>
            {detail.origin !== "project" && inProject && <Badge>{originLabel}</Badge>}
            {dirty && <Badge tone="warning">{text.unsaved}</Badge>}
          </>
        }
        version={detail.current_version}
        back={{ onClick: leave, label: text.backToList }}
        onEdit={editable ? () => setDialog("details") : undefined}
        actions={[
          { key: "copy", label: text.makeCopy, onSelect: () => void makeCopy() },
          editable && { key: "delete", label: text.delete, danger: true, onSelect: () => setDialog("delete") },
        ]}
      />

      <Tabs idPrefix="report-pack" tabs={tabs} active={tab} onChange={setTab} />

      {!editable && tab !== "sets" && (
        <div className="card" role="note"><span className="text-muted">{text.readOnlyNotice(originLabel.toLowerCase())}</span></div>
      )}
      {conflict && (
        <div className="card stack" role="alert">
          <span style={{ color: "var(--color-danger)" }}>{text.conflict}</span>
          <div><button type="button" className="btn" onClick={() => setDialog("reload")}>{text.reload}</button></div>
        </div>
      )}
      {problems.length > 0 && (
        <div className="card stack" role="alert">
          <strong>{text.problemsHeading}</strong>
          <ul style={{ margin: 0 }}>{problems.map((p) => <li key={p}>{p}</li>)}</ul>
        </div>
      )}

      {tab === "reports" && (
        <div {...tabPanelProps("report-pack", "reports")} className="stack">
          {editable && templates.length > 0 && (
            <LabeledSelect help={strings.help.reportPackTemplate}
              label={text.templateLabel}
              value={template}
              onChange={setTemplate}
              options={templates.map((t) => ({ value: t.name, label: t.name }))}
              placeholder={text.templatePlaceholder}
            />
          )}
          <ReportPackEntriesEditor
            entries={entries} onChange={setEntries} layouts={layouts} reports={reports} inProject={inProject}
            disabled={!editable} onValidity={setValidity}
          />
        </div>
      )}
      {tab === "variables" && (
        <div {...tabPanelProps("report-pack", "variables")}>
          <ReportPackVariablesEditor variables={variables} onChange={setVariables} catalogue={catalogue} disabled={!editable} />
        </div>
      )}
      {tab === "sets" && (
        <div {...tabPanelProps("report-pack", "sets")}>
          <ReportPackSetsPanel api={api} packId={packId} />
        </div>
      )}
      {tab === "history" && (
        <div {...tabPanelProps("report-pack", "history")}>
          {versions === null ? <Spinner /> : versions.length === 0 ? <p className="text-muted">{text.historyEmpty}</p> : (
            <table aria-label={text.historyTab}>
              <thead>
                <tr><th>{text.historyVersion}</th><th>{text.historyNote}</th><th>{text.historySaved}</th></tr>
              </thead>
              <tbody>
                {versions.map((v) => (
                  <tr key={v.version}>
                    <td>{v.version}</td>
                    <td>{v.comment}</td>
                    <td>{new Date(v.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {editable && (tab === "reports" || tab === "variables") && (
        <div className="row" style={{ alignItems: "flex-end", flexWrap: "wrap" }}>
          <SaveVersionButton disabled={!dirty || invalid.size > 0} saving={saving} onSave={save} />
          {invalid.size > 0 && <span className="text-muted">{text.needsInvalidFix}</span>}
        </div>
      )}

      {dialog === "details" && (
        <ReportPackFormModal
          api={api}
          pack={detail}
          onClose={() => setDialog(null)}
          onSaved={() => {
            showToast(text.detailsSaved);
            void load();
          }}
        />
      )}
      {dialog === "delete" && (
        <ConfirmDialog
          title={text.deleteTitle(detail.name)}
          message={text.deleteMessage(detail.current_version)}
          confirmLabel={text.delete}
          requireTypedText={detail.name}
          onCancel={() => setDialog(null)}
          onConfirm={() => {
            setDialog(null);
            void api.remove(packId).then(
              () => { showToast(text.deleted); navigate(backTo); },
              (err) => showToast(toErrorMessage(err, strings.common.error), "error"),
            );
          }}
        />
      )}
      {dialog === "reload" && (
        <ConfirmDialog
          title={text.reloadTitle}
          message={text.reloadMessage}
          confirmLabel={text.reload}
          onCancel={() => setDialog(null)}
          onConfirm={() => { setDialog(null); void load(); }}
        />
      )}
      {dialog === "leave" && (
        <ConfirmDialog
          title={text.leaveTitle}
          message={text.leaveMessage}
          confirmLabel={text.leaveConfirm}
          onCancel={() => setDialog(null)}
          onConfirm={() => { setDialog(null); navigate(backTo); }}
        />
      )}
    </div>
  );
}
