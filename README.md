# OpenCTI HoneyDB Connector

Table of Contents

- [OpenCTI HoneyDB Connector](#opencti-honeydb-connector)
  - [Introduction](#introduction)
  - [Installation](#installation)
    - [Requirements](#requirements)
  - [Configuration variables](#configuration-variables)
    - [OpenCTI environment variables](#opencti-environment-variables)
    - [Base connector environment variables](#base-connector-environment-variables)
    - [Connector extra parameters environment variables](#connector-extra-parameters-environment-variables)
  - [Deployment](#deployment)
    - [Docker Deployment](#docker-deployment)
    - [Manual Deployment](#manual-deployment)
  - [Usage](#usage)
  - [Behavior](#behavior)
  - [Debugging](#debugging)
  - [Additional information](#additional-information)

## Introduction

[HoneyDB](https://honeydb.io) is a community-driven honeypot sensor network.
Sensors run by the community report every connection they receive, and the
aggregated **bad hosts** list names the IP addresses seen attacking in the
trailing 24 hours.

This connector is an OpenCTI *external-import* connector. Once per period it
fetches the HoneyDB bad-hosts list and imports each host into OpenCTI as an
IPv4/IPv6 observable, attributed to a `HoneyDB` organization identity, with an
external reference to the host's page on honeydb.io, a configurable TLP
marking and score. Optionally it also creates a STIX indicator per host.

You need a HoneyDB API ID and API key. Create a free account and generate them
at <https://honeydb.io/threats>. The free tier is sufficient for the default
schedule: the connector makes **one** API call per run and the default period
is 24 hours.

## Installation

### Requirements

- Python >= 3.12 (for manual deployment)
- OpenCTI Platform >= 6.8.12
- [`pycti`](https://pypi.org/project/pycti/) library matching your OpenCTI version
- [`connectors-sdk`](https://github.com/OpenCTI-Platform/connectors.git@master#subdirectory=connectors-sdk) library matching your OpenCTI version
- A HoneyDB API ID and API key (<https://honeydb.io/threats>)

## Configuration variables

There are a number of configuration options, which are set either in `docker-compose.yml` (for Docker) or
in `config.yml` (for manual deployment).

### OpenCTI environment variables

Below are the parameters you'll need to set for OpenCTI:

| Parameter     | config.yml | Docker environment variable | Mandatory | Description                                          |
| ------------- | ---------- | --------------------------- | --------- | ---------------------------------------------------- |
| OpenCTI URL   | url        | `OPENCTI_URL`               | Yes       | The URL of the OpenCTI platform.                     |
| OpenCTI Token | token      | `OPENCTI_TOKEN`             | Yes       | The default admin token set in the OpenCTI platform. |

### Base connector environment variables

Below are the parameters you'll need to set for running the connector properly:

| Parameter       | config.yml      | Docker environment variable | Default         | Mandatory | Description                                                                              |
| --------------- | --------------- | --------------------------- | --------------- | --------- | ---------------------------------------------------------------------------------------- |
| Connector ID    | id              | `CONNECTOR_ID`              | /               | Yes       | A unique `UUIDv4` identifier for this connector instance.                                |
| Connector Type  | type            | `CONNECTOR_TYPE`            | EXTERNAL_IMPORT | No        | Should always be set to `EXTERNAL_IMPORT` for this connector.                            |
| Connector Name  | name            | `CONNECTOR_NAME`            | HoneyDB         | No        | Name of the connector.                                                                   |
| Connector Scope | scope           | `CONNECTOR_SCOPE`           | honeydb         | No        | The scope or type of data the connector is importing, either a MIME type or Stix Object. |
| Log Level       | log_level       | `CONNECTOR_LOG_LEVEL`       | error           | No        | Determines the verbosity of the logs. Options are `debug`, `info`, `warn`, or `error`.   |
| Duration Period | duration_period | `CONNECTOR_DURATION_PERIOD` | PT24H           | No        | Interval between two runs, ISO-8601 duration. See [Behavior](#behavior) before lowering. |

### Connector extra parameters environment variables

Below are the parameters you'll need to set for the connector:

| Parameter            | config.yml           | Docker environment variable    | Default                  | Mandatory | Description                                                                                                            |
| -------------------- | -------------------- | ------------------------------ | ------------------------ | --------- | ---------------------------------------------------------------------------------------------------------------------- |
| API ID               | api_id               | `HONEYDB_API_ID`               | /                        | Yes       | Your HoneyDB API ID.                                                                                                   |
| API key              | api_key              | `HONEYDB_API_KEY`              | /                        | Yes       | Your HoneyDB API key. Never logged.                                                                                    |
| API base URL         | api_base_url         | `HONEYDB_API_BASE_URL`         | `https://honeydb.io/api` | No        | Override for testing or proxies.                                                                                       |
| Score                | score                | `HONEYDB_SCORE`                | 50                       | No        | 0–100. Set as `x_opencti_score` on observables and as `confidence` on indicators.                                      |
| TLP level            | tlp_level            | `HONEYDB_TLP_LEVEL`            | clear                    | No        | Marking on every object: `clear`, `white`, `green`, `amber`, `amber+strict`, `red`.                                    |
| Create indicators    | create_indicators    | `HONEYDB_CREATE_INDICATORS`    | false                    | No        | Also create a STIX indicator per host with a `based-on` relationship to the observable.                                |
| Minimum count        | min_count            | `HONEYDB_MIN_COUNT`            | 1                        | No        | Skip hosts with fewer than this many events in the 24-hour window (noise control).                                     |
| Indicator valid days | indicator_valid_days | `HONEYDB_INDICATOR_VALID_DAYS` | 7                        | No        | Indicator `valid_until` = last-seen date + this many days. Hosts that stop appearing age out through OpenCTI's lifecycle. |

Every value is validated at startup; an invalid value stops the connector with
a message naming the accepted values.

## Deployment

### Docker Deployment

Before building the Docker container, you need to set the version of pycti in `requirements.txt` equal to whatever
version of OpenCTI you're running. Example, `pycti==6.8.12`. If you don't, it will take the latest version, but
sometimes the OpenCTI SDK fails to initialize.

Build a Docker Image using the provided `Dockerfile`.

Example:

```shell
# Replace the IMAGE NAME with the appropriate value
docker build . -t [IMAGE NAME]:latest
```

Make sure to replace the environment variables in `docker-compose.yml` with the appropriate configurations for your
environment. Then, start the docker container with the provided docker-compose.yml

```shell
docker compose up -d
# -d for detached
```

Two images exist for this connector:

| Image | Published by | Use when |
| --- | --- | --- |
| `opencti/connector-honeydb` | Filigran, from the [OpenCTI connectors repository](https://github.com/OpenCTI-Platform/connectors) | The connector has been merged upstream (this is what `docker-compose.yml` references). |
| `ghcr.io/honeydbio/opencti-connector-honeydb` | HoneyDB, from tagged releases of this repository | The upstream image is not yet available for your version, or you want a specific HoneyDB release. |

Both are built from the same source; swap the `image:` line to switch.

### Manual Deployment

Create a file `config.yml` based on the provided `config.yml.sample`.

Replace the configuration variables (especially the "**ChangeMe**" variables) with the appropriate configurations for
you environment.

Install the required python dependencies (preferably in a virtual environment):

```shell
pip3 install -r requirements.txt
```

Then, start the connector from `src` directory:

```shell
python3 main.py
```

## Usage

After Installation, the connector should require minimal interaction to use, and should update automatically at a regular interval specified in your `docker-compose.yml` or `config.yml` in `duration_period`.

However, if you would like to force an immediate download of a new batch of entities, navigate to:

`Data management` -> `Ingestion` -> `Connectors` in the OpenCTI platform.

Find the connector, and click on the refresh button to reset the connector's state and force a new
download of data by re-running the connector.

## Behavior

Each run makes exactly one request, `GET /api/bad-hosts`, and imports the
result as a single STIX bundle under one OpenCTI *work*, so the connector page
shows progress, counts and any error.

Objects created per host:

- **IPv4-Addr / IPv6-Addr observable** — `value` is the host. Carries
  `x_opencti_score` = `HONEYDB_SCORE`, labels `honeydb` and `honeypot`, a
  description with the 24-hour event count and the last-seen date, the
  configured TLP marking, `created_by` = the HoneyDB identity, and an external
  reference to `https://honeydb.io/ip/<host>`.
- **Indicator** (only when `HONEYDB_CREATE_INDICATORS=true`) — STIX pattern
  `[ipv4-addr:value = '<host>']` (or `ipv6-addr`), `indicator_types` =
  `malicious-activity`, `confidence` = `HONEYDB_SCORE`, `valid_from` = the
  last-seen date, `valid_until` = last-seen + `HONEYDB_INDICATOR_VALID_DAYS`,
  same labels, marking, author and external reference as the observable.
- **Relationship** `indicator --based-on--> observable`, again only with
  indicators enabled.

One **Identity** (organization `HoneyDB`) and the TLP marking definition are
included in every bundle so it is self-consistent.

Things to know:

- **Updates, not duplicates.** Every ID is deterministic (`pycti` generators
  for SDOs/SROs, `value`-based IDs for observables) and the bundle is sent
  with `update=true`, so a host seen on consecutive days keeps one observable
  whose description, score and indicator validity move forward.
- **Expiry.** Nothing is ever deleted by the connector. Indicators expire via
  `valid_until`, which OpenCTI's indicator lifecycle handles. Observables
  accumulate; use OpenCTI retention policies if you need them pruned.
- **Score vs. confidence.** `HONEYDB_SCORE` is a flat value: the bad-hosts
  endpoint has no per-host score. OpenCTI still caps stored confidence at
  the connector user's confidence level.
- **Dates are UTC.** HoneyDB reports `last_seen` as a date; the connector
  treats it as midnight UTC for `valid_from` / `valid_until`.
- **Period.** HoneyDB's list is a rolling 24-hour window refreshed once a
  day, so `PT24H` is the useful minimum. A shorter period only spends API
  quota; the connector warns at startup if the period is under one hour but
  does not clamp it.
- **Restarts are free.** The connector stores `last_run` in its state and
  skips the run if a restart happens inside the period, so a container
  restart never costs an extra API call. The next run is then scheduled from
  the restart time, i.e. the schedule shifts rather than doubles up.
- **Noise control.** `HONEYDB_MIN_COUNT` drops hosts with few events; they
  are counted as *filtered* in the work message. Entries the connector cannot
  parse are *skipped* with a warning. If every entry is unparsable the run is
  marked in error, because that indicates an API change rather than a quiet
  day.

## Debugging

The connector can be debugged by setting the appropiate log level.
Note that logging messages can be added using `self.helper.connector_logger,{LOG_LEVEL}("Sample message")`, i.
e., `self.helper.connector_logger.error("An error message")`.

A failed run shows as an errored work on the connector page, and the
connector state records `last_error` (timestamp and error class). The API key
never appears in logs, state or error messages. What the error classes mean:

| Error | Meaning | What to do |
| --- | --- | --- |
| `HoneyDBAuthError` | HTTP 401 | Check `HONEYDB_API_ID` / `HONEYDB_API_KEY`. |
| `HoneyDBPlanError` | HTTP 402 | Your HoneyDB plan or billing state blocks the request; see <https://honeydb.io/threats>. |
| `HoneyDBQuotaError` | HTTP 429 | API quota exhausted for the current window. The `honeydb-qpm-consumed`, `honeydb-qpm-remaining` and `honeydb-quota-window` headers are logged. Raise the period or upgrade the plan. |
| `HoneyDBTransientError` | Network failure or 5xx | Retried 3 times with exponential backoff, then the run fails; the next period retries. |
| `HoneyDBResponseError` | 2xx with an unexpected body | HoneyDB returned an error envelope, non-JSON, or every entry was unparsable. Open an issue if it persists. |

None of these stop the connector: it waits for the next period. There is no
tight retry loop.

## Additional information

- Source and issues: <https://github.com/honeydbio/opencti-connector-honeydb>
- Design documents (PRD and tech spec): the `design/181-*` files in
  <https://github.com/honeydbio/honeydb-web>
- Scripted access to the same data: the [`honeydb`](https://pypi.org/project/honeydb/) Python module
- HoneyDB API documentation: <https://honeydb.io/threats>
