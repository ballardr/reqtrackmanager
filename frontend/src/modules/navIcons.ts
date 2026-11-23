/**
 * Module: modules/navIcons
 *
 * Generic resolver for a module-contributed nav-rail entry's icon (`ModuleFrontendManifest.nav_icon` /
 * `ModuleNavEntry.nav_icon`, `app.modules.registry`). Each module supplies its icon name as plain data over the wire
 * (as `nav_label`) and it is resolved here for every module, so `Layout.tsx` has no per-module case (the boundary
 * violation CLAUDE.md's "Modular Feature System Boundary" describes). The name travels over the backend wire, unlike
 * `entityAccentColor`'s hex pair on a Tier A `module.ts`, because nav entries are read from `ModuleFrontendManifest`,
 * the one nav-rail source that also covers Tier B/C modules with no frontend `module.ts`. `ICONS_BY_NAME` is an
 * open-set palette: any lucide-react icon can be added, and none needs adding for a new module.
 */
import {
  AlertTriangle,
  Anchor,
  CircleHelp,
  Compass,
  Lightbulb,
  type LucideIcon,
  MessagesSquare,
  Network,
  Puzzle,
  Scale,
  ShieldAlert,
  ShieldCheck,
  Target,
  Telescope,
  UserRound,
  Users,
} from "lucide-react";

const ICONS_BY_NAME: Record<string, LucideIcon> = {
  puzzle: Puzzle,
  network: Network,
  "shield-check": ShieldCheck,
  "shield-alert": ShieldAlert,
  scale: Scale,
  compass: Compass,
  telescope: Telescope,
  "alert-triangle": AlertTriangle,
  anchor: Anchor,
  "circle-help": CircleHelp,
  users: Users,
  "user-round": UserRound,
  target: Target,
  "messages-square": MessagesSquare,
  lightbulb: Lightbulb,
};

/** The generic fallback `nav_icon`'s backend default resolves to (`"puzzle"`), so an unrecognised name (for example a third-party module's) still renders an icon. */
const FALLBACK_ICON = Puzzle;

/** Resolves a `nav_icon` name to its lucide-react icon component. */
export function resolveNavIcon(name: string | undefined): LucideIcon {
  if (!name) return FALLBACK_ICON;
  return ICONS_BY_NAME[name] ?? FALLBACK_ICON;
}
