# UX Style Guide

This document is normative for new and reworked frontend UI in this project — the rules below, not individual taste, decide which container/create/confirmation pattern a new screen uses. It is the direct output of [docs/ux-audit-2026-08.md](ux-audit-2026-08.md), a full audit of the existing UI's workflows and consistency; that document explains *why* each rule exists (the specific inconsistency it was written against) and tracks the implementation roadmap. This one states the rules themselves, so an agent or contributor can consult it without re-reading the whole audit.

Status: the principles and patterns below are agreed; the roadmap in the audit doc tracks how much of the existing UI has actually been brought into line with them. Where a rule and the current code disagree, the rule wins for new work — file it as a roadmap item rather than copying the inconsistent precedent.

## Why this exists

The audit found the app had quietly grown three different answers to "many settings, one page" (a 15-section flat accordion wall, an 8-tab bar, and a page combining both at once), four different answers to "how do I confirm a delete" (most commonly: no confirmation at all), zero shared components for side panels or toast feedback despite fourteen-plus create flows needing one, and no way to reach org administration without already knowing the URL. None of this was one bad decision — it's what happens when each new screen is built by asking "what did the last screen near this one do" instead of "what does the rule say." This document is that rule, written down once.

## Principles

Thirteen rules. Each names the pattern and the specific failure in the existing UI it was written against — the failure is the "why," useful for judging edge cases the rule doesn't spell out.

1. **One depth model, chosen by scale — not habit.** Resource-menu sub-pages for more than five setting groups opened rarely as a whole; tabs for five or fewer views of the same object, all relevant together; accordions for one optional block inside a single view — never as the whole page. *Why:* Org Admin's 15-way flat accordion and Project Admin's 8-tab bar independently invented two different answers to the same question, and Preferences uses both at once on one page.
2. **Every override says so, out loud.** Any value with a platform default shows its current state — Platform default or Custom — and a one-click way back, every time, not sometimes. *Why:* accent colour has a working revert control; header text reverts only if you know to blank the field; org logo and login background can't be reverted at all, in the UI or the API.
3. **Create is a layer, not a page reflow — and for a full entity create/rename form, that layer is a Modal.** *(Revised 2026-08-24 — see the seventh pass's roadmap in [docs/ux-audit-2026-08.md](ux-audit-2026-08.md); this supersedes the original SidePanel-for-entities call by direct product decision, flagged here rather than changed silently.)* A brand-new entity (a project, an organisation, a user, a group, a requirement) or a rename of an existing one opens in a `Modal`, centred and blocking the page behind it. The reasoning is about the app's own spatial reading order, not any one form's internal field layout: the app reads left to right as nav rail → resource menu (where present) → core content pane → side panel, each column showing something derived from the one to its left — the side panel's specific job in that order is "further detail about, or an action on, whatever the content pane is currently showing" (open a row, see its detail; select a record, edit it). `FilterPanel` (the shared list+filter sidebar behind Principle 10's `FilterBadge` rule, above) is the same slot used the same way and predates this decision: its narrowing controls (which statuses, which stages) are themselves derived from — scoped to — whatever entity type the content pane is currently listing, not an independent, freestanding form. (Worth a small side-note: `FilterPanel` itself has never had its own dedicated `Pattern:` write-up describing when to reach for it, despite being used on three pages and named in Principle 10 and the audit's "Filters, four more ways" finding — the same "built, working, never named" gap this pass already found twice elsewhere, not scoped as its own roadmap item here but worth remembering next time that list grows.) Creating a brand-new entity isn't detail about anything already on screen — it's a fresh, disconnected action with no "what came before it" in that reading order — so putting it in the side panel's slot borrows a position whose meaning is specifically "more about what's already showing" for something that isn't that. A `Modal` sits outside and on top of the whole nav → resource-menu → content → panel flow rather than occupying a position within it, which is the correct home for an action that doesn't belong anywhere in that order. `SidePanel` is retained for exactly the job that reading order actually assigns it: viewing an existing entity's full detail without navigating away, list still visible underneath (`Pattern: entity detail panel`, below) — not for creating anything new. `Popover` is unchanged, for a one- or two-field quick action anchored to whatever triggered it. *Why (original):* every one of the app's 14+ create flows was an inline form that pushed the surrounding list down; the app's Modal component had never been used for a create flow. *Why (revision):* a create flow was occupying the side panel's spatially-meaningful "detail about the current view" slot for something that isn't detail about the current view at all. See the new `Pattern: modal dialog for entity create/rename`, below, including a known dependency (`Modal.tsx` itself likely needs a size variant before it's a drop-in fit for every flow this affects).
4. **One component per pattern, not one per page.** A single shared `Tabs`, `SidePanel`, and `Popover`, used everywhere that pattern applies. *Why:* three pages independently hand-rolled the same tab-bar markup; consistency should be a side effect of reuse, not a rule enforced by memory across separate authors and dates.
5. **One door for "add one" and "add many."** Bulk operations live behind the same entry point as the single-item create, offered as a second option — not a separate block the user has to already know exists. *Why:* the CSV import wizard already does the job well but sits permanently on-screen, unlabelled, beside the single-add form it duplicates.
6. **Confirm proportional to consequence.** Two tiers, not four: an ordinary delete gets a lightweight Modal confirmation; an irreversible, wide-blast-radius action (deleting an organisation, for instance) gets type-the-name-to-confirm. Nothing in between silently deletes. *Why:* four competing confirmation patterns exist today, the most common of which is none at all — including the exact same "archive" operation confirming on one page and not its structural sibling.
7. **Every mutation ends with feedback.** A save, delete, vote, or import always tells the user it happened — a shared toast for success, a shared inline error state for failure, both wired through one place so a new mutation can't accidentally skip it. *Why:* success feedback exists in exactly one place in the current app (the CSV import summary).
8. **Every interactive control has a name.** An icon-only button gets a real `aria-label`, a tab bar gets real ARIA tab semantics with arrow-key navigation, a modal traps focus while open and returns it on close. *Why:* at least 20 unlabelled icon buttons and a shared Modal with neither a focus trap nor focus restoration — concentrated, fixable gaps, not a rewrite.
9. **Org administration is always one click away, even though content browsing isn't org-scoped.** Content (projects, requirements, and everything under them) deliberately pools across every org a user belongs to — that's correct and shouldn't change, so this isn't a case for a persistent "current org" context or an Azure/Entra-style tenant switcher that would force the whole app into one org's context at a time. What's actually missing is narrower: a nav-rail entry point to the org directory (`/orgs`), so reaching org-level settings doesn't depend on already having a bookmark or a stale link. *Why:* `/orgs` has no rail entry for anyone but a server admin — an ordinary org admin has no path back to their own org's settings from the persistent chrome.
10. **Every badge that names a filterable value is a `FilterBadge`, not a plain `.badge`.** If a row shows a badge for a value (status, outcome, stage, role, …) and the same page's filter panel offers that value as an option, clicking the badge must apply it as a filter (and clicking it again clear it) — the same click-to-toggle behaviour `FilterBadge` already gives `RequirementsPage`'s status badge. A badge for a value with no matching on-page filter stays a plain `.badge`; this rule only applies where both already exist on the same page. *Why:* `FilterBadge` was built and correctly used on four pages before this was ever written down as a rule, so a fifth page (`ProjectActionsPage`) reproduced the identical badge/filter-panel pair with a plain, inert badge — there was working precedent to copy, but nothing to check against before shipping the copy that missed it.
11. **Grouped secondary actions get one door too, not just creates.** Principle 5 is about "add one" vs. "add many"; the same shape applies to any pair of related, non-primary actions that would otherwise sit on screen together as two permanently-visible, competing buttons — most often a download and its companion (export data / download an import template). Collapse them behind one small `Popover` trigger instead. *Why:* the CSV wizard's "Export CSV" and "Download template" buttons reproduced Principle 5's exact "two blocks competing for the same job" shape, just for downloads instead of creates — the rule as originally written only named creates, so nothing flagged the download pair as the same problem.
12. **Every enum, status, or role value shown to a user goes through its label map — never the raw backend string.** A dropdown option, a filter `<select>`, a table cell, a badge — all read from the same `*_LABEL` lookup (e.g. `REQUIREMENT_STATUS_LABEL`, `CHANGE_REQUEST_STATUS_LABEL`, `PROJECT_ROLE_LABEL` in `frontend/src/api/types.ts`) that the row/badge rendering for that same value already uses, rather than interpolating the enum's wire value (`in_review`, `project_administrator`) directly into JSX. When a new enum value is added, its label goes into the same map at the same time — not inline in whichever component happens to render it first. *Why:* found four times independently in one pass (`ChangeRequestsPage.tsx`/`RequirementsPage.tsx`'s own filter selects, a requirement's version-history table, an Org Admin role badge) — each one had a working label map sitting right next to the broken code, used correctly by a sibling element on the same page, and missed anyway.
13. **Every form field gets a visible label, not just placeholder text.** Placeholder text disappears the moment a field has real content — it can't double as the field's name once something's typed into it. *Why:* the new-requirement form's Name/Reasoning/Description fields relied on placeholder-only labelling while every other field on the same form (Component, Category, Target version, Level) correctly used a real `<label>` — once populated, three of seven fields on one form had nothing on screen saying what they were.

## Pattern: settings hierarchy

Use this decision aid for any new settings surface, or any existing one being reworked. It's the rule that would have kept Org Admin (15 flat accordions) and Project Admin (8 tabs) from independently diverging into different answers to the same problem.

```mermaid
flowchart TD
  Start{"What are you adding?"}
  Start --> A{"A page of settings"}
  Start --> B{"An action on existing content"}
  A -->|"more than 5 groups, opened rarely as a whole"| ResourceMenu["Resource menu: sub-pages + left menu"]
  A -->|"5 or fewer views, all relevant together"| Tabs["Shared Tabs component"]
  A -->|"one optional block inside a single view"| Accordion["Accordion (CollapsibleSection)"]
  B -->|"create or rename an entity"| Modal["Modal"]
  B -->|"view an existing entity's full detail, keep list context"| Panel["Side panel"]
  B -->|"one or two fields, a single quick decision"| Popover["Popover"]
  B -->|"disruptive, read-only content to view"| Modal
```

*(The "create or rename" leaf was revised 2026-08-24 from an earlier "Side panel" answer — see Principle 3 above.)*

Read this top to bottom: the first question splits into two families depending on whether you're adding a whole page of settings or a single action on something that already exists; each leaf names the exact component to reach for. It matters here because "many settings on one page" is the single most repeated design problem in the current app, solved three different ways.

The resource-menu leaf is the enterprise-console shape the app's own header chrome already gestures at — a fixed dark top bar, independent of the light/dark theme, in the same family as Power Apps, Dynamics, and ServiceNow (see [docs/decisions.md](decisions.md), "Header chrome is theme-independent"). Azure and Entra use the same shape one level deeper: an overview blade, then a left resource menu grouping related settings, then a content pane.

**Addendum (2026-08-24): when one resource-menu group outgrows itself, split it into more flat top-level groups — don't add nested sub-navigation.** Two groups in the "after" tree below have since grown crowded, one level down — People (Users and Groups, currently two `CollapsibleSection`s crammed into one panel) and Integrations & Security (SSO/OIDC, SCIM, SMTP/email, 2FA/self-signup/external-user policy, and PATs, all under one combined section). This doesn't need a new nested-navigation capability: `ResourceMenu` already renders any number of flat top-level groups — going from 15 accordions to 6 groups in the fifth pass wasn't settling on a hard ceiling of exactly 6, just what fit that particular regroup. Promoting Users and Groups to their own top-level entries (replacing People), and splitting Integrations & Security into OAuth/SSO, Email, and Security, both just add more entries to the same flat list `ResourceMenu` already handles — no component change required. See the roadmap in [docs/ux-audit-2026-08.md](ux-audit-2026-08.md).

![Current: Org Admin as a flat list of 15 identically-weighted accordion sections, all collapsed. Proposed: the same page as a resource menu with 6 groups on the left and a content pane on the right, only the selected group's settings shown.](figures/ux-style-guide/settings-hierarchy.png)

Mockups, not screenshots — illustrative of the shape, not the exact pixels. Applied to Org Admin's actual 15 flat sections:

```mermaid
flowchart TD
  Root["Org Admin — before: 15 flat sections"] --> S1["Import / merge bundle"]
  Root --> S2["Users"]
  Root --> S3["Projects"]
  Root --> S4["Project statuses"]
  Root --> S5["Link types"]
  Root --> S6["Branding"]
  Root --> S7["Report defaults"]
  Root --> S8["Report templates"]
  Root --> S9["SSO / OIDC"]
  Root --> S10["SCIM"]
  Root --> S11["Default template"]
  Root --> S12["Groups"]
  Root --> S13["Shared resources"]
  Root --> S14["Advanced"]
  Root --> S15["Personal access tokens"]
```

```mermaid
flowchart TD
  Root2["Org Admin — after: 6 groups"] --> G1["Overview"]
  Root2 --> G2["People"]
  Root2 --> G3["Projects & workflow"]
  Root2 --> G4["Branding & defaults"]
  Root2 --> G5["Templates & reports"]
  Root2 --> G6["Integrations & security"]
  G1 --> G1a["Org name, export, danger zone"]
  G1 --> G1b["Import / merge bundle"]
  G1 --> G1c["Shared resources"]
  G2 --> G2a["Users"]
  G2 --> G2b["Groups"]
  G3 --> G3a["Projects: group & membership matrix"]
  G3 --> G3b["Project statuses"]
  G3 --> G3c["Link types"]
  G4 --> G4a["Branding — logo, colour, footer"]
  G4 --> G4b["Default template project"]
  G5 --> G5a["Report defaults"]
  G5 --> G5b["Report templates"]
  G6 --> G6a["SSO / OIDC — incl. IdP group-name mapping, moved from Groups"]
  G6 --> G6b["SCIM"]
  G6 --> G6c["SMTP & email"]
  G6 --> G6d["Security — 2FA requirement, self-signup, external-user policy"]
  G6 --> G6e["Personal access tokens — org-wide lifetime & list"]
```

Two trees, same content, regrouped rather than trimmed — every leaf in the second diagram traces back to a section in the first. Two notes on the regrouping itself: **Overview** groups rare-and-consequential items (import/merge, the danger zone, shared resources) that don't share a subject, only a "you'd look at this on arrival or almost never" frequency; and the old **Advanced** accordion doesn't survive as one item — its seven previously-crammed-together settings domains split across the tree by what they actually govern (SMTP/email gets its own item, 2FA/self-signup/external-user-policy becomes "Security," PAT lifetime joins the existing PAT list).

## Pattern: platform default vs. override

One control, applied uniformly to every overridable setting (today: accent colour, header title, footer identity, logo, login background). A status pill states the current source in words, not just an input's blank-or-filled state; a reset action is always present when the value is custom.

![Current: the Branding form shows the organisation logo filename with only an "Upload new file…" button — no way back to the platform default. Proposed: the same field with a "Custom" pill and an explicit "Reset to platform default" link, and a second field showing a "Platform default" pill with nothing to reset.](figures/ux-style-guide/platform-override.png)

Implementing the logo/login-background half of this needs a small, genuinely new backend capability (a `DELETE` reset endpoint alongside the existing upload `POST`) — treat that as its own reviewed change per [docs/soc2/policies/change-management-and-secure-development-policy.md](soc2/policies/change-management-and-secure-development-policy.md), not folded silently into a UI-only pass.

## Pattern: create panels, popovers, and one door for bulk

*(The side-panel-for-entities half of this section is historical — see the revised Principle 3 and the new `Pattern: modal dialog for entity create/rename`, below, for the current rule. Left as-is here rather than rewritten, since it documents the reasoning and mockups from when it was current; the "one door for bulk" and Popover-for-small-forms parts are unaffected by the revision.)*

Three shapes, chosen by how much the create flow needs: a full side panel for a multi-field entity, a small popover for one or two fields, and a single split entry point that offers both "add one" and "import many" instead of two disconnected blocks.

![Current: the Groups panel with an inline "Group name…" input and "Add group" button permanently sitting below the existing group list. Proposed: a "+ New group" button in the corner opening a small popover with just a name field and Cancel/Create.](figures/ux-style-guide/create-group-popover.png)

![Current: the Requirements page with two separate, unlabelled blocks stacked above the list — an inline "New requirement" form and an always-visible CSV import wizard. Proposed: a single "+ Add requirement" split button opening a dropdown with "Add one" and "Import from CSV" options.](figures/ux-style-guide/create-bulk-entry-point.png)

The CSV import wizard's own column-mapping/preview logic is unchanged here, it just stops being a second, permanently-visible block competing with the single-add form for the same job.

![Current: the Change Requests page with a large inline form description noting it opens a kind selector and per-field editors directly in the page body. Proposed: a plain "+ New change request" button with the list undisturbed below it.](figures/ux-style-guide/create-change-request.png)

The current inline form here (a kind selector plus a per-field checkbox-revealed editor) is the most field-heavy inline form in the app — under this pattern it moves into the same side panel unchanged, it just stops pushing the list down while doing it.

**The same "one door" shape applies past creates, too (Principle 11).** The CSV wizard's "Export CSV" and "Download template" were two permanently-visible, adjacent buttons for two related downloads — not a create flow, but the identical "two blocks competing for the same job" problem. They now live behind a single "Export" `Popover` trigger, the same component (and the same small-menu shape) `RequirementsPage`'s own "+ New requirement" uses for Add one/Import from CSV. Reach for this whenever a screen accumulates a second, related, non-primary action next to an existing one rather than adding it as its own permanent button.

## Pattern: modal dialog for entity create/rename

*(New 2026-08-24, superseding the SidePanel half of the pattern above for entity creates — see the seventh pass in [docs/ux-audit-2026-08.md](ux-audit-2026-08.md).)*

Creating a brand-new entity (project, organisation, user, group, requirement) or renaming an existing one now opens in a `Modal` — centred, blocking the page behind it, with the entire form visible without navigating away. This was a direct product decision, not a mechanical audit finding, and the reasoning is about where things sit in the app's own spatial reading order, not about any one form's internal field layout: the app reads left to right as nav rail → resource menu (where present) → core content pane → side panel — each column showing something *derived from* the one before it. `SidePanel`'s slot in that order specifically means "more about, or an action on, whatever the content pane currently shows" (open a row, see or edit its detail). A brand-new entity isn't detail about anything already on screen; it has no "what came before it" in that reading order, so it doesn't belong in the slot whose whole meaning is contextual derivation. `Modal` sits outside and on top of that entire flow rather than occupying a position within it, which is why it's the right home for an action that isn't contextual to the current view at all.

What doesn't change: `SidePanel` keeps its one remaining job — the one the reading order actually assigns it — viewing an existing entity's full detail without leaving the list behind it (`Pattern: entity detail panel`, below). `Popover` is untouched, for a one- or two-field quick action (a rename-in-place, a single-select stage move) anchored to whatever triggered it.

Known implementation dependency, not yet resolved: `Modal.tsx` today (`{ title, onClose, children }`, fixed `max-width: 560px`, no dedicated footer/action-button prop, caller supplies its own buttons in `children`) was built for its one current use — a read-only vote-comment viewer, plus `ConfirmDialog` built on top of it — and hasn't yet hosted a genuinely busy multi-field form like the CSV import wizard or a New Project form. Before converting every create flow onto it, check whether it needs a size/width variant (a `size="lg"` prop, say) rather than assuming every flow fits the current fixed width unchanged.

## Pattern: resource picker dialog

*(New 2026-08-24 — see [Shared org resources](ux-audit-2026-08.md#shared-org-resources-have-almost-no-way-to-consume-them).)*

A two-pane `Modal`: a source list on the left (today, just "Organisation shared resources," but built to admit more sources later — a project's own uploaded files, say — without a rewrite), and the selected source's actual files on the right, pickable and attachable to whatever opened the dialog. This is a new component, not a variant of anything that exists — nothing in the app today lets a user reach into a shared pool from outside the page that manages it directly.

First concrete wiring target: `RequirementDetailPage.tsx`'s Attachments card, using the backend endpoint that already exists for exactly this (`POST /{requirement_id}/files/link`) but currently has no frontend caller anywhere. Building the picker generically enough to also serve a report chapter's image picker (which today has its own bespoke resource-selection logic in `reports.py`/`ReportsPage.tsx`) is worth doing at the same time, rather than after, since both consumers want the identical "browse the shared pool, pick one, attach it here" shape.

## Pattern: role display — effective highest role only

*(New 2026-08-24 — see [Project role display](ux-audit-2026-08.md#project-role-display-every-role-shown-not-the-effective-highest).)*

`ProjectRole` (`backend/app/models/enums.py:21-27`) has a real precedence, not just four unordered labels: `project_manager` is the sole top tier; `project_administrator` and `stakeholder` are a shared, mutually-equal second tier; `member` is the floor. Anywhere a user's project role is shown as a compact summary (a row in a list, a header), collapse to this precedence — show `project_manager` alone if held; otherwise show whichever of `project_administrator`/`stakeholder` are held (both, if both); otherwise show `member`. A user genuinely holding more than one tier-2 role (both `project_administrator` and `stakeholder`, via different group memberships) still shows both, since they're not ordered relative to each other — only strictly lower roles get hidden once a higher one is present.

This is a display rule for summary contexts, not a data change — a genuine access-audit view (Org Admin's "View access" panel, specifically built to answer "what does this person actually have") should keep showing the full, uncollapsed role set per project, since collapsing there would remove the exact detail that view exists to surface. Apply the collapsing rule to compact list rows (Org Admin's Users table, a project's member list) and keep the full set in any view whose whole purpose is a detailed access audit.

## Pattern: split-button trigger

*(New 2026-08-24 — see [The "New Requirement" trigger](ux-audit-2026-08.md#the-new-requirement-trigger-doesnt-match-the-requested-split-button-interaction).)*

For a primary action that has exactly one common case and one (or a small number of) less-common alternative — "add a requirement" vs. "import a batch from CSV" — clicking the main control performs the common case directly; a small secondary affordance (a chevron, or hovering the control) reveals the alternative(s) without an extra click for the common path. This is different from the app's current `Popover`-menu-on-click shape (used today by `RequirementsPage`'s "+ New Requirement" trigger), which makes *every* click, including the common case, stop at a menu first.

Not yet built anywhere in the app — the closest existing precedent is the `Popover`-based two-option menu it's replacing, not a true split button. Worth building as its own small shared component (a button + adjacent chevron, sharing `Popover`'s existing positioning/outside-click-close logic for the revealed alternate-options list) rather than a one-off on `RequirementsPage`, since the same shape fits anywhere else a primary action currently forces a menu stop for its own most common case.

## Pattern: view toggle (tile vs. list)

*(New 2026-08-24, documenting an existing, working component that was never written up as a rule — the same story `FilterBadge` had before Principle 10. See [Favourites](ux-audit-2026-08.md#favourites-no-filter-nav-rail-lag-no-view-toggle).)*

`useViewMode`/`ViewToggle` already exists and is already used correctly on `ProjectListPage.tsx` and `RequirementsPage.tsx` — a small control switching a list between a tile/card grid and a table/list layout, state persisted per page. Any list page presenting more than a handful of items, where both "scan visually" (tiles) and "compare fields side by side" (list/table) are genuinely useful, should use this component rather than picking one fixed layout or, worse, hand-rolling a second toggle. `FavouritesPage.tsx` is the one page missing it today despite being exactly this shape — see the roadmap.

## Missing components identified this pass

Reviewing the seventh pass's findings against the style guide's existing component set surfaced five gaps: three new components with no precedent anywhere in the app, one existing component that needs extending before it can take on a new job, and one component that already existed but — like `FilterBadge` before it — had never been written up as a rule. (Splitting Org Admin's People and Integrations & Security groups turned out not to need a new navigation capability at all — see the settings-hierarchy addendum above — so it isn't listed here.)

| Gap | New or extend? | Where it's needed | Pattern |
|---|---|---|---|
| Modal dialog able to host a full multi-field entity form | Extend `Modal.tsx` (currently sized/shaped for a small read-only viewer) | Every entity create/rename flow | [Pattern: modal dialog for entity create/rename](#pattern-modal-dialog-for-entity-createrename) |
| Two-pane resource picker dialog | New | Attaching a shared org resource to a requirement (and, later, a report chapter image) | [Pattern: resource picker dialog](#pattern-resource-picker-dialog) |
| Split-button trigger (click = default action, hover/chevron = alternatives) | New | "New Requirement," and any future primary action with one dominant case | [Pattern: split-button trigger](#pattern-split-button-trigger) |
| Auto-growing textarea, capped at a sensible max height | New | New-requirement form's Reasoning/Description, and any other long-form text field | [docs/ux-audit-2026-08.md](ux-audit-2026-08.md#new-requirement-form-three-unlabelled-fields-no-auto-grow) |
| Action menu (kebab/⋯ trigger opening a small menu of related, non-primary actions) | New | Org rename + export combined; likely useful anywhere else two related secondary actions currently sit side by side as separate buttons | [docs/ux-audit-2026-08.md](ux-audit-2026-08.md#org-admin-usersgroups-org-level-actions-and-two-still-inline-create-forms) |
| View toggle (tile vs. list) | Already exists (`useViewMode`/`ViewToggle`), just never written up as a rule until now | `FavouritesPage`, and any future list page | [Pattern: view toggle (tile vs. list)](#pattern-view-toggle-tile-vs-list) |
| `FilterPanel` (list + narrowing-filter sidebar) | Already exists, used on three pages, named only in passing (Principle 10) — no dedicated `Pattern:` write-up yet | Any future list page adding filters | Not yet written — see the roadmap in [docs/ux-audit-2026-08.md](ux-audit-2026-08.md) |
| File-upload-trigger button (styled button + hidden input) | Extract from `CommentThread.tsx`'s own duplicated inline pattern — the one place in the app that already does this right | Every other file input in the app (attachments, avatar, org/platform logo & login background, shared resources — a bare native control today; bundle import — a third, `.input`-styled look) | [docs/ux-audit-2026-08.md](ux-audit-2026-08.md#file-upload-triggers-three-different-visual-treatments) |

Role-display collapsing (`Pattern: role display`, above) is a display rule, not a component — listed in its own pattern section rather than here.

## Pattern: confirmation, in two tiers — and feedback, always

Two tiers of "are you sure," matched to how hard the action is to undo — not four patterns chosen ad hoc per page. And one small, consistent way to say "done" afterward.

![Current: archiving a requirement fires immediately with no confirmation of any kind. Proposed: a Modal asking "Archive this requirement?" with an explanation and Cancel/Archive buttons.](figures/ux-style-guide/confirm-tier1-modal.png)

Tier 1 — ordinary delete/archive, applied everywhere one happens in the app.

![Current, hypothetically: if organisation deletion followed the app's own most common pattern, it would delete instantly with no confirmation. Proposed/actual: a "Delete Acme Corp?" dialog requiring the organisation's exact name to be typed before the delete button activates.](figures/ux-style-guide/confirm-tier2-type-to-confirm.png)

Tier 2 — irreversible, wide blast radius. The left panel is hypothetical, not real: organisation deletion is already implemented correctly today (type-the-exact-name-to-confirm), shown here against what it would look like if it had instead followed the app's single most common pattern, to make the point that it doesn't and shouldn't. Called out to be *named* as the deliberate upper tier rather than left as an unlabelled one-off, so a future irreversible, wide-blast-radius action (deleting a whole project, say) reaches for the same pattern instead of reinventing it.

![Current: archiving a requirement removes it from the list with nothing else on screen indicating the action succeeded. Proposed: the same list with a toast reading "✓ Requirement archived" in the corner.](figures/ux-style-guide/feedback-toast.png)

The other half of principle 7 — fired from one shared place, so a future mutation can't ship without it the way most of today's do.

## Pattern: wayfinding — a nav-rail entry to org administration

Not an Azure/Entra-style tenant switcher — this app deliberately pools content (projects and everything under them) across every org a user belongs to, and that's the right call, not a gap to fix. A switcher pattern implies the whole app scopes to one org at a time, which would contradict that pooling. The actual, narrower gap: `/orgs` (the personal org directory, and the only path to org administration) has no entry point anywhere in the persistent chrome except for server admins drilling in through `/server/organisations`.

The fix is a single nav-rail link — "Organisations" (or similar), visible to any user who is an org admin in at least one org, pointing at `/orgs`. For a user in exactly one org, `/orgs` already auto-redirects straight to that org's admin page, so the link is effectively a one-click path to "my org's settings." For a user in several, it lands on the existing directory list. No new context, no new global state — the directory page already does the job, it's just unreachable without already knowing the URL.

## Pattern: directories at scale (search, paginate, don't render everything at once)

Not every list is the same shape. A *feed* (Notifications, Project History, a reviews-due list) is scanned roughly in order — pagination alone is the right fix, already applied consistently (see [docs/ux-audit-2026-08.md](ux-audit-2026-08.md#scale-two-unbounded-lists)). A *directory* (Org Admin's Users and Groups, Project Admin's Groups tab) is instead *searched* — someone opens it already looking for one specific record — and needs all three of the following together, not pagination on its own:

```mermaid
flowchart TD
  Start{"Is this list searched for one record, or scanned in order?"}
  Start -->|"Directory — e.g. Users, Groups"| D1["Free-text search box"]
  D1 --> D2["limit/offset + LoadMoreButton"]
  D2 --> D3["Per-row child content (e.g. a group's member list) collapsed by default, not always-expanded"]
  Start -->|"Feed — e.g. Notifications, Project History"| F1["limit/offset + LoadMoreButton alone is enough"]
```

Read top to bottom: the branch point is what kind of list this is; everything below a "Directory" answer is required together, everything below "Feed" is already the existing, correctly-applied pattern. *Why:* Org Admin's Users table has three fixed audit filters (stale / no 2FA / no project access) but no way to search by name or email, and neither Users nor Groups paginate at all; Org Admin's and Project Admin's Groups sections both render every group's full member list open and inline, unconditionally, which is unnoticeable at a handful of seed-data groups and becomes the entire page at a hundred. Pagination on its own (the fix already shipped for Project History and the access-review table) doesn't solve "find the one person named Priya" — that needs search; and a directory's per-row detail (a group's members) needs to default to collapsed the way `CollapsibleSection` already does elsewhere, not render unconditionally, regardless of whether the list itself is paginated.

## Pattern: entity detail panel (view, not just create)

`SidePanel` isn't only for creating something new — the same shape (a layer anchored to the row that opened it, portalled above the page, the list underneath left untouched) is also the right container for *viewing* one record's full detail without navigating away from the list it's part of, for an entity that doesn't already have its own dedicated page. Open it read-only: no form fields, no Save button, just the data, with the same close affordance (✕, Escape, backdrop click) every other `SidePanel`/`Modal` already gives.

*Why:* every entity in the app worth looking at closely already gets a detail page or panel — a requirement, a change request, an action — except a user, who can be listed in Org Admin's Users table but never opened. An org admin auditing what one person actually has access to (which projects, which role on each, which org/project groups) has no equivalent of `RequirementDetailPage` to check, and has to reconstruct the answer by hand, project by project. The first candidate for this pattern is exactly that: a "view user" panel opened from a row in Org Admin's Users table (or a member row inside a group), listing their projects/roles/groups at a glance — see the roadmap in [docs/ux-audit-2026-08.md](ux-audit-2026-08.md#no-way-to-view-a-users-access).

## Pattern: bulk operations on a list

A checkbox column, a header checkbox that selects every currently-loaded row, and a contextual toolbar that appears once at least one row is selected — offering "N selected," a "Clear selection" control, and the available bulk actions. This is a *selection layer* on top of a list, not a new confirmation or feedback shape of its own: every bulk action still ends in the same Tier-1 `ConfirmDialog` and the same `Toast` every single-row mutation in the app already uses (Pattern "confirmation, in two tiers — and feedback, always," above) — a bulk action is just that same machinery invoked once per selected row instead of once for a single clicked row.

```mermaid
flowchart TD
  A["Row checkboxes unchecked (table/list view only)"] -->|"check 1+ rows, or header 'Select all'"| B["Toolbar: 'N selected' · Clear selection · bulk actions"]
  B -->|"Clear selection"| A
  B -->|"Archive selected"| C["ConfirmDialog (Tier 1): 'Archive N requirements?'"]
  B -->|"Move to stage"| D["Popover: pick a stage"]
  D -->|"Move"| E["ConfirmDialog (Tier 1): 'Move N requirements to \"Stage\"?'"]
  C -->|"Confirm"| F["Sequential loop over the existing single-row endpoint, once per selected row"]
  E -->|"Confirm"| F
  F --> G["Toast: 'N updated', or 'N updated, M failed' if any row errored"]
  G --> A
```

Read top to bottom: unchecking back to zero selected rows hides the toolbar again (the loop back to the top state); the two bulk actions diverge only in what they confirm before converging on the same execute-loop-then-toast tail. *Why it matters:* every branch after the toolbar reuses a component the app already has — `ConfirmDialog`, `Popover` (for the stage picker, the same "one door" shape Pattern "create panels, popovers, and one door for bulk" already names), and `Toast` — rather than inventing bulk-specific versions of any of them.

Piloted on `RequirementsPage.tsx`'s table/list view only (2026-08 UX audit roadmap: "Bulk operations on list pages," the sixth pass's own [Bulk operations: none exist](ux-audit-2026-08.md#bulk-operations-none-exist) finding — the audit named this "no existing pattern in the app to copy" and flagged it as needing a design decision before implementation). Three choices worth naming so a second page adopting this pattern doesn't have to re-derive them:

- **"Select all" means all *currently loaded* rows, never "everything matching the filter."** A list page here already paginates via `LoadMoreButton` (Pattern "directories at scale," above) rather than loading every row up front, so a true "select all 500 matching this filter" would need either loading all of them first or a server-side bulk-by-filter endpoint — neither exists, and promising it from a checkbox that only ever sees the rows already in the DOM would be misleading. Selecting more just means loading more first.
- **No new backend endpoint.** The execute step loops over the project's *existing* single-row endpoints (the same `DELETE .../requirements/{id}` archive and `PUT .../requirements/{id}` update the single-row Archive button and detail-page save already call) sequentially, client-side, tolerating individual failures rather than aborting the batch. This keeps a first pilot small and auditable; a page with materially larger selections, or a third bulk action, is the trigger to revisit whether a real bulk endpoint earns its keep — not a rule this pattern itself imposes.
- **Tier 1 confirmation stays Tier 1, not Tier 2, even at N > 1.** Bulk archive/move are exactly as reversible as their single-row equivalents (archive un-archives; a stage move can be moved again) — the count changes the wording ("Archive 7 requirements?" instead of "Archive this requirement?"), not the tier. A future bulk action that's *not* reversible per-row (a bulk permanent delete, say) would need Tier 2 the same way any single irreversible action already does.

## Pattern: sortable column header

A clickable `<th>` — rendered as a real `<button>` inside the cell, not a bare `<th onClick>`, so it's keyboard-operable like every other control in the app — that cycles unsorted → ascending → descending → unsorted on click. The currently-sorted column shows an `ArrowUp`/`ArrowDown` indicator (the same icons Tokens already names for reorder — no new icon convention introduced); every other column stays plain text until clicked. `aria-sort` on the `<th>` itself (not an `aria-label` on the button — see the shared component's own comment for why an `aria-label` there would silently rename the columnheader for every `getByRole("columnheader", { name })` query and assistive-tech user alike) is how a screen reader learns the table's current sort column/direction, matching the WAI-ARIA APG "sortable table" pattern.

```mermaid
flowchart LR
  U["Unsorted (default order)"] -->|click| A["Ascending"]
  A -->|click| D["Descending"]
  D -->|click| U
```

Read left to right: three clicks return to the starting state, and there's no fourth state — a column is never "descending, click again for nothing." *Why it matters:* four independent hand-rolled sort implementations (one per table) would repeat the exact "no shared component, no ARIA semantics" mistake the audit already found in this app's three tab bars — see [docs/ux-audit-2026-08.md](ux-audit-2026-08.md#pattern-inconsistency). One shared `SortableHeader` (`frontend/src/components/SortableHeader.tsx`) is used by every sortable table instead.

**Backend `sort`/`order` query params vs. client-side sort — decided per table, not once for the whole app:**

```mermaid
flowchart TD
  Q{"Does this list already page via limit/offset (LoadMoreButton)?"}
  Q -->|"Yes"| B["Backend sort/order params — header click refetches"]
  Q -->|"No — loads everything in one request"| C["Client-side sort of the already-loaded array (useMemo)"]
```

*Why:* sorting only the rows currently loaded from a paginated list would silently misrepresent the true full-list order — "sorted by name, ascending" has to mean sorted across every match, not just the first page fetched so far. A list that already loads everything up front has no such risk, so a client-side sort is both correct and avoids an unnecessary round-trip. See [docs/ux-audit-2026-08.md](ux-audit-2026-08.md#table-sorting-manual-reorder-only) for which of the app's tables landed on which side of this split, and `docs/decisions.md` for the reasoning per table.

Sortable columns are the obvious ones only — a name/title, a status, an ID/code, a created/modified date, a priority where one exists — never a column with no natural order (an actions column, a badge-only column). A table whose rows are shown as an accordion-of-cards rather than `<th>`-based columns (Org Admin's Groups section, Project Admin's Groups tab) has no column headers to make sortable in the first place — this pattern doesn't apply there, even though both are backend-paginated directories in the sense of the "directories at scale" pattern above.

## Tokens

`frontend/src/styles/theme.css` is already, functionally, the design system — CSS custom properties for colour, a working light/dark split, and spacing/radii used consistently even though not yet named as tokens. This section documents it as one, rather than proposing a new palette; every value below is already in the codebase.

| Token | Light | Dark | Use |
|---|---|---|---|
| `--color-primary` | `#475569` (slate) | `#94a3b8` | Primary actions, links |
| `--color-accent` | `#2f855a` (moss) | `#68d391` | Success/positive state |
| `--color-danger` | `#c53030` | `#fc8181` | Destructive actions, errors |
| `--color-warning` | `#b7791f` | `#f6c667` | Warnings |
| `--color-bg` | `#eef1f5` | `#14181f` | Page background |
| `--color-surface` | `#ffffff` | `#1c222c` | Card/panel background |
| `--color-header-bg` | `#14161c` (fixed, both themes) | — | App-chrome header — deliberately theme-independent, see `docs/decisions.md` |

Dark-theme equivalents already exist for every themed token (`:root[data-theme="dark"]`); the header chrome is the one deliberate exception, fixed regardless of theme. Not yet formalised as named tokens, though consistently used in practice: spacing clusters around `4 / 6 / 8 / 12 / 16 / 24px`, and border radius is a consistent `6px` throughout. Worth promoting to explicit `--space-*`/`--radius-*` custom properties as a small follow-up, rather than inventing a new scale — the values already agree with each other, they're just inline rather than named.

Typography: the app's own system-font stack (`-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`) at a 15px base.

**Framework & primitives.** *(New 2026-08-24.)* React + TypeScript, built with Vite; routing via `react-router-dom`. No component library and no CSS-in-JS/Tailwind — styling is plain CSS custom properties plus a small, hand-rolled set of utility classes in `frontend/src/styles/theme.css`, applied directly via `className`, the same way `.badge` already does (Principle 10's own "one small reusable visual pattern" note). New UI should reach for these before adding an equivalent: `.card`/`.stack`/`.row`/`.grid`/`.side-grid` for layout, `.btn`/`.btn-primary`/`.btn-danger` for buttons, `.input` for form controls, `.badge` for status/type/role chips, `.container` for the page-width wrapper. `frontend/src/components/` holds the shared, higher-level components this whole document is about (`Modal`, `SidePanel`, `Popover`, `Tabs`, `ConfirmDialog`, `Toast`, `FilterPanel`, `FilterBadge`, `CollapsibleSection`, `ResourceMenu`, `DefinitionList`, `SortableHeader`, `ViewToggle`) — a new page should compose from this set before reaching for a one-off.

**App chrome.** *(New 2026-08-24.)* A fixed top bar (`.app-header`, deliberately theme-independent — see the colour token table above) plus a pinned, full-height left nav rail (`.nav-rail`, `Layout.tsx`) that stays on screen while page content scrolls. The rail always shows a global section, plus a project-scoped section once a project is selected; it collapses to icon-only via a toggle pinned above the links, persisted per-user (`useUiPreference("nav_rail_collapsed")`), and a separate, independent preference (`content_boxed`) controls whether page content fills the remaining width or stays capped at 1200px. App and API version strings are pinned at the bottom of the rail (see the seventh pass's [App/API version](ux-audit-2026-08.md#appapi-version-investigated-working-as-designed) finding for how they're populated). `BrandingProvider`/`TerminologyProvider` wrap everything below the header, so org branding and terminology overrides reach every page and nav label without prop-drilling.

**Icons.** *(Expanded 2026-08-24 — the previous version of this table named six icons; the app actually uses about fifty. Verified against every `lucide-react` import in `frontend/src`, not assumed.)* `lucide-react` throughout, no other icon set — grouped below by what each means, so a new icon for an existing meaning reuses the entry rather than introducing a synonym:

| Meaning | Icon | Notes |
|---|---|---|
| Add / create | `Plus` | |
| Edit / rename | `Pencil` | One known exception: the report-template Edit button has no icon at all — worth fixing rather than copying. |
| Delete permanently | `Trash2` | A second exception (`CommentThread.tsx` using `X` for this) was fixed in the sixth pass. |
| Reorder up/down, or a sorted column's direction | `ArrowUp` / `ArrowDown` | Shared between manual reorder and `SortableHeader`'s sort-direction indicator — see "Pattern: sortable column header." |
| Expand / collapse | `ChevronUp` / `ChevronDown` | Reserved exclusively for `CollapsibleSection`. A `ChevronDown` is also proposed for a split-button's secondary-options affordance (`Pattern: split-button trigger`) — a different job at a different location (beside a button, not inside an accordion header), not a collision, but worth remembering both exist. |
| Close a dialog | `X` | `Modal.tsx`/`SidePanel.tsx`'s own close button — distinct from `Trash2` above; not used for delete anywhere anymore. |
| Archive / restore | `Archive` / `ArchiveRestore` | |
| View a record's full detail | `Eye` | Org Admin's "View access" panel trigger. |
| Favourite | `Star` | Filled when favourited, outline otherwise (`ProjectListPage.tsx`, `FavouritesPage.tsx`, and the nav-rail Favourites link itself). |
| Lock / unlock | `Lock` / `Unlock` | Currently one specific use — Org Admin's per-user "display name locked" toggle — not yet a general "this record is locked" convention; if a future requirement/action lock-state indicator is added (see the seventh pass's actions/change-request gate findings), reuse this pair rather than inventing a new one. |
| Attachment | `Paperclip` | |
| Comment / discussion | `MessageSquare` | |
| "Like" a comment | `Heart` | Filled when the current user has reacted, outline otherwise. |
| Notifications | `Bell` / `BellOff` | |
| Toast success / error | `Check` / `TriangleAlert` | `Check` is reused for "approve" (Project Admin's stage-approval button); `TriangleAlert` is reused for an inline warning on `RequirementsPage`. |
| Upload / download | `Upload` / `Download` | |
| Nav-rail collapse toggle | `PanelLeftClose` / `PanelLeftOpen` | |
| Tile / list view toggle | `LayoutGrid` / `List` | See `Pattern: view toggle (tile vs. list)`. `List` is also used, unrelatedly, for `RichTextEditor`'s bulleted-list formatting button — same icon, two unconnected contexts; not a collision worth resolving, just worth knowing both exist. |
| Loading | `Loader2` | |
| Sign out | `LogOut` | |
| Help | `HelpCircle` | |
| Entity/nav-rail markers, one icon per kind, not reused for anything else | `LayoutDashboard` (Overview), `ListChecks` (Requirements), `GitPullRequest` (Change Requests), `CheckSquare` (Actions), `FileText` (Reports), `Clock` (reviews due, project-scoped), `History` (Project History), `Settings` (Project Admin), `FolderKanban` (Projects), `CalendarClock` (My Reviews Due, cross-project), `Building2` (organisations — both "My organisations" and Server: Organisations reuse it, correctly, since both are about organisations), `Wrench` (Server Management) | Straight from `Layout.tsx`'s nav-rail link definitions — one settled icon per destination already; a new nav-rail entry should follow the same one-icon-per-entity-kind rule rather than reusing one of these for something unrelated. |
| Rich-text formatting (toolbar-only, not a general convention) | `Bold`, `Italic`, `Heading1`/`Heading2`/`Heading3`, `List`, `Link` (imported as `LinkIcon`), `Image` (imported as `ImageIcon`) | All `RichTextEditor.tsx`-only; the `as LinkIcon`/`as ImageIcon` import aliases are a naming detail (avoiding a collision with `react-router-dom`'s `Link` and the browser's native `Image` constructor), not two icons standing in for one meaning. |
