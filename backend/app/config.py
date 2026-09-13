"""
Module: config

Central application configuration loaded from environment variables (and an
optional .env file for local development). All deployment-specific values
(database connection, JWT secret, bootstrap server-admin credentials) are
read here so the rest of the application never touches os.environ directly.

External dependencies: pydantic-settings.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings sourced from environment variables.

    Attributes:
        database_url: SQLAlchemy connection string for PostgreSQL.
        jwt_secret: Symmetric secret used to sign access tokens.
        jwt_algorithm: JWT signing algorithm.
        app_secret_encryption_key: Symmetric key used to encrypt genuine
            secrets at rest at the application layer — `Organization.
            oidc_client_secret`, `Organization.smtp_password`, and `User.
            totp_secret` (see `app.models.encrypted_type.EncryptedString`).
            Distinct from `jwt_secret` (signs tokens; not used for
            encryption) so the two can be rotated independently. Like
            `jwt_secret`, this must be a strong random value distinct per
            deployment — the production Compose stack fails fast if it's
            left unset.
        access_token_expire_minutes: Access token lifetime in minutes.
        server_admin_enabled: Whether the deployment-config server admin
            bootstrap user is created/enabled on startup (I-M-06).
        server_admin_email: Email address for the bootstrap server admin.
        server_admin_password: Initial password for the bootstrap server
            admin. Should be rotated after first login in production.
        server_admin_create_org: Whether to auto-create an organisation for
            the bootstrap server admin and grant them org admin (I-M-08).
        cors_origins: Comma-separated list of allowed frontend origins.
        storage_backend: Which `FileStorageBackend` to use: "local" or "s3"
            (I-M-10). "s3" works against MinIO or real S3.
        storage_local_dir: Filesystem directory for the local backend.
        storage_s3_*: Connection details for the S3-compatible backend.
        smtp_*: SMTP connection details for outgoing email (C-N-03).
        deployment_notification_email: Address (or group address) notified
            of deployment-level events such as low disk space or database
            connectivity failures (I-M-09).
        disk_usage_warning_threshold_percent: Disk usage monitor threshold
            for the local storage backend (I-M-11).
        websocket_enabled: Whether the optional live-update WebSocket
            interface (I-A-04) is mounted at all. Deployments that can't or
            don't want persistent socket connections (e.g. behind certain
            proxies/load balancers) can disable it entirely.
        geoip_lookup_enabled: Whether login events attempt to resolve the
            client IP's approximate location (C-A-07). Defaults to disabled
            since it calls an external third-party service on every login;
            login itself is never blocked by a lookup failure or timeout.
        geoip_lookup_exclude_cidrs: Comma-separated CIDR ranges never sent to
            the geolocation lookup (e.g. private/internal network ranges),
            for privacy/security. Defaults to the standard private ranges.
        public_backend_url: This backend's own externally-reachable base URL,
            used to build the OIDC `redirect_uri` sent to the identity
            provider (E-U-01) — must exactly match what's registered as a
            valid redirect URI on the IdP client.
        frontend_base_url: The frontend's base URL, used to redirect back to
            the UI once an OIDC login completes (E-U-01).
        mcp_server_public_url: The MCP server's own browser-reachable base
            URL, used to redirect back there instead of the frontend when an
            OIDC login was initiated from its `/login` page rather than the
            main app (see `routers/auth_oidc.py`'s `client` parameter) — lets
            an SSO user land on `mcp_server`'s token page directly rather
            than the app UI.
        pat_default_max_lifetime_days: Fallback maximum lifetime, in days,
            for a Personal Access Token scoped to an organisation that
            hasn't set its own `Organization.pat_max_lifetime_days` —
            guarantees no PAT is ever unboundedly long-lived even if no org
            admin ever touches that per-org setting.
        oidc_internal_base_url_override: Dev/test-only escape hatch for a
            common containerized-IdP problem: an org's `oidc_issuer_url`
            must be the identity provider's browser-reachable public URL
            (it appears in issued tokens' `iss` claim and is where the
            browser gets redirected), but in a local Docker Compose stack
            that public URL (e.g. `http://localhost:8080`) is NOT reachable
            from inside the backend's own container — only the IdP's
            internal service hostname (e.g. `http://keycloak:8080`) is.
            When set, every backend-to-IdP HTTP call (discovery, token
            exchange, JWKS fetch) rewrites the issuer's scheme+host to this
            override while preserving the path, without changing what's
            validated or what the browser is redirected to. Left unset in
            production, where the IdP's public URL is reachable from
            everywhere, including the backend.
        two_factor_max_failed_attempts: Number of consecutive failed
            `/2fa/verify` codes (since the last success or lockout) before
            further attempts are locked out (hardening review: an
            unthrottled, reusable 2FA challenge against a bounded 6-digit
            TOTP keyspace, re-mintable via a fresh `/login` each time the
            challenge token expires, otherwise converges toward a
            near-certain bypass given enough repeated windows).
        two_factor_lockout_minutes: How long `/2fa/verify` is locked out
            for a given account once `two_factor_max_failed_attempts` is
            reached. The lockout is per-*account*, not per-challenge-token,
            so re-authenticating for a fresh token does not reset it.
        oidc_allow_private_network_targets: Deployment-level opt-in that
            disables the SSRF guard's public-IP check for org-configured
            OIDC endpoints (`services.oidc_client._assert_safe_external_url`),
            letting `oidc_issuer_url` resolve to a private/internal address.
            Off by default because `oidc_issuer_url` is set by an org's own
            admin — not a deployment-trusted value in the general case — so
            blocking private-network targets is the safe default. Deployments
            that run their own internal IdP (Keycloak/Authentik/etc. on a
            corporate LAN or VPC with no public IP at all) need this set to
            reach it; unlike `oidc_internal_base_url_override` (which rewrites
            to one specific internal address, for a single dev/test IdP),
            this is a blanket allow for every organisation's configured
            issuer, so it should only be enabled when every org sharing this
            deployment is trusted not to point their issuer at the
            deployment's own internal infrastructure (cloud metadata
            endpoints, internal admin APIs, etc.) — appropriate for a
            single-tenant or otherwise fully-trusted-tenant deployment, not a
            deployment serving mutually-untrusted organisations.
        access_review_show_org_names: Whether the server-admin access review
            (C-A-13) names the specific organisations each user belongs to,
            rather than only a count. `SystemUserOut`'s org-membership field
            is deliberately kept as a plain yes/no elsewhere (I-M-05: a
            server admin is content-blind by design) — naming actual orgs
            here is an explicit, opt-out-able exception to that, not an
            oversight. Defaults to showing names on the reasoning that a
            server admin already has direct database access regardless;
            deployments that want the stricter, count-only view for this
            specific screen can set this to `false`.
        allow_external_modules: Deployment-level opt-in for the modular
            feature system's third-party discovery sources
            (`app.modules.registry`'s Python entry-point scan and
            `extra_modules_path` directory scan, compliance-module-plan.md
            Phase 1). Off by default, mirroring `MCP_WRITES_ENABLED`'s
            existing off-by-default precedent in this codebase: a plugin-
            loading mechanism that auto-imports and runs third-party code
            pip-installed (or dropped on disk) into the deployment's own
            process is a genuinely new code-loading trust boundary, and
            `docs/soc2/trust-services-criteria-mapping.md`'s CC6.8 row
            already documents an open gap ("no automated dependency/
            container vulnerability scanning exists") — a plugin system
            that runs arbitrary discovered code makes that pre-existing gap
            materially riskier, so it must not ship silently on-by-default.
            When `False`, the registry contains only the static, in-repo,
            normally-code-reviewed `INSTALLED_MODULES` list; the entry-point
            and path scans are not even performed (not merely filtered
            afterward — see `app.modules.registry.build_registry`). A
            deployment operator who explicitly wants third-party modules
            turns this on knowingly, per the due-diligence expectation
            recorded in `docs/soc2/policies/
            vendor-and-subprocessor-management-policy.md`.

            Also gates `app.modules.registry.apply_external_module_
            migrations` (module system follow-up, 2026-09-05): when `True`,
            a discovered external module's own declared `migrations_
            import_path` is imported and its `run_migrations(connection)`
            applied automatically, once at startup — the same opt-in that
            already permits loading and running that module's code at all
            now also covers applying its own database schema changes,
            rather than requiring the operator to additionally hand-run a
            migration out of band. Never applies to an `INSTALLED_MODULES`
            (first-party) module regardless of this setting — first-party
            schema changes always go through a reviewed PR into `backend/
            alembic/versions/`.
        extra_modules_path: Optional local directory scanned for third-party
            modules (each an immediate subdirectory containing a
            `module.py` with a module-level `MODULE_DEFINITION`) when
            `allow_external_modules` is `True` — for a self-hosted operator
            adding a custom module without publishing a package. Has no
            effect at all while `allow_external_modules` is `False` (its
            default), same rationale as that flag's docstring.
        module_frame_allowed_origins: Comma-separated list of origins the
            frontend is allowed to embed a Tier B remote module in a
            sandboxed `<ModuleFrame>` iframe (`Content-Security-Policy:
            frame-src`, compliance-module-plan.md Phase 3). Empty by
            default — `frame-src 'none'` is sent until a deployment operator
            explicitly lists a trusted module origin, mirroring `cors_
            origins`' own comma-separated-list shape but for the opposite
            direction (what this app is allowed to frame, not who is
            allowed to frame this app — see `main.py`'s security-headers
            middleware). A registered module's own declared `frame_url`
            (`app.modules.registry.ModuleFrontendManifest`) must resolve to
            an origin in this list or `get_frontend_manifest` rejects it
            (logs and returns `None`) — mechanically enforced, not trusted
            from the module's own declaration, mirroring Phase 4's
            path-prefix enforcement for MCP tools.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://reqtrack:reqtrack@localhost:5432/reqtrack"
    jwt_secret: str = "change-me-in-production"
    app_secret_encryption_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 12

    server_admin_enabled: bool = True
    server_admin_email: str = "admin@example.com"
    server_admin_password: str = "ChangeMe123!"
    server_admin_create_org: bool = True

    cors_origins: str = "http://localhost:3000"

    storage_backend: str = "local"
    storage_local_dir: str = "./data/files"
    storage_s3_bucket: str = "reqtrackmanager"
    storage_s3_endpoint_url: str = "http://minio:9000"
    storage_s3_access_key: str = "minioadmin"
    storage_s3_secret_key: str = "minioadmin"
    storage_s3_region: str = "us-east-1"

    smtp_host: str = "mailhog"
    smtp_port: int = 1025
    smtp_use_tls: bool = False
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_address: str = "noreply@reqtrackmanager.local"

    deployment_notification_email: str | None = None
    disk_usage_warning_threshold_percent: int = 90

    websocket_enabled: bool = True

    geoip_lookup_enabled: bool = False
    geoip_lookup_exclude_cidrs: str = "127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,::1/128,fc00::/7"

    public_backend_url: str = "http://localhost:8000"
    frontend_base_url: str = "http://localhost:3000"
    mcp_server_public_url: str = "http://localhost:8100"
    pat_default_max_lifetime_days: int = 90
    two_factor_max_failed_attempts: int = 5
    two_factor_lockout_minutes: int = 15
    oidc_internal_base_url_override: str | None = None
    oidc_allow_private_network_targets: bool = False
    access_review_show_org_names: bool = True
    allow_external_modules: bool = False
    extra_modules_path: str | None = None
    module_frame_allowed_origins: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        """Returns the configured CORS origins as a list of strings."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def module_frame_allowed_origin_list(self) -> list[str]:
        """Returns the configured Tier B module-frame origin allowlist as a
        list of strings — empty by default, so `frame-src 'none'` is what
        ships until an operator opts a specific origin in."""
        return [origin.strip() for origin in self.module_frame_allowed_origins.split(",") if origin.strip()]

    @property
    def geoip_lookup_exclude_networks(self) -> list:
        """Parses `geoip_lookup_exclude_cidrs` into `ipaddress` network objects."""
        import ipaddress

        networks = []
        for cidr in self.geoip_lookup_exclude_cidrs.split(","):
            cidr = cidr.strip()
            if cidr:
                networks.append(ipaddress.ip_network(cidr, strict=False))
        return networks


@lru_cache
def get_settings() -> Settings:
    """Returns a cached Settings instance for the process lifetime."""
    return Settings()
