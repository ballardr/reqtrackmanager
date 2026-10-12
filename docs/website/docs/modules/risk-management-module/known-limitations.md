---
sidebar_position: 36
---

# Known limitations

## Not built yet

- **No Risk reports.** There is no module report, and no organisation-wide risk dashboard or project-overview tile. The register and matrix on each project are the views today.
- **Owner must be a user.** A Risk's owner can't yet be a group, so a Risk can lose its accountable owner when that person leaves. Shared group ownership is planned across the platform, not just here.
- **Change detection covers Requirements only.** Editing or archiving a Requirement flags the treatments resting on it; changing a linked Action, or (once installed) a Design, does not yet.
- **No Design or System Element links.** Reserved for the Engineering Design module. See [Treatment and relationships](./treatment-and-relationships.md#relationship-types).
- **Not part of project or organisation export.** Risks aren't carried in a zip export and import yet, and the scoring levels a Risk references aren't part of an organisation export either.
- **Change Impact analysis** isn't available; the planned module for it will read Risks when it exists.

## By design

- **Ratings are derived, never stored.** Changing the matrix re-rates existing Risks on their next view. A review keeps its own snapshot of the rating at the time.
- **Residual levels are set by a person.** They aren't recalculated when treatments change; the Mitigated and Accepted checks only require that a residual rating exists.
- **Two-axis matrices only get per-cell ratings.** The three-axis model uses threshold bands.
- **The Accepted lock is strict.** An Accepted Risk's levels, criteria and strategy can't be edited without first moving it back to Assessed.
- **Reviews can't be edited or deleted.** Record a new one instead.

## Where this fits

See [Overview](./overview.md) for what the module does support.
