# Trust Services Criteria Mapping

This is the control matrix an auditor works through directly: every criterion in the 2017 Trust Services Criteria (as revised 2022) for **Security** (CC1–CC9) and **Confidentiality** (C1), mapped to how ReqTrackManager actually implements it — or doesn't yet.

## How to read this table

- **Control Description** states what ReqTrackManager (the application/technical control) or the Company (an organizational control) does to meet the criterion.
- **Evidence** points to the specific file, mechanism, or existing document that substantiates the control — an auditor should be able to go directly there.
- **Status**:
  - ✅ **Implemented** — the control exists today and is evidenced by the codebase.
  - 🟡 **Partially Implemented** — a real control exists but has a known gap; the gap is stated explicitly.
  - 🔴 **Gap — Organizational Action Required** — no technical control exists; this needs either an organizational process (most CC1/CC2/CC4/CC9 items — these are inherently about the Company, not the software) or new engineering work.

This matrix does not replace the individual policy documents in [policies/](policies/) — it summarizes and cites them.

## CC1 — Control Environment

| # | Criterion | Control Description | Evidence | Status |
| --- | --- | --- | --- | --- |
| CC1.1 | Commitment to integrity and ethical values | Company-level code of conduct and ethics policy | [policies/information-security-policy.md](policies/information-security-policy.md) §Acceptable Use | 🔴 Organizational action required — Company must adopt and communicate |
| CC1.2 | Board/governance oversight independent of management | Governance structure for the security program | **[Company must define]** | 🔴 Organizational action required |
| CC1.3 | Management establishes structure, authority, and reporting lines | Named information security owner; defined roles for server admin, org admin, engineering, ops | [policies/information-security-policy.md](policies/information-security-policy.md); application-level roles in [system-description.md](system-description.md) §7 | 🟡 Application-level roles exist and are enforced in code (`backend/app/services/rbac.py`); Company-level org chart is a placeholder |
| CC1.4 | Commitment to competence | Hiring, training, and role-appropriate skill requirements | [policies/security-awareness-training-policy.md](policies/security-awareness-training-policy.md) | 🔴 Organizational action required |
| CC1.5 | Enforces accountability | Individual accountability for actions is enforced at the system level via per-user audit logging | `backend/app/services/audit.py` (`log_event`, records `actor_id` on every mutating action); `LoginEvent` table for authentication events | ✅ Technically implemented; Company-level performance/accountability process is a placeholder |

## CC2 — Communication and Information

| # | Criterion | Control Description | Evidence | Status |
| --- | --- | --- | --- | --- |
| CC2.1 | Obtains/generates quality information to support internal control | System generates structured audit events and login history usable for control monitoring | `audit_events`, `login_events` tables; [policies/system-operations-monitoring-and-logging-policy.md](policies/system-operations-monitoring-and-logging-policy.md) | ✅ |
| CC2.2 | Internally communicates information necessary for internal control, including objectives and responsibilities | Policies are documented (this package); formal internal communication/training program | This package's [policies/](policies/) | 🔴 Documented, but not yet formally communicated/attested by staff — Company action required |
| CC2.3 | Communicates with external parties (customers, regulators) regarding matters affecting internal control | Customer-facing status/incident communication process; public documentation of the product's security posture | [README.md](../../README.md), [enterprise-integration.md](../enterprise-integration.md) describe technical behavior; formal customer notification process | 🔴 Organizational action required |

## CC3 — Risk Assessment

| # | Criterion | Control Description | Evidence | Status |
| --- | --- | --- | --- | --- |
| CC3.1 | Specifies objectives clearly enough to identify/assess risk | Product requirements and architectural goals are formally documented | `docs/requirements.md`, `docs/solution-architecture.md` §Architectural Goals | ✅ |
| CC3.2 | Identifies and analyzes risk to objectives, across the entity | Formal, recurring risk assessment process and risk register | [policies/risk-assessment-policy.md](policies/risk-assessment-policy.md) | 🔴 Process documented as a policy; no risk register or completed assessment exists yet — Company action required |
| CC3.3 | Considers the potential for fraud in assessing risk | Fraud-risk consideration folded into the risk assessment methodology; technical fraud-relevant controls (e.g. self-approval prevention) exist in the product | [policies/risk-assessment-policy.md](policies/risk-assessment-policy.md); e.g. a change request's submitter cannot approve their own request (enforced in `backend/app/routers/change_requests.py`, tested in `tests/playwright/tests/e2e-workflows/change-request-approval-separation.spec.ts`) | 🟡 |
| CC3.4 | Identifies and assesses changes that could significantly affect internal control | Architectural/security decisions are logged as they're made, including their risk rationale | `docs/decisions.md` (ongoing record of every architectural and security decision, including hardening passes) | ✅ Practice exists and is evidenced; not yet formalized as a standing process independent of engineering activity |

## CC4 — Monitoring Activities

| # | Criterion | Control Description | Evidence | Status |
| --- | --- | --- | --- | --- |
| CC4.1 | Performs ongoing and/or separate evaluations of whether controls are present and functioning | Automated test suites run on every push/PR and function as continuous control evaluation for application-level controls (RBAC boundaries, auth, workflow guarantees); periodic security review passes | `.github/workflows/ci.yml`; backend pytest suite (198 tests, ~90% line coverage, published per run); Playwright E2E suite; `docs/decisions.md`'s hardening-pass sections | ✅ CI now runs and gates on all of this automatically (was previously manual-only) — see [policies/change-management-and-secure-development-policy.md](policies/change-management-and-secure-development-policy.md). Branch protection requiring the check to pass before merge is not yet configured (a GitHub repo setting, not a workflow-file change) — Company action required |
| CC4.2 | Evaluates and communicates deficiencies to those responsible for corrective action | Findings from security review passes are documented and remediated, with the fix and rationale recorded | `docs/decisions.md` hardening-pass sections; this package's own creation is itself an instance of this (see the round of fixes in the "Massif (v3) hardening pass" section) | 🟡 Demonstrated in practice for engineering-driven reviews; no formal deficiency-tracking system (ticketing, SLA for remediation) exists — Company action required |

## CC5 — Control Activities

| # | Criterion | Control Description | Evidence | Status |
| --- | --- | --- | --- | --- |
| CC5.1 | Selects and develops control activities that mitigate risk to acceptable levels | RBAC, input validation, audit logging, and SSRF/CSRF-class fixes selected in direct response to identified risks | `backend/app/services/rbac.py`; `docs/decisions.md` security hardening sections | ✅ |
| CC5.2 | Selects and develops general controls over technology | Environment-variable-driven configuration with fail-fast validation in production; separate dev/test vs. production Compose stacks | `backend/app/config.py`; `docker-compose.yml` (fails to start without required secrets); [deployment.md](../deployment.md) | ✅ |
| CC5.3 | Deploys control activities through policies that establish expectations, and procedures that put policies into action | This package | [policies/](policies/) | 🟡 Policies drafted; formal deployment (owner sign-off, staff attestation) is a Company action |

## CC6 — Logical and Physical Access Controls

| # | Criterion | Control Description | Evidence | Status |
| --- | --- | --- | --- | --- |
| CC6.1 | Implements logical access security software/infrastructure/architecture | JWT-based authentication, bcrypt password hashing, TOTP-based 2FA, per-org OIDC SSO, `token_version`-based mass session revocation; the read-only MCP server (AI-assistant integration) reuses this same mechanism rather than a separate credential type, introducing no new access-control surface | `backend/app/security.py`, `backend/app/services/totp.py`, `backend/app/routers/auth_oidc.py`, `mcp-server/server.py` | ✅ See [policies/access-control-policy.md](policies/access-control-policy.md) |
| CC6.2 | Registers and authorizes new internal/external users prior to granting access | Org admins provision members and assign roles; SSO users are provisioned on first login gated by an optional required-group check; server admin bootstrap is config-gated | `backend/app/routers/orgs.py`; `backend/app/services/oidc_provisioning.py` (`find_or_provision_user`, `meets_required_group`) | ✅ |
| CC6.3 | Role-based access consistent with least privilege and segregation of duties | Org roles (org_admin, project_creator, member) and project roles (project manager, project administrator, stakeholder, member), independently scoped; server admin explicitly does not inherit organization content access | `backend/app/services/rbac.py`; `backend/app/models/enums.py` | ✅ A follow-up review found and fixed two endpoints (`deactivate_org_user`, `archive_org_user`) that scoped the caller's role correctly but not the *target* of the action to the same organization — see [policies/access-control-policy.md](policies/access-control-policy.md) |
| CC6.4 | Restricts physical access to facilities and protected information assets | Physical data center security | Relies entirely on the hosting/cloud provider — see [system-description.md](system-description.md) §10 (CSOCs) | 🔴 Carve-out to subservice organization — Company must name the provider and reference their report |
| CC6.5 | Discontinues logical/physical access when no longer required | Org admins can deactivate a member (`is_active = False`, immediately rejected on the next REST request and, since the hardening pass, within 60 seconds on an already-open WebSocket connection too); password-change/2FA-disable revoke all outstanding sessions via `token_version` | `backend/app/routers/orgs.py` (`deactivate_org_user`); `backend/app/routers/ws.py` (`_user_still_active`); `backend/app/security.py` (`token_version`) | 🟡 Deactivation and mass session revocation both take effect promptly now; there is still no automated offboarding trigger tied to an HR/identity-lifecycle event — that link is a Company process, not an application feature |
| CC6.6 | Implements controls to protect against threats from outside system boundaries | TLS termination and network exposure are the deployer's responsibility (the app serves plain HTTP internally by design); CORS origin allow-list; SSRF guard on org-configured OIDC endpoints | [deployment.md](../deployment.md) §TLS and reverse proxy; `backend/app/main.py` (`CORSMiddleware`); `backend/app/services/oidc_client.py` (`_assert_safe_external_url`) | 🟡 No rate limiting or brute-force/account-lockout protection on login exists yet — see [policies/access-control-policy.md](policies/access-control-policy.md) Known Gaps |
| CC6.7 | Restricts the transmission, movement, and removal of information to authorized users/processes | File attachments and reports are served only through authorization-checked endpoints, not directly from storage; storage credentials scoped per deployment.md's hardening guidance | `backend/app/routers/files.py`; [deployment.md](../deployment.md) §Hardening: scope MinIO credentials | ✅ |
| CC6.8 | Prevents or detects and acts upon unauthorized/malicious software | Endpoint/host-level malware protection, dependency vulnerability scanning | No automated dependency/container scanning exists in this repository | 🔴 Gap — see [policies/change-management-and-secure-development-policy.md](policies/change-management-and-secure-development-policy.md) |

## CC7 — System Operations

| # | Criterion | Control Description | Evidence | Status |
| --- | --- | --- | --- | --- |
| CC7.1 | Detects and monitors for configuration changes and vulnerabilities that could introduce risk | Container health checks; optional Prometheus/Loki/Tempo/Grafana Alloy observability stack; disk-usage monitor with alerting | `docker-compose.yml` health checks; `--profile observability`; [deployment.md](../deployment.md) §Observability | 🟡 Infrastructure/app monitoring exists; no dependency/CVE vulnerability scanning — see CC6.8 |
| CC7.2 | Monitors system components for anomalies indicative of security events | `/health` and `/metrics` (Prometheus-format) endpoints; structured audit and login-event logging; failed-login events recorded, including 2FA verification attempts and SSO logins (both previously missing, closed in the hardening pass) | `backend/app/main.py` (`/health`, `/metrics`); `backend/app/services/audit.py`; `backend/app/routers/auth.py` (`verify_2fa`); `backend/app/routers/auth_oidc.py` (`oidc_callback`) | 🟡 Data capture is now comprehensive across native, 2FA, and SSO login paths, and audit-event coverage was extended to the mutating endpoints a review found missing it (org branding/report-template/project-settings/component-category/CR-task-vote/custom-field/requirement-link actions); no automated alerting rules/SIEM correlation on top of the captured data exists yet |
| CC7.3 | Evaluates security events to determine whether they represent an incident | Incident classification process | [policies/incident-response-plan.md](policies/incident-response-plan.md) | 🔴 Process documented; not yet exercised — Company action required |
| CC7.4 | Responds to identified security incidents | Incident response plan, including a concrete technical containment tool (mass session revocation) | [policies/incident-response-plan.md](policies/incident-response-plan.md); `token_version` revocation (`backend/app/security.py`) | 🟡 |
| CC7.5 | Identifies, develops, and implements activities to recover from identified security incidents | Backup/restore scripts; recovery runbook | `scripts/backup.sh`, `scripts/restore.sh`; [deployment.md](../deployment.md) §Database | 🟡 Backup/restore tooling exists but is **not scheduled automatically** — the operator must configure cron/a scheduler, and must periodically test restores (documented but not enforced) |

## CC8 — Change Management

| # | Criterion | Control Description | Evidence | Status |
| --- | --- | --- | --- | --- |
| CC8.1 | Authorizes, designs, develops/acquires, configures, documents, tests, approves, and implements changes to infrastructure, data, software, and procedures | Every change to schema, security-sensitive logic, or architecture is recorded with rationale; automated test suites gate correctness in CI; separate dev/test vs. production Compose stacks prevent test runs from touching production data; production container images are built (validating both Dockerfiles) on every change | `docs/decisions.md`; `backend/tests/`, `tests/playwright/`; `.github/workflows/ci.yml`; [deployment.md](../deployment.md) §Two separate Compose stacks | 🟡 The CI gate itself now exists and runs automatically; **no enforced code review requirement** (branch protection) exists yet — see [policies/change-management-and-secure-development-policy.md](policies/change-management-and-secure-development-policy.md) |

## CC9 — Risk Mitigation

| # | Criterion | Control Description | Evidence | Status |
| --- | --- | --- | --- | --- |
| CC9.1 | Identifies, selects, and develops risk mitigation activities for risks arising from potential business disruptions | Business continuity / disaster recovery plan | Out of scope for this package (Availability TSC not selected — see [README.md](README.md) §Scope); backup/restore tooling exists as a partial technical foundation | 🔴 Out of scope by decision, but flagged: any future Availability-scoped engagement needs a formal BC/DR plan, which does not exist |
| CC9.2 | Manages risks associated with vendors and business partners | Vendor identification, due diligence, and ongoing monitoring | [policies/vendor-and-subprocessor-management-policy.md](policies/vendor-and-subprocessor-management-policy.md); [system-description.md](system-description.md) §8 | 🔴 Subservice organizations identified structurally; no due-diligence records or subprocessor list exist yet — Company action required |

## C1 — Confidentiality

| # | Criterion | Control Description | Evidence | Status |
| --- | --- | --- | --- | --- |
| C1.1 | Identifies and maintains confidential information to meet the entity's objectives | Data classification scheme; multi-tenant isolation enforced at the RBAC/query layer; secrets sourced from environment configuration, never hardcoded; genuine secret columns (`oidc_client_secret`, `smtp_password`, `totp_secret`) encrypted at the application layer | [policies/data-classification-and-confidentiality-policy.md](policies/data-classification-and-confidentiality-policy.md); `backend/app/services/rbac.py`; `backend/app/models/encrypted_type.py`; [system-description.md](system-description.md) §7 | ✅ The previously-known plaintext-secret gap is resolved; see [policies/encryption-and-key-management-policy.md](policies/encryption-and-key-management-policy.md) |
| C1.2 | Disposes of confidential information to meet the entity's objectives | Account deactivation; retention/disposal policy | [policies/data-retention-and-disposal-policy.md](policies/data-retention-and-disposal-policy.md) | 🔴 Deactivation exists (`is_active = False`); no automated data purge/hard-deletion or documented retention schedule exists yet — Company action required

## Summary of gaps requiring action before an audit

1. **No branch protection enforcing the CI check before merge.** CI itself now runs and gates (see below); requiring it to pass before merge is a GitHub repo setting, not a workflow-file change — Company action required. (CC8.1)
2. **No account lockout / brute-force protection on login.** (CC6.6)
3. **No automated dependency/container vulnerability scanning.** (CC6.8, CC7.1)
4. **No formal, scheduled backup automation** — scripts exist but must be operator-scheduled; restore testing isn't enforced. (CC7.5)
5. **No formal risk register, vendor due-diligence records, or deficiency-tracking system.** (CC3.2, CC9.2, CC4.2)
6. **Container images are built in CI but not published** — deliberate, pending sufficient real-world (developer) usage; see [policies/change-management-and-secure-development-policy.md](policies/change-management-and-secure-development-policy.md). Not a gap to close by default, just to revisit later.
7. **Every 🔴 organizational item above** — these require the Company to staff and operationalize a program around this documentation, not further engineering work.

**Resolved since the initial control matrix** (see `docs/decisions.md`): plaintext secret storage (C1.1), the cross-org account-deactivation authorization gap (CC6.3), missing 2FA/SSO login-event and audit-trail coverage (CC7.2), the WebSocket deactivation-recheck window (CC6.5), and — this pass — the complete absence of a CI pipeline (CC4.1, CC8.1), which was previously the single most consequential gap in this whole matrix.
