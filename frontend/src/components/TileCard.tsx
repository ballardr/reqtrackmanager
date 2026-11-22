/**
 * Module: components/TileCard
 *
 * The one card of every tile view (`ViewToggle` "tiles"): Projects, Favourites, Compliance Standards,
 * Requirements and Change Requests draw their rows through it, so the same kind of object looks the same
 * everywhere.
 *
 * Responsibilities:
 * - `TileGrid` lays the cards out in the shared responsive grid.
 * - `TileCard` draws the title row (the title is the link, styled as every link in the product, with
 *   badges after it and an actions slot at the right) and the card body the page passes as children.
 *
 * Design decisions:
 * - The title is the link, never the whole card: a card may hold actions (a star, a menu) and
 *   filter badges, and a link around them would nest interactive controls.
 * - Presentational and module-agnostic: the page supplies the content, an optional `accentColor` (the
 *   entity stripe, from `ENTITY_ACCENT_COLOR` or a module's own `entityAccentColor`) and an optional
 *   `eyebrow` row above the title. Nothing here knows about a record type.
 *
 * Depends on react-router-dom `Link`; styles are `.tile-grid` and `.tile-card*` in `styles/theme.css`.
 */
import type { CSSProperties, ReactNode } from "react";
import { Link } from "react-router-dom";

import { CellText } from "./CellText";

/**
 * The responsive grid that holds a page's tile cards.
 *
 * @param props.children The cards.
 * @returns A grid wrapper.
 */
export function TileGrid({ children }: { children: ReactNode }) {
  return <div className="grid tile-grid">{children}</div>;
}

/** Props of {@link TileCard}. */
export interface TileCardProps {
  /** The card's name; a string so it can also be the title's tooltip when it is cut off. */
  title: string;
  /** Where the title links to. Omitted, the title is plain muted text (a record the person cannot open). */
  to?: string;
  /** Badges drawn after the title on the same row (a template mark). */
  titleBadges?: ReactNode;
  /** A control at the right of the title row (a favourite star, a row menu). */
  actions?: ReactNode;
  /** A row above the title (a record code with its move buttons). */
  eyebrow?: ReactNode;
  /** An entity accent colour for the left stripe, as `ENTITY_ACCENT_COLOR` or a module registers it. */
  accentColor?: string;
  /** Draws the whole card muted, for a project the person is not a member of. */
  muted?: boolean;
  /** The card body: secondary text, status badges and counts. */
  children?: ReactNode;
}

/**
 * A tile card: an optional eyebrow, the title row, then the body.
 *
 * @param props See {@link TileCardProps}.
 * @returns The card element; give it to a {@link TileGrid}.
 */
export function TileCard({ title, to, titleBadges, actions, eyebrow, accentColor, muted = false, children }: TileCardProps) {
  const classes = ["card", "stack", "tile-card"];
  if (accentColor) classes.push("entity-accent-card");
  if (muted) classes.push("text-muted");
  const style = accentColor ? ({ ["--entity-accent-color"]: accentColor } as CSSProperties) : undefined;
  return (
    <div className={classes.join(" ")} style={style}>
      {eyebrow}
      <div className="tile-card-head">
        <div className="tile-card-heading">
          {to ? (
            <Link to={to} className="tile-card-title"><CellText>{title}</CellText></Link>
          ) : (
            <span className="tile-card-title"><CellText>{title}</CellText></span>
          )}
          {titleBadges}
        </div>
        {actions}
      </div>
      {children}
    </div>
  );
}
