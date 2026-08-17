# Project Instructions

## Validation

- User inputs may be written casually and can include imprecise terminology
- Agents must not only validate their own outputs but also challenge assumptions made by other agents where relevent.

## Documentation Requirements

- Prefer diagrams in documentation wherever they will improve clarity
- User Mermaid diagrams by default where possible
- Every diagram must include explanitory context immediately before or after it, including:
    - what the diagram represents
    - how to read the diagram (key actors, flows, boundaries), and
    - why it matters in the surrounding context
- Validate Mermaid diagrams before finalising to ensure they render correctly (no broken fences, no malformed syntax, no dangling nodes)
- Exception: screenshots/images in README.md do not need explanatory text immediately before or after them. The diagram rule above is about Mermaid diagrams conveying structure/flow that needs a reading key; README screenshots are illustrative product shots and a short caption (e.g. a table cell above each image) is sufficient — they must not be padded with "what this shows / why it matters" prose to satisfy the diagram rule.

When writing requirements:
- every requirement must include explicit reasoning
- Reasoning must state:
    - Why the requirement exists
    - What risk, defect class or constraint it addresses
    - The expected outcome if implemented

Any documentation output must maintain logical coherence, hierarchical consistancy and technology alignment.

All source files must include file-level documentation describing:
- The purpose of the module
- The responsibilities of the module
- Any important design decisions
- External dependencies or integrations

Example:

```python
"""
Module: user_service

Provides user account management functionality including:
- User creation
- User lookup
- User lifecycle management

This module is used by the API layer and should not directly access
HTTP request objects.
"""
```

## Function Documentation

Every function, method, and class must have documentation explaining:
- What it does
- Parameters and their types
- Return values
- Exceptions that may be raised
- Important side effects

Example:
```python
def calculate_total(items: list[Item]) -> Decimal:
    """
    Calculates the total cost of a collection of items.

    Args:
        items: List of items to calculate.

    Returns:
        The total monetary value of all items.

    Raises:
        ValueError: If an item has an invalid price.
    """
```

## Architecture and Environment Requirements

- The project must include a Docker Compose stack for testing, and this stack may also be used for general local running.
- The project must include documentation that:
  - describes what the project is
  - explains how to set up the development environment
  - explains how to run the project in both development and production environments
- The architecture should be designed with future scaling in mind, while starting with a single frontend container and a single backend container.
- The project should use PostgreSQL as its backend data store.
- The project must provide a method for monitoring service health, including container health checks and a Prometheus-compatible metrics endpoint that can be scraped for monitoring.
- The project should support Loki-based log aggregation and Tempo-based tracing, and the documentation should include setup instructions for both, including how to configure and use Grafana Alloy for shipping logs, traces, and metrics to these systems.
- As some requirements may be sensitive, designs must keep security at the forefront of architectural decisions.

## Compliance: SOC 2 Policy Adherence

- `docs/soc2/policies/` contains this project's adopted SOC 2 policy set (information security, access control, change management/secure development, system operations/monitoring/logging, incident response, vendor management, data classification/confidentiality, encryption/key management, data retention/disposal, risk assessment, security awareness training) and `docs/soc2/trust-services-criteria-mapping.md` maps them to the Security and Confidentiality Trust Services Criteria. These are binding on agent work in this repository, not just descriptive.
- Before making a change that touches authentication, authorization/RBAC, secrets or credentials, logging/audit trails, data retention or deletion, multi-tenant data isolation, or third-party/vendor integrations, consult the relevant policy in `docs/soc2/policies/` and follow it.
- Do not introduce a change that regresses a control described in these policies (e.g. weakening org/project-scoped authorization checks, logging or returning a Restricted-classified value such as a password hash or secret, storing a new secret in plaintext without noting it as a gap, bypassing the audit-logging pattern in `backend/app/services/audit.py` for a mutating action) without first flagging it explicitly to the user — do not silently ship a regression against an adopted policy.
- Follow [change-management-and-secure-development-policy.md](docs/soc2/policies/change-management-and-secure-development-policy.md)'s practice for security-sensitive changes specifically: run the existing test suites, and for anything touching the areas above, perform the same identify → verify → remediate review this codebase's own hardening passes use (see `docs/decisions.md`), recording the outcome there.
- These policies document existing gaps candidly (e.g. no CI gate, no account lockout, plaintext OIDC client secret) rather than hiding them — do not treat a documented gap as license to introduce further, unrelated ones. If new work closes one of these gaps, update the corresponding policy's "Known Gaps / Exceptions" section and the control matrix's Status column to reflect it.
- This section does not change the authority of [docs/requirements.md](docs/requirements.md), which remains the product requirements source of truth; the SOC 2 policies govern *how* changes are made, not *what* the product does.

## Frontend UX Style Guide Adherence

- [docs/ux-style-guide.md](docs/ux-style-guide.md) is binding on new and reworked frontend UI in this repository, not just descriptive — it is the direct output of a full UX audit ([docs/ux-audit-2026-08.md](docs/ux-audit-2026-08.md)) and states the rules the existing UI itself is being brought into line with.
- Before adding a new settings surface, create/edit flow, confirmation dialog, or destructive action in the frontend, consult the style guide's principles and patterns (settings hierarchy depth model, platform-default override visibility, create-as-a-layer, one-component-per-pattern, confirmation tiers, feedback-on-every-mutation, accessible control naming) and follow them rather than copying the nearest existing inconsistent example — "what did the last screen near this one do" is explicitly the failure mode the style guide exists to stop.
- Where a shared component the style guide calls for (`Tabs`, `SidePanel`, `Popover`, a two-tier confirm, `Toast`) does not exist yet, check [docs/ux-audit-2026-08.md](docs/ux-audit-2026-08.md)'s roadmap table first — it may already be scoped or in progress. Building a fifth one-off version of a pattern the style guide names is the exact debt this document was written to stop accruing (see that audit's "the newest feature already reproduces the pattern" finding).
- If a change must deviate from the style guide for a specific reason, say so explicitly to the user rather than silently diverging, and consider whether the style guide itself needs updating.
- This does not change the authority of [docs/requirements.md](docs/requirements.md); the style guide governs UI *pattern/structure* choices, not product scope.

## Documentation and Decision Governance

- The requirements document at [docs/requirements.md](docs/requirements.md) is fully authoritative and must not be changed by the agent. All decisions should be made in compliance with the requirements laid out in this document.
- The architecture document at [docs/solution-architecture.md](docs/solution-architecture.md) should be updated when there are architectural changes.
- The decisions log at [docs/decisions.md](docs/decisions.md) should be used to record architectural and implementation decisions.

## README Requirements

The README.md must always reflect the current state of the project.

When making significant changes, update the README to include:
- Project purpose
- Installation instructions
- Configuration requirements
- Usage examples
- Architecture overview
- Development workflow (a short section is sufficient — a pointer/summary linking to `docs/development.md` for the full local-setup/testing/linting/CI instructions satisfies this; the detailed how-to-hack-on-this-repo content belongs there, not duplicated inline)
- Known limitations
- Code Quality Rules
- Prefer clear, maintainable code over clever solutions.
- Do not introduce undocumented behaviour.
- Do not remove existing documentation unless it is incorrect.
- Update documentation when changing functionality.
- Add tests for new functionality.
- Code warnings (compiler/type-checker, linter, build-tool, and library deprecation warnings) must be fixed, not ignored, suppressed, or left in place. Do not silence a warning with an inline disable/ignore comment as a substitute for fixing it, unless the warning is a documented false positive.
- Do not edit linting configs (e.g. eslint/ruff/flake8/tsconfig rule sets and similar) to disable, downgrade, or narrow a rule as a way to make a warning go away. Fix the underlying code instead. A rule change is only acceptable when the rule itself is wrong for the project, and that must be raised with the user explicitly rather than done silently.
- When a dependency's current version is flagged as deprecated (by the library itself, its registry, or a warning it emits), upgrade it to a supported version or replacement. Never downgrade or pin to an older version to make a deprecation warning go away.
- When you find an issue or bug — including one unrelated to the current task, discovered incidentally during a review, hardening pass, or test run — fix it as part of the same piece of work. Never classify it as "out of scope to fix"; document-and-defer is not an acceptable substitute for fixing it.

## Testing Requirements

- Every new UI feature must come with a Playwright end-to-end test covering it — no UI feature is considered done until it has e2e coverage.
- Every new piece of frontend UI (component or page) must also have Storybook coverage set up as part of the same change — no new frontend development is considered done without accompanying Storybook stories, in addition to the Playwright e2e requirement above.
- Every backend change must come with a test that verifies the behaviour matches the request and pins it against future deviation/regression.
- `backend/scripts/seed_demo_data.py` (a small, realistic manual-demo dataset) and `backend/scripts/seed_e2e_dataset.py` (the fixed persona/org/project dataset the Playwright suite is written against) must be kept in sync with the current schema and feature set. Whenever a change adds/renames/removes a model field, table, enum value, or a whole feature area, check whether either script needs a corresponding update — new fields should be populated with a sensible demo value rather than left at a default that hides the feature, and a removed/renamed field or relationship must not be left referencing something that no longer exists. Treat a script that fails to run, or that no longer demonstrates a feature it used to, as a bug the same as a failing test.

## Frontend Dependency Changes

- CI (`ci.yml`) and `frontend/Dockerfile` both install with Node 24; `frontend/.nvmrc` pins the same major version for local use (`nvm use` in `frontend/`). Keep all three in lockstep when bumping Node in future — a mismatched local Node major version bundles a different npm major version, which can resolve transitive optional dependencies differently and write a `package-lock.json` that passes locally but fails CI's `npm ci` with "Missing: `<pkg>` from lock file". This has happened repeatedly.
- After adding, removing, or bumping a package in `frontend/package.json`, run `frontend/scripts/sync-lockfile.sh` (extra arguments pass through to `npm install`, e.g. a package name to add) rather than a bare `npm install` — it refuses to run under the wrong Node major version and re-verifies with `npm ci` before you commit.
- A tracked pre-commit hook (`.githooks/pre-commit`, wired up automatically via `frontend`'s `postinstall` script) also runs `npm ci --dry-run` whenever `frontend/package.json` or `package-lock.json` is staged, and blocks the commit if they're out of sync — this doesn't replace the step above, it's the backstop for when it's skipped.

## Playwright MCP Usage

- Use the Playwright MCP browser tools (`mcp__playwright__*`) sparingly — driving a live browser through MCP consumes tokens much faster than reading code or running the Playwright test suite directly.
- Prefer running the existing Playwright spec suite (via the CLI/Docker Compose stack) for verification. Reserve the MCP browser tools for targeted, one-off investigation of something the spec suite and static code reading can't resolve (e.g. confirming an actual rendered UI state or chasing a hard-to-reproduce bug).

## Agent Tool Isolation

- Do not default to `isolation: "worktree"` when spawning implementation agents in this repo. Edit the working tree directly.
- Only use `isolation: "worktree"` when there's a concrete reason: multiple agents genuinely running in parallel over the same files, or the user explicitly wants an easy-rollback branch for a risky change.
- Sequential background agents (one implementation pass after another, even across separate `Agent` calls) do not need isolation — nothing else is touching the repo concurrently, so a worktree adds `git merge`/`git worktree remove` bookkeeping and more complex resume prompts (exact worktree paths) for no benefit.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
