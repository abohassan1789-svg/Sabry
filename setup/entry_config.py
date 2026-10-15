"""ahcode-config.exe — the installer's configuration helper (console, run hidden)."""
import sys

from app.config.frozen_runtime import prepare

if __name__ == "__main__":
    prepare(chdir=False)
    from app.config.configure_cli import main

    sys.exit(main())
