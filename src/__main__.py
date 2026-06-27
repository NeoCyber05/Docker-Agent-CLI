"""``python -m docker_agent`` entrypoint.

Parity: ``src/entrypoints/cli.ts``.
"""

from __future__ import annotations

from src.cli import main

if __name__ == "__main__":
    main()