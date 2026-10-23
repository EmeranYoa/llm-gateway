"""Print the OpenAPI schema of the admin API as JSON.

The dashboard generates its TypeScript types from this schema:

    uv run python -m app.admin_api.export_openapi                        # to stdout
    uv run python -m app.admin_api.export_openapi dashboard/openapi.json  # to a file

Writing to a file gives the same bytes on every system (UTF-8, "\\n" line endings),
which a shell redirection does not always do on Windows.

Building the schema needs the gateway configuration only: the database and Redis
clients connect lazily, so neither has to be running.
"""

import json
import sys
from pathlib import Path

from app.admin_api.main import create_admin_app
from app.config import Settings


def export_openapi() -> str:
    """Return the OpenAPI schema of the admin API as stable, indented JSON."""
    app = create_admin_app(Settings(gateway_config_path=Path("config/gateway.yaml")))
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main(arguments: list[str]) -> None:
    schema = export_openapi()
    if arguments:
        Path(arguments[0]).write_text(schema, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(schema)


if __name__ == "__main__":
    main(sys.argv[1:])
