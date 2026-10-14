"""Backward-compatibility entrypoint forwarding to aegis_cli.cli.main."""
import sys
from aegis_cli.cli import main

if __name__ == "__main__":
    sys.exit(main(prog="soma"))
