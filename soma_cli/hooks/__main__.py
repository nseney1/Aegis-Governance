"""Backward-compatibility entrypoint forwarding to aegis_cli.hooks.__main__."""
import sys
from aegis_cli.hooks.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
