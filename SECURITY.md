# Security

This repository may be used with sensitive clinical export data.

## Data handling
- Never commit raw TriNetX exports or row-level patient data.
- Store real inputs under `data/` (git-ignored).
- Use synthetic or de-identified fixtures under `tests/fixtures/`.

See: `docs/SECURITY_PRIVACY.md`.
