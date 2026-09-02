import ipaddress
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

import stix2
from pycti import Identity, Indicator, MarkingDefinition, StixCoreRelationship

if TYPE_CHECKING:
    from pycti import OpenCTIConnectorHelper

TlpLevel = Literal["clear", "white", "green", "amber", "amber+strict", "red"]

HONEYDB_NAME = "HoneyDB"
HONEYDB_URL = "https://honeydb.io"
HONEYDB_DESCRIPTION = (
    "HoneyDB is a community-driven honeypot sensor network that publishes "
    "threat intelligence about hosts attacking the internet."
)
LABELS = ["honeydb", "honeypot"]
LAST_SEEN_FORMAT = "%Y-%m-%d"


class ConverterToStix:
    """
    Provides methods for converting HoneyDB bad-hosts entries into STIX 2.1 objects.

    REQUIREMENTS:
        - `generate_id()` methods from `pycti` library MUST be used to generate the `id` of each entity (except observables),
        e.g. `pycti.Identity.generate_id(name="Source Name", identity_class="organization")` for a STIX Identity.

    Every ID emitted here is a pure function of the input, so re-running the
    connector on unchanged data yields the same IDs and OpenCTI upserts instead
    of duplicating.
    """

    def __init__(
        self,
        helper: "OpenCTIConnectorHelper",
        tlp_level: TlpLevel,
        score: int,
        create_indicators: bool,
        min_count: int,
        indicator_valid_days: int,
    ):
        """
        :param helper: The connector's helper. Used for logs.
        :param tlp_level: TLP marking applied to every object.
        :param score: `x_opencti_score` on observables, `confidence` on indicators.
        :param create_indicators: Also emit an Indicator + `based-on` relationship.
        :param min_count: Entries with fewer events than this are filtered out.
        :param indicator_valid_days: Indicator `valid_until` = last seen + N days.
        """
        self.helper = helper
        self.score = score
        self.create_indicators = create_indicators
        self.min_count = min_count
        self.indicator_valid_days = indicator_valid_days

        self.author = self.create_author()
        self.tlp_marking = self._create_tlp_marking(level=tlp_level.lower())

        # Counters for the last `convert()` call.
        self.converted = 0
        self.filtered = 0
        self.skipped = 0

    @staticmethod
    def create_author() -> stix2.Identity:
        """
        Create Author
        :return: Author in Stix2 object
        """
        return stix2.Identity(
            id=Identity.generate_id(name=HONEYDB_NAME, identity_class="organization"),
            name=HONEYDB_NAME,
            identity_class="organization",
            description=HONEYDB_DESCRIPTION,
            external_references=[
                stix2.ExternalReference(
                    source_name=HONEYDB_NAME,
                    url=HONEYDB_URL,
                    description="HoneyDB web site",
                )
            ],
        )

    @staticmethod
    def _create_tlp_marking(level: str) -> stix2.MarkingDefinition:
        mapping = {
            "white": stix2.TLP_WHITE,
            "clear": stix2.TLP_WHITE,
            "green": stix2.TLP_GREEN,
            "amber": stix2.TLP_AMBER,
            "amber+strict": stix2.MarkingDefinition(
                id=MarkingDefinition.generate_id("TLP", "TLP:AMBER+STRICT"),
                definition_type="statement",
                definition={"statement": "custom"},
                custom_properties={
                    "x_opencti_definition_type": "TLP",
                    "x_opencti_definition": "TLP:AMBER+STRICT",
                },
            ),
            "red": stix2.TLP_RED,
        }
        return mapping[level]

    @staticmethod
    def _external_reference(ip: str) -> stix2.ExternalReference:
        return stix2.ExternalReference(
            source_name=HONEYDB_NAME,
            url=f"{HONEYDB_URL}/ip/{ip}",
            description=f"HoneyDB details for {ip}",
        )

    @staticmethod
    def _description(count: int, last_seen: datetime) -> str:
        return (
            "Reported by HoneyDB honeypot sensors. "
            f"Events (24h): {count}. Last seen: {last_seen.strftime(LAST_SEEN_FORMAT)}."
        )

    def _parse_last_seen(self, value: Any, ip: str) -> datetime:
        """
        Parse HoneyDB's `YYYY-MM-DD` last-seen date as UTC midnight. An
        unparsable value is not fatal: fall back to now and note it at debug.
        """
        try:
            return datetime.strptime(str(value), LAST_SEEN_FORMAT).replace(tzinfo=UTC)
        except (TypeError, ValueError):
            self.helper.connector_logger.debug(
                "[CONVERTER] Unparsable last_seen, using current time",
                {"value": ip, "last_seen": str(value)},
            )
            return datetime.now(UTC)

    def create_relationship(
        self, source_id: str, relationship_type: str, target_id: str
    ) -> stix2.Relationship:
        """
        Creates Relationship object
        :param source_id: ID of source in string
        :param relationship_type: Relationship type in string
        :param target_id: ID of target in string
        :return: Relationship STIX2 object
        """
        return stix2.Relationship(
            id=StixCoreRelationship.generate_id(
                relationship_type, source_id, target_id
            ),
            relationship_type=relationship_type,
            source_ref=source_id,
            target_ref=target_id,
            created_by_ref=self.author["id"],
            object_marking_refs=[self.tlp_marking["id"]],
        )

    def create_obs(
        self, ip: ipaddress.IPv4Address | ipaddress.IPv6Address, description: str
    ) -> stix2.IPv4Address | stix2.IPv6Address:
        """
        Create an IPv4/IPv6 observable for `ip`.
        """
        custom_properties = {
            "x_opencti_created_by_ref": self.author["id"],
            "x_opencti_score": self.score,
            "x_opencti_labels": LABELS,
            "x_opencti_description": description,
            "x_opencti_external_references": [self._external_reference(str(ip))],
        }
        cls = stix2.IPv6Address if ip.version == 6 else stix2.IPv4Address
        return cls(
            value=str(ip),
            object_marking_refs=[self.tlp_marking["id"]],
            custom_properties=custom_properties,
        )

    def create_indicator(
        self,
        ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
        description: str,
        last_seen: datetime,
    ) -> stix2.Indicator:
        """
        Create a STIX-pattern indicator for `ip`, valid from its last-seen date
        for `indicator_valid_days` days.
        """
        observable_type = "ipv6-addr" if ip.version == 6 else "ipv4-addr"
        main_observable_type = "IPv6-Addr" if ip.version == 6 else "IPv4-Addr"
        pattern = f"[{observable_type}:value = '{ip}']"
        return stix2.Indicator(
            id=Indicator.generate_id(pattern),
            name=str(ip),
            description=description,
            pattern=pattern,
            pattern_type="stix",
            indicator_types=["malicious-activity"],
            valid_from=last_seen,
            valid_until=last_seen + timedelta(days=self.indicator_valid_days),
            confidence=self.score,
            labels=LABELS,
            created_by_ref=self.author["id"],
            object_marking_refs=[self.tlp_marking["id"]],
            external_references=[self._external_reference(str(ip))],
            custom_properties={
                "x_opencti_score": self.score,
                "x_opencti_main_observable_type": main_observable_type,
            },
        )

    def convert(self, entries: Iterable[dict[str, Any]]) -> Iterator[Any]:
        """
        Convert HoneyDB bad-hosts entries into STIX objects.

        Yields, per accepted entry, the observable and — when indicators are
        enabled — the indicator and its `based-on` relationship, in that order.
        Updates `converted`, `filtered` and `skipped` as it goes; the caller
        reads them after the iterator is exhausted.
        """
        self.converted = 0
        self.filtered = 0
        self.skipped = 0

        for entry in entries:
            if not isinstance(entry, dict):
                self.skipped += 1
                self.helper.connector_logger.warning(
                    "[CONVERTER] Skipping non-object entry",
                    {"entry_type": type(entry).__name__},
                )
                continue

            raw_host = entry.get("remote_host")
            try:
                count = int(entry["count"])
            except (KeyError, TypeError, ValueError):
                self.skipped += 1
                self.helper.connector_logger.warning(
                    "[CONVERTER] Skipping entry with missing or non-numeric count",
                    {"keys": sorted(entry.keys())},
                )
                continue

            try:
                ip = ipaddress.ip_address(str(raw_host).strip())
            except ValueError:
                self.skipped += 1
                self.helper.connector_logger.warning(
                    "[CONVERTER] Skipping entry that is not an IP address",
                    {"value": str(raw_host)},
                )
                continue

            if count < self.min_count:
                self.filtered += 1
                continue

            last_seen = self._parse_last_seen(entry.get("last_seen"), str(ip))
            description = self._description(count, last_seen)

            observable = self.create_obs(ip, description)
            self.converted += 1
            yield observable

            if self.create_indicators:
                indicator = self.create_indicator(ip, description, last_seen)
                yield indicator
                yield self.create_relationship(
                    indicator["id"], "based-on", observable["id"]
                )
