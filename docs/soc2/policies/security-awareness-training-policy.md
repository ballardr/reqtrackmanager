# Security Awareness Training Policy

| | |
| --- | --- |
| Policy Owner | **[Name / Title]** |
| Approved By | **[Name / Title]** |
| Effective Date | **[YYYY-MM-DD]** |
| Review Cadence | Annually |
| Applies To | All employees and contractors |

## Purpose

Satisfies CC1.4: the Company's commitment to competence, specifically that staff understand their security responsibilities. See [trust-services-criteria-mapping.md](../trust-services-criteria-mapping.md) §CC1.

This policy is almost entirely organizational rather than technical — it cannot be evidenced by the codebase the way access control or logging can, because it's about people and process, not software. It is included in full for completeness, not abbreviated, since a SOC 2 auditor will ask for it by name.

## Scope

Applies to everyone with access to Company systems, regardless of role — engineering staff and non-engineering staff alike, since account compromise (phishing, credential reuse) is not an engineering-only risk.

## Policy

1. **All new hires/contractors complete security awareness training before being granted system access**, covering at minimum: acceptable use ([information-security-policy.md](information-security-policy.md)), phishing/social-engineering recognition, credential hygiene (unique passwords, use of 2FA), and how to report a suspected incident ([incident-response-plan.md](incident-response-plan.md)).
2. **All staff complete refresher training at least annually.**
3. **Engineering staff additionally receive role-specific secure-development training**, covering the OWASP Top 10 class of vulnerabilities and this codebase's own secure-development conventions ([change-management-and-secure-development-policy.md](change-management-and-secure-development-policy.md)).
4. **Completion is tracked and attestable** — the Company must be able to show, per person, that training was completed and when. **[Company must select/implement a tracking mechanism — an LMS, a signed form, or equivalent.]**
5. **Policy acknowledgment is separate from training completion**: staff must separately attest that they have read and agree to follow this policy set (`docs/soc2/policies/`), not only that they sat through a training session.

## Roles and Responsibilities

| Role | Responsibility |
| --- | --- |
| **[HR/People Ops or equivalent]** | Schedules and tracks training completion for new hires and annual refreshers |
| Information security owner | Defines training content and reviews it annually |
| Engineering lead | Defines and delivers the secure-development-specific training component |

## Implementation in ReqTrackManager

Not applicable in the code-evidence sense — this control lives entirely in Company process. The closest thing this repository offers is a *reference point* for what role-specific secure-development training should actually cover: the hardening-pass write-ups in `docs/decisions.md` are real, concrete examples of the vulnerability classes (SSRF, IDOR, login-CSRF/session-fixation) engineering staff should be trained to recognize, since they're this application's own history rather than generic examples.

## Known Gaps / Exceptions

No training program, tracking mechanism, or completion records currently exist. This entire policy is a Company action item.

## Related Documents

[information-security-policy.md](information-security-policy.md), [incident-response-plan.md](incident-response-plan.md), [change-management-and-secure-development-policy.md](change-management-and-secure-development-policy.md), `docs/decisions.md`.
