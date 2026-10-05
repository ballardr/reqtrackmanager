/**
 * Module: modules/stakeholders/RepresentationPanel
 *
 * The "represents Persona" links (Phase 0 resolution 12), shown from either
 * end on the detail pages: a Stakeholder's "Represents" list (editable: pick a
 * Persona to add, remove one) and a Persona's "Represented by" list
 * (read-only: the link is owned from the Stakeholder side). One component for
 * both so the two ends can't drift; only the heading, the link target and
 * whether `edit` is passed differ.
 *
 * The panel loads its own list and renders nothing if that load fails: the
 * links ride on the *other* artefact's sub-component, so an org that switched
 * Stakeholders (or Personas) off simply doesn't see the panel rather than an
 * error. Adding and removing each give a toast; removal sits behind a tier-1
 * `ConfirmDialog` (docs/ux-style-guide.md "confirmation, in two tiers").
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ConfirmDialog } from "../../components/ConfirmDialog";
import { LabeledSelect } from "../../components/LabeledSelect";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import type { RepresentedLink } from "./types";

/** What makes a panel editable: the candidates to add and the two mutations. */
export interface RepresentationEdit {
  /** Everything that could be linked; already-linked ones are filtered out. */
  options: { value: string; label: string }[];
  /** Accessible name and visible label of the add picker, e.g. "Persona to represent". */
  pickerLabel: string;
  onAdd: (id: string) => Promise<void>;
  onRemove: (link: RepresentedLink) => Promise<void>;
}

export function RepresentationPanel({
  heading,
  emptyText,
  load,
  linkFor,
  edit,
  reloadKey,
}: {
  heading: string;
  emptyText: string;
  load: () => Promise<RepresentedLink[]>;
  /** Route of a linked record's own detail page. */
  linkFor: (link: RepresentedLink) => string;
  edit?: RepresentationEdit;
  /** Change to force a reload from outside. */
  reloadKey?: number;
}) {
  const { showToast } = useToast();
  const [links, setLinks] = useState<RepresentedLink[] | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [picked, setPicked] = useState("");
  const [removing, setRemoving] = useState<RepresentedLink | null>(null);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let active = true;
    load()
      .then((rows) => {
        if (!active) return;
        setLinks(rows);
        setUnavailable(false);
      })
      .catch(() => {
        if (active) setUnavailable(true);
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh, reloadKey]);

  if (unavailable || links === null) return null;

  const linkedIds = new Set(links.map((l) => l.id));
  const candidates = edit?.options.filter((o) => !linkedIds.has(o.value)) ?? [];

  async function mutate(action: () => Promise<void>, success: string, failure: string) {
    try {
      await action();
      showToast(success);
      setRefresh((n) => n + 1);
    } catch (err) {
      showToast(toErrorMessage(err, failure), "error");
    }
  }

  return (
    <div className="stack" style={{ gap: "0.35rem" }}>
      <span className="text-muted" style={{ fontSize: "0.8rem", fontWeight: 600 }}>{heading}</span>
      {links.length === 0 ? (
        <span className="text-muted">{emptyText}</span>
      ) : (
        <ul style={{ margin: 0, paddingLeft: "1.25rem" }}>
          {links.map((l) => (
            <li key={l.link_id}>
              <Link to={linkFor(l)}>{l.name}</Link>
              {edit && (
                <button className="btn" style={{ marginLeft: "0.5rem" }} aria-label={`Remove ${l.name}`} onClick={() => setRemoving(l)}>
                  Remove
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {edit && (
        <div className="row" style={{ gap: "0.5rem", alignItems: "flex-end" }}>
          <LabeledSelect label={edit.pickerLabel} value={picked} onChange={setPicked} options={candidates} placeholder="Choose…" />
          <button
            className="btn"
            disabled={!picked}
            onClick={async () => {
              const id = picked;
              setPicked("");
              await mutate(() => edit.onAdd(id), "Link added.", "Could not add the link.");
            }}
          >
            Add
          </button>
        </div>
      )}
      {edit && removing && (
        <ConfirmDialog
          title={`Remove ${removing.name}?`}
          message="The two records stay; only the link between them is removed."
          confirmLabel="Remove"
          onConfirm={async () => {
            const link = removing;
            setRemoving(null);
            await mutate(() => edit.onRemove(link), "Link removed.", "Could not remove the link.");
          }}
          onCancel={() => setRemoving(null)}
        />
      )}
    </div>
  );
}
