"""ahcode-dbcheck.exe — connection test run by the wizard before files are copied."""
import sys

from app.config.dbcheck_cli import main

if __name__ == "__main__":
    sys.exit(main())
