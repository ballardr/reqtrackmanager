# Performance findings

What the profiling runs (`perf/`, how-to in [perf/README.md](../perf/README.md)) found about how the product scales,
and what was done. One entry per finding, latest state only. Numbers are from Docker Desktop on a Mac (amd64, one
backend worker, shared host), so **statement and row counts are exact and latencies are indicative**: untouched
endpoints differed by 2-10x between two otherwise identical runs, so a latency difference alone is never taken as a
finding or as proof of a fix.

```mermaid
flowchart LR
    R["Tier runs + profiles"] --> F["Finding<br/>(evidence, cause)"]
    F --> X["Fix + guard test<br/>(statements, rows read)"]
    X --> V["Re-run same tier:<br/>before / after"]
    V -->|"counts fall"| C["Closed"]
    V -->|"still over budget"| F
```

## Closed

| # | Symptom | Cause | Fix | Before to after (T2, 1,000 requirements) | Guard |
|---|---------|-------|-----|------------------------------------------|-------|
| F1 | A "page of 50" request cost as much as the whole project: 1.3 s at 5,000 requirements and 5.2 s at 20,000 (p95) | The list loaded and serialised every requirement, then sliced. Once the per-row lookups were paged, the remaining cost was reading all 19,031 rows: 59% of CPU, nearly all of it psycopg2 turning six UUID columns per row into Python objects, plus building a mapped entity per row | The database applies every filter, the order (component, category, manual; or one column, `COLLATE "C"` to match Python's order) and the page; one UUID column per row; the full records, versions, people, tags and counts are loaded for the returned page only. A keyword filter (tag names) still narrows in Python; a scope widened over related projects still reads each project whole to order them together | Rows read per request (1,000 requirements): versions 946 to 50, tags 1,151 to 61, comment counts 672 to 36. p95 at 20,000: page of 50 5.2 s to 0.75 s (same as at 5,000, so flat in project size); status + sort 5.4 s to 0.63 s; text search 5.7 s to 0.68 s; has comments 6.3 s to 0.30 s | `test_requirements_page_cost_does_not_grow_with_the_project` (versions and records read), `test_requirements_sorted_page_matches_the_full_sorted_list`, `test_requirements_list_filters_and_default_order_are_unchanged`, `test_requirements_sql_filters_and_sort_match_what_python_would_return` (accents, punctuation, every sort column) |
| F2 | Project overview ran 282 statements | A module-availability lookup (5 statements) repeated for each of about 20 record types; counts read every requirement id back and sent them in `IN (...)` lists | Module state read once per module for the request; counts and stage progress are database aggregates | Statements per request 282 to 96 (flat in the data) | `test_project_metrics_query_count_does_not_grow_with_the_project` |
| F3 | A record's link list ran 57 statements at 100 requirements and 170 at 1,000 | Two lookups per link (the other record and its current version) | Link types, other records and their names loaded once for the whole list | Statements 57 / 170 to 16 / 16 | `test_requirement_links_query_count_does_not_grow_with_the_link_count` |
| F4 | Every requirement list counted comments with a sequential scan | No index on the comment target | Migration 0107 adds `ix_review_comments_target` | Planner cost 1,856 to 454; no measurable time change at 1,100 comments | `test_review_comment_index.py` |
| F5 | Found by a full run on a Linux server (T3-sized project): project export ran one `SELECT email` per requirement (4,363), the requirements report one version and one tag query per requirement (1,777 and more), and a record import update four structure queries and two person lookups per row (3,554) | Per-row lookups of a person, a version, a tag list and the type's structure | Export reads each person or group once (`principal_to_bundle` memoised for the request); the report reads versions and tags in one statement each; the import finds the named records and prepares them once for the whole file | 40 requirements: export 106 to 67 statements, report 99 to 21, record import 399 to 126 (the remaining 40 are one lookup per named record) | `test_export_report_and_record_import_statements_do_not_grow_with_the_requirements` |
| F6 | A comment thread cost three statements per comment (reaction count, my reaction, attachments) | `comment_to_out` queried per comment | `comments_to_out` reads authors, reaction counts, my reactions and attachments in one statement each; the requirement, action and change request lists use it | Statements for a thread of 12: flat with the thread length | `test_requirement_comments_statements_do_not_grow_with_the_thread` |

## Open

| # | Observation | Evidence | Next step |
|---|-------------|----------|-----------|
| O1 | The page-of-50 list is 0.75 s at p95 at T3 and T4, above the 300 ms budget; the count over the whole project is the remaining database work | `latency.csv` T3/T4, four users on one worker on a shared host | Re-measure on a dedicated host before changing anything further |
| O2 | `link-candidates` (1.1-1.3 s), `link-graph` for a hub (1.5-1.9 s) and a hub's link list (0.7 s) are flat between T3 and T4, so they depend on the hub's degree, not the project size | `latency.csv` | Profile with `--profiling cpu` on a hub; the link list is already 16 statements |
| O6 | Project import runs, per requirement, about 3 tag-vocabulary statements, 2 parent-project lookups, 1 organisation-role lookup and 1 audit insert (576 statements for 40 requirements); a record import still looks up each named record with its own statement | Probe of a 40-requirement project | Needs bundle-scoped caches (the tag list changes as the import creates tags, and the organisation-role lookup shares a memo with project roles that the import creates), so it is its own change with its own tests |
| O3 | Other modules list links and comments with the same per-row lookups as F3 and F6 (decisions, context and strategy, stakeholders: their own `comment_to_out` and `_link_to_out`) | Read from code; not measured, because the dataset generator has no generators for those module types yet | Measure once the module generators exist; apply the F3 pattern where it holds |
| O4 | T3 and T4 (5,000 and 20,000 requirements) not yet measured; the buffer cache and `work_mem` question is open for them | Runs in progress on a Linux server and a Raspberry Pi | Add findings from those bundles |
| O5 | Four workers hold about 400 MiB each with almost nothing shared | Memory profile | A pre-fork server is its own change; the user decides whether to pursue it |
