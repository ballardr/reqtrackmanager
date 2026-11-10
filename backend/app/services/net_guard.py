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
- The check resolves the name itself and judges the addresses, not the spelling of the name.
  `assert_public_host` does not pin the connection to the address it checked; a caller that must close the
  gap between the check and the connect (DNS rebinding) uses `resolve_public_addresses` and connects to the
  address it returns (the OIDC client does). The SMTP relay re-checks immediately before sending instead.
- The deployment operator can opt a feature out (`Settings.oidc_allow_private_network_targets`,
  `org_smtp_allow_private_network_targets`) for an internal relay or IdP with no public address.

Dependencies: standard library only.
"""

from __future__ import annotations

import ipaddress
import socket


def resolve_public_addresses(hostname: str) -> list[str]:
    """The addresses `hostname` resolves to, provided every one is globally routable.

    Args:
        hostname: A DNS name or an IP literal (no scheme, no port).

    Returns:
        The addresses in resolver order, without duplicates; a caller that connects pins its connection to one
        of them so the name cannot answer differently between this check and the connect.

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
    addresses: list[str] = []
    for _family, _type, _proto, _canon, sockaddr in infos:
        address = str(sockaddr[0]).split("%", 1)[0]
        if not ipaddress.ip_address(address).is_global:
            raise ValueError(f"Host {hostname!r} resolves to a non-public address, which is not permitted here.")
        if address not in addresses:
            addresses.append(address)
    return addresses


def assert_public_host(hostname: str) -> None:
    """Raises unless `hostname` resolves only to globally routable addresses (see `resolve_public_addresses`).

    Raises:
        ValueError: As `resolve_public_addresses`.
    """
    resolve_public_addresses(hostname)
