# Vendor and Subprocessor Management Policy

| | |
| --- | --- |
| Policy Owner | **[Name / Title]** |
| Approved By | **[Name / Title]** |
| Effective Date | **[YYYY-MM-DD]** |
| Review Cadence | Annually, and whenever a new subprocessor is onboarded |
| Applies To | Anyone with authority to select or configure a third-party service the application depends on |

## Purpose

Satisfies CC9.2: managing risk associated with vendors and business partners. See [trust-services-criteria-mapping.md](../trust-services-criteria-mapping.md) §CC9.

## Scope

Covers every third party whose service the Company relies on to operate ReqTrackManager or whose service processes Company/customer data on the Company's behalf — cloud hosting, SMTP delivery, object storage, and (for organizations that enable it) each customer's own external OIDC identity provider.

## Policy

1. **Every subprocessor must be identified and documented** in a maintained list (name, function, what data it can access, its own compliance posture). **[Company must create and maintain this list — see [system-description.md](../system-description.md) §8 for the structural starting point.]**
2. **Before engaging a new subprocessor that will process customer data**, the Company performs due diligence proportionate to the risk — at minimum, reviewing the vendor's own security/compliance attestations (e.g. their SOC 2 report, if they have one) and their data processing terms.
3. **Credentials issued to a subprocessor are scoped to the minimum access required**, not shared administrative credentials. This is not merely a policy statement here — the deployment guide contains a worked example of doing exactly this for the bundled object storage backend (see Implementation below), and the same principle must be applied to every other subprocessor credential (SMTP, cloud provider IAM, etc.).
4. **Material changes to the subprocessor list are communicated to affected customers** in advance where contractually required (common in customer DPAs — e.g. a 30-day notice-and-objection window before a new subprocessor goes live).
5. **A customer-supplied OIDC identity provider (SSO) is not treated as a Company-managed subprocessor**, since the Company neither selects nor operates it — but its trust boundary must be understood and documented, since a compromised customer IdP could provision accounts into that customer's own organization. This is a shared-responsibility boundary, not a gap: the Company's control ends at validating the IdP's signed tokens (see [enterprise-integration.md](../enterprise-integration.md)); trusting what that IdP asserts about a user's identity is the customer's own responsibility once they've chosen to enable SSO.

## Roles and Responsibilities

| Role | Responsibility |
| --- | --- |
| Information security owner | Maintains the subprocessor list, approves new subprocessors |
| Engineering/Operations | Provisions scoped (not administrative) credentials for each subprocessor |

## Implementation in ReqTrackManager

The application's structural subprocessor categories are fixed by its architecture and enumerated in [system-description.md](../system-description.md) §8: a hosting/cloud provider, an SMTP provider, an S3-compatible object storage provider, and (opt-in, per organization) that organization's own OIDC identity provider. `deployment.md`'s "Hardening: scope MinIO credentials" section is a concrete, already-written example of policy point 3 above — it walks through moving the backend off the storage provider's root administrator credentials onto a bucket-scoped service account, specifically so that a backend compromise or leaked environment variable doesn't grant broader access than the application actually needs.

## Known Gaps / Exceptions

1. **No maintained subprocessor list exists yet** — the categories are known structurally, but the actual named vendors, their access scope, and their own compliance posture have not been documented. This is the primary action item.
2. **No formal due-diligence records exist** for any vendor currently in use.
3. **Credential scoping is documented as a recommendation for object storage but not verified as done for every other subprocessor** (SMTP, cloud IAM) — the Company should confirm each individually.

## Related Documents

[system-description.md](../system-description.md) §8–10, [risk-assessment-policy.md](risk-assessment-policy.md), `docs/deployment.md` §Hardening: scope MinIO credentials, `docs/enterprise-integration.md`.
