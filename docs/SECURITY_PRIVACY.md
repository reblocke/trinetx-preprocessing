# Security and Privacy

## Non-negotiables
- Do not commit raw TriNetX exports, row-level patient data, or derived row-level outputs.
- Store real data under `data/` (git-ignored).
- Use only synthetic or de-identified fixtures in `tests/fixtures/`.

## Logging
- Logs must not print patient identifiers.
- Prefer aggregate counts and high-level summaries.

## Sharing
- If you need to share an error case, reduce it to a synthetic reproducer.
- If a schema sample is needed, redact and minimize.
