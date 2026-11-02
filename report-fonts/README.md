# Extra report fonts

Put TrueType (`.ttf`) fonts here to offer them to report authors. This directory is mounted read-only into the backend
at `/app/report-fonts`; no rebuild is needed. Then open **Server management > Report fonts** and press **Rescan**.

- You are responsible for the fonts' licences. A font whose licence forbids embedding is refused.
- `.otf` and `.ttc` files are not supported.
- See [docs/deployment.md](../docs/deployment.md#extra-report-fonts).

The font files themselves are not tracked by git.
