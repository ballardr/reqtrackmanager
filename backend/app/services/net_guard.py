"""
Module: services.net_guard

The one check that keeps a tenant-supplied hostname from steering a server-side connection at the platform's
own network.

Responsibilities:
- Resolve a hostname and refuse it unless every address it resolves to is globally routable (`assert_public_host`).

Design decisions:
- Used for every outbound target an organisation's own administrator chooses (their SMTP relay, their OIDC
  issuer): the administrator is a tenant, not the deployment's operator, so the address must not be able to
  name the metadata service, the database, an internal admin API or a loopback port.
- The check resolves the name itself and judges the addresses, not the spelling of the name. It does not pin
  the connection to the address it checked, so a name that changes its answer between the check and the
  connect (DNS rebinding) is a residual risk the callers accept and document.
- The deployment operator can opt a feature out (`Settings.oidc_allow_private_network_targets`,
  `org_smtp_allow_private_network_targets`) for an internal relay or IdP with no public address.

Dependencies: standard library only.
"""

from __future__ import annotations

import ipaddress
import socket


def assert_public_host(hostname: str) -> None:
    """Raises unless `hostname` resolves only to globally routable addresses.

    Args:
        hostname: A DNS name or an IP literal (no scheme, no port).

    Raises:
        ValueError: If the name is empty, does not resolve, or any address it resolves to is private,
            loopback, link-local, reserved or otherwise not global. The message never contains the address.
    """
    if not hostname or not hostname.strip():
        raise ValueError("A host name is required.")
    try:
        infos = socket.getaddrinfo(hostname.strip(), None)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve host {hostname!r}.") from exc
    for _family, _type, _proto, _canon, sockaddr in infos:
        if not ipaddress.ip_address(sockaddr[0].split("%", 1)[0]).is_global:
            raise ValueError(f"Host {hostname!r} resolves to a non-public address, which is not permitted here.")
