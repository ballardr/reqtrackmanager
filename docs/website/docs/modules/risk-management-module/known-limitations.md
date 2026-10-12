---
sidebar_position: 38
---

# Known limitations

## Not built yet

- **No organisation-wide risk view.** The four [reports](./reports.md) are per project (use *Include child projects* to cover a hierarchy), and there is no organisation-wide risk dashboard or project-overview tile.
- **Change detection covers Requirements only.** Editing or archiving a Requirement flags the treatments resting on it; changing a linked Action, or (once installed) a Design, does not yet.
- **No Design or System Element links.** Reserved for the Engineering Design module. See [Treatment and relationships](./treatment-and-relationships.md#relationship-types).
- **Export carries less than the live record.** Version history, comments, scoring configuration and links to anything but same-project Requirements are not carried; see [Export and import](./export-and-import.md).
- **Change Impact analysis** isn't available; the planned module for it will read Risks when it exists.

## By design

- **Ratings are derived, never stored.** Changing the matrix re-rates existing Risks on their next view. A review keeps its own snapshot of the rating at the time.
- **Residual levels are set by a person.** They aren't recalculated when treatments change; the Mitigated and Accepted checks only require that a residual rating exists.
- **Two-axis matrices only get per-cell ratings.** The three-axis model uses threshold bands.
- **The Accepted lock is strict.** An Accepted Risk's levels, criteria and strategy can't be edited without first moving it back to Assessed.
- **Reviews can't be edited or deleted.** Record a new one instead.

## Where this fits

See [Overview](./overview.md) for what the module does support.
