#!/usr/bin/env python3
"""
Module: perf.plot_results

Draws the website's performance figures from results bundles in `perf/results/` and writes only the SVGs into the repository.

Responsibilities:
- Read the bundles named in `BUNDLES` (after running the anonymisation check over each), confirm each is what the table says
  it is (workers, tiers) and, per figure, that the bundles drawn together are comparable, saying why if not.
- Write each figure twice, a light and a dark SVG, to `docs/website/static/img/performance/`, so the site can show the
  one that matches its theme.
- Figures: memory against project size at 4 and 6 workers; the backend's memory over the 30-minute soak; throughput
  against the number of workers on each host; one-worker latency against project size on two hosts; the database's
  costliest statements under load.

Design decisions:
- The data stays out of the repository (`perf/results/` is git-ignored; each host keeps its own bundles), so a figure can be
  rebuilt only where those bundles are; the SVGs are byte-for-byte reproducible from them (fixed hash salt, no creation date,
  text kept as text). The table of which bundle represents which host is a judgement a person makes and is written down here.
- Colour follows the host, not its rank: Linux server blue, Dell workstation orange, Raspberry Pi aqua, in both themes;
  the palette is the validated categorical reference palette (three slots validate against every pair in both modes).
  Aqua is below 3:1 on the light surface, so every series is labelled and every figure has a table in the page.
- One axis per panel and no dual axes: different measures are different panels.

Usage:
    python3 perf/plot_results.py      (with the bundles of `BUNDLES` in perf/results/)

Dependencies: matplotlib (`pip install -r perf/requirements-plots.txt`), PyYAML; `perf.analyse`, `perf.lib.scrub`.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("svg")
import matplotlib.pyplot as plt  # noqa: E402
import yaml  # noqa: E402
from matplotlib.ticker import FuncFormatter, ScalarFormatter  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyse  # noqa: E402

from perf.lib import scrub  # noqa: E402

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
OUT = HERE.parent / "docs" / "website" / "static" / "img" / "performance"

THEMES = {
    "light": {"surface": "#fcfcfb", "ink": "#0b0b0b", "secondary": "#52514e", "muted": "#898781", "grid": "#e1e0d9", "axis": "#c3c2b7",
              "series": ["#2a78d6", "#eb6834", "#1baf7a"]},
    "dark": {"surface": "#1a1a19", "ink": "#f0efec", "secondary": "#c3c2b7", "muted": "#898781", "grid": "#2c2c2a", "axis": "#383835",
             "series": ["#3987e5", "#d95926", "#199e70"]},
}
#: Host key to (display name, categorical slot): colour follows the host in every figure. The Linux server has 16 cores and 30 GiB; its
#: results directory is named `linux-vm-4c8g`, a label that does not describe it and is kept only because it names the directories.
HOSTS = {"linux": ("Linux server", 0), "dell": ("Dell workstation (WSL2)", 1), "pi": ("Raspberry Pi 5", 2)}
LINUX_DIR, DELL_DIR, PI_DIR = "linux-vm-4c8g", "dell-workstation-wsl2", "rpi5-8g"


def bundle_spec(role: str, directory: str, workers: int, tiers: tuple) -> tuple:
    """One entry of `BUNDLES`: `(role, directory under perf/results/, expected workers, expected tiers)`."""
    return role, directory, workers, tiers


_ALL = ("T0", "T1", "T2", "T3", "T4")
#: The bundles the figures are drawn from, by role. Each is checked against its stated worker count and tiers.
BUNDLES = [
    bundle_spec("memory-4w", f"{LINUX_DIR}/2026-10-29-f93d8abb-3", 4, _ALL),
    bundle_spec("memory-6w", f"{LINUX_DIR}/2026-10-29-f93d8abb-4", 6, _ALL),
    bundle_spec("onew-linux", f"{LINUX_DIR}/2026-10-31-f299c390", 1, _ALL),
    bundle_spec("onew-pi", f"{PI_DIR}/2026-10-31-f299c390", 1, _ALL),
    bundle_spec("capacity-linux-1", f"{LINUX_DIR}/2026-10-28-38efb504", 1, ("T2",)),
    bundle_spec("capacity-linux-2", f"{LINUX_DIR}/2026-10-28-38efb504-2", 2, ("T2",)),
    bundle_spec("capacity-linux-4", f"{LINUX_DIR}/2026-10-28-38efb504-3", 4, ("T2",)),
    bundle_spec("capacity-linux-6", f"{LINUX_DIR}/2026-10-28-38efb504-4", 6, ("T2",)),
    bundle_spec("capacity-dell-1", f"{DELL_DIR}/2026-10-28-874d93b9", 1, ("T2",)),
    bundle_spec("capacity-dell-2", f"{DELL_DIR}/2026-10-28-874d93b9-2", 2, ("T2",)),
    bundle_spec("capacity-dell-4", f"{DELL_DIR}/2026-10-28-874d93b9-3", 4, ("T2",)),
    bundle_spec("capacity-dell-6", f"{DELL_DIR}/2026-10-28-874d93b9-4", 6, ("T2",)),
    bundle_spec("capacity-pi-1", f"{PI_DIR}/2026-10-28-38efb504", 1, ("T2",)),
]
TIER_REQUIREMENTS = {"T0": 30, "T1": 100, "T2": 1000, "T3": 5000, "T4": 20000}
#: Text is measured in DejaVu Sans (shipped with matplotlib, so the layout is the same on every machine) and written to the SVG
#: with the reader's own system font first, so the figure matches the page.
MEASURED_FONT = "DejaVu Sans"
SVG_FONT_STACK = "system-ui, -apple-system, 'Segoe UI', 'DejaVu Sans', sans-serif"
BUDGET_INTERACTIVE_MS = 300


class NotComparable(Exception):
    """Published bundles that cannot be drawn together, with the reason."""


def load_bundles() -> dict:
    """The bundles of `BUNDLES` as `{role: {path, run, host}}`, each checked for what it should be and for anything identifying.

    Raises:
        SystemExit: If a bundle is missing, aborted, not what the table says, or fails the anonymisation check.
    """
    bundles = {}
    for role, directory, workers, tiers in BUNDLES:
        path = RESULTS / directory
        if not (path / "run.json").is_file():
            raise SystemExit(f"{role}: {path} is not a results bundle (copy the host's bundles into perf/results/ first)")
        run = json.loads((path / "run.json").read_text())
        if run.get("aborted") or run.get("non_publishable"):
            raise SystemExit(f"{role}: the bundle is aborted or non-publishable ({run.get('non_publishable_reasons')})")
        if run["workers"] != workers or not set(tiers) <= set(run["tiers"]):
            raise SystemExit(f"{role}: expected {workers} workers and tiers {tiers}, the bundle has {run['workers']} and {run['tiers']}")
        findings = list(scrub.scan_tree(path))
        if findings:
            raise SystemExit(f"{role}: the bundle fails the anonymisation check:\n" + "\n".join(findings))
        bundles[role] = {"path": path, "run": run, "host": json.loads((path / "host.json").read_text())}
    return bundles


def rows(bundle: dict, name: str) -> list:
    """Rows of one of a bundle's CSV files (empty if it has none)."""
    return analyse.read_csv(bundle["path"] / name)


def apply_theme(theme: dict) -> None:
    """Sets the matplotlib defaults for one theme: surface, ink, recessive grid, thin marks, text kept as text in the SVG."""
    plt.rcParams.update({
        "svg.fonttype": "none", "svg.hashsalt": "reqtrack-performance", "font.family": MEASURED_FONT, "font.size": 9.5,
        "figure.facecolor": theme["surface"], "axes.facecolor": theme["surface"], "savefig.facecolor": theme["surface"],
        "axes.edgecolor": theme["axis"], "axes.labelcolor": theme["secondary"], "xtick.color": theme["muted"], "ytick.color": theme["muted"],
        "text.color": theme["ink"], "axes.grid": True, "grid.color": theme["grid"], "grid.linewidth": 0.8, "axes.axisbelow": True,
        "axes.spines.top": False, "axes.spines.right": False, "lines.linewidth": 2, "legend.frameon": False, "legend.fontsize": 9,
    })


def style_axes(ax, theme: dict) -> None:
    """Hairline baseline, recessive ticks, no vertical grid."""
    ax.grid(axis="x", visible=False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(theme["axis"])
    ax.tick_params(length=0, labelsize=9)


def requirements_axis(ax) -> None:
    """A log x axis in requirements per project with plain-number ticks at the tiers."""
    ax.set_xscale("log")
    ax.set_xticks(list(TIER_REQUIREMENTS.values()))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{int(v):,}"))
    ax.xaxis.set_minor_formatter(FuncFormatter(lambda *_a: ""))
    ax.set_xlabel("Requirements in the project")


def mark(ax, x, y, color, theme, *, hollow: bool = False, label: str | None = None) -> None:
    """A line with 8 px markers and a 2 px ring in the surface colour; hollow markers flag a value that is a floor."""
    ax.plot(x, y, color=color, marker="o", markersize=6, markeredgewidth=2, markeredgecolor=theme["surface"], label=label, zorder=3)
    if hollow:
        ax.plot(x[-1:], y[-1:], marker="o", markersize=7, markerfacecolor=theme["surface"], markeredgecolor=color, markeredgewidth=2,
                linestyle="none", zorder=4)


def label_end(ax, x, y, text, theme, dy: float = 0.0) -> None:
    """A direct label beside the last point, in ink (never the series colour)."""
    ax.annotate(text, (x, y), textcoords="offset points", xytext=(8, dy), va="center", color=theme["secondary"], fontsize=9)


def per_tier_peak(bundle: dict, service: str = "backend") -> dict:
    """The largest memory sample (MiB) of `service` in each tier of a bundle."""
    peak: dict = defaultdict(float)
    for r in rows(bundle, "samples.csv"):
        if r["service"] == service:
            peak[r["tier"]] = max(peak[r["tier"]], float(r["mem_mib"]))
    return dict(peak)


def per_tier_worker(bundle: dict) -> dict:
    """The largest private memory (MiB) of any single worker in each tier of a bundle."""
    peak: dict = defaultdict(float)
    for r in rows(bundle, "processes.csv"):
        if r["role"] == "worker":
            peak[r["tier"]] = max(peak[r["tier"]], float(r["private_mib"]))
    return dict(peak)


def figure_memory(bundles: list, theme: dict):
    """Backend memory against project size at 4 and 6 workers: the container's peak, and the largest worker."""
    four, six = bundles["memory-4w"], bundles["memory-6w"]
    if four["run"]["commit"] != six["run"]["commit"]:
        raise NotComparable("the 4 and 6 worker bundles are from different commits")
    fig, (left, right) = plt.subplots(1, 2, figsize=(7.4, 3.5), sharex=True)
    cap_gib = int(four["run"]["caps"]["per_service"]["backend"]["mem"].rstrip("m")) / 1024
    for workers, bundle in ((4, four), (6, six)):
        color = theme["series"][0] if workers == 4 else theme["series"][1]
        total, worker = per_tier_peak(bundle), per_tier_worker(bundle)
        tiers = [t for t in TIER_REQUIREMENTS if t in total]
        xs = [TIER_REQUIREMENTS[t] for t in tiers]
        mark(left, xs, [total[t] / 1024 for t in tiers], color, theme, hollow=total[tiers[-1]] / 1024 > cap_gib * 0.98, label=f"{workers} workers")
        mark(right, xs, [worker[t] / 1024 for t in tiers], color, theme)
    left.axhline(cap_gib, color=theme["muted"], linestyle=(0, (4, 3)), linewidth=1.2)
    left.annotate(f"test cap {cap_gib:.1f} GiB", (30, cap_gib), textcoords="offset points", xytext=(0, 5), color=theme["secondary"], fontsize=9)
    left.set_ylabel("Backend container, peak (GiB)")
    right.set_ylabel("Largest single worker (GiB)")
    for ax in (left, right):
        requirements_axis(ax)
        style_axes(ax, theme)
        ax.set_ylim(bottom=0)
    left.legend(loc="upper left", bbox_to_anchor=(0, 0.9))
    fig.tight_layout()
    return fig


def figure_soak(bundles: list, theme: dict):
    """The backend's memory over the 30-minute soak at three project sizes (4 workers), with the trend per hour."""
    samples = rows(bundles["memory-4w"], "samples.csv")
    fig, ax = plt.subplots(figsize=(7.4, 3.4))
    for slot, tier in enumerate(("T2", "T3", "T4")):
        points = analyse.soak_trace(samples, tier)
        slope = analyse.memory_slope_mib_per_hour(samples, tier)
        xs, ys = [t / 60 for t, _ in points], [m / 1024 for _, m in points]
        ax.plot(xs, ys, color=theme["series"][slot], label=f"{TIER_REQUIREMENTS[tier]:,} requirements ({tier})")
        label_end(ax, xs[-1], ys[-1], f"{slope:+.0f} MiB/h" if slope is not None else "", theme)
    ax.set_xlabel("Minutes into the soak")
    ax.set_ylabel("Backend container (GiB)")
    ax.set_ylim(bottom=0)
    ax.set_xlim(0, 36)
    style_axes(ax, theme)
    ax.legend(loc="lower right", ncols=1)
    fig.tight_layout()
    return fig


def peak_delivered(bundle: dict, scenario: str) -> float | None:
    """The most requests per second any level of a capacity climb delivered, or None if the scenario was not run."""
    budgets = yaml.safe_load(analyse.BUDGETS.read_text())
    levels = analyse.capacity_curve(rows(bundle, "latency.csv"), budgets, scenario)["levels"]
    return max((lv["delivered_rps"] for lv in levels), default=None)


def figure_throughput(bundles: list, theme: dict):
    """Peak delivered requests per second against the number of backend workers, per host: the browse mix, and the mix with the other record types."""
    fig, panels = plt.subplots(1, 2, figsize=(7.4, 3.5), sharey=True)
    capacity = {role: b for role, b in bundles.items() if role.startswith("capacity-")}
    commits = {b["run"]["commit"][:8] for b in capacity.values()}
    if len(commits) > 2:
        # Two are expected: the Dell was run at a later commit that differs from the others in documentation only.
        raise NotComparable(f"capacity bundles from {len(commits)} commits")
    for ax, scenario, title in ((panels[0], "capacity", "Browsing and editing"), (panels[1], "capacity_mixed", "With the other record types")):
        for key, (name, slot) in HOSTS.items():
            points = sorted((b["run"]["workers"], peak_delivered(b, scenario)) for role, b in capacity.items() if role.startswith(f"capacity-{key}-"))
            points = [(w, v) for w, v in points if v is not None]
            if not points:
                continue
            xs, ys = [w for w, _ in points], [v for _, v in points]
            mark(ax, xs, ys, theme["series"][slot], theme, label=name)
        ax.set_title(title, fontsize=9.5, color=theme["secondary"], loc="left")
        ax.set_xticks([1, 2, 4, 6])
        ax.set_xlabel("Backend workers")
        style_axes(ax, theme)
        ax.set_ylim(bottom=0)
    panels[0].set_ylabel("Requests per second delivered, at the peak")
    panels[0].legend(loc="upper left")
    fig.tight_layout()
    return fig


def one_worker_latency(bundle: dict, request: str | tuple) -> dict:
    """Mean latency (ms) of `request` at one simulated user per tier, weighted by request count over the repeats.

    `request` may list alternative names for one request, because a bundle recorded before a rename still carries the
    old one (a bundle holds only one of them)."""
    names = (request,) if isinstance(request, str) else request
    total: dict = defaultdict(float)
    count: dict = defaultdict(int)
    for r in rows(bundle, "latency.csv"):
        if r["scenario"] == "browse" and r["request"] in names and r["users"] == "1" and r["mean_ms"]:
            total[r["tier"]] += float(r["mean_ms"]) * int(r["count"])
            count[r["tier"]] += int(r["count"])
    return {t: total[t] / count[t] for t in total if count[t]}


def figure_scaling(bundles: list, theme: dict):
    """One-worker latency against project size on the Linux server and the Raspberry Pi, for three requests, with the interactive budget."""
    linux, pi = bundles["onew-linux"], bundles["onew-pi"]
    if linux["run"]["commit"] != pi["run"]["commit"]:
        raise NotComparable("the one-worker bundles are from different commits")
    requests = (("GET /projects/{id}/requirements (page of 50)", "Page of 50 requirements"),
                ("GET /projects/{id}/requirements/{id}", "One requirement"),
                (("POST /projects/{id}/overview-metrics (dashboard)", "GET /projects/{id}/metrics (dashboard)"), "Project dashboard"))
    fig, panels = plt.subplots(1, 3, figsize=(7.6, 3.4), sharey=True)
    for ax, (request, title) in zip(panels, requests, strict=False):
        for bundle, key in ((linux, "linux"), (pi, "pi")):
            name, slot = HOSTS[key]
            latency = one_worker_latency(bundle, request)
            tiers = [t for t in TIER_REQUIREMENTS if t in latency]
            mark(ax, [TIER_REQUIREMENTS[t] for t in tiers], [latency[t] for t in tiers], theme["series"][slot], theme, label=name)
        ax.axhline(BUDGET_INTERACTIVE_MS, color=theme["muted"], linestyle=(0, (4, 3)), linewidth=1.2)
        ax.set_yscale("log")
        ax.set_xscale("log")
        ax.set_title(title, fontsize=9.5, color=theme["secondary"], loc="left")
        ax.set_xticks([30, 1000, 20000])
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{int(v):,}"))
        ax.xaxis.set_minor_formatter(FuncFormatter(lambda *_a: ""))
        ax.set_xlabel("Requirements")
        style_axes(ax, theme)
    panels[0].set_yticks([10, 30, 100, 300, 1000])
    panels[0].yaxis.set_major_formatter(ScalarFormatter())
    panels[0].set_ylim(8, 1200)
    panels[0].set_ylabel("Mean latency, one user (ms)")
    panels[0].annotate("300 ms budget", (30, BUDGET_INTERACTIVE_MS), textcoords="offset points", xytext=(0, 4),
                       color=theme["secondary"], fontsize=8.5)
    panels[0].legend(loc="lower right", fontsize=8.5)
    fig.tight_layout()
    return fig


def statement_name(query: str) -> str:
    """A short readable name for a normalised statement: the verb and its first real table, with 'count' for a count."""
    text = re.sub(r"\s+", " ", query).strip()
    verb = text.split(" ", 1)[0].upper()
    tables = [t for t in re.findall(r"\b(?:FROM|JOIN|INTO|UPDATE)\s+\"?([a-z_][a-z_0-9]*)", text, re.IGNORECASE) if t.lower() != "select"]
    kind = " count" if re.search(r"count\(", text, re.IGNORECASE) else ""
    return f"{verb}{kind} {tables[0] if tables else ''}".strip()


def figure_statements(bundles: list, theme: dict):
    """The database's costliest statements over the six-worker capacity climb (total time and number of calls)."""
    bundle = bundles["capacity-linux-6"]
    stats = [r for r in rows(bundle, "pgstat.csv") if r["scenario"] == "capacity" and r["tier"] == "T2"]
    top = sorted(stats, key=lambda r: float(r["total_ms"]), reverse=True)[:8][::-1]
    names, seen = [], defaultdict(int)
    for r in top:
        base = statement_name(r["query"])
        seen[base] += 1
        names.append(base if seen[base] == 1 else f"{base} ({seen[base]})")
    fig, ax = plt.subplots(figsize=(7.4, 3.5))
    totals = [float(r["total_ms"]) / 1000 for r in top]
    ax.barh(range(len(top)), totals, color=theme["series"][0], height=0.6, edgecolor=theme["surface"], linewidth=2)
    ax.set_yticks(range(len(top)), names)
    for index, r in enumerate(top):
        ax.annotate(f"{totals[index]:.0f} s: {int(r['calls']):,} calls at {float(r['mean_ms']):.1f} ms", (totals[index], index),
                    textcoords="offset points", xytext=(6, 0), va="center", color=theme["secondary"], fontsize=8.5)
    ax.set_xlabel("Database time over the run (seconds)")
    ax.set_xlim(0, max(totals) * 1.75)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    ax.spines["left"].set_color(theme["axis"])
    ax.spines["bottom"].set_color(theme["axis"])
    ax.tick_params(length=0, labelsize=9)
    fig.tight_layout()
    return fig


FIGURES = {
    "memory-by-project-size": figure_memory,
    "backend-memory-soak": figure_soak,
    "throughput-by-workers": figure_throughput,
    "latency-by-project-size": figure_scaling,
    "costliest-statements": figure_statements,
}


def main() -> int:
    """Writes every figure in both themes; returns 1 if a figure's bundles cannot be drawn together."""
    bundles = load_bundles()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, build in FIGURES.items():
        for theme_name, theme in THEMES.items():
            apply_theme(theme)
            try:
                fig = build(bundles, theme)
            except NotComparable as reason:
                print(f"{name}: not drawn, {reason}", file=sys.stderr)
                return 1
            target = OUT / f"{name}-{theme_name}.svg"
            fig.savefig(target, format="svg", metadata={"Date": None, "Creator": "perf/plot_results.py"})
            target.write_text(re.sub(r"font-family: [^;\"]*", f"font-family: {SVG_FONT_STACK}", target.read_text()))
            plt.close(fig)
        print(f"wrote {name} (light and dark)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
