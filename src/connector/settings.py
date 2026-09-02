from datetime import timedelta
from typing import Literal

from connectors_sdk import (
    BaseConfigModel,
    BaseConnectorSettings,
    BaseExternalImportConnectorConfig,
    ListFromString,
)
from pydantic import Field, HttpUrl, SecretStr, field_validator

# Polling more often than this gains nothing: HoneyDB's bad-hosts list is a
# rolling 24-hour window that the API caches once per day.
SHORT_PERIOD_THRESHOLD = timedelta(hours=1)


class ExternalImportConnectorConfig(BaseExternalImportConnectorConfig):
    """
    Override the `BaseExternalImportConnectorConfig` to add parameters and/or defaults
    to the configuration for connectors of type `EXTERNAL_IMPORT`.
    """

    id: str = Field(description="A UUID v4 to identify the connector in OpenCTI.")
    name: str = Field(
        description="The name of the connector.",
        default="HoneyDB",
    )
    scope: ListFromString = Field(
        description="The scope of the connector.",
        default=["honeydb"],
    )
    duration_period: timedelta = Field(
        description="The period of time to await between two runs of the connector.",
        default=timedelta(hours=24),
    )


class HoneyDBConfig(BaseConfigModel):
    """
    Define parameters and/or defaults for the configuration specific to the `HoneyDBConnector`.
    """

    api_id: str = Field(
        description="Your HoneyDB API ID (see https://honeydb.io/threats).",
        min_length=1,
    )
    api_key: SecretStr = Field(
        description="Your HoneyDB API key (see https://honeydb.io/threats).",
    )
    api_base_url: HttpUrl = Field(
        description="Base URL of the HoneyDB API.",
        default=HttpUrl("https://honeydb.io/api"),
    )
    score: int = Field(
        description=(
            "Score (0-100) applied as `x_opencti_score` on observables and as "
            "`confidence` on indicators."
        ),
        default=50,
        ge=0,
        le=100,
    )
    tlp_level: Literal[
        "clear",
        "white",
        "green",
        "amber",
        "amber+strict",
        "red",
    ] = Field(
        description=(
            "TLP marking for imported data (`clear`, `white`, `green`, `amber`, "
            "`amber+strict`, `red`)."
        ),
        default="clear",
    )
    create_indicators: bool = Field(
        description=(
            "Whether to also create STIX Indicators (with a `based-on` relationship "
            "to each observable)."
        ),
        default=False,
    )
    min_count: int = Field(
        description=(
            "Skip hosts with fewer than this many events in the 24-hour window."
        ),
        default=1,
        ge=1,
    )
    indicator_valid_days: int = Field(
        description=(
            "Number of days after a host's last-seen date until its indicator "
            "expires (`valid_until`)."
        ),
        default=7,
        ge=1,
    )

    @field_validator("api_key")
    @classmethod
    def _api_key_not_empty(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value():
            raise ValueError("api_key must not be empty")
        return value


class ConnectorSettings(BaseConnectorSettings):
    """
    Override `BaseConnectorSettings` to include `ExternalImportConnectorConfig` and `HoneyDBConfig`.
    """

    connector: ExternalImportConnectorConfig = Field(
        default_factory=ExternalImportConnectorConfig
    )
    honeydb: HoneyDBConfig = Field(default_factory=HoneyDBConfig)

    def short_period_warning(self) -> str | None:
        """
        Return a warning message when the configured period is shorter than the
        source refresh interval, otherwise `None`. Nothing is clamped: an
        administrator may have a reason, but they should know it costs quota.
        """
        period = self.connector.duration_period
        if period < SHORT_PERIOD_THRESHOLD:
            return (
                f"CONNECTOR_DURATION_PERIOD is {period}; HoneyDB refreshes the "
                "bad-hosts list once per day, so polling more often than PT1H only "
                "consumes API quota. PT24H is recommended."
            )
        return None
