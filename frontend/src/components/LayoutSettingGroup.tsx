/**
 * Module: components/LayoutSettingGroup
 *
 * One group of a layout's settings (Page, Header and footer, Look, …), drawn the same way in the Blocks view's layout
 * panel and in the text view's page setup dialog.
 *
 * Responsibilities: the basic `page` group is a plain heading that is always open; every other group is a closed-by-default
 * `CollapsibleSection` (state remembered per person under `layoutSettings:<group>`) whose bar says what it holds: an
 * "N changed" pill with an accent edge when a setting is not at its default, and a danger "N problems" pill that also
 * holds the group open when the server reported a problem inside it.
 *
 * Design decisions: arrangement only. The fields inside are the callers' own, so the same group is the same set in both
 * places; the group table and the counts live in `utils/reportLayoutSettingGroups`.
 */
import type { ReactNode } from "react";

import { useStrings } from "../context/TerminologyContext";
import { LAYOUT_SETTING_GROUPS, layoutGroupSummary, type LayoutSettingGroupKey } from "../utils/reportLayoutSettingGroups";
import { CollapsibleSection } from "./CollapsibleSection";

/**
 * @param group Which group this is.
 * @param changed How many of its settings differ from their defaults.
 * @param problems How many server problems are about its settings (holds it open).
 * @param children The group's fields.
 */
export function LayoutSettingGroup({
  group, changed = 0, problems = 0, children,
}: {
  group: LayoutSettingGroupKey;
  changed?: number;
  problems?: number;
  children: ReactNode;
}) {
  const text = useStrings().pageSetup;
  const title = text.groups[group];
  const arrangement = LAYOUT_SETTING_GROUPS.find((g) => g.key === group);
  if (!arrangement?.collapsible) {
    return (
      <div className="stack">
        <h3 style={{ margin: 0 }}>{title}</h3>
        {children}
      </div>
    );
  }
  const summary = problems > 0
    ? text.groupProblem(problems)
    : layoutGroupSummary(group, changed, { changed: text.groupChanged, pageStyles: text.groupPageStyles });
  return (
    <CollapsibleSection
      sectionKey={`layoutSettings:${group}`} title={title} variant="plain" defaultCollapsed={!arrangement.startsOpen}
      summary={summary} marked={changed > 0} forceOpen={problems > 0}
    >
      {children}
    </CollapsibleSection>
  );
}
