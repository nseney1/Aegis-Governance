"""Allow `python3 -m aegis_cli` when the aegis script is not on PATH."""
import sys

from aegis_cli.cli import main

if __name__ == "__main__":
    sys.exit(main(prog="aegis"))
