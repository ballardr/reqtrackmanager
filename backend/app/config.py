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
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://reqtrack:reqtrack@localhost:5432/reqtrack"
    jwt_secret: str = "change-me-in-production"
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

    @property
    def cors_origin_list(self) -> list[str]:
        """Returns the configured CORS origins as a list of strings."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

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
