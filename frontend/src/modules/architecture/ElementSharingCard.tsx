/**
 * Module: modules/architecture/ElementSharingCard
 *
 * The "Sharing" card of an element's page: for an element this project owns, the collections it is a member of (and so who
 * can use it) with controls to add it to another collection or take it out of one; for an element another owner shares
 * with the project, a plain statement that it is read-only here. A collection's grants are managed on the Sharing page, so
 * the card only names each collection and links to it. Only collections the element is a direct member of are listed: an
 * element also reaches people through a collection holding one of its ancestors, which the tree on the Elements page
 * shows.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { DetailCard } from "../../components/DetailCard";
import { InlineSelect } from "../../components/LabeledSelect";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectCollectionApi } from "./api";
import type { ArchitectureCollection, ArchitectureElement } from "./types";

interface Membership {
  collection: ArchitectureCollection;
  isMember: boolean;
}

/**
 * @param projectId The project whose collections are read.
 * @param element The element shown.
 */
export function ElementSharingCard({ projectId, element }: { projectId: string; element: ArchitectureElement }) {
  const { showToast } = useToast();
  const calls = useMemo(() => projectCollectionApi(projectId), [projectId]);
  const [memberships, setMemberships] = useState<Membership[] | null>(null);
  const [refresh, setRefresh] = useState(0);
  const reload = useCallback(() => setRefresh((n) => n + 1), []);
  const owned = !element.shared && element.project_id === projectId;

  useEffect(() => {
    if (!owned) return;
    let live = true;
    (async () => {
      const collections = await calls.list();
      const found = await Promise.all(collections.map(async (collection) => ({
        collection,
        isMember: (await calls.members(collection.id)).some((m) => m.element_id === element.id),
      })));
      if (live) setMemberships(found);
    })().catch(() => { if (live) setMemberships([]); });
    return () => { live = false; };
  }, [calls, element.id, owned, refresh]);

  async function change(action: () => Promise<unknown>, done: string) {
    try {
      await action();
      showToast(done);
      reload();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not change the sharing."), "error");
    }
  }

  if (!owned) {
    return (
      <DetailCard heading="Sharing">
        <p className="text-muted" style={{ margin: 0 }}>
          This element is owned by {element.organization_id ? "the organisation" : "another project"} and shared with this project. It can be
          placed in diagrams, connected to and linked here, but only its owner changes it.
        </p>
      </DetailCard>
    );
  }
  if (memberships === null) return <DetailCard heading="Sharing"><Spinner /></DetailCard>;
  const inCollections = memberships.filter((m) => m.isMember);
  const others = memberships.filter((m) => !m.isMember);

  return (
    <DetailCard heading="Sharing" action={<Link to={`/projects/${projectId}/modules/architecture/sharing`}>Manage collections</Link>}>
      {inCollections.length === 0 ? <p className="text-muted" style={{ margin: 0 }}>Not in any collection, so not shared.</p> : (
        <ul style={{ margin: 0, paddingLeft: 0, listStyle: "none" }} className="stack">
          {inCollections.map(({ collection }) => (
            <li key={collection.id} className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
              <span>{collection.name} · {collection.grant_count} {collection.grant_count === 1 ? "grant" : "grants"}</span>
              <button
                className="btn btn-sm" aria-label={`Remove from ${collection.name}`}
                onClick={() => void change(() => calls.removeMember(collection.id, element.id), "Element removed from the collection.")}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
      {others.length > 0 && (
        <InlineSelect
          ariaLabel="Add to a collection" value="" placeholder="Add to a collection…" autoWidth
          options={others.map(({ collection }) => ({ value: collection.id, label: collection.name }))}
          onChange={(next) => next && void change(() => calls.addMembers(next, [element.id]), "Element added to the collection.")}
        />
      )}
    </DetailCard>
  );
}
