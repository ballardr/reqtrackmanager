# Module 11 — Acting on Behalf Of — Implementation Plan

See [future-modules-2026-09-index.md](future-modules-2026-09-index.md) for
cross-cutting architecture referenced throughout.

**Source:** not from `future-modules-2026-09-overview.md` — requested
directly by the user 2026-09-16 (motivating example: a decision is made in
a meeting, and the project manager — who wasn't necessarily the one who
made the call — is the one who actually updates the record; a reasoning
field should capture why). The user explicitly asked for this to be
tracked as its own numbered module rather than folded into Module 0,
which is the right call — see "Why this is not Module 0's problem" below.

**This is a security-sensitive plan.** It touches authorization directly,
so per `CLAUDE.md`'s policy-consultation rule,
[docs/soc2/policies/access-control-policy.md](../soc2/policies/access-control-policy.md)
was read in full before any of this was drafted, not after. That policy
states a core invariant, repeated across every existing exception in this
codebase (Personal Access Tokens, the MCP-channel approval restriction):
**"a caller can never gain access beyond what their real role already
grants."** Every mechanism in this codebase that touches who-can-do-what
so far only *narrows* access, never widens it. This module's central
design question — resolved in Phase 0, not assumed here — is whether it
stays inside that invariant or becomes the first exception to it. See "The
central fork" below.

**Status:** Proposed. Not started. No other module in this roadmap
depends on this one; it's an optional, cross-cutting capability that
*enriches* approval-shaped actions across the whole product — both the
nine new content modules and existing, already-shipped functionality
(`Requirement` approval, `ChangeRequest` decisions) — rather than being a
prerequisite for anything. It can be built at any point, independently of
build order elsewhere in this roadmap.

## Why this is not Module 0's problem

Module 0 is deliberately scoped to generic, policy-neutral data plumbing
(the relationship model, per-project sequence numbering) — infrastructure
with no authorization implications of its own, safe to build without a
security review beyond normal engineering care. This module is the
opposite: its entire point is to change who can be recorded as having
done what, which is exactly the category of change `CLAUDE.md` singles
out for mandatory policy consultation and, if the design ends up widening
access in any way, the identify → verify → remediate review
`docs/soc2/policies/change-management-and-secure-development-policy.md`
item 4 requires before it can be considered complete. Bundling it into
Module 0 would either force that scrutiny onto every other module riding
on Module 0's back, or (worse) let it slip through under Module 0's
lighter-weight "policy-neutral plumbing" framing. It gets its own module,
its own Phase 0, and its own explicit sign-off gate.

## Status / Resume Here

0 / 5 phases complete. Phase 0 is next.

| # | Phase | Status |
|---|-------|--------|
| 0 | Exploratory: the central fork, resolved with explicit user sign-off | [ ] Not started |
| 1 | Data model + evidence attachment + service helper (attribution-only path) | [ ] Not started |
| 2 | Backend integration into existing + new approval-shaped endpoints | [ ] Not started |
| 3 | Frontend UI | [ ] Not started |
| 4 | Docs website coverage | [ ] Not started — depends on Phase 3 |

*(Phase count and shape below assume Phase 0 resolves toward the
recommended, lower-risk option. If the user instead chooses the
higher-risk option, this plan's phases need a substantial rewrite — see
Phase 0's own note on this.)*

## Phase 0 — Exploratory: Requirements Clarification & Design Validation

**Why this phase carries unusual weight:** unlike almost every fork
elsewhere in this roadmap (table shape, field structure, naming), this one
has a real security posture attached to each side, not just an
implementation-cost trade-off. Getting it wrong in the direction of "more
capability than intended" is the kind of mistake `CLAUDE.md` explicitly
says must be flagged before it ships, not discovered by a later audit.

### The central fork

**Option A — Attribution only (recommended).** The user performing the
action must **already hold whatever permission that action normally
requires**, via their own real role — nothing about RBAC resolution
changes. What this module adds is a required, audited *annotation*:
"this action, which I was independently authorized to perform, is being
recorded as representing `<on_behalf_of_user>`'s decision/instruction,
for this reason: `<reasoning>`." A project manager who already holds
`PROJECT_MANAGER` and could approve a Decision anyway can additionally
record that they're doing so on behalf of the person who actually made
the call in a meeting. This is **fully consistent** with the access
control policy's core invariant — no caller ever gains anything they
didn't already have — and needs no security-boundary re-review beyond
normal engineering care, because it doesn't touch the boundary at all.

**Option B — True delegated authority (higher risk, not recommended by
default).** A user (A) can grant another user (B) — who does **not**
otherwise hold the relevant permission — the ability to act with A's
authority, scoped and time-bounded (e.g. B, who isn't a Decision Maker,
approves a specific Decision "as" A while A is on leave). This is a
genuine widening mechanism and would be the **first of its kind** in this
codebase — every existing bearer-credential/scope mechanism (PATs, module
frame tokens, the MCP channel restriction) is explicitly designed to only
ever narrow what a caller can do, never grant them anything new. Building
this means:
- A scoped, time-bounded grant record (delegator, delegate, what
  permission/role/artefact-type it covers, validity window or single-use,
  mandatory reasoning, revocable at any time by the delegator or an org
  admin).
- The RBAC resolution chain (`access-control-policy.md`'s "Diagram: role
  resolution") gaining a genuinely new resolution path, not just another
  scope composing with existing ones the way module-contributed roles do.
- A notification to A whenever a delegated grant is actually used, so
  delegation happening without A's awareness is at minimum visible after
  the fact.
- Treatment identical in weight to the "AI approval via MCP" precedent
  (`docs/decisions.md`'s entry of that name) — an explicit, deliberate,
  user-approved reopening of a boundary this policy currently treats as
  structural, with a full identify → verify → remediate review before any
  of it ships, not an agent default and not something this plan should
  design further until the user has explicitly chosen it over Option A.

**Recommendation: Option A.** The motivating example — a project manager
recording a decision made in a meeting they may not have been the one
driving — is fully satisfied by attribution: the PM already has authority
to update the project (that's the entire premise of "the project manager
needs to actually update the project"); what's missing today is only a
structured way to say *who the decision is really attributed to and why
the PM is the one typing it in*, not a way for someone lacking authority
to act anyway. Option B solves a different problem — a substitute
approver acting for someone who's genuinely unavailable, without the
substitute holding that authority themselves — which the user's example
doesn't obviously call for. **This is flagged for explicit user
confirmation before Phase 1, same as every fork in this roadmap** — not
assumed — but the rest of this plan (Phases 1–3, the acceptance criteria)
is written against Option A, since that's the recommended and
substantially better-understood path; if the user wants Option B, this
plan needs a real rewrite, not an extension.

### Other open questions for Phase 0 (assuming Option A)

1. **Validation of `on_behalf_of_user`.** Should the system require that
   the named on-behalf-of user actually holds (or held, at the time) a
   role that would itself have authorized this action — so "recorded on
   behalf of Jane" is only accepted if Jane could plausibly have approved
   this herself — or is it an unvalidated free choice of any user in the
   organisation/project? Recommend requiring org/project membership at
   minimum (prevents naming someone with no relationship to the work at
   all) and, where Module 8 (Governance) exists and has an approval policy
   for the artefact type in question, checking the named user against that
   policy's role requirement — degrading to membership-only validation
   where Governance isn't enabled, the same graceful-degradation pattern
   Module 10 (Reporting) uses.
2. **Where does the annotation live: a dedicated table, or audit-log
   detail only?** `AuditEvent.detail` (`backend/app/models/audit.py`) is
   already a free-form JSON field and could carry this without any new
   table at all. Recommend a dedicated table anyway (see Phase 1) —
   `ReviewComment`'s own precedent (a generic `target_type`/`target_id`
   table, not folded into the audit log) is because a UI needs to query
   and display this data directly (e.g. "recorded by X on behalf of Y,
   because Z" shown on the Decision detail page itself), which parsing
   arbitrary JSON out of the audit trail for isn't a good fit for. An
   audit-log entry is still written in addition, for the standard
   who/what/when trail.
3. **Is recording "on behalf of" mandatory, optional, or per-project
   configurable?** Recommend optional by default, with a per-project
   toggle for "require a reason when approving on behalf of someone else"
   — consistent with this roadmap's general "lightweight by default"
   principle, and avoiding forcing every approval in every project through
   an extra field most projects will never need.
4. **Does using this feature at all need its own RBAC gate?** Recommend
   no additional gate beyond whatever the underlying action already
   requires — since Option A never grants new capability, there is no
   privilege-escalation surface in letting any already-authorized actor
   use it. The MCP-channel restriction (`access-control-policy.md`,
   Authorization item 4's final, unnumbered paragraph) reasons about the
   same underlying invariant from the other direction — a restriction that
   can only ever narrow needs no new RBAC scope of its own either, because
   there's nothing to escalate to; this feature is the same shape, just an
   addition rather than a restriction.
5. **Which actions get this affordance first?** Recommend starting with
   the highest-value, already-identified cases: `Decision` approval
   (Module 4) — the user's own motivating example — plus the two existing
   approval actions already in production (`Requirement` approval,
   `ChangeRequest` decisions), rather than retrofitting every approval
   surface across all eleven modules in one pass. Extend to Design
   approval, Risk acceptance, Strategy approval, Compliance sign-off, and
   Governance-gated actions opportunistically as those modules are built.
6. **Inherent limitation, worth stating plainly rather than discovering
   later:** like every other free-text attestation already in this system
   (a Decision's own `rationale`, a `change_note`), there is no
   cryptographic or technical proof that "on behalf of Jane" is true — it
   is a trusted, honour-system claim by the recording user, backed by the
   audit trail's who/when, not by any verification that Jane actually said
   what's being attributed to her. This is consistent with how this
   system already treats every other free-text justification field, not a
   new class of risk this module introduces.

**Exit criteria:** user has explicitly chosen Option A or Option B, and
(if A) confirmed the open questions above, before Phase 1 starts. If B is
chosen, this plan's remaining phases must be rewritten before proceeding —
do not attempt to extend Phases 1–3 below to cover Option B by addition.

## Phase 1 — Data model + evidence attachment + service helper (attribution-only path)

**Scope:** `OnBehalfOfAnnotation` — `target_type`/`target_id` (polymorphic,
mirroring `ReviewComment`'s own shape, not FK'd to one table), `actor_id`
(who actually performed the action — already independently authorized),
`on_behalf_of_user_id`, `reasoning` (text, required whenever this record
exists at all — an annotation with no reasoning defeats its own purpose),
`created_at`. Plus `OnBehalfOfAnnotationFile` — a join table mirroring
`CommentFile`'s exact shape (`annotation_id`, `file_id` → the existing
`FileAsset`, `uploaded_by`), so evidence (an email screenshot, an exported
Teams/Slack thread, meeting minutes) can be attached to the annotation the
same way a file is already attached to a `ReviewComment` — reusing the
existing upload/storage/download machinery unchanged, not a new
attachment system. Plus a shared service helper
(`services/on_behalf_of.py::record`, or similar) that: (a) does **not**
perform or replace any authorization check — the caller's own normal RBAC
check for the underlying action happens first, unchanged, exactly as
today; (b) validates `on_behalf_of_user_id` per Phase 0 Q1's resolution;
(c) writes the `OnBehalfOfAnnotation` row plus any attached
`OnBehalfOfAnnotationFile` rows; (d) calls the existing
`services/audit.py::log_event` with this detail included, so the
standard audit trail also carries it.

**Why:** without a first-class, queryable record of this, "who really
made this call" either lives only in a Decision's own free-text rationale
(unstructured, not filterable, easy to omit) or nowhere at all — exactly
the gap the user's own example describes. Evidence attachment specifically
(added 2026-09-17, per the user's own follow-up) matters because the
underlying reasoning is usually going to point at something that happened
*outside* the system — a meeting, an email thread, a Teams/Slack
conversation — and a text field alone can't carry that; being able to
attach the actual email export or chat screenshot the reasoning refers to
is what makes the annotation independently checkable later, rather than
just a claim resting on the recording user's own account of it.

**Attachment is optional, not required** — mirroring `CommentFile`'s own
optional relationship to `ReviewComment` (a comment doesn't require a
file, and shouldn't here either: plenty of "on behalf of" recordings will
have no more evidence than the reasoning text itself, e.g. a decision
made in a meeting the recording user personally attended, with nothing
external to attach). No new validation logic is needed beyond whatever
`FileAsset` upload already enforces (size/type limits, storage backend) —
this phase adds a join table, not a new upload pipeline.

## Phase 2 — Backend integration into existing + new approval-shaped endpoints

**Scope:** per Phase 0 Q5's prioritisation — add an optional
`on_behalf_of_user_id`/`reasoning` pair to the request schema of
`approve_requirement`, `decide_change_request` (both already existing,
`backend/app/routers/requirements.py`/`change_requests.py`), and Decision
Management's own approval endpoint (Module 4 Phase 2) once that module
exists; call the Phase 1 helper from each. No change to any existing
authorization dependency (`require_project_manage` etc.) on any of these
endpoints — this phase is strictly additive.

**Why:** the two existing endpoints are the concrete, already-shipped
cases this module's motivating example maps onto most directly
(`decide_change_request` in particular — a change request decided
following a meeting is close to the literal scenario described); wiring
those first proves the mechanism against real, already-tested code paths
before extending it to every new module's own approval action.

**MCP tools — flagged, not resolved here (2026-09-21 addendum).** This
session's general instruction that every not-yet-built module plan get an
explicit MCP-tools commitment (**Decided by: User**) is deliberately *not*
applied to this module the same way it is to the others. This module has
no router of its own to attach a `McpToolDefinition` to in the first
place — Phase 2's own scope is additive fields on *existing* endpoints
(`approve_requirement`, `decide_change_request`, Decision Management's
`approve_decision_endpoint`), not a new module-owned surface, and `docs/
modules.md` §6's path-prefix constraint (a tool's `path_template` must fall
inside its *declaring* module's own router) means no tool could be
declared "by" this module regardless of intent.

The real question is narrower and more sensitive than "should this module
get MCP tools," and per this plan's own security framing it is flagged
here rather than defaulted either way (**Decided by: Agent, deliberately
unresolved**): should the `on_behalf_of_user_id`/`reasoning` fields Phase 2
adds to those existing endpoints' *response* schemas become visible
through the read-only MCP tools those artefacts already have or will have
(e.g. Decision Management's own `get_decision` tool, `backend/app/modules/
decisions/module.py`'s Phase 4 addendum)? Exposing "this was approved by
X, recorded as representing Y's decision, because Z" to an AI assistant
caller is a materially different disclosure than exposing the approval
itself: it can reveal internal delegation/command relationships (who is
really making calls behind whom) that may be sensitive independent of who
is authorized to view the underlying artefact, and unlike a plain approval
record it names a *second* person — the on-behalf-of subject — who took no
action visible anywhere else in that artefact's own fields. Handing that
to an automated caller is exactly the kind of exposure this plan's own
access-control framing above says must be checked before it ships, not
assumed safe because the underlying artefact read is already permitted.

This plan does **not** recommend silently including these fields in any
existing MCP-tool response schema by default. Before Phase 2 ships,
whichever phase actually owns the response schema being extended
(`requirements.py`, `change_requests.py`, or Decision Management's own
`schemas.py`) must explicitly decide, with the user, whether
`on_behalf_of_user_id`/`reasoning` (and any attached evidence file
metadata) should be: (a) included in the ordinary authenticated REST
response only, with that module's existing MCP-tool response left
unchanged from today (an MCP caller effectively doesn't see it — the
current default, requiring no action from this phase); (b) included, with
a documentation note added to `docs/mcp-server.md` that an AI assistant
reading this field must not treat it as more private than the approval it
annotates; or (c) deliberately stripped from whatever DTO the read-only
MCP path serves, even while the full REST response includes it for the
human-facing UI. This decision must be made explicitly at that point, not
defaulted to "expose everything the REST endpoint already returns," per
`CLAUDE.md`'s rule that a security-sensitive judgment call in this area
gets flagged to the user rather than shipped silently.

## Phase 3 — Frontend UI

**Scope:** an optional, collapsed-by-default "Recording on behalf of
someone else?" section on every approval/decision UI this module reaches
(per Phase 2's scope), with a user picker, a reasoning textarea, and an
optional evidence attachment control reusing the existing file-upload
component `CommentFile`'s own attachment UI already uses (per Phase 1 —
no new upload widget); display of existing annotations on the relevant
detail page ("Approved by X on behalf of Y — reason: ..." with any
attached evidence file listed/downloadable alongside it, the same as a
comment's own attachments render today), reusing whatever user-picker
component already exists elsewhere in the frontend rather than building a
new one (per the UX style guide's "one component per pattern" rule).
Playwright e2e + Storybook coverage per standing testing requirements,
including a case with an attached evidence file, not just the text-only
path.

## Phase 4 — Docs website coverage

**Goal:** add "Acting on Behalf Of" to `docs/website/` (the published docs
site, `docs/plans/docs-website-plan.md`) — what the annotation records,
when to use it, and its explicit boundary (it never grants authority, only
attributes an already-authorized action to someone else) — following the
site's existing structure, tone, and Mermaid-diagram conventions.

This phase is added per this session's instruction that every not-yet-built
module plan make explicit its docs-website coverage commitment (**Decided
by: User**, 2026-09-21); the specific scope below is **Decided by: Agent**.

**Why this is its own tracked phase, not folded silently into Phase 3:**
this feature's core value proposition is easy to misread as "delegated
authority" if documented casually — the site's own explanation needs to
state the Option A boundary as plainly as this plan itself does (see "The
central fork" above), so a reader doesn't come away believing this lets
one user act with another's permissions. A dedicated, checklist-visible
phase makes that framing an explicit exit criterion rather than an
afterthought bundled into a general approval-workflow page.

**Scope:**

- A docs-site page or section (wherever the site already documents
  approval workflows for Requirements, Change Requests, and — once it
  ships — Decision Management) covering: what recording "on behalf of"
  means and does not mean (explicitly, in the site's own words: it never
  grants the recording user or the named on-behalf-of user any capability
  neither already had — this plan's own first acceptance criterion); when
  to use it (the meeting-decision scenario that motivated this module);
  the required reasoning field and optional evidence attachment; and where
  it becomes visible (the artefact's own detail page, alongside the
  standard audit trail).
- A short Mermaid sequence diagram: actor performs an already-authorized
  action → normal RBAC check (unchanged) → optional on-behalf-of annotation
  recorded → both the mutation and the annotation land in the audit trail.
- Cross-link from wherever the site already documents Requirement approval,
  Change Request decisions, and (once it ships) Decision Management's own
  approval workflow, to this page — the annotation is only ever additive
  to an approval action those pages already describe, never a separate
  workflow of its own.
- A brief pointer, matching this plan's own "Documentation obligations"
  section below, to `docs/soc2/policies/access-control-policy.md`: the
  docs-site page covers *how a user uses it*, the SOC 2 policy covers
  *why it's safe*; the two are not duplicates of each other.
- **Screenshot requirement (2026-09-22 addendum).** Making this explicit
  here rather than leaving it implicit is **Decided by: User** (the same
  instruction as the phase itself, applied specifically to screenshots this
  time — `docs/plans/docs-website-plan.md`'s "Screenshots" section already
  bound this page to its standard, but this phase's Scope above never said
  so in as many words). This page is subject to that standard in full:
  1440×900 viewport, captured against the seeded demo dataset, stored
  under `docs/website/static/img/screenshots/`, real alt text plus a
  one-line caption. Plausible candidate screens (**Decided by: Agent**) are
  the expanded "Recording on behalf of someone else?" section on an
  approval UI (user picker, reasoning field) and the resulting "Approved by
  X on behalf of Y — reason: ..." display on the artefact's detail page.
  **Caution, mirroring this plan's own MCP-tools flag above:** unlike an
  ordinary approval record, that display names a second person who took no
  visible action of their own — the same category of disclosure this plan
  already treats as sensitive enough to gate behind an explicit decision
  for the read-only MCP path, rather than assumed safe because the
  underlying artefact read is already permitted. Even against the
  fictional seed dataset, whoever captures this screenshot should use a
  generic, business-neutral reasoning string (e.g. "attending an external
  meeting") rather than one that reads as personal, medical, or otherwise
  sensitive, so a screenshot meant to illustrate the feature doesn't itself
  model the kind of disclosure this plan is otherwise careful about.

**Status:** not started. Depends on Phase 3 (frontend) shipping — there is
no real user-facing workflow to document accurately before then, the same
reasoning Decision Management's own Phase 6 and Compliance's own
docs-website page each deferred to their frontend phase. Not a blocker for
this plan's own completion criteria beyond the ordinary docs-website rule.

## Documentation obligations specific to this module

Beyond the standard per-phase `docs/decisions.md` entry every module gets:
if and when this ships, `docs/soc2/policies/access-control-policy.md`
needs a new numbered item under Authorization describing the mechanism
(mirroring how the MCP-channel restriction and PAT scoping are each their
own numbered item today) — framed as a narrow, additive annotation
capability that does not alter the role-resolution chain, with an explicit
note (matching that policy's own existing style) confirming it was
reviewed against, and found consistent with, the "never gain access beyond
your real role" invariant. This is not optional documentation — per
`CLAUDE.md`, a change touching authorization that isn't reflected in the
adopted SOC 2 policy set is exactly the kind of gap that policy set is
meant not to have.

## Acceptance criteria (this plan's own synthesis — not from the overview, confirm with user)

- A user can record that an action they performed (and were already
  independently authorized to perform) represents another named user's
  decision or instruction, with a required reason.
- Recording this never grants the recording user, or the named
  on-behalf-of user, any capability either did not already have.
- The annotation is visible on the relevant artefact's own detail page,
  not only in the audit trail.
- The annotation is captured in the standard audit trail alongside every
  other mutating action.
- Supporting evidence (an email, a chat export, meeting minutes) can
  optionally be attached to an annotation, reusing the existing file
  attachment mechanism — never required, since not every annotation has
  external evidence to attach.
- An attached evidence file is only ever visible to someone who could
  already view the underlying artefact the annotation is attached to —
  never a separate or broader access boundary than that artefact's own,
  the same "a requirement's own attachment is gated by that requirement's
  access, never open more broadly" rule `download_file` already enforces
  for `ReviewComment`'s own attachments (`access-control-policy.md`'s
  report-image-boundary fix is the cautionary example of getting this
  check wrong for a *different* attachment path — worth checking this one
  explicitly against the same boundary before shipping, not assuming it's
  automatically correct because `CommentFile`'s mechanism is reused).
- Using this feature requires no RBAC grant beyond whatever the underlying
  action already required.
- `docs/soc2/policies/access-control-policy.md` documents the mechanism
  before it ships to production.
