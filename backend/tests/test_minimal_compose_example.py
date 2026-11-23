"""
Pins the minimal example stack (`deployments/minimal/`): the application's own services and nothing else, with the
production stack's protections kept.

Skipped when the repository root is not visible (the backend container mounts only backend/).
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "deployments" / "minimal"
COMPOSE = EXAMPLE / "docker-compose.yml"

pytestmark = pytest.mark.skipif(not COMPOSE.exists(), reason="repository root not visible")

APPLICATION_SERVICES = {"db", "storage", "backend", "converter", "frontend", "mcp-server"}


class _ComposeLoader(yaml.SafeLoader):
    """Reads a compose file, passing over the merge tags (`!reset`, `!override`) that only Docker Compose understands."""


def _compose() -> dict:
    """The example compose file as a mapping."""
    return yaml.load(COMPOSE.read_text(), Loader=_ComposeLoader)  # noqa: S506 - SafeLoader subclass


def test_runs_the_application_services_and_no_extras() -> None:
    """The stack is exactly the six application services, none behind a profile, with no observability service."""
    services = _compose()["services"]
    assert set(services) == APPLICATION_SERVICES
    assert not [name for name, body in services.items() if body.get("profiles")]


def test_database_and_storage_publish_no_port() -> None:
    """Only the backend, frontend and MCP server are reachable from the host; the data services are not."""
    services = _compose()["services"]
    assert "ports" not in services["db"]
    assert "ports" not in services["storage"]
    assert "ports" not in services["converter"]
    # The API serves an unauthenticated /metrics and /docs, so it binds loopback unless told otherwise.
    assert services["backend"]["ports"] == ["${BACKEND_BIND_ADDRESS:-127.0.0.1}:8000:8000"]


def test_keeps_the_strong_secret_check_and_requires_every_secret() -> None:
    """No insecure default: each secret is required, and the backend refuses placeholders."""
    backend = _compose()["services"]["backend"]["environment"]
    assert backend["REQUIRE_STRONG_SECRETS"] == "true"
    for name in ("JWT_SECRET", "APP_SECRET_ENCRYPTION_KEY", "SERVER_ADMIN_PASSWORD", "STORAGE_S3_SECRET_KEY"):
        assert ":?" in str(backend[name]), name
    assert ":?" in COMPOSE.read_text().split("POSTGRES_PASSWORD: ")[1].splitlines()[0]


def test_converter_stays_in_its_sandbox() -> None:
    """The converter shares an internal network with the backend alone and keeps its hardening."""
    compose = _compose()
    assert compose["networks"]["converter"]["internal"] is True
    members = {name for name, body in compose["services"].items() if "converter" in (body.get("networks") or [])}
    assert members == {"backend", "converter"}
    converter = compose["services"]["converter"]
    assert converter["read_only"] is True
    assert converter["cap_drop"] == ["ALL"]


def test_mail_is_off_until_configured() -> None:
    """Delivery defaults to disabled, so the stack starts with no SMTP provider."""
    assert _compose()["services"]["backend"]["environment"]["EMAIL_DELIVERY"] == "${EMAIL_DELIVERY:-disabled}"


def test_storage_identity_is_limited_to_the_application_bucket() -> None:
    """The one S3 identity can act on the application bucket only, with no wildcard action."""
    content = _compose()["configs"]["storage_identity"]["content"]
    actions = re.findall(r'"actions":\[(.*?)\]', content, re.S)[0]
    assert all(a.strip().strip('"').endswith(":reqtrackmanager") for a in actions.split(","))


def test_env_example_lists_every_required_variable() -> None:
    """`.env.example` names each variable the compose file refuses to start without."""
    required = set(re.findall(r"\$\{(\w+):\?", COMPOSE.read_text()))
    listed = set(re.findall(r"^([A-Z_]+)=", (EXAMPLE / ".env.example").read_text(), re.M))
    assert required <= listed, required - listed
