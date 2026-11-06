/**
 * Module: components/ScoringSection
 *
 * One titled block of a scoring editor (default model, models shown, criteria, levels, rating bands): a card the
 * person can fold to its title, the choice remembered per scheme and tier. The scoring editors are long, and most
 * visits touch one block, so each is a `CollapsibleSection` rather than a permanent part of the page. The outer
 * `<section>` keeps each block a landmark that tests and assistive technology can find by its heading.
 */
import type { ReactNode } from "react";

import { CollapsibleSection } from "./CollapsibleSection";

/**
 * @param sectionKey Identifies the block for the remembered fold state (scheme, tier and block). A preference key is
 *   at most 100 characters, so it never carries an id.
 * @param title The block's heading.
 * @param summary Short text for a pill on the folded bar.
 * @param defaultCollapsed Whether the block starts folded (default open).
 */
export function ScoringSection({
  sectionKey, title, summary, defaultCollapsed = false, children,
}: {
  sectionKey: string;
  title: string;
  summary?: string;
  defaultCollapsed?: boolean;
  children: ReactNode;
}) {
  return (
    <section>
      <CollapsibleSection sectionKey={`sc:${sectionKey}`} title={title} summary={summary} defaultCollapsed={defaultCollapsed}>
        {children}
      </CollapsibleSection>
    </section>
  );
}
