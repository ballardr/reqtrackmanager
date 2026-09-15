---
sidebar_position: 3
---

# SOC 2 compliance posture

ReqTrackManager ships with an adopted SOC 2 policy package and a Security + Confidentiality Trust Services Criteria (TSC) control matrix, maintained in the repository at [`docs/soc2/`](https://github.com/ballardr/reqtrackmanager/tree/main/docs/soc2). This page summarises what that package is and what it says — candidly, including what's still a gap — rather than reproducing it in full; the source documents are the ones an auditor (or a prospective customer's security review) would actually work through.

## What's been done

- A **system description** covering infrastructure, software, people, data, and system boundaries.
- Eleven individual **policies** — information security, risk assessment, access control, change management/secure development, system operations/monitoring/logging, incident response, vendor and subprocessor management, data classification and confidentiality, encryption and key management, data retention and disposal, and security awareness training.
- A **control matrix** mapping every criterion in the Security (CC1–CC9) and Confidentiality (C1) Trust Services Criteria to a concrete control, grounded in the actual codebase rather than generic template language — each row cites the specific file or mechanism an auditor could go read directly (`backend/app/services/rbac.py`, `backend/app/services/audit.py`, and so on), not just a policy statement.

This is groundwork that would be useful if a real SOC 2 engagement is ever undertaken — it is **not** a claim of a finished audit, a certification, or an attestation from any third party.

## What's genuinely in place today

The policy package doesn't just describe intent; it points at controls that already exist and are exercised:

- **Tenant isolation** enforced at the RBAC/authorization layer on every organisation- and project-scoped request — see [Roles, groups, and access control](../concepts/roles-groups-and-access-control.md).
- **Audit and login-event logging** covering mutating actions and both successful and failed authentication attempts, including 2FA and SSO logins.
- **Application-layer encryption** for every genuinely sensitive stored secret (OIDC client secrets, SMTP passwords, TOTP secrets) — see [Encryption and secrets handling](./encryption-and-secrets-handling.md).
- **Automated test suites gating every change** in CI (backend pytest, Playwright end-to-end specs), which the control matrix treats as continuous evaluation of application-level controls, not just a development-quality check.
- **Two-factor authentication and scoped personal access tokens** — see [Two-factor auth and personal access tokens, security angle](./two-factor-auth-and-pats-security.md).

## Known gaps, stated candidly

The control matrix's own summary lists what's still open, rather than treating a documented gap as closed. As of this page's writing, the gaps requiring attention before a real audit include:

- **No branch protection enforcing the CI check before merge** — CI runs and gates on every push and PR, but requiring it to pass before a merge is allowed is a repository setting, not yet configured.
- **No account lockout or brute-force protection on the first-factor password check** — the second-factor (2FA) challenge step does lock out after repeated failed codes; the initial password check doesn't yet.
- **No automated dependency or container vulnerability scanning.**
- **No formal, scheduled backup automation** — backup/restore scripts exist, but scheduling and restore testing are left to the operator.
- **No formal risk register, vendor due-diligence records, or deficiency-tracking system.**
- A number of purely **organisational** items — a named information security owner, a governance structure, staff training and attestation — that describe the operating company adopting this software, not the software itself, and so can't be closed by an engineering change at all.

The full, current list — including which items have already been resolved since the package was first written — lives in [`docs/soc2/trust-services-criteria-mapping.md`](https://github.com/ballardr/reqtrackmanager/tree/main/docs/soc2/trust-services-criteria-mapping.md)'s own "Summary of gaps" section, which is the authoritative version of this list rather than this page's snapshot of it.

## Where this fits

- [Encryption and secrets handling](./encryption-and-secrets-handling.md) and [Two-factor auth and personal access tokens, security angle](./two-factor-auth-and-pats-security.md) — the two feature areas this page cross-links into for their own security rationale, rather than repeating it here.
- The full policy package in the repository at [`docs/soc2/`](https://github.com/ballardr/reqtrackmanager/tree/main/docs/soc2) — start with `README.md` there for how the package is organised, then `trust-services-criteria-mapping.md` for the row-by-row control matrix.
