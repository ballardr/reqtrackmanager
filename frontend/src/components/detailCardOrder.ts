/**
 * Module: components/detailCardOrder
 *
 * The one place the default card order of a record detail page is written down and applied (docs/ux-style-guide.md,
 * "Pattern: detail page card order"). Every card belongs to a rank; `DetailLayout` sorts its children by rank, keeping the
 * authored order inside a rank, so a card added later lands in its place whichever line the page writes it on.
 *
 * Ranks, first to last: `header`, `body` (the record's details, then the cards most relevant to its purpose), `organising`
 * (components and codes, tags, external references), `supporting` (versions, attachments, history) and `discussion`
 * (comments, last because a thread grows long).
 *
 * Design decisions: the rank is read from an element's `rank` prop (`DetailCard`) or a static `detailRank` on its
 * component (`withDetailRank`), so a shared card carries its rank everywhere. Only direct children (and fragment children)
 * are ordered, so a page puts its cards straight into `DetailLayout`. An element with no rank is `body`. The sort is by
 * rank only, never by tree depth.
 */
import { Children, Fragment, cloneElement, isValidElement, type ComponentType, type ReactNode } from "react";

/** The ranks of a detail page's cards, in the order they are drawn. */
export const DETAIL_RANKS = ["header", "body", "organising", "supporting", "discussion"] as const;

/** One of {@link DETAIL_RANKS}. */
export type DetailRank = (typeof DETAIL_RANKS)[number];

/**
 * Marks a card component with its rank, so every page that places it orders it the same way.
 *
 * @param component The component that draws the card.
 * @param rank Where its cards sit on a detail page.
 * @returns The same component, with `detailRank` set.
 */
export function withDetailRank<T extends ComponentType<never>>(component: T, rank: DetailRank): T {
  (component as T & { detailRank?: DetailRank }).detailRank = rank;
  return component;
}

/**
 * The rank of one child of a detail page.
 *
 * @param child A React node.
 * @returns Its `rank` prop, else its component's `detailRank`, else `body`.
 */
export function detailRankOf(child: ReactNode): DetailRank {
  if (!isValidElement(child)) return "body";
  const own = (child.props as { rank?: DetailRank }).rank;
  if (own) return own;
  const fromType = typeof child.type === "function" || typeof child.type === "object"
    ? (child.type as { detailRank?: DetailRank } | null)?.detailRank
    : undefined;
  return fromType ?? "body";
}

/** Replaces each fragment by its children, so a page can group cards without hiding them from the order. */
function flatten(nodes: ReactNode, prefix: string): ReactNode[] {
  return Children.toArray(nodes).flatMap((node): ReactNode[] => {
    if (!isValidElement(node)) return [node];
    const key = `${prefix}${String(node.key)}`;
    if (node.type === Fragment) return flatten((node.props as { children?: ReactNode }).children, `${key}/`);
    return [cloneElement(node, { key })];
  });
}

/**
 * Orders a detail page's children by rank, keeping the authored order inside a rank.
 *
 * @param children What the page passed to `DetailLayout`.
 * @returns The nodes (fragments opened, empty values dropped), `header` first and `discussion` last.
 */
export function orderDetailChildren(children: ReactNode): ReactNode[] {
  return flatten(children, "")
    .map((element, index) => ({ element, index, rank: DETAIL_RANKS.indexOf(detailRankOf(element)) }))
    .sort((a, b) => a.rank - b.rank || a.index - b.index)
    .map(({ element }) => element);
}
