/**
 * Module: components/ScoringAxisLevels
 *
 * The "Levels" block shared by the organisation `ScoringSchemeEditor` and the project `ProjectScoringSettings`
 * (generic scoring-matrix core): one collapsible block per axis (folded by default, remembered per person) holding
 * that axis's levels as a labelled grid. An axis the tier may edit shows the editable `DefinitionList` grid (name,
 * weight, guidance, and a threshold on a derived axis); any other axis (an organisation axis seen from a project)
 * shows the same columns read-only, so nothing looks editable that is not.
 *
 * The caller supplies the three level calls for its tier and `onChanged` (to re-fetch the scheme); every mutation
 * reports its outcome through the shared toast, a failure staying in the list's own error line.
 */
import { useToast } from "../context/ToastContext";
import { scoringOriginLabel, type ScoringAxis, type ScoringLevel, type ScoringScheme } from "../api/scoring";
import { Badge } from "./Badge";
import { CollapsibleSection } from "./CollapsibleSection";
import { DefinitionList } from "./DefinitionList";
import { levelFields, parseLevel } from "./scoringLevelFields";

/** The level calls of one tier (organisation or project); `body` is `parseLevel`'s result. */
export interface ScoringLevelCalls {
  create: (axisKey: string, body: ReturnType<typeof parseLevel>) => Promise<unknown>;
  update: (levelId: string, body: ReturnType<typeof parseLevel>) => Promise<unknown>;
  remove: (levelId: string, reassignToId?: string) => Promise<unknown>;
}

/** A level's columns, read-only, in the same grid as the editable list. */
function ReadOnlyLevels({ axis }: { axis: ScoringAxis }) {
  const derived = !!axis.derived_source;
  const columns = `minmax(10rem, 1.5fr) 6.5rem ${derived ? "6.5rem " : ""}minmax(12rem, 3fr)`;
  return (
    <div className="definition-grid" style={{ gridTemplateColumns: columns }}>
      <span className="definition-grid__head">Level</span>
      <span className="definition-grid__head">Weight</span>
      {derived && <span className="definition-grid__head">From</span>}
      <span className="definition-grid__head">Guidance</span>
      {axis.levels.map((level: ScoringLevel) => (
        <div key={level.id} style={{ display: "contents" }}>
          <span className="definition-grid__cell">{level.name}</span>
          <span className="definition-grid__cell">{level.weight}</span>
          {derived && <span className="definition-grid__cell">{level.threshold ?? ""}</span>}
          <span className="definition-grid__cell text-muted">{level.description ?? ""}</span>
        </div>
      ))}
    </div>
  );
}

/**
 * @param scheme The tier's effective scheme.
 * @param calls The tier's level calls.
 * @param onChanged Called after each successful change, to re-fetch the scheme.
 * @param projectId The project being edited; omit for the organisation (which may edit every axis it sees).
 */
export function ScoringAxisLevels({
  scheme, calls, onChanged, projectId,
}: {
  scheme: ScoringScheme;
  calls: ScoringLevelCalls;
  onChanged: () => void;
  projectId?: string;
}) {
  const { showToast } = useToast();
  return (
    <div className="stack" style={{ gap: "var(--space-3)" }}>
      {scheme.axes.map((axis) => {
        const editable = !projectId || (axis.origin === "project" && axis.owner_project_id === projectId);
        const origin = axis.origin && axis.origin !== "built_in" ? scoringOriginLabel(axis.origin, axis.owner_project_id, projectId) : null;
        return (
          <CollapsibleSection
            key={axis.key} variant="plain" defaultCollapsed sectionKey={`sc_lv:${scheme.key}:${projectId ? "p" : "o"}:${axis.key}`}
            title={<span className="row" style={{ gap: "var(--space-2)" }}>{axis.label}{origin && <Badge>{origin}</Badge>}</span>}
            summary={`${axis.levels.length} levels`}
          >
            {axis.description && <span className="text-muted">{axis.description}</span>}
            {axis.derived_source && (
              <span className="text-muted">
                Worked out from demand: a record lands in the highest level whose threshold its value reaches. A level chosen by hand wins.
              </span>
            )}
            {editable ? (
              <DefinitionList<ScoringLevel>
                layout="grid"
                items={axis.levels}
                minItems={2}
                fields={levelFields(axis)}
                getReassignLabel={(l) => l.name}
                onRename={async (id, values) => {
                  await calls.update(id, parseLevel(values, !!axis.derived_source));
                  showToast("Level saved.");
                  onChanged();
                }}
                onAdd={async (values) => {
                  await calls.create(axis.key, parseLevel(values, !!axis.derived_source));
                  showToast("Level added.");
                  onChanged();
                }}
                onDelete={async (id, reassignToId) => {
                  await calls.remove(id, reassignToId);
                  showToast("Level deleted.");
                  onChanged();
                }}
                deleteLabel={`Delete ${axis.label} level`}
                addLabel={`Add ${axis.label} level`}
              />
            ) : (
              <ReadOnlyLevels axis={axis} />
            )}
          </CollapsibleSection>
        );
      })}
    </div>
  );
}
