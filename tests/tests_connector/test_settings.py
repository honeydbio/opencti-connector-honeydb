from datetime import timedelta

import pytest
from conftest import make_settings
from connectors_sdk import ConfigValidationError


def test_defaults():
    settings = make_settings()

    assert settings.connector.name == "Test Connector"
    assert str(settings.honeydb.api_base_url) == "https://honeydb.io/api"
    assert settings.honeydb.score == 50
    assert settings.honeydb.tlp_level == "clear"
    assert settings.honeydb.create_indicators is False
    assert settings.honeydb.min_count == 1
    assert settings.honeydb.indicator_valid_days == 7


def test_connector_defaults_when_only_id_given():
    settings = make_settings(
        {"connector": {"name": None, "scope": None, "duration_period": None}}
    )

    assert settings.connector.name == "HoneyDB"
    assert settings.connector.scope == ["honeydb"]
    assert settings.connector.duration_period == timedelta(hours=24)


def test_to_helper_config_is_dict():
    assert isinstance(make_settings().to_helper_config(), dict)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"honeydb": {"api_id": None}}, id="missing_api_id"),
        pytest.param({"honeydb": {"api_id": ""}}, id="empty_api_id"),
        pytest.param({"honeydb": {"api_key": None}}, id="missing_api_key"),
        pytest.param({"honeydb": {"api_key": ""}}, id="empty_api_key"),
        pytest.param({"honeydb": {"score": -1}}, id="score_below_zero"),
        pytest.param({"honeydb": {"score": 101}}, id="score_above_100"),
        pytest.param({"honeydb": {"tlp_level": "purple"}}, id="bad_tlp"),
        pytest.param({"honeydb": {"min_count": 0}}, id="min_count_zero"),
        pytest.param({"honeydb": {"indicator_valid_days": 0}}, id="valid_days_zero"),
        pytest.param({"honeydb": {"api_base_url": "not a url"}}, id="bad_url"),
        pytest.param({"connector": {"id": None}}, id="missing_connector_id"),
    ],
)
def test_rejections(overrides):
    with pytest.raises(ConfigValidationError):
        make_settings(overrides)


def test_bad_tlp_error_names_accepted_values():
    with pytest.raises(ConfigValidationError) as excinfo:
        make_settings({"honeydb": {"tlp_level": "purple"}})
    cause = str(excinfo.value.__cause__)
    for level in ("clear", "white", "green", "amber", "amber+strict", "red"):
        assert level in cause


def test_api_key_is_never_exposed():
    settings = make_settings({"honeydb": {"api_key": "super-secret-key"}})

    assert "super-secret-key" not in repr(settings)
    assert "super-secret-key" not in str(settings)
    assert "super-secret-key" not in repr(settings.honeydb)
    assert settings.honeydb.api_key.get_secret_value() == "super-secret-key"


def test_api_key_absent_from_other_fields_validation_error():
    with pytest.raises(ConfigValidationError) as excinfo:
        make_settings({"honeydb": {"api_key": "super-secret-key", "score": 500}})
    assert "super-secret-key" not in str(excinfo.value)
    assert "super-secret-key" not in str(excinfo.value.__cause__)


@pytest.mark.parametrize(
    "period, expect_warning",
    [
        pytest.param("PT30M", True, id="PT30M_warns"),
        pytest.param("PT1H", False, id="PT1H_quiet"),
        pytest.param("PT24H", False, id="PT24H_quiet"),
    ],
)
def test_short_period_warning(period, expect_warning):
    settings = make_settings({"connector": {"duration_period": period}})
    warning = settings.short_period_warning()
    if expect_warning:
        assert warning is not None
        assert "PT24H" in warning
    else:
        assert warning is None
