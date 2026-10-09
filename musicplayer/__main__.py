"""Compatibility entry point; use `hallucinate` for new installations."""

from hallucinate.app import main

if __name__ == "__main__":
    raise SystemExit(main())
