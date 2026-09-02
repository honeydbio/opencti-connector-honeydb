from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from conftest import make_settings

from connector import HoneyDBConnector
from honeydb_client import (
    HoneyDBAuthError,
    HoneyDBPlanError,
    HoneyDBQuotaError,
    HoneyDBResponseError,
    HoneyDBTransientError,
)

NOW = datetime(2026, 9, 2, 12, 0, 0, tzinfo=UTC)


def make_connector(fake_helper, overrides=None, entries=None) -> HoneyDBConnector:
    settings = make_settings(overrides)
    connector = HoneyDBConnector(config=settings, helper=fake_helper)
    connector.client = MagicMock()
    connector.client.bad_hosts.return_value = entries if entries is not None else []
    return connector


@pytest.fixture
def frozen_now():
    with patch("connector.connector._utc_now", return_value=NOW):
        yield NOW


def test_startup_logs_redacted_config_and_no_key(fake_helper):
    make_connector(
        fake_helper, {"honeydb": {"api_key": "super-secret-key", "api_id": "id-1"}}
    )
    logged = str(fake_helper.connector_logger.info.call_args_list)
    assert "id-1" in logged
    assert "super-secret-key" not in logged
    assert "super-secret-key" not in str(
        fake_helper.connector_logger.warning.call_args_list
    )


def test_startup_warns_on_short_period(fake_helper):
    make_connector(fake_helper, {"connector": {"duration_period": "PT10M"}})
    fake_helper.connector_logger.warning.assert_called_once()
    assert "PT24H" in fake_helper.connector_logger.warning.call_args.args[0]


def test_startup_quiet_on_default_period(fake_helper):
    make_connector(fake_helper, {"connector": {"duration_period": "PT24H"}})
    fake_helper.connector_logger.warning.assert_not_called()


def test_client_gets_user_agent_and_credentials(fake_helper):
    settings = make_settings({"honeydb": {"api_key": "k", "api_id": "i"}})
    connector = HoneyDBConnector(config=settings, helper=fake_helper)
    headers = connector.client.session.headers
    assert headers["User-Agent"].startswith("opencti-connector-honeydb/")
    assert headers["X-HoneyDb-ApiId"] == "i"
    assert headers["X-HoneyDb-ApiKey"] == "k"


def test_success_run(fake_helper, bad_hosts_fixture, frozen_now):
    connector = make_connector(fake_helper, entries=bad_hosts_fixture)

    connector.process_message()

    connector.client.bad_hosts.assert_called_once()
    fake_helper.api.work.initiate_work.assert_called_once()
    fake_helper.send_stix2_bundle.assert_called_once()
    kwargs = fake_helper.send_stix2_bundle.call_args.kwargs
    assert kwargs["update"] is True
    assert kwargs["work_id"] == "work-id"
    assert kwargs["cleanup_inconsistent_bundle"] is True
    # 5 observables + author + marking
    bundle_objects = fake_helper.stix2_create_bundle.call_args.args[0]
    assert len(bundle_objects) == 7

    fake_helper.set_state.assert_called_once()
    state = fake_helper.set_state.call_args.args[0]
    assert state["last_run"] == "2026-09-02T12:00:00+00:00"
    assert state["last_count"] == 5
    assert "last_error" not in state

    fake_helper.api.work.to_processed.assert_called_once()
    args, kwargs = fake_helper.api.work.to_processed.call_args
    assert args[0] == "work-id"
    assert "5 observables" in args[1]
    assert "3 skipped" in args[1]
    assert not kwargs.get("in_error")


def test_success_clears_previous_error(fake_helper, bad_hosts_fixture, frozen_now):
    fake_helper.get_state.return_value = {
        "last_error": {"at": "x", "type": "HoneyDBQuotaError"}
    }
    connector = make_connector(fake_helper, entries=bad_hosts_fixture)
    connector.process_message()
    state = fake_helper.set_state.call_args.args[0]
    assert "last_error" not in state


def test_empty_list_is_success_without_bundle(fake_helper, frozen_now):
    connector = make_connector(fake_helper, entries=[])

    connector.process_message()

    fake_helper.send_stix2_bundle.assert_not_called()
    fake_helper.set_state.assert_called_once()
    assert fake_helper.set_state.call_args.args[0]["last_count"] == 0
    args, kwargs = fake_helper.api.work.to_processed.call_args
    assert "0 observables" in args[1]
    assert not kwargs.get("in_error")


def test_all_unparsable_marks_work_in_error(fake_helper, frozen_now):
    entries = [{"remote_host": "nope", "count": 1}, {"count": "x"}]
    connector = make_connector(fake_helper, entries=entries)

    connector.process_message()

    fake_helper.send_stix2_bundle.assert_not_called()
    _, kwargs = fake_helper.api.work.to_processed.call_args
    assert kwargs["in_error"] is True
    state = fake_helper.set_state.call_args.args[0]
    assert state["last_error"]["type"] == "HoneyDBResponseError"
    assert "last_run" not in state


@pytest.mark.parametrize(
    "error",
    [
        HoneyDBQuotaError("quota", {"honeydb-qpm-remaining": "0"}),
        HoneyDBAuthError("auth"),
        HoneyDBPlanError("plan"),
        HoneyDBTransientError("transient"),
        HoneyDBResponseError("response"),
    ],
)
def test_client_errors_mark_work_in_error_and_keep_last_run(
    fake_helper, frozen_now, error
):
    fake_helper.get_state.return_value = {
        "last_run": "2026-08-01T00:00:00+00:00",
        "last_count": 10,
    }
    connector = make_connector(fake_helper)
    connector.client.bad_hosts.side_effect = error

    connector.process_message()  # must not raise

    fake_helper.send_stix2_bundle.assert_not_called()
    fake_helper.api.work.to_processed.assert_called_once()
    args, kwargs = fake_helper.api.work.to_processed.call_args
    assert args[0] == "work-id"
    assert kwargs["in_error"] is True

    state = fake_helper.set_state.call_args.args[0]
    assert state["last_run"] == "2026-08-01T00:00:00+00:00"
    assert state["last_count"] == 10
    assert state["last_error"] == {
        "at": "2026-09-02T12:00:00+00:00",
        "type": type(error).__name__,
    }
    assert "quota" not in str(state)  # class name only, never the message
    fake_helper.connector_logger.error.assert_called()


def test_quota_headers_are_logged(fake_helper, frozen_now):
    connector = make_connector(fake_helper)
    connector.client.bad_hosts.side_effect = HoneyDBQuotaError(
        "quota", {"honeydb-qpm-remaining": "0"}
    )
    connector.process_message()
    logged = str(fake_helper.connector_logger.error.call_args_list)
    assert "honeydb-qpm-remaining" in logged


def test_auth_error_logs_hint(fake_helper, frozen_now):
    connector = make_connector(fake_helper)
    connector.client.bad_hosts.side_effect = HoneyDBAuthError("auth")
    connector.process_message()
    logged = str(fake_helper.connector_logger.error.call_args_list)
    assert "HONEYDB_API_KEY" in logged


def test_unexpected_exception_does_not_propagate(fake_helper, frozen_now):
    connector = make_connector(fake_helper)
    connector.client.bad_hosts.side_effect = RuntimeError("boom")

    connector.process_message()

    _, kwargs = fake_helper.api.work.to_processed.call_args
    assert kwargs["in_error"] is True
    assert (
        fake_helper.set_state.call_args.args[0]["last_error"]["type"] == "RuntimeError"
    )


def test_error_before_work_does_not_call_to_processed(fake_helper, frozen_now):
    fake_helper.get_state.side_effect = [RuntimeError("state unavailable"), {}]
    connector = make_connector(fake_helper)

    connector.process_message()

    fake_helper.api.work.to_processed.assert_not_called()
    fake_helper.api.work.initiate_work.assert_not_called()


def test_restart_inside_period_skips(fake_helper, frozen_now):
    fake_helper.get_state.return_value = {
        "last_run": (NOW - timedelta(hours=2)).isoformat(timespec="seconds"),
        "last_count": 5,
    }
    connector = make_connector(fake_helper, {"connector": {"duration_period": "PT24H"}})

    connector.process_message()

    fake_helper.api.work.initiate_work.assert_not_called()
    connector.client.bad_hosts.assert_not_called()
    fake_helper.set_state.assert_not_called()
    logged = str(fake_helper.connector_logger.info.call_args_list)
    assert "skipping" in logged


def test_run_after_period_elapsed(fake_helper, frozen_now, bad_hosts_fixture):
    fake_helper.get_state.return_value = {
        "last_run": (NOW - timedelta(hours=25)).isoformat(timespec="seconds"),
    }
    connector = make_connector(
        fake_helper, {"connector": {"duration_period": "PT24H"}}, bad_hosts_fixture
    )
    connector.process_message()
    connector.client.bad_hosts.assert_called_once()


def test_scheduled_run_slightly_early_is_not_skipped(fake_helper, frozen_now):
    # The helper reschedules after a run finishes; clock jitter of a few
    # seconds must not turn a legitimate run into a skip.
    fake_helper.get_state.return_value = {
        "last_run": (NOW - timedelta(hours=24) + timedelta(seconds=30)).isoformat(
            timespec="seconds"
        ),
    }
    connector = make_connector(fake_helper, {"connector": {"duration_period": "PT24H"}})
    connector.process_message()
    connector.client.bad_hosts.assert_called_once()


@pytest.mark.parametrize(
    "state",
    [
        None,
        {},
        {"last_run": "not a date"},
        {"last_run": 12345},
        {"last_run": "2026-09-02 10:00:00"},  # legacy naive format, 2h ago -> skip
    ],
)
def test_state_variants(fake_helper, frozen_now, state):
    fake_helper.get_state.return_value = state
    connector = make_connector(fake_helper, {"connector": {"duration_period": "PT24H"}})
    connector.process_message()
    if state == {"last_run": "2026-09-02 10:00:00"}:
        connector.client.bad_hosts.assert_not_called()
    else:
        connector.client.bad_hosts.assert_called_once()


def test_run_schedules_with_period_seconds(fake_helper):
    connector = make_connector(fake_helper, {"connector": {"duration_period": "PT24H"}})
    connector.run()
    fake_helper.schedule_process.assert_called_once_with(
        message_callback=connector.process_message, duration_period=86400.0
    )
