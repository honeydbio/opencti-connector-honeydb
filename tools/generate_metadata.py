"""
Generate `__metadata__/connector_config_schema.json` and
`__metadata__/CONNECTOR_CONFIG_DOC.md` from `ConnectorSettings`.

This mirrors what `shared/tools/composer/generate_connectors_config_schemas`
does in the upstream OpenCTI-Platform/connectors repository, so the committed
files are byte-identical to what upstream would generate. CI runs it and fails
on any diff, which keeps the files from drifting away from `settings.py`.

Usage: `make metadata` (or `python tools/generate_metadata.py`).
"""

import json
import os
import sys

import jsonschema_markdown

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from connector import ConnectorSettings  # noqa: E402

CONNECTOR_NAME = "honeydb"
METADATA_DIR = os.path.join(ROOT, "__metadata__")
SCHEMA_PATH = os.path.join(METADATA_DIR, "connector_config_schema.json")
DOC_PATH = os.path.join(METADATA_DIR, "CONNECTOR_CONFIG_DOC.md")
CUSTOM_CONFIG_DOC_DESCRIPTION = (
    "Below is an exhaustive enumeration of all configurable parameters "
    "available, each accompanied by detailed explanations of their purposes, "
    "default behaviors, and usage guidelines to help you understand and utilize "
    "them effectively."
)


def main() -> None:
    os.makedirs(METADATA_DIR, exist_ok=True)

    schema = ConnectorSettings.config_json_schema(
        by_alias=False, connector_name=CONNECTOR_NAME, mode="validation"
    )
    with open(SCHEMA_PATH, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(schema, indent=2))
    print(f"Connector config JSON schema written to {SCHEMA_PATH}")

    schema["description"] = CUSTOM_CONFIG_DOC_DESCRIPTION
    markdown = jsonschema_markdown.generate(
        schema,
        title="Connector Configurations",
        hide_empty_columns=True,
        footer=False,
    )
    with open(DOC_PATH, "w", encoding="utf-8") as fh:
        fh.write(markdown)
    print(f"Connector config documentation written to {DOC_PATH}")


if __name__ == "__main__":
    main()
