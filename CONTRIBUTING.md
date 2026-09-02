# Contributing

## Layout

This repository is laid out so that its contents are a verbatim copy of
`external-import/honeydb/` in the upstream
[OpenCTI-Platform/connectors](https://github.com/OpenCTI-Platform/connectors)
monorepo, which is where Filigran builds and publishes the
`opencti/connector-honeydb` image and lists the connector in the catalogue.

**Root-only files** exist for this repository and are **not** copied upstream:

- `LICENSE`, `CONTRIBUTING.md`, `.gitignore`
- `pyproject.toml` (ruff configuration), `Makefile`
- `tools/` (metadata generation and tooling requirements)
- `.github/` (CI and release workflows)

Everything else — `Dockerfile`, `.dockerignore`, `docker-compose.yml`,
`entrypoint.sh`, `README.md`, `__metadata__/`, `src/`, `tests/` — is the
upstream connector.

## Development

```shell
make venv          # Python 3.12 venv with runtime, test and tooling deps (uses uv)
source .venv/bin/activate
make lint          # ruff format --check + ruff check
make test          # pytest
make metadata      # regenerate __metadata__/connector_config_schema.json and CONNECTOR_CONFIG_DOC.md
make docker        # build the image locally
make check         # lint + test + metadata drift check (what CI runs)
```

Tests never contact honeydb.io or an OpenCTI instance.

`__metadata__/connector_config_schema.json` and `CONNECTOR_CONFIG_DOC.md`
are **generated** from `src/connector/settings.py`. Edit the settings model,
run `make metadata`, and commit the result; CI fails if they drift.

`connectors-sdk` is installed from upstream `master` on purpose, for parity
with how upstream builds every connector. That makes a source rebuild
non-reproducible over time; tagged releases are the reproducible artefact
(the release workflow builds the ghcr image from the tag), and CI runs weekly
so SDK drift is noticed early.

## Releasing

1. Bump `__version__` in `src/connector/__init__.py` (it is also the
   `User-Agent` the connector sends).
2. Tag `vX.Y.Z` and push the tag. The release workflow publishes
   `ghcr.io/honeydbio/opencti-connector-honeydb:X.Y.Z` and `:latest`.

## Syncing to upstream (OpenCTI-Platform/connectors)

Before every upstream sync:

1. Re-diff this repo against `templates/external-import` upstream for
   structural changes (Dockerfile base image, `requirements.txt` pins,
   manifest fields) and adopt them.
2. `make metadata` and confirm `git diff __metadata__/` is empty.
3. Get a green CI run against fresh SDK `master`.

Then:

1. Fork `OpenCTI-Platform/connectors` and create `external-import/honeydb/`.
2. Copy everything except the root-only files listed above.
3. Run upstream's formatters from the monorepo root (they enforce `black`
   and `isort`; ruff-formatted code satisfies both):
   `black external-import/honeydb && isort --profile black external-import/honeydb`.
4. Open the companion issue in `OpenCTI-Platform/connectors` using their
   connector-request template, then the PR referencing it, and request review
   from the connectors team.
5. Until the upstream image exists, users can run the ghcr image by swapping
   the `image:` line in `docker-compose.yml`.

Verified status is requested from Filigran after the upstream PR merges.
