# Encryption and Key Management Policy

| | |
| --- | --- |
| Policy Owner | **[Name / Title]** |
| Approved By | **[Name / Title]** |
| Effective Date | **[YYYY-MM-DD]** |
| Review Cadence | Annually |
| Applies To | Engineering, Operations |

## Purpose

Supports C1.1 (maintaining confidential information) and CC6.1 by defining how data is protected in transit and at rest, and how secrets/keys are managed. See [trust-services-criteria-mapping.md](../trust-services-criteria-mapping.md) §C1.

## Scope

Covers encryption of data in transit, encryption of data at rest, and the handling of application secrets (signing keys, credentials, per-organization SSO client secrets).

## Policy

### Encryption in transit

1. All external traffic to ReqTrackManager (browser-to-frontend, browser/API-client-to-backend) must be encrypted with TLS in production. The application containers serve plain HTTP internally by design — TLS termination is the deployer's responsibility, performed by a reverse proxy in front of both containers.
2. Backend-to-identity-provider traffic (OIDC discovery, token exchange, JWKS fetch) uses whatever scheme the provider's discovery document specifies — `https` in any real deployment.
3. Backend-to-database and backend-to-object-storage traffic **[Company must state whether this is encrypted — depends on whether these run on the same private network segment as the backend, or over a network requiring its own TLS/VPN]**.

### Encryption at rest

1. Password hashes use bcrypt (adaptive, salted) — not reversible encryption, and not a fast general-purpose hash, appropriate specifically because password verification never needs the plaintext back.
2. Genuine secrets stored in the database — `Organization.oidc_client_secret`, `Organization.smtp_password`, `User.totp_secret` — are encrypted at the **application layer** (Fernet symmetric encryption, keyed from `APP_SECRET_ENCRYPTION_KEY`, distinct from `JWT_SECRET`) via a reusable `EncryptedString` column type, not left to infrastructure-level disk encryption alone (SOC 2 hardening pass — see Known Gaps below for what this closes). Application code reads/writes plaintext transparently; only the database ever sees ciphertext.
3. All other data at rest (requirement/change-request content, file attachments, audit logs) — data that needs access *control* but isn't itself a bearer secret — relies on **infrastructure-level encryption at rest**, the database volume's and object storage bucket's own encryption. This is a deliberate shared-responsibility design for that category of data: encrypting at the storage layer is simpler to get right and doesn't require the application to manage its own key hierarchy for every column. **[Company must confirm disk/volume encryption is enabled on its actual database and object storage infrastructure — this cannot be verified from the application code alone.]**

### Secrets and key management

1. Application secrets (`JWT_SECRET`, `APP_SECRET_ENCRYPTION_KEY`, database password, SMTP credentials, object storage credentials, bootstrap admin password) are sourced exclusively from environment variables, never hardcoded, and the production Compose stack refuses to start if any required secret is left at its (insecure) default — a fail-fast control, not merely a documented expectation.
2. `JWT_SECRET` must be a strong, random value distinct per deployment; it is the sole key protecting every issued session token's integrity, so its compromise is equivalent to a total authentication bypass. `APP_SECRET_ENCRYPTION_KEY` is a separate, independently-rotatable key protecting the `EncryptedString` columns above — kept distinct from `JWT_SECRET` specifically so the two can be rotated on different schedules without one rotation forcing the other.
3. Secrets must not be committed to source control, logged, or included in error responses.

## Roles and Responsibilities

| Role | Responsibility |
| --- | --- |
| Operations | Generates and rotates deployment secrets; confirms infrastructure-level encryption at rest is enabled |
| Engineering | Ensures no secret is hardcoded, logged, or otherwise mishandled in application code |

## Implementation in ReqTrackManager

- **Fail-fast secret enforcement**: the production `docker-compose.yml` requires `JWT_SECRET`, `APP_SECRET_ENCRYPTION_KEY`, `SERVER_ADMIN_PASSWORD`, `POSTGRES_PASSWORD`, `MINIO_ROOT_PASSWORD`, and `SMTP_HOST` to be set, refusing to start otherwise (see [deployment.md](../deployment.md) §Production deployment).
- **Password hashing**: `backend/app/security.py` (`_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")`).
- **Application-layer secret encryption**: `backend/app/models/encrypted_type.py` (`EncryptedString`), applied to `Organization.oidc_client_secret`, `Organization.smtp_password`, and `User.totp_secret`; covered by `backend/tests/test_encrypted_type.py`, which confirms the raw database value is genuinely ciphertext, not just a formatting difference.
- **Secret sourcing**: `backend/app/config.py` — every credential is a `Settings` field read from the environment, never a literal in application code.
- **Sensitive-value redaction**: `backend/app/main.py::redact_sensitive_validation_errors`.

## Known Gaps / Exceptions

1. ~~OIDC client secrets are stored in plaintext~~ — **resolved.** `Organization.oidc_client_secret` is now encrypted at the application layer via `EncryptedString` (SOC 2 hardening pass).
2. ~~TOTP secrets are stored as a plain string column~~ — **resolved**, same mechanism. `User.totp_secret` is now `EncryptedString`.
3. **`Organization.smtp_password`** was found, during this hardening pass, to be the same risk class as the two gaps above but not yet disclosed anywhere — it is now also `EncryptedString`, closed in the same change rather than left as a separate future gap.
4. **No key rotation process is documented** for `JWT_SECRET`, `APP_SECRET_ENCRYPTION_KEY`, or subprocessor credentials. Recommendation: define a rotation cadence and a process for rotating each without invalidating every session/re-encrypting every secret abruptly (e.g. dual-key verification during a transition window; for `APP_SECRET_ENCRYPTION_KEY` specifically, a rotation would need to decrypt-under-old-key/re-encrypt-under-new-key for every affected row, since `EncryptedString` as implemented uses a single active key, not key-versioned ciphertext).
5. **Infrastructure-level encryption at rest has not been verified** for the remaining data categories (requirement/change-request content, file attachments, audit logs) — it depends entirely on deployment configuration outside this repository.

## Related Documents

[data-classification-and-confidentiality-policy.md](data-classification-and-confidentiality-policy.md), [access-control-policy.md](access-control-policy.md), `docs/enterprise-integration.md`, `docs/deployment.md` §Production deployment.
