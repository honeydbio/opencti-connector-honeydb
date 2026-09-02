import ipaddress
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
import stix2
from pycti import Identity, Indicator, StixCoreRelationship

from connector.converter_to_stix import LABELS, ConverterToStix


def make_converter(**kwargs) -> ConverterToStix:
    params = {
        "tlp_level": "clear",
        "score": 50,
        "create_indicators": False,
        "min_count": 1,
        "indicator_valid_days": 7,
    }
    params.update(kwargs)
    return ConverterToStix(MagicMock(), **params)


def by_type(objects, stix_type):
    return [o for o in objects if o["type"] == stix_type]


def test_observables_only(bad_hosts_fixture):
    converter = make_converter()
    objects = list(converter.convert(bad_hosts_fixture))

    # 5 valid IPs (one with a string count, one with a bad last_seen);
    # skipped: not-an-ip, "many", missing count.
    assert converter.converted == 5
    assert converter.filtered == 0
    assert converter.skipped == 3
    assert len(objects) == 5
    assert len(by_type(objects, "ipv4-addr")) == 4
    assert len(by_type(objects, "ipv6-addr")) == 1
    assert by_type(objects, "indicator") == []
    assert by_type(objects, "relationship") == []


def test_observable_fields():
    converter = make_converter(score=70, tlp_level="amber")
    entry = {"remote_host": "203.0.113.10", "count": 42, "last_seen": "2026-09-01"}
    (obs,) = list(converter.convert([entry]))

    assert obs["type"] == "ipv4-addr"
    assert obs["value"] == "203.0.113.10"
    assert obs["object_marking_refs"] == [stix2.TLP_AMBER["id"]]
    assert obs["x_opencti_created_by_ref"] == converter.author["id"]
    assert obs["x_opencti_score"] == 70
    assert obs["x_opencti_labels"] == LABELS
    assert "42" in obs["x_opencti_description"]
    assert "2026-09-01" in obs["x_opencti_description"]
    assert "HoneyDB" in obs["x_opencti_description"]
    (ref,) = obs["x_opencti_external_references"]
    assert ref["source_name"] == "HoneyDB"
    assert ref["url"] == "https://honeydb.io/ip/203.0.113.10"


def test_ipv6_observable():
    (obs,) = list(
        make_converter().convert(
            [{"remote_host": "2001:db8::1", "count": 1, "last_seen": "2026-09-01"}]
        )
    )
    assert obs["type"] == "ipv6-addr"
    assert obs["value"] == "2001:db8::1"


def test_indicators_and_relationships(bad_hosts_fixture):
    converter = make_converter(create_indicators=True, indicator_valid_days=10)
    objects = list(converter.convert(bad_hosts_fixture))

    assert converter.converted == 5
    assert len(objects) == 15
    observables = by_type(objects, "ipv4-addr") + by_type(objects, "ipv6-addr")
    indicators = by_type(objects, "indicator")
    relationships = by_type(objects, "relationship")
    assert len(observables) == 5
    assert len(indicators) == 5
    assert len(relationships) == 5

    # Order per entry: observable, indicator, relationship.
    assert [o["type"] for o in objects[:3]] == [
        "ipv4-addr",
        "indicator",
        "relationship",
    ]

    ind = indicators[0]
    assert ind["pattern"] == "[ipv4-addr:value = '203.0.113.10']"
    assert ind["pattern_type"] == "stix"
    assert ind["name"] == "203.0.113.10"
    assert ind["indicator_types"] == ["malicious-activity"]
    assert ind["valid_from"] == datetime(2026, 9, 1, tzinfo=UTC)
    assert ind["valid_until"] == ind["valid_from"] + timedelta(days=10)
    assert ind["confidence"] == 50
    assert ind["labels"] == LABELS
    assert ind["created_by_ref"] == converter.author["id"]
    assert ind["object_marking_refs"] == [stix2.TLP_WHITE["id"]]
    assert ind["x_opencti_score"] == 50
    assert ind["x_opencti_main_observable_type"] == "IPv4-Addr"
    assert ind["external_references"][0]["url"] == "https://honeydb.io/ip/203.0.113.10"
    assert ind["id"] == Indicator.generate_id(ind["pattern"])

    ipv6_ind = next(i for i in indicators if "ipv6" in i["pattern"])
    assert ipv6_ind["pattern"] == "[ipv6-addr:value = '2001:db8::1']"
    assert ipv6_ind["x_opencti_main_observable_type"] == "IPv6-Addr"

    rel = relationships[0]
    assert rel["relationship_type"] == "based-on"
    assert rel["source_ref"] == ind["id"]
    assert rel["target_ref"] == objects[0]["id"]
    assert rel["created_by_ref"] == converter.author["id"]
    assert rel["object_marking_refs"] == [stix2.TLP_WHITE["id"]]
    assert rel["id"] == StixCoreRelationship.generate_id(
        "based-on", ind["id"], objects[0]["id"]
    )


def test_author_identity():
    converter = make_converter()
    author = converter.author
    assert author["id"] == Identity.generate_id("HoneyDB", "organization")
    assert author["name"] == "HoneyDB"
    assert author["identity_class"] == "organization"
    assert author["external_references"][0]["url"] == "https://honeydb.io"


@pytest.mark.parametrize(
    "level, expected_id",
    [
        ("clear", stix2.TLP_WHITE["id"]),
        ("white", stix2.TLP_WHITE["id"]),
        ("green", stix2.TLP_GREEN["id"]),
        ("amber", stix2.TLP_AMBER["id"]),
        ("red", stix2.TLP_RED["id"]),
    ],
)
def test_tlp_mapping(level, expected_id):
    assert make_converter(tlp_level=level).tlp_marking["id"] == expected_id


def test_tlp_amber_strict_is_custom_marking():
    marking = make_converter(tlp_level="amber+strict").tlp_marking
    assert marking["x_opencti_definition"] == "TLP:AMBER+STRICT"
    assert marking["definition_type"] == "statement"


def test_min_count_filters_not_skips():
    converter = make_converter(min_count=5)
    entries = [
        {"remote_host": "203.0.113.10", "count": 42, "last_seen": "2026-09-01"},
        {"remote_host": "203.0.113.11", "count": 4, "last_seen": "2026-09-01"},
    ]
    objects = list(converter.convert(entries))
    assert len(objects) == 1
    assert converter.filtered == 1
    assert converter.skipped == 0


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param(
            {"remote_host": "203.0.113.1", "last_seen": "2026-09-01"}, id="no_count"
        ),
        pytest.param({"remote_host": "203.0.113.1", "count": "many"}, id="text_count"),
        pytest.param({"remote_host": "203.0.113.1", "count": None}, id="null_count"),
        pytest.param({"count": 3}, id="no_host"),
        pytest.param({"remote_host": "example.com", "count": 3}, id="hostname"),
        pytest.param("203.0.113.1", id="not_an_object"),
    ],
)
def test_unparsable_entries_are_skipped_with_warning(entry):
    converter = make_converter()
    assert list(converter.convert([entry])) == []
    assert converter.skipped == 1
    assert converter.filtered == 0
    converter.helper.connector_logger.warning.assert_called_once()


def test_bad_last_seen_falls_back_to_now():
    converter = make_converter(create_indicators=True)
    before = datetime.now(UTC)
    objects = list(
        converter.convert(
            [{"remote_host": "203.0.113.1", "count": 3, "last_seen": "yesterday"}]
        )
    )
    ind = by_type(objects, "indicator")[0]
    assert ind["valid_from"] >= before.replace(microsecond=0)
    converter.helper.connector_logger.debug.assert_called_once()


def test_counters_reset_between_runs(bad_hosts_fixture):
    converter = make_converter()
    list(converter.convert(bad_hosts_fixture))
    list(converter.convert(bad_hosts_fixture[:1]))
    assert converter.converted == 1
    assert converter.skipped == 0


def test_ids_are_deterministic(bad_hosts_fixture):
    first = [
        o["id"]
        for o in make_converter(create_indicators=True).convert(bad_hosts_fixture)
    ]
    second = [
        o["id"]
        for o in make_converter(create_indicators=True).convert(bad_hosts_fixture)
    ]
    assert first == second
    assert len(set(first)) == len(first)


def test_ip_address_types_accepted_by_create_obs():
    converter = make_converter()
    obs = converter.create_obs(ipaddress.ip_address("203.0.113.10"), "desc")
    assert obs["value"] == "203.0.113.10"
