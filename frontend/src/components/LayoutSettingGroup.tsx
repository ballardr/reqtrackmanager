/**
 * Module: components/LayoutSettingGroup
 *
 * One group of a layout's settings (Page, Margins, Header, Footer, Look ...), drawn the same way in the Blocks
 * view's layout panel and the text view's page setup dialog. Arrangement only: the fields are the callers', and the
 * group table and counts live in `utils/reportLayoutSettingGroups`.
 *
 * Each group is a closed-by-default `CollapsibleSection` (state remembered per person under
 * `layoutSettings:<group>`; Page and Margins start open on a layout not yet published beyond its first version).
 * Its bar shows an "N changed" pill or the group's own `summary`, an accent edge when a setting is not at its
 * default, and a danger "N problems" pill that holds the group open when the server reported a problem inside it.
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
