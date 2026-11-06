/**
 * Module: modules/product_feedback/RequestColumnChooser
 *
 * The Columns control of the request lists (the project list and the organisation inbox): the shared `ColumnChooser`
 * over the optional columns (status, demand and Pain Points on the project tier, owner, created, last updated and one score column per scoring model),
 * bound to the choice `useRequestListFilters` keeps per person. Code and title are always on.
 */
import type { ScoringScheme } from "../../api/scoring";
import { ColumnChooser } from "../../components/ColumnChooser";
import { modelShortName } from "./requestLevels";
import { scoreColumnId, type RequestListFilters } from "./requestListState";

/**
 * @param filters The list state, which holds the column choice.
 * @param scheme The scoring scheme in effect (the names of the score columns).
 */
export function RequestColumnChooser({ filters, scheme }: { filters: RequestListFilters; scheme: ScoringScheme | null }) {
  const modelLabel = (id: string) => {
    const model = scheme?.models.find((m) => scoreColumnId(m.key) === id);
    return model ? `Score (${modelShortName(model.label)})` : id;
  };
  const names: Record<string, string> = { status: "Status", demand: "Demand", pain_points: "Pain Points", owner: "Owner", created: "Created", updated: "Last updated" };
  return (
    <ColumnChooser
      columns={filters.columnIds.map((id) => ({ id, label: names[id] ?? modelLabel(id) }))}
      visible={filters.columns.visible} onToggle={filters.columns.toggle} onReset={filters.columns.reset}
      isDefault={filters.columns.isDefault} alwaysOn="Code and title"
    />
  );
}
