---
paths: ["backend/alembic/versions/*.py"]
---

For the general methodology (why `pytest`'s `create_all`-based fixtures never exercise real
Alembic migration SQL, and how to test a data-migrating revision against a throwaway
container), see `~/.claude/rules/alembic-migration-testing.md`.

**PIE Manager's own instance of this bug**, kept here as the concrete example: migration
`mm66nn77oo88` retargeted historical fee-transaction rows via 3 sequential `UPDATE`
statements. The 2nd `UPDATE`'s rename shifted a row off the 3rd `UPDATE`'s own
`WHERE`/`GROUP BY ... HAVING COUNT(*) = 2` filter, silently dropping that group's TTF leg —
caught only by testing against a real throwaway Postgres container, not by the pytest suite
(which builds its schema via `Base.metadata.create_all` and never runs Alembic at all).
Fixed by computing all 3 target row-sets from a single snapshot of the original data before
issuing any `UPDATE`.
