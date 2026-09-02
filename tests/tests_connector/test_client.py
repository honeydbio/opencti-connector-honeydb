import json
from unittest.mock import MagicMock

import pytest
import requests
import requests_mock

from honeydb_client import (
    HoneyDBAuthError,
    HoneyDBClient,
    HoneyDBPlanError,
    HoneyDBQuotaError,
    HoneyDBResponseError,
    HoneyDBTransientError,
)

BASE = "https://honeydb.io/api"
URL = f"{BASE}/bad-hosts"
SECRET = "super-secret-key"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("honeydb_client.api_client.time.sleep", lambda _s: None)


def make_client(base_url=BASE) -> HoneyDBClient:
    return HoneyDBClient(
        MagicMock(),
        base_url=base_url,
        api_id="my-api-id",
        api_key=SECRET,
        user_agent="opencti-connector-honeydb/test",
    )


def test_success_returns_array_and_sends_headers(bad_hosts_fixture):
    with requests_mock.Mocker() as m:
        m.get(URL, json=bad_hosts_fixture, headers={"honeydb-qpm-remaining": "9"})
        client = make_client()
        result = client.bad_hosts()

    assert result == bad_hosts_fixture
    sent = m.request_history[0].headers
    assert sent["X-HoneyDb-ApiId"] == "my-api-id"
    assert sent["X-HoneyDb-ApiKey"] == SECRET
    assert sent["User-Agent"] == "opencti-connector-honeydb/test"
    assert sent["Accept"] == "application/json"
    client.helper.connector_logger.info.assert_called()
    logged = client.helper.connector_logger.info.call_args_list[-1].args[1]
    assert logged["entries"] == len(bad_hosts_fixture)
    assert logged["honeydb-qpm-remaining"] == "9"


@pytest.mark.parametrize("base", [BASE, BASE + "/"])
def test_base_url_trailing_slash_is_normalised(base):
    with requests_mock.Mocker() as m:
        m.get(URL, json=[])
        make_client(base).bad_hosts()
    assert m.request_history[0].url == URL


def test_base_url_accepts_pydantic_httpurl():
    from pydantic import HttpUrl

    with requests_mock.Mocker() as m:
        m.get(URL, json=[])
        make_client(HttpUrl(BASE)).bad_hosts()
    assert m.request_history[0].url == URL


def test_401_raises_auth_error():
    with requests_mock.Mocker() as m:
        m.get(URL, status_code=401, json={"status": "Invalid API Credentials"})
        with pytest.raises(HoneyDBAuthError) as excinfo:
            make_client().bad_hosts()
    assert "HONEYDB_API_KEY" in str(excinfo.value)
    assert m.call_count == 1


def test_402_raises_plan_error():
    with requests_mock.Mocker() as m:
        m.get(URL, status_code=402, json={"status": "Payment required"})
        with pytest.raises(HoneyDBPlanError) as excinfo:
            make_client().bad_hosts()
    assert "Payment required" in str(excinfo.value)
    assert m.call_count == 1


def test_429_raises_quota_error_with_headers():
    headers = {
        "honeydb-qpm-consumed": "100",
        "honeydb-qpm-remaining": "0",
        "honeydb-quota-window": "month",
        "Content-Type": "application/json",
    }
    with requests_mock.Mocker() as m:
        m.get(URL, status_code=429, headers=headers, json={"status": "Too many"})
        with pytest.raises(HoneyDBQuotaError) as excinfo:
            make_client().bad_hosts()
    assert excinfo.value.quota_headers == {
        "honeydb-qpm-consumed": "100",
        "honeydb-qpm-remaining": "0",
        "honeydb-quota-window": "month",
    }
    assert m.call_count == 1


def test_5xx_then_success_retries():
    with requests_mock.Mocker() as m:
        m.get(
            URL,
            [
                {"status_code": 503},
                {"status_code": 502},
                {"status_code": 500},
                {"json": [], "status_code": 200},
            ],
        )
        assert make_client().bad_hosts() == []
    assert m.call_count == 4


def test_5xx_exhausts_retries():
    with requests_mock.Mocker() as m:
        m.get(URL, status_code=503)
        with pytest.raises(HoneyDBTransientError) as excinfo:
            make_client().bad_hosts()
    assert m.call_count == 4
    assert "503" in str(excinfo.value)


def test_timeout_raises_transient_error():
    with requests_mock.Mocker() as m:
        m.get(URL, exc=requests.exceptions.ConnectTimeout)
        with pytest.raises(HoneyDBTransientError):
            make_client().bad_hosts()
    assert m.call_count == 4


def test_unexpected_4xx_raises_transient_error():
    with requests_mock.Mocker() as m:
        m.get(URL, status_code=404, text="nope")
        with pytest.raises(HoneyDBTransientError):
            make_client().bad_hosts()
    assert m.call_count == 1


def test_200_error_envelope_raises_response_error():
    with requests_mock.Mocker() as m:
        m.get(URL, json={"status": "Error! Please try again later."})
        with pytest.raises(HoneyDBResponseError) as excinfo:
            make_client().bad_hosts()
    assert "Please try again later" in str(excinfo.value)


def test_200_non_json_raises_response_error():
    with requests_mock.Mocker() as m:
        m.get(URL, text="<html>maintenance</html>")
        with pytest.raises(HoneyDBResponseError):
            make_client().bad_hosts()


def test_200_wrong_json_type_raises_response_error():
    with requests_mock.Mocker() as m:
        m.get(URL, text=json.dumps("just a string"))
        with pytest.raises(HoneyDBResponseError):
            make_client().bad_hosts()


@pytest.mark.parametrize(
    "response",
    [
        {"status_code": 401, "json": {"status": "bad"}},
        {"status_code": 402, "json": {"status": "bad"}},
        {"status_code": 429, "json": {"status": "bad"}},
        {"status_code": 503},
        {"status_code": 200, "json": {"status": "bad"}},
        {"status_code": 200, "text": "not json"},
        {"exc": requests.exceptions.ConnectionError},
    ],
)
def test_api_key_never_appears_in_exception_text(response):
    with requests_mock.Mocker() as m:
        m.get(URL, **response)
        with pytest.raises(Exception) as excinfo:
            make_client().bad_hosts()
    assert SECRET not in str(excinfo.value)
    assert SECRET not in repr(excinfo.value)
