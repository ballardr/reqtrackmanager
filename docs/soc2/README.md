# SOC 2 Documentation Package

This folder is ReqTrackManager's SOC 2 readiness documentation: the system description, control matrix, and policy set an auditor expects to review at the start of a SOC 2 engagement. It was generated from the current state of the codebase and its existing documentation (`docs/decisions.md`, `docs/solution-architecture.md`, `docs/deployment.md`, `docs/enterprise-integration.md`) rather than written independently of it, so every control claim here is traceable to a real mechanism — a file, a config setting, a test — not a generic boilerplate assertion.

## Scope

Per the operating organization's decision, this package is scoped to two Trust Services Criteria:

- **Security** (the "Common Criteria," CC1–CC9) — mandatory for any SOC 2 report.
- **Confidentiality** (C1) — included because organizations store requirements and change-request content that is typically commercially sensitive, and the platform is multi-tenant.

**Availability** and **Processing Integrity** are explicitly out of scope for this package. If a future engagement adds them, they'll need their own control documentation (Availability in particular would need a formal Business Continuity / Disaster Recovery plan, which does not exist yet — see the Known Limitations note below).

## What's in this folder

| Document | Purpose |
| --- | --- |
| [system-description.md](system-description.md) | The SOC 2 "system description" (AICPA description criteria): infrastructure, software, people, data, procedures, system boundaries, and the subservice organizations and complementary user-entity controls the report will need to carve out. |
| [trust-services-criteria-mapping.md](trust-services-criteria-mapping.md) | The control matrix: every CC1–CC9 and C1 criterion, mapped to how ReqTrackManager actually implements it (or doesn't yet — gaps are marked, not hidden). This is the document an auditor will work through line by line. |
| [policies/](policies/) | The individual policy documents the matrix cites as evidence — information security, risk assessment, access control, change management, operations/monitoring, incident response, vendor management, data classification/confidentiality, encryption, data retention, and security awareness training. |

## What this package is — and isn't

This is a **documentation baseline**, not a completed audit and not a substitute for organizational adoption:

- **Placeholders need filling in.** Anything in `[brackets]` — the legal entity name, named policy owners, review dates, a risk register, a subprocessor list — is specific to the company operating this software, not to the software itself, and can't be generated from the codebase. Fill these in before presenting this package to an auditor.
- **Policies need formal adoption.** A policy document only counts as a control once a named owner has approved it, dated it, and the organization can show it was actually communicated (CC2.2) — none of that exists yet; these are drafts ready for that step.
- **Type II needs operating evidence, not just design evidence.** A SOC 2 Type II report attests that controls operated effectively over an observation window (commonly 3–12 months) — access review tickets, incident response records, actual backup/restore test logs, code review history. This package documents control *design*; it cannot manufacture a history of control *operation*. A Type I report (design only, as of a point in time) is achievable sooner than Type II.
- **Gaps are marked, not smoothed over.** Several controls a SOC 2 auditor will expect either don't exist yet or are only partially implemented — e.g., no automated CI/test-gating pipeline, no account-lockout/brute-force protection on login, no formal vendor due-diligence process, OIDC client secrets stored without application-layer encryption. Each is called out explicitly in the relevant policy and in the control matrix's Status column, with a recommendation, rather than described in a way that would mislead an auditor or the organization's own leadership.

## How the pieces relate to the rest of `docs/`

This package deliberately doesn't duplicate content that already lives elsewhere in `docs/` — it cites it. `solution-architecture.md` remains the source of truth for how the system is built; `deployment.md` remains the source of truth for how to operate it; `decisions.md` remains the record of *why* specific security choices were made (including the two prior hardening passes referenced throughout the control matrix). `docs/requirements.md` is unrelated to this package and was not consulted or changed — it's this application's own product requirements, not the operating organization's compliance requirements.
