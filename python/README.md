# docker-agent (Python rewrite)

Python rewrite of the TypeScript `docker-agent` CLI. See `../docs/plans/2026-06-27-python-rewrite-ROADMAP.md` for the full plan and `../docs/plans/2026-06-27-py-01-scaffolding-types.md` for the current phase.

## Dev

```bash
uv sync
uv run pytest
uv run ruff check .
uv run mypy src
```