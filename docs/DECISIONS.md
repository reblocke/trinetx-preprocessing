# Decisions Log

Record decisions that affect behavior, reproducibility, or maintainability.

## Template
- Date:
- Decision:
- Context:
- Options considered:
- Rationale:
- Consequences:
- References (files/lines, links):

## Entries

### YYYY-MM-DD — Example decision title
- Date: YYYY-MM-DD
- Decision: Use Parquet for intermediate files instead of CSV.
- Context: CSV parsing is slow and memory-heavy.
- Options considered:
  - Keep CSV
  - Parquet (pyarrow)
  - SQLite
- Rationale: Faster reads, compression, stable schemas.
- Consequences: Adds dependency on `pyarrow`; need clear install path.
- References: docs/ARCHITECTURE.md; profiling notes.
