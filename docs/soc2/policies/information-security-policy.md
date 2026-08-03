# Information Security Policy

| | |
| --- | --- |
| Policy Owner | **[Name / Title, e.g. Head of Engineering / CISO]** |
| Approved By | **[Name / Title]** |
| Effective Date | **[YYYY-MM-DD]** |
| Review Cadence | Annually, and after any significant security incident or system change |
| Applies To | All employees, contractors, and any third party with access to ReqTrackManager systems or data |

## Purpose

This policy establishes the Company's overall commitment to protecting the confidentiality, integrity, and availability of information processed by ReqTrackManager, and sets the governance structure that every other policy in this package (access control, change management, incident response, etc.) operates under. It exists to satisfy CC1.1–CC1.5 and CC5.3 of the SOC 2 Common Criteria — see [trust-services-criteria-mapping.md](../trust-services-criteria-mapping.md).

## Scope

This policy applies to the ReqTrackManager application, its supporting infrastructure, and everyone who develops, operates, or administers it. It does not apply to customer organizations' own internal security practices, except where a specific complementary user-entity control is called out in [system-description.md](../system-description.md) §9.

## Policy

1. The Company designates a named **information security owner** responsible for this policy set, for tracking exceptions, and for reporting security posture to leadership. **[Name the role/person.]**
2. Security is a shared responsibility: every individual with system access is responsible for following this policy and reporting suspected incidents per [incident-response-plan.md](incident-response-plan.md).
3. This policy set (this document plus every other document in `docs/soc2/policies/`) must be reviewed at least annually and re-approved by the policy owner. Reviews driven by a significant change (e.g. a new subprocessor, a security incident, a major architecture change) supersede the annual cadence.
4. Policy exceptions must be documented, time-bound, and approved by the information security owner — an exception is not a silent deviation.
5. Violations of this policy by staff are subject to the Company's standard disciplinary process. **[Company must define.]**
6. This policy, and the technical controls it governs, are designed around the principle of least privilege and defense in depth — no single control is treated as sufficient on its own. This is reflected structurally in the product: authentication, RBAC, audit logging, and input validation are independent layers (see [access-control-policy.md](access-control-policy.md)), not one combined check.

## Acceptable Use

1. Company systems and access credentials are to be used only for authorized business purposes.
2. Individuals must not share credentials, circumvent access controls, or attempt to access data outside their authorized scope (including another customer organization's data — the multi-tenant boundary described in [system-description.md](../system-description.md) §7).
3. Individuals must report lost/stolen devices or suspected credential compromise immediately per [incident-response-plan.md](incident-response-plan.md).
4. Use of Company systems to install unauthorized software, disable security controls, or exfiltrate data outside authorized workflows is prohibited.

## Roles and Responsibilities

| Role | Responsibility |
| --- | --- |
| Information security owner | Owns this policy set, tracks exceptions, reports on security posture |
| Engineering | Implements technical controls, follows secure development practices ([change-management-and-secure-development-policy.md](change-management-and-secure-development-policy.md)) |
| Operations | Operates infrastructure per [system-operations-monitoring-and-logging-policy.md](system-operations-monitoring-and-logging-policy.md) |
| All staff | Follow acceptable use, complete security awareness training ([security-awareness-training-policy.md](security-awareness-training-policy.md)), report incidents |

## Implementation in ReqTrackManager

Application-level enforcement of "least privilege, defense in depth" is concrete, not aspirational: authentication (`backend/app/security.py`, `backend/app/services/totp.py`), authorization/RBAC (`backend/app/services/rbac.py`), and audit logging (`backend/app/services/audit.py`) are three independently-invoked layers on every mutating request — a bug in one does not silently disable the others. The repeated hardening passes recorded in `docs/decisions.md` are the evidence this design intent holds up under adversarial review, not just in the abstract.

## Known Gaps / Exceptions

No formal governance structure, named owner, or staff communication/attestation process exists yet — this is the primary Company action item this policy package surfaces. See [trust-services-criteria-mapping.md](../trust-services-criteria-mapping.md) CC1/CC2 rows.

## Related Documents

[system-description.md](../system-description.md), [trust-services-criteria-mapping.md](../trust-services-criteria-mapping.md), and every other policy in this folder.
