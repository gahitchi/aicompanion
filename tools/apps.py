"""App and URL launchers. Cross-platform impl lives in platform_io;
re-exported here so the registry keeps importing them from tools.apps."""
from platform_io import open_app, open_url  # noqa: F401  (re-export)
