"""
Module: services.oidc_client

A minimal, provider-agnostic OIDC authorization-code-flow client (E-U-01).
Uses standard OIDC discovery (`.well-known/openid-configuration`) rather
than hardcoding any one provider's endpoint shape, so the same code works
against Keycloak, Authentik, Entra ID, or any other RFC-compliant issuer —
only the per-organisation `oidc_issuer_url`/`oidc_client_id`/
`oidc_client_secret` configuration changes between providers.

Deliberately not using `authlib`'s Starlette/FastAPI integration (which
expects server-side session middleware for state, not configured in this
app): the `state` parameter instead carries the org id in a short-lived
signed JWT (`app.security`), so this flow needs no server-side session
storage at all.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

import httpx
from joserfc import jwt as jose_jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from joserfc.jwt import JWTClaimsRegistry

from app.config import get_settings

_HTTP_TIMEOUT = 10.0

# RSA/ECDSA/RSA-PSS only — deliberately excludes "none" and the HMAC (HS*)
# family. `key_set` below is the IdP's own *public* JWKS; if HS* were
# accepted, a token signed with that public material used as an HMAC
# secret would verify successfully (the classic JWT "algorithm confusion"
# attack — the same vulnerability class as this project's own
# python-jose/CVE-2024-33663 and Authlib/GHSA-wvwj-cvrp-7pv5 findings,
# both patched by dependency upgrade elsewhere; here it's closed by never
# trusting the token's own `alg` header to pick a symmetric algorithm).
_ALLOWED_ID_TOKEN_ALGORITHMS = ("RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512")


def _assert_safe_external_url(url: str) -> None:
    """Blocks SSRF via org-admin-configured OIDC endpoints (E-U-01).

    `oidc_issuer_url` is set by any org's own admin — a routine, per-tenant
    role in this multi-tenant app, not a deployment-trusted value — and this
    module makes server-side requests to it (plus, transitively, to
    `token_endpoint`/`jwks_uri` pulled out of whatever discovery document
    that URL returns, which could point somewhere entirely different).
    Without this check, an org admin could point their org's issuer at
    internal-only infrastructure (a cloud metadata endpoint, an internal
    admin API, etc.) and trigger the backend into making requests against it
    merely by calling the unauthenticated `/auth/oidc/{slug}/login` route.

    Resolves the hostname and rejects it if any resolved address falls in a
    private/loopback/link-local/reserved range — checked at the resolved IP,
    not just the literal hostname string, since a hostname can otherwise be
    chosen specifically to resolve to a blocked address (DNS rebinding is a
    further step beyond this check's scope, since httpx re-resolves per
    connection rather than connecting to a pinned IP; this at least closes
    the straightforward "point it at 169.254.169.254 directly" case).

    Skipped entirely when `oidc_internal_base_url_override` is configured
    (the existing dev/test-only escape hatch, itself only ever an
    operator-set environment variable — trusted, per this deployment's own
    documented single-tenant local topology where the IdP legitimately lives
    on a private/loopback address on purpose), or when the deployment has set
    `oidc_allow_private_network_targets` (for deployments that run their own
    internal IdP with no public IP at all — see that setting's docstring for
    the trust tradeoff this implies).
    """
    settings = get_settings()
    if settings.oidc_internal_base_url_override or settings.oidc_allow_private_network_targets:
        return
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"Refusing to fetch {url!r}: not a valid http(s) URL.")
    try:
        addr_infos = socket.getaddrinfo(parts.hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve OIDC endpoint host {parts.hostname!r}: {exc}") from exc
    for _family, _, _, _, sockaddr in addr_infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if not ip.is_global:
            raise ValueError(
                f"Refusing to fetch {url!r}: {parts.hostname!r} resolves to a non-public address ({ip}), "
                "which is not permitted for org-configured OIDC endpoints."
            )


def _internal_url(url: str) -> str:
    """Rewrites `url`'s scheme+host to `oidc_internal_base_url_override`
    when configured, preserving path/query — see that setting's docstring.
    Used for every actual outbound HTTP call to the IdP; never for URLs
    handed to the browser (those must stay on the IdP's public host)."""
    override = get_settings().oidc_internal_base_url_override
    if not override:
        return url
    override_parts = urlsplit(override)
    parts = urlsplit(url)
    return urlunsplit((override_parts.scheme, override_parts.netloc, parts.path, parts.query, parts.fragment))


def discover(issuer_url: str) -> dict:
    """Fetches an OIDC provider's discovery document."""
    url = f"{issuer_url.rstrip('/')}/.well-known/openid-configuration"
    _assert_safe_external_url(url)
    resp = httpx.get(_internal_url(url), timeout=_HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def build_authorize_url(discovery: dict, *, client_id: str, redirect_uri: str, state: str) -> str:
    """Builds the URL to redirect the user's browser to for login."""
    params = {
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
        "scope": "openid email profile", "state": state,
    }
    return f"{discovery['authorization_endpoint']}?{httpx.QueryParams(params)}"


def exchange_code_for_tokens(discovery: dict, *, client_id: str, client_secret: str, redirect_uri: str, code: str) -> dict:
    """Exchanges an authorization code for tokens at the provider's token endpoint."""
    _assert_safe_external_url(discovery["token_endpoint"])
    resp = httpx.post(
        _internal_url(discovery["token_endpoint"]),
        data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "client_id": client_id, "client_secret": client_secret,
        },
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def verify_id_token(discovery: dict, id_token: str, *, client_id: str, issuer_url: str) -> dict:
    """Verifies an ID token's signature (via the provider's published JWKS),
    issuer, and audience, and returns its claims.

    Raises:
        ValueError: If the token is malformed, unsigned by a known key, or
            its issuer/audience don't match what was configured.
    """
    _assert_safe_external_url(discovery["jwks_uri"])
    jwks_resp = httpx.get(_internal_url(discovery["jwks_uri"]), timeout=_HTTP_TIMEOUT)
    jwks_resp.raise_for_status()
    key_set = KeySet.import_key_set(jwks_resp.json())
    try:
        token = jose_jwt.decode(id_token, key_set, algorithms=_ALLOWED_ID_TOKEN_ALGORITHMS)
        # OIDC Core 1.0 §2 requires iss/aud/exp on every ID token; this app
        # re-checks iss/aud itself just below (against the specific
        # per-organisation issuer/client_id, which this generic registry
        # has no way to know), but still asks the registry to enforce their
        # *presence* plus exp's value, rather than silently accepting a
        # token missing them.
        JWTClaimsRegistry(iss={"essential": True}, aud={"essential": True}, exp={"essential": True}).validate(
            token.claims
        )
    except JoseError as exc:
        raise ValueError(f"Invalid OIDC id_token: {exc}") from exc
    claims = token.claims

    if claims.get("iss") != issuer_url and claims.get("iss") != discovery.get("issuer"):
        raise ValueError("id_token issuer does not match the configured issuer.")
    aud = claims.get("aud")
    aud_ok = aud == client_id or (isinstance(aud, list) and client_id in aud)
    if not aud_ok:
        raise ValueError("id_token audience does not match this organisation's client id.")
    return dict(claims)
