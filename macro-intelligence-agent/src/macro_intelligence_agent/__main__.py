"""Allow invoking the CLI via `python3 -m macro_intelligence_agent`."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
