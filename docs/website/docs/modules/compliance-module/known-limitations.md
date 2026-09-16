---
sidebar_position: 8
---

# Known limitations

- **No branded report styling.** Compliance reports/exports do not currently support the branded report-template styling (logo, accent colour, cover page) core requirement reports can use — they render with a fixed, unbranded layout.
- **A project bundle's compliance assignment needs a matching standard already present.** It can only be restored into an organisation that already has a matching standard/version (by reference and version label) — it is never recreated from the bundle itself. Re-establish the standard first (directly, or via an organisation bundle import) if importing a project into an organisation that doesn't yet have it. See [Reporting and export → Export/import bundles](./reporting-and-export.md#exportimport-bundles).
- **No automated compliance determination.** Automated compliance rules, automatic compliance determination from required-action outcomes, compliance certificates/digital signatures, and customer-facing compliance portals are explicitly out of scope for this module today — the data model is deliberately built so none of them are precluded later.
- **Standards Manager/Contributor grants are per-person only.** There is no way to grant either role to everyone in a group at once — the org's designated fallback compliance-managers group ([Overview → Roles](./overview.md#roles)) is a narrow floor-satisfaction mechanism only, not a general group-based grant path.

## Where this fits

See [Overview](./overview.md) for what the module *does* support.
