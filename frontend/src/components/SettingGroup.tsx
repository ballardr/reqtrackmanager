/**
 * Module: components/SettingGroup
 *
 * One collapsible group of settings (a layout's Header, a custom table's Borders), the same bar wherever a form is
 * arranged in groups.
 *
 * Responsibilities: a closed-by-default `CollapsibleSection` (state remembered per person under `sectionKey`) whose
 * bar says what it holds: the given `summary`, else an "N changed" pill, with an accent edge when a setting is not at
 * its default, and a danger "N problems" pill that also holds the group open when the server reported a problem
 * inside it.
 *
 * Design decisions: arrangement only. The caller decides which settings are in the group and how many differ from
 * their defaults; the layout settings (`LayoutSettingGroup`) and a block's form (`ReportLayoutBlockForm`) both draw
 * their groups through this one component.
 */
import type { ReactNode } from "react";

import { useStrings } from "../context/TerminologyContext";
import { CollapsibleSection } from "./CollapsibleSection";

/**
 * @param sectionKey What the open/closed choice is remembered under.
 * @param title The group's name on its bar.
 * @param changed How many of its settings differ from their defaults.
 * @param summary Pill text in place of the "N changed" count (a group that always has a value, such as the page size).
 * @param defaultOpen Whether it starts open until the person chooses.
 * @param problems How many server problems are about its settings (holds it open).
 * @param children The group's fields.
 */
export function SettingGroup({
  sectionKey, title, changed = 0, summary: given, defaultOpen = false, problems = 0, children,
}: {
  sectionKey: string;
  title: string;
  changed?: number;
  summary?: string;
  defaultOpen?: boolean;
  problems?: number;
  children: ReactNode;
}) {
  const text = useStrings().pageSetup;
  const summary = problems > 0 ? text.groupProblem(problems) : given ?? (changed > 0 ? text.groupChanged(changed) : undefined);
  return (
    <CollapsibleSection
      sectionKey={sectionKey} title={title} variant="plain" defaultCollapsed={!defaultOpen}
      summary={summary} marked={changed > 0} forceOpen={problems > 0}
    >
      {children}
    </CollapsibleSection>
  );
}
