/**
 * Module: modules/navIcons
 *
 * Generic resolver for a module-contributed nav-rail entry's icon
 * (`ModuleFrontendManifest.nav_icon`/`ModuleNavEntry.nav_icon`, `app.modules.
 * registry`) — `Layout.tsx` used to render every module nav entry with the
 * same hardcoded `<Wrench>`, so Compliance, Decisions and all five of
 * Context & Strategy's own entries (Strategy, Future State, Pain Point,
 * Guiding Principle, Open Question) were visually indistinguishable in the
 * nav rail. Fixed by having each module supply its own icon **name** (plain
 * string data carried over the wire, same as `nav_label`) and resolving it
 * here, generically, for every module — not by adding a per-module case to
 * `Layout.tsx` itself, which would repeat the exact "module's own data
 * hand-edited into a core file" failure mode CLAUDE.md's "Modular Feature
 * System Boundary" section documents for `entityAccentColor`/`artefact_
 * types`. Unlike `entityAccentColor` (a literal hex pair on a Tier A
 * module's own `module.ts`), the icon *name* has to travel over the backend
 * wire: nav entries are read from `ModuleFrontendManifest`, the one nav-rail
 * source that also covers Tier B/C modules with no frontend `module.ts` of
 * their own. `ICONS_BY_NAME` below is the broad, open-set "palette" a module
 * picks a name from — adding an unused icon to it is never required to
 * support a new module, since the full lucide-react set the project already
 * depends on is available to add from as needed.
 */
import {
  AlertTriangle,
  Anchor,
  CircleHelp,
  Compass,
  type LucideIcon,
  Puzzle,
  Scale,
  ShieldCheck,
  Target,
  Telescope,
  UserRound,
  Users,
} from "lucide-react";

const ICONS_BY_NAME: Record<string, LucideIcon> = {
  puzzle: Puzzle,
  "shield-check": ShieldCheck,
  scale: Scale,
  compass: Compass,
  telescope: Telescope,
  "alert-triangle": AlertTriangle,
  anchor: Anchor,
  "circle-help": CircleHelp,
  users: Users,
  "user-round": UserRound,
  target: Target,
};

/** The same generic fallback `nav_icon`'s own backend default resolves to
 * (`"puzzle"`) — used here too so a name this palette doesn't recognise
 * (e.g. a third-party module that guessed wrong) still renders something
 * rather than nothing. */
const FALLBACK_ICON = Puzzle;

/** Resolves a `nav_icon` name to its lucide-react icon component. */
export function resolveNavIcon(name: string | undefined): LucideIcon {
  if (!name) return FALLBACK_ICON;
  return ICONS_BY_NAME[name] ?? FALLBACK_ICON;
}
