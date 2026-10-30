/**
 * Module: components/ReportDuplicateDialog
 *
 * The dialog that duplicates one report layout or pack, or starts a layout from a built-in starter, as an editable basis
 * for a new report: a name, and (in a project) where the copy goes (this project, or up to the organisation).
 *
 * Responsibilities:
 * - Ask the server for the plan as the form changes (a dry run, debounced): the name it suggests, whether the name is
 *   taken or shadows an inherited report, what does not carry cleanly, and any project picture that blocks a copy up.
 * - Create the copy and hand the result to the caller, which opens it.
 *
 * Design decisions: the server decides every rule (names, folders, pictures, permissions); the dialog only shows the plan,
 * so the preview and the copy cannot disagree. A person who lacks the organisation's right sees the server's refusal
 * when they pick that destination, rather than a guess made here. Follows the form header pattern (`FormActions` in the
 * dialog header) and the required-field and field-help patterns.
 */
import { useEffect, useRef, useState } from "react";

import {
  DUPLICATE_ORIGIN_LABEL, DUPLICATE_TARGET_LABEL, type DuplicateKind, type DuplicateRequest, type DuplicateResult, type DuplicateTarget,
  type ReportDuplicateApi, type ReportStarter,
} from "../api/reportDuplicate";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { FormActions } from "./FormActions";
import { TextField } from "./FormFields";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";
import { Spinner } from "./Spinner";

/** What is being duplicated: a layout or pack the scope can reach, or a built-in starter (chosen in the dialog when no key). */
export type DuplicateSource =
  | { kind: "layout" | "pack"; id: string; name: string }
  | { kind: "starter"; key?: string };

const PLAN_DELAY_MS = 250;

/** The call for a source: a starter is named by key, a layout or pack by id; an empty name leaves the suggestion to the server. */
function buildRequest(
  kind: DuplicateKind, sourceId: string, starterKey: string, target: DuplicateTarget, name: string, dryRun: boolean,
): DuplicateRequest {
  return {
    kind, target, dry_run: dryRun,
    ...(kind === "starter" ? { starter_key: starterKey } : { source_id: sourceId }),
    ...(name ? { name } : {}),
  };
}

/**
 * @param api The calls, bound to the organisation or project the person is working in.
 * @param source What to duplicate.
 * @param note A line shown above the form (the designer says unsaved edits are not copied).
 * @param onClose Called by Cancel.
 * @param onDuplicated Called with the created copy; the caller opens it.
 */
export function ReportDuplicateDialog({
  api, source, note, onClose, onDuplicated,
}: {
  api: ReportDuplicateApi; source: DuplicateSource; note?: string; onClose: () => void; onDuplicated: (result: DuplicateResult) => void;
}) {
  const text = useStrings().reportDuplicate;
  const strings = useStrings();
  const { showToast } = useToast();
  const inProject = api.scope.kind === "project";
  const isStarter = source.kind === "starter";
  const [starters, setStarters] = useState<ReportStarter[] | null>(null);
  const [starterKey, setStarterKey] = useState(source.kind === "starter" ? (source.key ?? "") : "");
  const [target, setTarget] = useState<DuplicateTarget>(inProject ? "project" : "organization");
  const [name, setName] = useState("");
  const [nameEdited, setNameEdited] = useState(false);
  const typed = (value: boolean) => { edited.current = value; setNameEdited(value); };
  const [plan, setPlan] = useState<DuplicateResult | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const latest = useRef(0);
  /** Whether the person has typed a name (read inside the plan effect without re-running it). */
  const edited = useRef(false);

  useEffect(() => {
    if (!isStarter) return;
    let cancelled = false;
    api.starters().then((found) => { if (!cancelled) setStarters(found); }, () => { if (!cancelled) setPlanError(text.startersFailed); });
    return () => { cancelled = true; };
  }, [api, isStarter, text.startersFailed]);

  const ready = !isStarter || starterKey !== "";
  const kind = source.kind;
  const sourceId = source.kind === "starter" ? "" : source.id;
  /** What the server is asked to plan with: the typed name, else nothing, so it suggests one. */
  const askedName = nameEdited ? name.trim() : "";

  useEffect(() => {
    if (!ready) return;
    const ticket = ++latest.current;
    const timer = window.setTimeout(() => {
      api.duplicate(buildRequest(kind, sourceId, starterKey, target, askedName, true)).then(
        (found) => {
          if (ticket !== latest.current) return;
          setPlan(found);
          setPlanError(null);
          if (!edited.current) setName(found.name);
        },
        (err) => {
          if (ticket !== latest.current) return;
          setPlan(null);
          setPlanError(toErrorMessage(err, text.planFailed));
        },
      );
    }, PLAN_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [api, ready, kind, sourceId, starterKey, target, askedName, text.planFailed]);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const done = await api.duplicate(buildRequest(kind, sourceId, starterKey, target, name.trim(), false));
      showToast(text.created);
      onDuplicated(done);
    } catch (err) {
      setError(toErrorMessage(err, text.failed));
    } finally {
      setBusy(false);
    }
  }

  const noun = source.kind === "pack" ? text.pack : text.layout;
  const title = source.kind === "starter" ? text.starterTitle : text.title(noun);
  const trimmed = name.trim();
  const blocked = (plan?.blocked_images.length ?? 0) > 0;
  const chosenStarter = starters?.find((s) => s.key === starterKey);
  const canCreate = !busy && plan !== null && trimmed !== "" && !plan.name_taken && !blocked && planError === null;
  return (
    <Modal title={title} onClose={onClose}>
      <div className="stack">
        <FormActions
          error={error} onCancel={onClose} onSave={() => void create()} saveLabel={busy ? text.creating : text.createButton}
          saveDisabled={!canCreate} cancelDisabled={busy}
        />
        {note && <p className="text-muted" role="note" style={{ margin: 0 }}>{note}</p>}
        {source.kind !== "starter" && (
          <p className="text-muted" style={{ margin: 0 }}>
            {text.from(source.name, DUPLICATE_ORIGIN_LABEL[plan?.origin ?? ""] ?? "")}
          </p>
        )}
        <p className="text-muted" style={{ margin: 0 }}>{text.intro}</p>
        {source.kind === "starter" && (
          <LabeledSelect
            required label={text.starterLabel} value={starterKey} onChange={(value) => { setStarterKey(value); typed(false); }}
            placeholder={text.starterPlaceholder} disabled={starters === null} helpNotNeeded hint={chosenStarter?.description}
            options={(starters ?? []).map((s) => ({ value: s.key, label: s.name }))}
          />
        )}
        {inProject && (
          <LabeledSelect
            label={text.targetLabel} help={strings.help.reportDuplicateTarget} value={target} placeholder={null}
            onChange={(value: string) => setTarget(value as DuplicateTarget)}
            options={(Object.keys(DUPLICATE_TARGET_LABEL) as DuplicateTarget[]).map((key) => ({ value: key, label: DUPLICATE_TARGET_LABEL[key] }))}
          />
        )}
        <TextField
          required label={text.nameLabel} value={name} helpNotNeeded disabled={!ready}
          onChange={(value) => { setName(value); typed(true); }}
        />
        {ready && plan === null && planError === null && <Spinner />}
        {planError && <p role="alert" style={{ margin: 0, color: "var(--color-danger)" }}>{planError}</p>}
        {plan?.name_taken && <p role="alert" style={{ margin: 0, color: "var(--color-danger)" }}>{text.nameTaken(noun)}</p>}
        {blocked && plan && (
          <div role="alert" className="stack" style={{ gap: "var(--space-1)", color: "var(--color-danger)" }}>
            <span>{text.blockedImages}</span>
            <ul style={{ margin: 0 }}>{plan.blocked_images.map((file) => <li key={file}>{file}</li>)}</ul>
          </div>
        )}
        {plan?.warnings.map((warning) => <p key={warning} className="text-muted" style={{ margin: 0 }}>{warning}</p>)}
      </div>
    </Modal>
  );
}
