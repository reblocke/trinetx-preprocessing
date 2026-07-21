# Codex Workflow

This repo is refactored using an autonomous Codex chain (`gpt-5.2-codex`).

## How we run tasks
- Each task has a single prompt file under `docs/prompts/` (or `docs/`).
- Example:
  ```bash
  codex exec --model gpt-5.2-codex --full-auto - < docs/prompts/001_scaffold.txt
  ```

## Rules for prompts
- Keep scope narrow: one milestone per prompt.
- Require tests to pass at the end.
- Require docs updates when behavior or assumptions change.
- Require a short “what changed” summary in the final message.

## Guardrails
- Never allow Codex to read or commit `data/`.
- Prefer synthetic fixtures for all test/validation work.
- If output semantics change, it must be written to `docs/DECISIONS.md`.
