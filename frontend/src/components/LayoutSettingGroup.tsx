/**
 * Module: components/LayoutSettingGroup
 *
 * One group of a layout's settings (Page, Margins, Header, Footer, Look, …), drawn the same way in the Blocks view's
 * layout panel and in the text view's page setup dialog.
 *
 * Responsibilities: every group is a closed-by-default `CollapsibleSection` (state remembered per person under
 * `layoutSettings:<group>`; Page and Margins start open on a layout not yet published beyond its first version) whose
 * bar says what it holds: an "N changed" pill, or the group's own `summary` where it always has a value (the page
 * size), with an accent edge when a setting is not at its default, and a danger "N problems" pill that also holds the
 * group open when the server reported a problem inside it.
 *
 * Design decisions: arrangement only. The fields inside are the callers' own, so the same group is the same set in both
 * places; the group table and the counts live in `utils/reportLayoutSettingGroups`.
 */
import type { ReactNode } from "react";

import { useStrings } from "../context/TerminologyContext";
import { LAYOUT_SETTING_GROUPS, layoutGroupSummary, type LayoutSettingGroupKey } from "../utils/reportLayoutSettingGroups";
import { SettingGroup } from "./SettingGroup";

/**
 * @param group Which group this is.
 * @param changed How many of its settings differ from their defaults.
 * @param summary The pill text in place of the "N changed" count (the effective page size, the margins).
 * @param newLayout Whether the layout is new, which opens the groups that `opensOnNewLayout`.
 * @param problems How many server problems are about its settings (holds it open).
 * @param children The group's fields.
 */
export function LayoutSettingGroup({
  group, changed = 0, summary: given, newLayout = false, problems = 0, children,
}: {
  group: LayoutSettingGroupKey;
  changed?: number;
  summary?: string;
  newLayout?: boolean;
  problems?: number;
  children: ReactNode;
}) {
  const text = useStrings().pageSetup;
  const opensOnNewLayout = LAYOUT_SETTING_GROUPS.find((g) => g.key === group)?.opensOnNewLayout ?? false;
  const summary = given ?? layoutGroupSummary(group, changed, { changed: text.groupChanged, pageStyles: text.groupPageStyles });
  return (
    <SettingGroup
      sectionKey={`layoutSettings:${group}`} title={text.groups[group]} changed={changed} summary={summary}
      defaultOpen={newLayout && opensOnNewLayout} problems={problems}
    >
      {children}
    </SettingGroup>
  );
}
