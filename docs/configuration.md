# Configuration

All configuration is via environment variables (set them in `docker-compose.yml`).

## Core

| Variable | Default | Description |
|---|---|---|
| `DASH_DB_PATH` | `/data/dashboard.db` | SQLite database path inside the container |
| `DASH_PORT` | `8443` | HTTPS port the app listens on (also map it in `ports`) |
| `DASH_INTERVAL` | `30` | Seconds between background status checks |
| `DASH_CHECK_TIMEOUT` | `4` | Per-check timeout in seconds |

## TLS

| Variable | Default | Description |
|---|---|---|
| `DASH_TLS_CERT` | `/data/cert.pem` | Certificate path (auto-generated if missing) |
| `DASH_TLS_KEY` | `/data/key.pem` | Private key path (auto-generated if missing) |
| `DASH_TLS_HOSTS` | *(empty)* | Extra SAN hosts for the self-signed cert (comma-separated) |

## Updates

| Variable | Default | Description |
|---|---|---|
| `DASH_UPDATE_REPO` | *(empty)* | GitHub `owner/repo` to check for releases. Off if unset. |
| `DASH_UPDATE_COMMAND` | `docker compose pull && docker compose up -d` | One-liner shown when an update is available |
| `DASH_UPDATE_URL` | *(derived)* | Override the release-check URL |
| `DASH_UPDATE_INTERVAL` | `86400` | Seconds between background update checks |
| `DASH_VERSION` | *(from `VERSION`)* | Override the reported version |

There is no `DASH_PASSWORD` — authentication is account-based (see
[Administration](./administration.md)).
