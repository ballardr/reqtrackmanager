# Performance results

One directory per run: `<host-label>/<date>-<commit>/` (`-2`, `-3` for a repeat on the same day and commit), written by
`perf/run_profile.sh`. **Results are git-ignored** (only this file is tracked): each host keeps its own, and an
anonymised archive is copied between machines. Summarised
measurements only (no raw request logs, no real data), anonymised by construction and checked by
`python3 perf/scrub_check.py` (also a repository test, and part of the pre-commit hook for a bundle that is deliberately force-added).

| File | Contents |
|------|----------|
| `host.json` | Generic host characteristics: architecture, cores, RAM, Docker VM allocation, OS family, storage class |
| `run.json` | Commit, scenarios, tiers, dataset spec, worker count, caps, comparability flags |
| `dataset.json` | Rows per table, realised link-degree histogram, database size |
| `samples.csv` | Per-service memory and CPU over time (seconds since each scenario started) |
| `latency.csv` | Per-endpoint count, failures and latency percentiles per scenario, tier and repeat |

Host labels are generic and stable (for example `mac-docker-desktop`, `linux-vm-4c8g`, `rpi5-8g`); never a name you
gave a machine. Known labels are listed below; add a row when a new host class is first run.

| Label | Host |
|-------|------|
| _none yet_ | |
