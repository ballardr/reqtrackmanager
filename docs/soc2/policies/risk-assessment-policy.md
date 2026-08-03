# Risk Assessment Policy

| | |
| --- | --- |
| Policy Owner | **[Name / Title]** |
| Approved By | **[Name / Title]** |
| Effective Date | **[YYYY-MM-DD]** |
| Review Cadence | Annually, and upon significant change to the system, its data, or its threat landscape |
| Applies To | Engineering, Operations, and the information security owner |

## Purpose

Satisfies CC3.1–CC3.4: the Company must be able to show it identifies, analyzes, and responds to risks to its objectives, including fraud risk and risk introduced by change. See [trust-services-criteria-mapping.md](../trust-services-criteria-mapping.md) §CC3.

## Scope

Covers risk to the ReqTrackManager application, its infrastructure, and the data it processes — technical risk (vulnerabilities, architecture weaknesses), operational risk (process failures), and third-party risk (see [vendor-and-subprocessor-management-policy.md](vendor-and-subprocessor-management-policy.md)).

## Policy

1. **Objectives are documented first.** Risk cannot be assessed against undefined objectives — `docs/requirements.md` and `docs/solution-architecture.md` §Architectural Goals serve this role for the product itself; the Company must separately state its business/compliance objectives. (CC3.1)
2. **A formal risk assessment is performed at least annually**, and additionally whenever a significant change occurs (new major feature touching authentication/authorization, a new subprocessor, a security incident, a new regulatory obligation). **[Company must schedule and execute the first one.]** (CC3.2, CC3.4)
3. **The assessment considers fraud risk explicitly**, not only accidental/technical risk — e.g., could a user forge approval of their own change request, could an org admin grant themselves access to another organization, could an SSO-provisioned account bypass the required-group gate. Several of these specific fraud-adjacent scenarios are already covered by targeted tests (see Implementation below) rather than left purely theoretical. (CC3.3)
4. **Findings are recorded in a risk register** listing: the risk, its likelihood/impact, the mitigating control (existing or planned), the owner, and the target date. **[Company must create and maintain this register — a template is not included here since its content is Company-specific, but every 🔴/🟡 row in `trust-services-criteria-mapping.md` is a reasonable starting entry.]**
5. **Risk acceptance requires explicit sign-off** by the information security owner; risk cannot be silently accepted by omission.
6. **New risks discovered during engineering work are captured, not just audit-cycle risks.** This is already the de facto practice for this codebase — see Implementation below — and this policy formalizes it as a requirement rather than an incidental habit.

## Roles and Responsibilities

| Role | Responsibility |
| --- | --- |
| Information security owner | Owns the risk register, schedules assessments, tracks remediation |
| Engineering | Surfaces technical risk discovered during development/review; implements agreed mitigations |
| Management | Approves risk acceptance decisions |

## Implementation in ReqTrackManager

This codebase already has a working, if informal, version of steps 3 and 6 above: `docs/decisions.md` records a running history of identified risks and their fixes, including two full security-hardening passes that specifically probed for privilege-escalation, IDOR, SSRF, and login-CSRF-class risks (see the "Security hardening pass" and "Massif (v3) hardening pass" sections) using a structured identify → independently re-verify → remediate process. Fraud-relevant risk (CC3.3) has concrete technical mitigations already in place and tested, e.g.:

- A change request's submitter cannot approve their own request (`backend/app/routers/change_requests.py`; `tests/playwright/tests/e2e-workflows/change-request-approval-separation.spec.ts`).
- Org-scoped user-listing/filter endpoints require admin rights *of that specific organization*, not admin rights anywhere (`backend/app/routers/orgs.py`; negative-path tests in `backend/tests/test_access_review.py`).
- SSO-provisioned accounts cannot bypass an organization's required-group access gate (`backend/app/services/oidc_provisioning.py::meets_required_group`).

What's missing is the formal cadence and register (steps 2 and 4) — the mitigations exist, but they weren't produced by a scheduled risk assessment process; they were produced by ad hoc engineering review. Turning that from "happens when someone thinks to look" into "happens on a schedule, tracked to closure" is the concrete gap this policy closes going forward.

## Known Gaps / Exceptions

No risk register exists yet; no formal assessment has been scheduled. See [trust-services-criteria-mapping.md](../trust-services-criteria-mapping.md) CC3.2 row.

## Related Documents

[vendor-and-subprocessor-management-policy.md](vendor-and-subprocessor-management-policy.md), [incident-response-plan.md](incident-response-plan.md), `docs/decisions.md`.
