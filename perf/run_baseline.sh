#!/bin/sh
# Records the sizing baseline of a host in one command, so it can run unattended (overnight) and be repeated whenever the
# product has grown:
#
#   PROD_HEALTH_URL=https://prod.example/health perf/run_baseline.sh <host-label> [extra run_profile.sh options]   (shared host)
#   DEDICATED=1 perf/run_baseline.sh <host-label> [extra run_profile.sh options]                                 (nothing else runs there)
#
# The runs, in order: (1) the capacity climb at 1, 2, 4 and 6 workers (one worker is the Raspberry Pi's count) with levels low enough to find the usable one (T2, ten
# projects, plain and with the other record types in the mix); (2) the same climb at T3 with six workers and the
# recommended PostgreSQL memory settings; (3) every tier T0-T4 with the soak at four workers (the default), which gives memory per
# service at idle, under load and over time. A run that fails or aborts does not stop the next: every outcome is listed
# at the end and the exit status is non-zero if any failed. Each run is its own bundle under perf/results/<host-label>/;
# compare one with the last comparable bundle by `python3 perf/compare.py <bundle>`. A shared host should be run in a
# quiet window (the runs stop if PROD_HEALTH_URL slows).
set -u
here=$(cd "$(dirname "$0")" && pwd)
label=${1:?usage: perf/run_baseline.sh <host-label> [options]}
shift
if [ "${DEDICATED:-}" = "1" ]; then
    common="--dedicated"
else
    watch=""
    [ -n "${PROD_HEALTH_URL:-}" ] && watch="--watch-url $PROD_HEALTH_URL"
    common="--allow-heavy --max-load-per-core 3 $watch"
fi
failed=0
summary=""

run() {
    name=$1
    shift
    started=$(date +%s)
    echo "=== $name: $(date -u +%H:%M:%SZ)"
    # shellcheck disable=SC2086
    if "$here/run_profile.sh" "$label" "$@" $common; then
        outcome="ok     "
    else
        outcome="FAILED "
        failed=1
    fi
    minutes=$(( ($(date +%s) - started + 30) / 60 ))
    summary="$summary\n  $outcome $name (${minutes} min)"
}

run "1 capacity by worker count (T2, ten projects, plain and mixed)" --full --tiers T2 --breadth projects-10 --scenarios capacity,capacity_mixed --workers-sweep 1,2,4,6 --max-cpus 12 --capacity-users 32,64,128,192,256,384 "$@"
run "2 capacity at T3 (ten projects, six workers, shared_buffers 512MB)" --full --tiers T3 --breadth projects-10 --scenarios capacity --capacity-tier T3 --workers 6 --db-pool-size 4 --db-max-overflow 10 --max-cpus 12 --pg-shared-buffers 512MB --pg-work-mem 16MB --capacity-users 64,128,192,256 "$@"
run "3 memory and scaling baseline (T0-T4, soak, four workers)" --full --workers 4 "$@"

echo
echo "=== finished: $(date -u +%H:%M:%SZ)"
printf "%b\n" "$summary"
echo "bundles: ls -td perf/results/$label/*/ | head -6"
exit $failed
