import time
from typing import TYPE_CHECKING, Any

import requests

from honeydb_client.exceptions import (
    HoneyDBAuthError,
    HoneyDBPlanError,
    HoneyDBQuotaError,
    HoneyDBResponseError,
    HoneyDBTransientError,
)

if TYPE_CHECKING:
    from pycti import OpenCTIConnectorHelper

# HoneyDB reports quota usage on every authenticated response with these
# lower-cased header names; they are surfaced on 429 and logged on success.
QUOTA_HEADER_PREFIX = "honeydb-"
RETRYABLE_STATUS = frozenset({500, 502, 503, 504})
ERROR_BODY_PREVIEW_CHARS = 200


class HoneyDBClient:
    """
    Thin client for the single HoneyDB endpoint this connector needs.

    Authentication uses the `X-HoneyDb-ApiId` / `X-HoneyDb-ApiKey` headers, the
    same scheme as the official `honeydb` Python module. The API key is only
    ever placed in the session headers: it is never logged, hashed, truncated,
    or included in exception text.
    """

    def __init__(
        self,
        helper: "OpenCTIConnectorHelper",
        base_url: Any,
        api_id: str,
        api_key: str,
        user_agent: str,
        timeout: tuple[float, float] = (10, 120),
        max_retries: int = 3,
        backoff_factor: float = 1.0,
    ):
        """
        :param helper: Connector helper, used for logs only.
        :param base_url: HoneyDB API base URL (with or without a trailing slash).
        :param api_id: HoneyDB API ID.
        :param api_key: HoneyDB API key.
        :param user_agent: `User-Agent` header value sent on every request.
        :param timeout: `(connect, read)` timeouts in seconds. The read timeout is
            generous because HoneyDB falls back to a live aggregation when its
            daily cache object is missing.
        :param max_retries: Retries after the first attempt for network errors
            and 5xx responses. 401/402/429 are never retried.
        :param backoff_factor: Sleep `backoff_factor * 2**attempt` between retries.
        """
        self.helper = helper
        self.base_url = str(base_url).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-HoneyDb-ApiId": api_id,
                "X-HoneyDb-ApiKey": api_key,
                "Accept": "application/json",
                "User-Agent": user_agent,
            }
        )

    @staticmethod
    def _quota_headers(response: requests.Response) -> dict[str, str]:
        return {
            name.lower(): value
            for name, value in response.headers.items()
            if name.lower().startswith(QUOTA_HEADER_PREFIX)
        }

    @staticmethod
    def _status_text(response: requests.Response) -> str:
        """Best-effort extraction of HoneyDB's `{"status": "..."}` error envelope."""
        try:
            body = response.json()
        except ValueError:
            return ""
        if isinstance(body, dict) and isinstance(body.get("status"), str):
            return body["status"][:ERROR_BODY_PREVIEW_CHARS]
        return ""

    def _get_with_retry(self, url: str) -> requests.Response:
        """
        GET `url`, retrying network errors and 5xx responses with exponential
        backoff. Returns the last response; raises `HoneyDBTransientError` when
        every attempt failed on the network.
        """
        attempts = self.max_retries + 1
        last_error: Exception | None = None
        response: requests.Response | None = None

        for attempt in range(attempts):
            if attempt:
                time.sleep(self.backoff_factor * (2 ** (attempt - 1)))
            try:
                response = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as err:
                last_error = err
                self.helper.connector_logger.warning(
                    "[API] Request failed, will retry",
                    {"url_path": url, "attempt": attempt + 1, "error": str(err)},
                )
                continue

            if response.status_code in RETRYABLE_STATUS:
                self.helper.connector_logger.warning(
                    "[API] Server error, will retry",
                    {
                        "url_path": url,
                        "attempt": attempt + 1,
                        "status_code": response.status_code,
                    },
                )
                continue
            return response

        if response is not None:
            return response
        raise HoneyDBTransientError(
            f"request to {url} failed after {attempts} attempts: "
            f"{type(last_error).__name__}: {last_error}"
        )

    def bad_hosts(self) -> list[dict[str, Any]]:
        """
        Fetch the community bad-hosts list (trailing 24 hours).

        :return: The API's JSON array, untouched. Entries look like
            `{"remote_host": str, "count": int, "last_seen": "YYYY-MM-DD"}`.
        :raises HoneyDBAuthError: 401.
        :raises HoneyDBPlanError: 402.
        :raises HoneyDBQuotaError: 429, with the `honeydb-*` headers attached.
        :raises HoneyDBTransientError: network failure or non-2xx after retries.
        :raises HoneyDBResponseError: 2xx body that is not a JSON array.
        """
        url = f"{self.base_url}/bad-hosts"
        self.helper.connector_logger.info(
            "[API] HTTP GET request to endpoint", {"url_path": url}
        )
        response = self._get_with_retry(url)
        status = response.status_code

        if status == 401:
            raise HoneyDBAuthError(
                "HoneyDB rejected the API credentials (HTTP 401); check "
                "HONEYDB_API_ID and HONEYDB_API_KEY"
            )
        if status == 402:
            raise HoneyDBPlanError(
                "HoneyDB refused the request for plan/billing reasons (HTTP 402): "
                f"{self._status_text(response) or 'no detail'}"
            )
        if status == 429:
            quota = self._quota_headers(response)
            raise HoneyDBQuotaError(
                "HoneyDB API quota exhausted (HTTP 429); the run will be retried "
                f"next period. Quota headers: {quota}",
                quota_headers=quota,
            )
        if not 200 <= status < 300:
            raise HoneyDBTransientError(
                f"HoneyDB returned HTTP {status} for {url}: "
                f"{self._status_text(response) or 'no detail'}"
            )

        try:
            body = response.json()
        except ValueError as err:
            raise HoneyDBResponseError(
                f"HoneyDB returned a non-JSON body for {url}"
            ) from err

        if isinstance(body, dict):
            # The API's error envelope is an object; success is always an array.
            raise HoneyDBResponseError(
                "HoneyDB returned an error envelope with HTTP "
                f"{status}: {self._status_text(response) or 'no detail'}"
            )
        if not isinstance(body, list):
            raise HoneyDBResponseError(
                f"HoneyDB returned an unexpected JSON type for {url}: "
                f"{type(body).__name__}"
            )

        self.helper.connector_logger.info(
            "[API] Bad hosts fetched",
            {"entries": len(body), **self._quota_headers(response)},
        )
        return body
