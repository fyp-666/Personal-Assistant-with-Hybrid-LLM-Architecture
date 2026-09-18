"""Compatibility entry for previously installed daily briefing jobs.

New callers should use: hybrid-assistant gmail
"""

from cli.gmail import main

if __name__ == "__main__":
    main()
