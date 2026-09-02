import json
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))
from typing import Any
from unittest.mock import MagicMock

import pytest

from connector import ConnectorSettings

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

VALID_SETTINGS_DICT: dict[str, Any] = {
    "opencti": {
        "url": "http://localhost:8080",
        "token": "test-token",
    },
    "connector": {
        "id": "connector-id",
        "name": "Test Connector",
        "scope": "test, connector",
        "log_level": "error",
        "duration_period": "PT5M",
    },
    "honeydb": {
        "api_id": "test-api-id",
        "api_key": "test-api-key",
        "tlp_level": "clear",
    },
}


@pytest.fixture
def mock_opencti_connector_helper(monkeypatch):
    """Mock all heavy dependencies of OpenCTIConnectorHelper, typically API calls to OpenCTI."""

    module_import_path = "pycti.connector.opencti_connector_helper"
    monkeypatch.setattr(f"{module_import_path}.killProgramHook", MagicMock())
    monkeypatch.setattr(f"{module_import_path}.sched.scheduler", MagicMock())
    monkeypatch.setattr(f"{module_import_path}.ConnectorInfo", MagicMock())
    monkeypatch.setattr(f"{module_import_path}.OpenCTIApiClient", MagicMock())
    monkeypatch.setattr(f"{module_import_path}.OpenCTIConnector", MagicMock())
    monkeypatch.setattr(f"{module_import_path}.OpenCTIMetricHandler", MagicMock())
    monkeypatch.setattr(f"{module_import_path}.PingAlive", MagicMock())


class StubConnectorSettings(ConnectorSettings):
    """
    Subclass of `ConnectorSettings` (implementation of `BaseConnectorSettings`) for testing purpose.
    It overrides `BaseConnectorSettings._load_config_dict` to return a fake but valid config dict.
    """

    @classmethod
    def _load_config_dict(cls, _, handler) -> dict[str, Any]:
        return handler(VALID_SETTINGS_DICT)


def make_settings(overrides: dict[str, Any] | None = None) -> ConnectorSettings:
    """Build settings from `VALID_SETTINGS_DICT` with per-section overrides."""
    data = json.loads(json.dumps(VALID_SETTINGS_DICT))
    for section, values in (overrides or {}).items():
        for key, value in values.items():
            if value is None:
                # `None` means "absent", as if the variable were never set.
                data.setdefault(section, {}).pop(key, None)
            else:
                data.setdefault(section, {})[key] = value

    class OverriddenSettings(ConnectorSettings):
        @classmethod
        def _load_config_dict(cls, _, handler) -> dict[str, Any]:
            return handler(data)

    return OverriddenSettings()


@pytest.fixture
def bad_hosts_fixture() -> list[dict[str, Any]]:
    with open(os.path.join(FIXTURES_DIR, "bad_hosts.json")) as fh:
        return json.load(fh)


@pytest.fixture
def fake_helper() -> MagicMock:
    """A helper stand-in: logger calls are recorded, OpenCTI is never contacted."""
    helper = MagicMock()
    helper.connect_id = "connector-id"
    helper.connect_name = "Test Connector"
    helper.get_state.return_value = None
    helper.api.work.initiate_work.return_value = "work-id"
    helper.send_stix2_bundle.return_value = ["bundle"]
    helper.stix2_create_bundle.side_effect = lambda objects: json.dumps(
        {"objects": len(objects)}
    )
    return helper
