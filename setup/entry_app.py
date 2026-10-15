"""A-H CODE.exe — the installed application."""
import sys

from app.config.frozen_runtime import prepare, smoke_import

if __name__ == "__main__":
    prepare()
    if len(sys.argv) == 3 and sys.argv[1] == "--smoke-imports":
        sys.exit(smoke_import(["app.config", "app.database", "app.models", "app.repositories",
                               "app.services", "app.reports", "app.security", "app.ui"],
                              sys.argv[2]))
    from app.main import main

    main()
