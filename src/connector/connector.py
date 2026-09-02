import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from pycti import OpenCTIConnectorHelper

from connector.converter_to_stix import ConverterToStix
from connector.settings import ConnectorSettings
from honeydb_client import (
    HoneyDBAuthError,
    HoneyDBClient,
    HoneyDBError,
    HoneyDBPlanError,
    HoneyDBQuotaError,
    HoneyDBResponseError,
    HoneyDBTransientError,
)

STATE_LAST_RUN = "last_run"
STATE_LAST_COUNT = "last_count"
STATE_LAST_ERROR = "last_error"

# The helper reschedules `duration_period` seconds after a run *finishes*, so
# a scheduled run always arrives slightly later than `last_run + period`. The
# grace keeps clock jitter from turning a legitimate run into a skip.
RESTART_SKIP_GRACE = timedelta(seconds=60)

FRIENDLY_NAME = "HoneyDB bad hosts import"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


class HoneyDBConnector:
    """
    Specifications of the external import connector:

    This class encapsulates the main actions, expected to be run by any connector of type `EXTERNAL_IMPORT`.
    This type of connector aim to fetch external data to create STIX bundle and send it to OpenCTI.
    The STIX bundle in the queue will be processed by OpenCTI workers.
    This type of connector uses the basic methods of the helper.

    ---

    Attributes:
        config (ConnectorSettings):
            Store the connector's configuration. It defines how to connector will behave.
        helper (OpenCTIConnectorHelper):
            Handle the connection and the requests between the connector, OpenCTI and the workers.
            _All connectors MUST use the connector helper with connector's configuration._
        client (HoneyDBClient):
            Provide methods to request the HoneyDB API.
        converter_to_stix (ConverterToStix):
            Provide methods for converting HoneyDB entries into STIX 2.1 objects.

    ---

    Best practices:
        - `self.helper.api.work.initiate_work(...)` is used to initiate a new work
        - `self.helper.schedule_process()` is used to schedule connector's runs frequency
        - `self.helper.connector_logger.[info/debug/warning/error]` is used when logging a message
        - `self.helper.stix2_create_bundle(stix_objects)` is used when creating a bundle
        - `self.helper.send_stix2_bundle(stix_objects_bundle)` is used to send the bundle to OpenCTI
        - `self.helper.set_state()` is used to store persistent data in connector's state
    """

    def __init__(self, config: ConnectorSettings, helper: OpenCTIConnectorHelper):
        """
        Initialize `HoneyDBConnector` with its configuration.

        Args:
            config (ConnectorSettings): Configuration of the connector
            helper (OpenCTIConnectorHelper): Helper to manage connection and requests to OpenCTI
        """
        from connector import __version__

        self.config = config
        self.helper = helper

        self.client = HoneyDBClient(
            self.helper,
            base_url=self.config.honeydb.api_base_url,
            api_id=self.config.honeydb.api_id,
            api_key=self.config.honeydb.api_key.get_secret_value(),
            user_agent=f"opencti-connector-honeydb/{__version__}",
        )
        self.converter_to_stix = ConverterToStix(
            self.helper,
            tlp_level=self.config.honeydb.tlp_level,
            score=self.config.honeydb.score,
            create_indicators=self.config.honeydb.create_indicators,
            min_count=self.config.honeydb.min_count,
            indicator_valid_days=self.config.honeydb.indicator_valid_days,
        )

        # Redacted configuration summary: the API key is deliberately absent.
        self.helper.connector_logger.info(
            "[CONNECTOR] Configuration",
            {
                "api_id": self.config.honeydb.api_id,
                "api_base_url": str(self.config.honeydb.api_base_url),
                "duration_period": str(self.config.connector.duration_period),
                "tlp_level": self.config.honeydb.tlp_level,
                "score": self.config.honeydb.score,
                "create_indicators": self.config.honeydb.create_indicators,
                "min_count": self.config.honeydb.min_count,
                "indicator_valid_days": self.config.honeydb.indicator_valid_days,
            },
        )
        warning = self.config.short_period_warning()
        if warning:
            self.helper.connector_logger.warning(warning)

    # ------------------------------------------------------------------ state

    def _get_state(self) -> dict[str, Any]:
        state = self.helper.get_state()
        return dict(state) if isinstance(state, dict) else {}

    @staticmethod
    def _parse_last_run(state: dict[str, Any]) -> datetime | None:
        value = state.get(STATE_LAST_RUN)
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed

    def _should_skip(self, state: dict[str, Any], now: datetime) -> bool:
        """
        True when the previous successful run is still inside the configured
        period. The helper runs the process immediately on every start, so
        without this a container restart would cost an extra API call.
        """
        last_run = self._parse_last_run(state)
        if last_run is None:
            return False
        period = self.config.connector.duration_period
        elapsed = now - last_run
        if elapsed + RESTART_SKIP_GRACE < period:
            self.helper.connector_logger.info(
                "[CONNECTOR] Last run is inside the configured period, skipping",
                {
                    "last_run": _iso(last_run),
                    "next_run_due": _iso(last_run + period),
                },
            )
            return True
        return False

    def _record_success(self, now: datetime, count: int) -> None:
        state = self._get_state()
        state[STATE_LAST_RUN] = _iso(now)
        state[STATE_LAST_COUNT] = count
        state.pop(STATE_LAST_ERROR, None)
        self.helper.set_state(state)

    def _record_failure(self, now: datetime, err: Exception) -> None:
        # Only the class name is stored: the message could carry an API error
        # body, and state is visible in the platform UI.
        state = self._get_state()
        state[STATE_LAST_ERROR] = {"at": _iso(now), "type": type(err).__name__}
        self.helper.set_state(state)

    # ------------------------------------------------------------------- run

    def _collect_intelligence(self) -> list:
        """
        Collect intelligence from HoneyDB and convert it into STIX objects.
        :return: List of STIX objects (empty when nothing was imported)
        """
        entries = self.client.bad_hosts()
        stix_objects = list(self.converter_to_stix.convert(entries))

        if entries and self.converter_to_stix.skipped == len(entries):
            raise HoneyDBResponseError(
                f"every one of the {len(entries)} entries was unparsable; the "
                "HoneyDB API response shape may have changed"
            )

        # Ensure consistent bundle by adding the author and TLP marking
        if stix_objects:
            stix_objects.append(self.converter_to_stix.author)
            stix_objects.append(self.converter_to_stix.tlp_marking)
        return stix_objects

    def _fail(self, work_id: str | None, now: datetime, err: Exception, hint: str):
        message = f"{self.helper.connect_name}: {hint}: {err}"
        self.helper.connector_logger.error(message)
        if isinstance(err, HoneyDBQuotaError) and err.quota_headers:
            self.helper.connector_logger.error(
                "[CONNECTOR] HoneyDB quota headers", dict(err.quota_headers)
            )
        if work_id is not None:
            self.helper.api.work.to_processed(work_id, message, in_error=True)
        self._record_failure(now, err)

    def process_message(self) -> None:
        """
        Connector main process to collect intelligence
        :return: None
        """
        self.helper.connector_logger.info(
            "[CONNECTOR] Starting connector...",
            {"connector_name": self.helper.connect_name},
        )
        work_id: str | None = None
        now = _utc_now()

        try:
            state = self._get_state()
            if STATE_LAST_RUN in state:
                self.helper.connector_logger.info(
                    "[CONNECTOR] Connector last run",
                    {
                        "last_run": state.get(STATE_LAST_RUN),
                        "last_count": state.get(STATE_LAST_COUNT),
                    },
                )
            else:
                self.helper.connector_logger.info(
                    "[CONNECTOR] Connector has never run..."
                )

            if self._should_skip(state, now):
                return

            # Friendly name will be displayed on OpenCTI platform
            work_id = self.helper.api.work.initiate_work(
                self.helper.connect_id, FRIENDLY_NAME
            )
            self.helper.connector_logger.info(
                "[CONNECTOR] Running connector...",
                {"connector_name": self.helper.connect_name},
            )

            stix_objects = self._collect_intelligence()
            converter = self.converter_to_stix

            if stix_objects:
                stix_objects_bundle = self.helper.stix2_create_bundle(stix_objects)
                bundles_sent = self.helper.send_stix2_bundle(
                    stix_objects_bundle,
                    work_id=work_id,
                    update=True,
                    cleanup_inconsistent_bundle=True,
                )
                self.helper.connector_logger.info(
                    "[CONNECTOR] Sending STIX objects to OpenCTI...",
                    {"bundles_sent": str(len(bundles_sent))},
                )
            else:
                self.helper.connector_logger.info("[CONNECTOR] No objects to import")

            self._record_success(now, converter.converted)

            indicators = converter.converted if converter.create_indicators else 0
            message = (
                f"{self.helper.connect_name} imported {converter.converted} "
                f"observables, {indicators} indicators, {converter.filtered} "
                f"filtered, {converter.skipped} skipped"
            )
            self.helper.api.work.to_processed(work_id, message)
            self.helper.connector_logger.info(message)

        except HoneyDBQuotaError as err:
            self._fail(work_id, now, err, "API quota exhausted")
        except HoneyDBAuthError as err:
            self._fail(work_id, now, err, "authentication failed")
            self.helper.connector_logger.error(
                "[CONNECTOR] Will retry next period; fix HONEYDB_API_ID / "
                "HONEYDB_API_KEY to recover"
            )
        except HoneyDBPlanError as err:
            self._fail(work_id, now, err, "plan does not allow the request")
        except HoneyDBTransientError as err:
            self._fail(work_id, now, err, "HoneyDB API unavailable")
        except HoneyDBResponseError as err:
            self._fail(work_id, now, err, "unexpected HoneyDB API response")
        except HoneyDBError as err:
            self._fail(work_id, now, err, "HoneyDB API error")
        except (KeyboardInterrupt, SystemExit):
            self.helper.connector_logger.info(
                "[CONNECTOR] Connector stopped...",
                {"connector_name": self.helper.connect_name},
            )
            sys.exit(0)
        except Exception as err:
            # Never re-raise: an unhandled exception kills the scheduler, the
            # container restarts, and every restart costs an API call.
            self._fail(work_id, now, err, "unexpected error")

    def run(self) -> None:
        """
        Start the connector, schedule its runs and trigger the first run.
        It allows you to schedule the process to run at a certain interval.
        This specific scheduler from the `OpenCTIConnectorHelper` will also check the queue size of a connector.
        If `CONNECTOR_QUEUE_THRESHOLD` is set, and if the connector's queue size exceeds the queue threshold,
        the connector's main process will not run until the queue is ingested and reduced sufficiently,
        allowing it to restart during the next scheduler check. (default is 500MB)

        Example:
            - If `CONNECTOR_DURATION_PERIOD=PT24H`, then the connector is running every 24 hours.
        """
        self.helper.schedule_process(
            message_callback=self.process_message,
            duration_period=self.config.connector.duration_period.total_seconds(),
        )
