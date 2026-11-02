"""
Module: perf.lib.hostinfo

Collects generic host characteristics for a results bundle, from an allowlist only.

Responsibilities:
- Report CPU architecture and core count, RAM, the Docker VM allocation, OS family and major version, Docker and
  Compose versions, a storage class and a generic CPU family.
- Validate the host label (`validate_label`) so a bundle is never named after the machine or its owner.

Design decisions:
- Allowlist, never denylist: every field is read by name and reduced to a generic value. Raw output of
  `docker info`, `uname -a`, `hostname`, `/proc/cpuinfo`, `system_profiler`, `ip addr`, `env` or `git log` is never
  copied, because it carries hostnames, serial numbers, usernames, addresses and daemon ids.
- Every value passes `_generic`, which rejects anything that is not a short plain token, as a last guard.
- Python 3.9+, standard library only.

Dependencies: the host's `docker`, and on Linux `/proc` and `/sys`.
"""

from __future__ import annotations

import getpass
import os
import platform
import re
import socket
import subprocess
from pathlib import Path
from typing import Callable, Optional

SCHEMA_VERSION = 1
LABEL_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,30}$")
_GENERIC = re.compile(r"^[A-Za-z0-9._+ -]{1,40}$")
_ARM_PARTS = {
    "0xd03": "cortex-a53", "0xd07": "cortex-a57", "0xd08": "cortex-a72", "0xd0b": "cortex-a76", "0xd0c": "neoverse-n1",
    "0xd0d": "cortex-a77", "0xd40": "neoverse-v1", "0xd41": "cortex-a78", "0xd44": "cortex-x1", "0xd4f": "neoverse-v2",
}
_STORAGE_CLASSES = ("ssd", "nvme", "hdd", "sd-card", "network", "unknown")

Runner = Callable[..., "subprocess.CompletedProcess"]


class HostInfoError(ValueError):
    """A value could not be reduced to something safe to record."""


def _generic(value: object, what: str) -> str:
    """Returns `value` as a short plain token, else raises `HostInfoError` (nothing identifying slips through)."""
    text = str(value).strip()
    if not _GENERIC.match(text):
        raise HostInfoError(f"{what} is not a short generic value")
    return text


def validate_label(label: str) -> str:
    """Checks a host label: lower-case words and digits, 3 to 31 characters, not the machine's name or the user's.

    Args:
        label: The operator's label, such as `rpi5-8g`.

    Returns:
        The label.

    Raises:
        HostInfoError: If it does not match the pattern or contains the hostname or username.
    """
    if not LABEL_PATTERN.match(label):
        raise HostInfoError("host label must be 3 to 31 characters of a-z, 0-9 and '-', starting with a letter or digit")
    identifying = {socket.gethostname().split(".")[0].lower(), _username().lower()}
    for name in identifying:
        if len(name) >= 3 and name in label:
            raise HostInfoError("host label must not contain this machine's hostname or the current username; choose a generic label such as 'rpi5-8g'")
    return label


def _username() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001  (no passwd entry in some containers)
        return os.environ.get("USER", "")


def normalise_arch(machine: str) -> str:
    """`amd64` or `arm64` (or `other`) from a machine string such as `x86_64`, `aarch64` or `arm64`."""
    machine = machine.lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("aarch64", "arm64", "armv8l"):
        return "arm64"
    return "other"


def os_family(operating_system: str) -> str:
    """A generic OS family and major version from Docker's `OperatingSystem` string.

    Args:
        operating_system: For example `Docker Desktop`, `Ubuntu 24.04.1 LTS` or `Debian GNU/Linux 12 (bookworm)`.

    Returns:
        For example `docker-desktop`, `ubuntu-24` or `debian-12`; `linux` when nothing recognisable is found.
    """
    text = operating_system.lower()
    for family in ("docker desktop", "ubuntu", "debian", "raspbian", "alpine", "fedora", "centos", "rocky", "red hat", "amazon", "arch", "macos"):
        if family in text:
            slug = family.replace(" ", "-")
            if slug == "docker-desktop":
                return slug
            match = re.search(r"\b(\d+)(?:\.\d+)*\b", text[text.index(family):])
            return f"{slug}-{match.group(1)}" if match else slug
    return "linux"


def cpu_family(cpuinfo_text: str = "", brand: str = "") -> str:
    """A generic CPU family from `/proc/cpuinfo` text and/or a brand string (never copied).

    Returns:
        `apple`, `intel`, `amd`, an `arm-<core>` name from the ARM part number, `arm`, or `other`.
    """
    both = (brand + "\n" + cpuinfo_text).lower()
    if "apple" in both:
        return "apple"
    if "intel" in both:
        return "intel"
    if "amd" in both:
        return "amd"
    part = re.search(r"cpu part\s*:\s*(0x[0-9a-f]+)", both)
    if part:
        return f"arm-{_ARM_PARTS.get(part.group(1), 'generic')}"
    if "aarch64" in both or "arm" in both:
        return "arm"
    return "other"


def _read(path: str) -> str:
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return ""


def host_ram_bytes(run: Runner = subprocess.run) -> Optional[int]:
    """Total physical RAM in bytes, from `/proc/meminfo` or macOS `sysctl hw.memsize`; None if unknown."""
    match = re.search(r"MemTotal:\s*(\d+) kB", _read("/proc/meminfo"))
    if match:
        return int(match.group(1)) * 1024
    try:
        done = run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=10, check=False)
        return int(done.stdout.strip()) if done.returncode == 0 and done.stdout.strip().isdigit() else None
    except (OSError, subprocess.SubprocessError):
        return None


def storage_class(override: Optional[str] = None) -> str:
    """The storage class: the operator's `override`, else a best-effort guess from Linux sysfs, else `unknown`."""
    if override:
        if override not in _STORAGE_CLASSES:
            raise HostInfoError(f"storage class must be one of {', '.join(_STORAGE_CLASSES)}")
        return override
    block = Path("/sys/block")
    if not block.is_dir():
        return "unknown"
    classes = set()
    for device in block.iterdir():
        name = device.name
        if name.startswith(("loop", "ram", "zram", "dm-", "md")):
            continue
        if name.startswith("mmcblk"):
            classes.add("sd-card")
        elif name.startswith("nvme"):
            classes.add("nvme")
        elif _read(f"/sys/block/{name}/queue/rotational").strip() == "1":
            classes.add("hdd")
        else:
            classes.add("ssd")
    for preferred in ("sd-card", "hdd", "nvme", "ssd"):
        if preferred in classes:
            return preferred
    return "unknown"


def is_virtualised() -> Optional[bool]:
    """Whether Linux reports a hypervisor (CPU flag); None where that cannot be told."""
    cpuinfo = _read("/proc/cpuinfo")
    if not cpuinfo:
        return None
    return " hypervisor" in cpuinfo


def _docker_fields(run: Runner) -> dict:
    """Docker's CPU count, memory, OS family and versions via a `--format` of chosen fields only."""
    fields = "{{.NCPU}}|{{.MemTotal}}|{{.OperatingSystem}}|{{.ServerVersion}}|{{.Architecture}}"
    try:
        done = run(["docker", "info", "--format", fields], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HostInfoError(f"docker is not available: {exc}") from exc
    if done.returncode != 0:
        raise HostInfoError("docker info failed; is the Docker daemon running?")
    parts = done.stdout.strip().split("|")
    if len(parts) != 5:
        raise HostInfoError("docker info returned an unexpected shape")
    return {"ncpu": int(parts[0]), "mem": int(parts[1]), "os": parts[2], "docker": parts[3], "arch": parts[4]}


def _compose_version(run: Runner) -> str:
    try:
        done = run(["docker", "compose", "version", "--short"], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return done.stdout.strip().lstrip("v") if done.returncode == 0 else "unknown"


def _mac_brand(run: Runner) -> str:
    if platform.system() != "Darwin":
        return ""
    try:
        done = run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=10, check=False)
        return done.stdout.strip() if done.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def collect(*, storage: Optional[str] = None, run: Runner = subprocess.run) -> dict:
    """The `host.json` document: generic characteristics only.

    Args:
        storage: The operator's storage class (`ssd`, `nvme`, `hdd`, `sd-card`, `network`), else guessed.
        run: A `subprocess.run`-compatible callable (replaced in tests).

    Returns:
        A dict of allowlisted fields. Every string value is a short generic token.

    Raises:
        HostInfoError: If Docker is unavailable or a value cannot be made generic.
    """
    docker = _docker_fields(run)
    ram = host_ram_bytes(run)
    document = {
        "schema_version": SCHEMA_VERSION,
        "arch": normalise_arch(docker["arch"]),
        "host_cores": os.cpu_count() or docker["ncpu"],
        "docker_cores": docker["ncpu"],
        "host_ram_gib": round(ram / 2**30, 1) if ram else None,
        "docker_ram_gib": round(docker["mem"] / 2**30, 1),
        "docker_vm": "docker desktop" in docker["os"].lower(),
        "os": os_family(docker["os"]),
        "docker_version": _generic(docker["docker"], "docker version"),
        "compose_version": _generic(_compose_version(run), "compose version"),
        "cpu_family": cpu_family(_read("/proc/cpuinfo"), _mac_brand(run)),
        "storage": storage_class(storage),
        "virtualised": is_virtualised(),
        "python": f"{platform.python_version_tuple()[0]}.{platform.python_version_tuple()[1]}",
    }
    for key in ("os", "cpu_family", "storage", "python", "arch"):
        _generic(document[key], key)
    return document
