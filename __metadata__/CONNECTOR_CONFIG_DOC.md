# Connector Configurations

Below is an exhaustive enumeration of all configurable parameters available, each accompanied by detailed explanations of their purposes, default behaviors, and usage guidelines to help you understand and utilize them effectively.

### Type: `object`

| Property | Type | Required | Possible values | Default | Description |
| -------- | ---- | -------- | --------------- | ------- | ----------- |
| OPENCTI_URL | `string` | ✅ | Format: [`uri`](https://json-schema.org/understanding-json-schema/reference/string#built-in-formats) |  | The base URL of the OpenCTI instance. |
| OPENCTI_TOKEN | `string` | ✅ | Format: [`password`](https://json-schema.org/understanding-json-schema/reference/string#built-in-formats) |  | The API token to connect to OpenCTI. |
| HONEYDB_API_ID | `string` | ✅ | Length: `string >= 1` |  | Your HoneyDB API ID (see https://honeydb.io/threats). |
| HONEYDB_API_KEY | `string` | ✅ | Format: [`password`](https://json-schema.org/understanding-json-schema/reference/string#built-in-formats) |  | Your HoneyDB API key (see https://honeydb.io/threats). |
| CONNECTOR_NAME | `string` |  | string | `"HoneyDB"` | The name of the connector. |
| CONNECTOR_SCOPE | `array` |  | string | `["honeydb"]` | The scope of the connector. |
| CONNECTOR_LOG_LEVEL | `string` |  | `debug` `info` `warn` `warning` `error` | `"error"` | The minimum level of logs to display. |
| CONNECTOR_TYPE | `const` |  | `EXTERNAL_IMPORT` | `"EXTERNAL_IMPORT"` |  |
| CONNECTOR_DURATION_PERIOD | `string` |  | Format: [`duration`](https://json-schema.org/understanding-json-schema/reference/string#built-in-formats) | `"P1D"` | The period of time to await between two runs of the connector. |
| HONEYDB_API_BASE_URL | `string` |  | Format: [`uri`](https://json-schema.org/understanding-json-schema/reference/string#built-in-formats) | `"https://honeydb.io/api"` | Base URL of the HoneyDB API. |
| HONEYDB_SCORE | `integer` |  | `0 <= x <= 100` | `50` | Score (0-100) applied as `x_opencti_score` on observables and as `confidence` on indicators. |
| HONEYDB_TLP_LEVEL | `string` |  | `clear` `white` `green` `amber` `amber+strict` `red` | `"clear"` | TLP marking for imported data (`clear`, `white`, `green`, `amber`, `amber+strict`, `red`). |
| HONEYDB_CREATE_INDICATORS | `boolean` |  | boolean | `false` | Whether to also create STIX Indicators (with a `based-on` relationship to each observable). |
| HONEYDB_MIN_COUNT | `integer` |  | `1 <= x ` | `1` | Skip hosts with fewer than this many events in the 24-hour window. |
| HONEYDB_INDICATOR_VALID_DAYS | `integer` |  | `1 <= x ` | `7` | Number of days after a host's last-seen date until its indicator expires (`valid_until`). |
