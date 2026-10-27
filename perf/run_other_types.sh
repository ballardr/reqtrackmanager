#!/bin/sh
# Runs the whole set of profiles for the record types other than requirements and the links between them, one after
# another, so it can run unattended (overnight) in one command:
#
#   PROD_HEALTH_URL=https://prod.example/health perf/run_other_types.sh <host-label> [extra run_profile.sh options]
#
# A host that also serves production should have PROD_HEALTH_URL set (the runs stop if production slows) and be run in
# a quiet window; leave it unset on a dedicated host and pass --dedicated instead. A run that fails or aborts does not
# stop the ones after it: every run's outcome is listed at the end, and the exit status is non-zero if any failed.
# Each run is its own bundle directory under perf/results/<host-label>/ (copy those; pass --archive to also get a
# .tar.gz of each beside it, inside perf/results/). Nothing is written outside the project except the dataset snapshots
# (--cache-dir).
#
# The runs, in order: (1) lists, links and search at T2 and T3; (2) exports, import previews and the bundles at T2;
# (3) the six-worker capacity climb at 256, 384 and 512 connections, writes spread over ten projects, once as before
# and once with the other types in the mix (both on this commit, so the two curves compare directly); (4) a nested tree at T1,
# which has the dormant and hidden links.
set -u
here=$(cd "$(dirname "$0")" && pwd)
label=${1:?usage: perf/run_other_types.sh <host-label> [options]}
shift
watch=""
[ -n "${PROD_HEALTH_URL:-}" ] && watch="--watch-url $PROD_HEALTH_URL"
common="--max-load-per-core 3 $watch"
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

run "1 lists, links, search (T2, T3)" --full --tiers T2,T3 --scenarios lists_by_type,links_mixed,search_all_types --workers 4 "$@"
run "2 exports, import previews, bundles (T2)" --full --tiers T2 --scenarios export_by_type,import_preview_by_type,bundle_export,org_bundle_export --workers 4 --allow-heavy "$@"
run "3 capacity, plain and with the other types (T2, ten projects, six workers)" --full --tiers T2 --breadth projects-10 --scenarios capacity,capacity_mixed --workers 6 --db-pool-size 4 --db-max-overflow 10 --max-cpus 12 --capacity-users 256,384,512 --allow-heavy "$@"
run "4 nested tree (T1)" --full --tiers T1 --breadth nested-3x5 --scenarios links_mixed,lists_by_type,org_bundle_export --workers 4 --allow-heavy "$@"

echo
echo "=== finished: $(date -u +%H:%M:%SZ)"
printf "%b\n" "$summary"
echo "bundles: ls -td perf/results/$label/*/ | head -4"
exit $failed
