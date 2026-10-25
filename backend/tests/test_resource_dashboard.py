"""Tests for the resource-profiling observability files: cAdvisor stays inside the `observability` profile with
read-only mounts and no published port, Prometheus scrapes it, and the provisioned "Resource usage" dashboard is
valid and queries only metrics that something in the stack emits.

The files live in the repository's `observability/` directory next to `backend/`; tests skip when it is absent
(for example in a container that only mounts the backend).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_OBS = _ROOT / "observability"
pytestmark = pytest.mark.skipif(not (_OBS / "prometheus.yml").exists(), reason="observability/ not mounted")

_DASHBOARD = _OBS / "grafana" / "dashboards" / "resource-usage.json"
_EMITTED = {  # metrics the dashboard may read, and who emits them
    "container_memory_working_set_bytes", "container_memory_rss", "container_cpu_usage_seconds_total",
    "container_start_time_seconds", "container_oom_events_total",  # cAdvisor
    "worker_resident_memory_bytes", "db_pool_connections",  # app/metrics.py
}


def _compose() -> dict:
    return yaml.safe_load((_ROOT / "docker-compose.yml").read_text())["services"]


def test_cadvisor_is_observability_only_read_only_and_unpublished():
    cadvisor = _compose()["cadvisor"]
    assert cadvisor["profiles"] == ["observability"]
    assert "ports" not in cadvisor, "Prometheus reaches it on the compose network; nothing needs a host port"
    assert not cadvisor.get("privileged")
    assert cadvisor["cap_add"] == ["SYSLOG"]
    assert all(mount.endswith(":ro") for mount in cadvisor["volumes"])
    assert "healthcheck" in cadvisor


def test_prometheus_scrapes_cadvisor_and_keeps_only_compose_services():
    config = yaml.safe_load((_OBS / "prometheus.yml").read_text())
    job = next(j for j in config["scrape_configs"] if j["job_name"] == "cadvisor")
    assert job["static_configs"][0]["targets"] == ["cadvisor:8080"]
    assert any(r.get("action") == "keep" and r["source_labels"] == ["service"] for r in job["metric_relabel_configs"])


def test_grafana_provisions_prometheus_and_the_dashboard_directory():
    grafana = _compose()["grafana"]
    assert "./observability/grafana/provisioning:/etc/grafana/provisioning:ro" in grafana["volumes"]
    assert "./observability/grafana/dashboards:/var/lib/grafana/dashboards:ro" in grafana["volumes"]
    datasource = yaml.safe_load((_OBS / "grafana/provisioning/datasources/prometheus.yml").read_text())["datasources"][0]
    assert datasource["uid"] == "prometheus" and datasource["url"] == "http://prometheus:9090"
    provider = yaml.safe_load((_OBS / "grafana/provisioning/dashboards/dashboards.yml").read_text())["providers"][0]
    assert provider["options"]["path"] == "/var/lib/grafana/dashboards"


def test_dashboard_panels_are_well_formed_and_use_known_metrics():
    dashboard = json.loads(_DASHBOARD.read_text())
    panels = dashboard["panels"]
    assert [p["id"] for p in panels] == list(range(1, len(panels) + 1))
    for panel in panels:
        assert panel["title"] and panel["description"]
        assert panel["datasource"]["uid"] == "prometheus"
        for target in panel["targets"]:
            names = set(re.findall(r"\b((?:container|worker|db)_[a-z_]+)\b", target["expr"]))
            assert names and names <= _EMITTED, f"{panel['title']}: {names - _EMITTED}"


def test_worker_gauge_names_in_the_dashboard_match_the_application():
    from app import metrics

    assert metrics.worker_resident_memory_bytes._name == "worker_resident_memory_bytes"
    assert metrics.db_pool_connections._name == "db_pool_connections"
