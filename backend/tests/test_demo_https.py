"""Tests for the demonstration's HTTPS proxy (`tests/container/docker-compose.demo.yml`, `tests/container/caddy/`,
`scripts/demo.sh`).

The overlay is read as data and `demo.sh` is run with a fake `docker` on the path, so most tests need no Docker. The
Caddyfile is adapted with the pinned Caddy image when Docker and the image are available, and skipped otherwise.
Skipped when the repository root is not visible (the backend container mounts only backend/).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DEMO_SH = ROOT / "scripts" / "demo.sh"
CONTAINER = ROOT / "tests" / "container"
BASE = CONTAINER / "docker-compose.yml"
OVERLAY = CONTAINER / "docker-compose.demo.yml"
CADDY_DIR = CONTAINER / "caddy"

pytestmark = pytest.mark.skipif(not DEMO_SH.is_file(), reason="repository checkout not available")

APPLICATION_SERVICES = ("frontend", "backend", "mcp-server")
SUPPORT_SERVICES = ("db", "storage", "mailhog", "keycloak", "docs")


class _ComposeLoader(yaml.SafeLoader):
    """Reads Compose's `!reset` and `!override` tags as the value they wrap (`!reset []` reads as an empty list)."""


def _construct_tagged(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> object:
    """Builds the value a Compose merge tag wraps."""
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    assert isinstance(node, yaml.ScalarNode)
    return loader.construct_scalar(node)


_ComposeLoader.add_multi_constructor("!", _construct_tagged)


def _load(path: Path) -> dict:
    return yaml.load(path.read_text(), Loader=_ComposeLoader)  # noqa: S506 - a SafeLoader subclass


@pytest.fixture
def fake_docker(tmp_path):
    """Puts a `docker` on the path that logs its arguments and the environment `demo.sh` exports to Compose."""
    log = tmp_path / "docker.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "docker"
    script.write_text(
        "#!/bin/sh\n"
        f'echo "ENV $COMPOSE_FILE|$DEMO_TLS_MODE|$DEMO_PUBLIC_URL|$DEMO_MCP_MODE|$DEMO_MCP_HOST|$DEMO_MCP_URL|$DEMO_ACME_MODE" >> "{log}"\n'
        f'echo "$@" >> "{log}"\n'
        'case "$*" in\n'
        '  *"config --format json"*) echo \'{"name":"container"}\' ;;\n'
        '  *"volume ls"*) echo "container_reqtrack_demo_caddy_data" ;;\n'
        "esac\n"
        "exit 0\n"
    )
    script.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("DEMO_")}
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return log, env


def _demo(env, *args, **extra):
    return subprocess.run(["bash", str(DEMO_SH), *args], capture_output=True, text=True, env={**env, **extra}, timeout=60, check=False)


def _first_env(log: Path) -> list[str]:
    return log.read_text().splitlines()[0].removeprefix("ENV ").split("|")


# ---- the overlay -----------------------------------------------------------------------------------------------


def test_the_base_stack_for_developers_has_no_proxy_and_keeps_its_direct_ports():
    base = _load(BASE)["services"]
    assert "caddy" not in base
    for name in APPLICATION_SERVICES:
        assert base[name]["ports"], f"{name} keeps its published port for Playwright and pytest"


def test_the_proxy_is_the_only_service_published_to_every_interface():
    overlay = _load(OVERLAY)["services"]
    assert overlay["caddy"]["ports"] == ["80:80", "443:443"]
    for name in APPLICATION_SERVICES:
        assert overlay[name]["ports"] == [], f"{name} publishes nothing in the demonstration"
    for name in SUPPORT_SERVICES:
        assert overlay[name]["ports"], name
        assert all(port.startswith("127.0.0.1:") for port in overlay[name]["ports"]), f"{name} is published on loopback only"


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
def test_the_merged_configuration_publishes_only_the_proxy_and_loopback():
    env = {**os.environ, "DEMO_PUBLIC_URL": "https://localhost", "COMPOSE_FILE": "docker-compose.yml:docker-compose.demo.yml"}
    done = subprocess.run(["docker", "compose", "--profile", "demo-metrics", "--profile", "demo-schedule", "config", "--format", "json"],
                          cwd=CONTAINER, capture_output=True, text=True, env=env, timeout=60, check=False)
    if done.returncode != 0:
        pytest.skip(f"docker compose cannot render the configuration here: {done.stderr[-200:]}")
    services = json.loads(done.stdout)["services"]
    for name, service in services.items():
        for port in service.get("ports", []):
            if port.get("host_ip") in ("127.0.0.1", "::1"):
                continue
            assert name == "caddy", f"{name} publishes {port.get('published')} to every interface"
    assert services["frontend"]["environment"]["VITE_API_BASE_URL"] == "", "API calls are relative paths on one origin"
    backend = services["backend"]["environment"]
    assert backend["CORS_ORIGINS"] == backend["FRONTEND_BASE_URL"] == backend["PUBLIC_BACKEND_URL"] == "https://localhost"
    assert services["demo-scheduler"]["environment"]["DEMO_API_BASE"] == "http://backend:8000/api/v1"


def test_forwarded_headers_are_trusted_from_the_proxys_address_alone():
    overlay = _load(OVERLAY)
    allowed = overlay["services"]["backend"]["environment"]["FORWARDED_ALLOW_IPS"]
    proxy = overlay["services"]["caddy"]["networks"]["edge"]["ipv4_address"]
    assert "*" not in allowed
    address = proxy.removeprefix("${DEMO_EDGE_PROXY_IP:-").removesuffix("}")
    # The backend listens dual-stack, so an IPv4 peer is reported as ::ffff:<address>; both spellings are the proxy.
    assert allowed.count(address) == 2 and "::ffff:" in allowed
    assert set(overlay["services"]["backend"]["networks"]) == {"default", "converter", "edge"}
    assert overlay["services"]["backend"]["networks"]["edge"]["aliases"] == ["backend-edge"]
    assert "backend-edge:8000" in (CADDY_DIR / "Caddyfile").read_text(), "the proxy reaches the backend over the edge network"


def test_the_proxy_container_is_hardened_and_probed_on_loopback():
    caddy = _load(OVERLAY)["services"]["caddy"]
    assert caddy["cap_drop"] == ["ALL"] and caddy["cap_add"] == ["NET_BIND_SERVICE"]
    assert caddy["read_only"] is True and "no-new-privileges:true" in caddy["security_opt"]
    assert "127.0.0.1" in " ".join(caddy["healthcheck"]["test"])
    assert not any(v.endswith(":9180") or ":9180:" in v for v in caddy.get("ports", [])), "health and metrics stay private"


def test_certificates_live_in_named_volumes_that_a_reset_leaves_alone():
    volumes = _load(OVERLAY)["volumes"]
    assert set(volumes) == {"reqtrack_demo_caddy_data", "reqtrack_demo_caddy_config"}


# ---- the Caddyfile ---------------------------------------------------------------------------------------------


def _adapt(host: str, mode: str, mcp: str = "off") -> str | None:
    if shutil.which("docker") is None:
        return None
    env = {"DEMO_PUBLIC_HOST": host, "DEMO_TLS_MODE": mode, "DEMO_MCP_MODE": mcp, "DEMO_MCP_HOST": f"mcp.{host}"}
    flags = [part for key, value in env.items() for part in ("-e", f"{key}={value}")]
    done = subprocess.run(["docker", "run", "--rm", "--pull", "never", "-v", f"{CADDY_DIR}:/etc/caddy:ro", *flags, "caddy:2.10-alpine",
                           "caddy", "adapt", "--config", "/etc/caddy/Caddyfile"], capture_output=True, text=True, timeout=120, check=False)
    return done.stdout if done.returncode == 0 else None


def test_hsts_is_sent_for_a_named_host_and_never_for_localhost():
    named = _adapt("demo.example.org", "public", "on")
    local = _adapt("localhost", "internal", "on")
    if named is None or local is None:
        pytest.skip("the Caddy image is not available here")
    assert "Strict-Transport-Security" in named and "max-age=31536000" in named
    assert "Strict-Transport-Security" not in local
    assert '"internal"' in local and '"internal"' not in named, "the local authority is used for localhost only"
    assert "mcp.demo.example.org" in named


def test_the_proxy_overwrites_forwarded_headers_and_logs_no_query():
    text = (CADDY_DIR / "Caddyfile").read_text()
    assert "trusted_proxies" not in text, "a client-supplied forwarded header is never trusted"
    assert text.count("header_up X-Forwarded-For {http.request.remote.host}") >= 2
    assert "header_up X-Forwarded-Proto https" in text
    assert "request>uri regexp" in text and "request>headers delete" in text, "the query string and headers stay out of the log"
    assert "admin off" in text, "no configuration API is reachable from the network"


# ---- scripts/demo.sh -------------------------------------------------------------------------------------------


def test_localhost_uses_the_local_authority_and_the_mcp_server_gets_mcp_localhost(fake_docker):
    log, env = fake_docker
    assert _demo(env).returncode == 0
    files, tls, url, mcp_mode, mcp_host, mcp_url, acme = _first_env(log)
    assert files == "docker-compose.yml:docker-compose.demo.yml"
    assert (tls, url, mcp_mode, mcp_host, mcp_url, acme) == ("internal", "https://localhost", "on", "mcp.localhost", "https://mcp.localhost", "")


def test_a_dns_name_uses_a_public_certificate_and_an_ip_address_does_not(fake_docker):
    log, env = fake_docker
    assert _demo(env, DEMO_PUBLIC_HOST="demo.example.org", DEMO_ACME_EMAIL="ops@example.org").returncode == 0
    tls, url, mcp_mode, mcp_host, mcp_url, acme = _first_env(log)[1:]
    assert (tls, url, mcp_mode, mcp_host, mcp_url, acme) == (
        "public",
        "https://demo.example.org",
        "on",
        "mcp.demo.example.org",
        "https://mcp.demo.example.org",
        "email",
    )
    log.write_text("")
    assert _demo(env, DEMO_PUBLIC_HOST="203.0.113.9").returncode == 0
    tls, url, mcp_mode = _first_env(log)[1:4]
    assert (tls, url, mcp_mode) == ("internal", "https://203.0.113.9", "off"), "an IP address has no name for the MCP server"
    log.write_text("")
    assert _demo(env, DEMO_PUBLIC_HOST="demo.example.org", DEMO_MCP_HOST="off").returncode == 0
    assert _first_env(log)[3] == "off"


def test_a_host_that_is_not_a_name_is_refused_before_anything_starts(fake_docker):
    log, env = fake_docker
    done = _demo(env, DEMO_PUBLIC_HOST="evil.example/;x")
    assert done.returncode == 2 and "DEMO_PUBLIC_HOST" in done.stderr
    assert not log.exists()


def test_the_ready_message_gives_the_https_address_and_the_trust_hint_for_the_local_authority(fake_docker):
    _, env = fake_docker
    done = _demo(env)
    assert "https://localhost" in done.stdout and "--trust-local-ca" in done.stdout
    assert "http://localhost:3000" not in done.stdout
    named = _demo(env, DEMO_PUBLIC_HOST="demo.example.org")
    assert "https://demo.example.org" in named.stdout and "--trust-local-ca" not in named.stdout


def test_trusting_the_local_authority_only_prints_commands(fake_docker):
    log, env = fake_docker
    done = _demo(env, "--trust-local-ca")
    assert done.returncode == 0 and "caddy-local-root.crt" in done.stdout
    assert not log.exists(), "nothing is run and no trust store is changed"


def test_purging_certificates_removes_only_the_proxy_volumes(fake_docker):
    log, env = fake_docker
    assert _demo(env, "--purge-certificates").returncode == 0
    calls = log.read_text().splitlines()
    assert any("rm -sf caddy" in call for call in calls)
    removed = [c for c in calls if c.startswith("volume rm")]
    assert removed and set(removed) == {"volume rm container_reqtrack_demo_caddy_data"}
    assert any("label=com.docker.compose.volume=reqtrack_demo_caddy_config" in c for c in calls)


def test_a_reset_and_a_teardown_leave_the_certificates(fake_docker):
    log, env = fake_docker
    for option in ("--reset", "--teardown"):
        log.write_text("")
        assert _demo(env, option).returncode == 0
        text = log.read_text()
        assert "volume rm" not in text and " down" not in text and " rm " not in text


def test_the_proxy_scrape_keeps_only_request_series():
    config = _load(ROOT / "observability" / "prometheus.demo.yml")
    job = next(j for j in config["scrape_configs"] if j["job_name"] == "reqtrackmanager-proxy")
    assert job["static_configs"][0]["targets"] == ["caddy:9180"]
    relabel = job["metric_relabel_configs"][0]
    assert relabel["action"] == "keep" and relabel["regex"].startswith("caddy_http_"), "Go runtime series never reach a bundle"
