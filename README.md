# Dash — Home Lab Dashboard

A self-hosted "network console" for your home lab. Register internal services as
links, and the dashboard checks whether each one is up — **server-side**, so it
works for internal hosts that a browser couldn't reach directly (no CORS or
mixed-content limits). Search, tag-filter, and switch between a card grid or a
dense list. Served over **HTTPS** with per-user accounts. Runs fully offline as a
single Docker container.

- **Backend:** Python + FastAPI (serves the API *and* the static frontend)
- **Storage:** SQLite — one file on a host bind-mount (`./data/dashboard.db`)
- **Frontend:** plain HTML/CSS/JS — no build step, no CDN, no web fonts
- **Security:** HTTPS (self-signed cert, auto-generated), accounts with
  pbkdf2-hashed passwords, cookie sessions
- **Checks:** `tcp` (port open) or `http` (any response = up), on a background loop

![dash — rows view](docs/screenshots/dashboard-rows-dark.png)

## Documentation

Full docs live in [`docs/`](docs/README.md):

- [Getting started](docs/getting-started.md) · [User guide](docs/user-guide.md) ·
  [Administration](docs/administration.md)
- [Deployment](docs/deployment.md) · [Configuration](docs/configuration.md) ·
  [Updates](docs/updates.md) · [Architecture & API](docs/architecture.md)

## Quick start

**One line** on any Linux host — installs Docker if it's missing, then sets up and
starts dash:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/preston-peterson/dash/main/install.sh)
```

Or, from a clone of this repo:

```bash
docker compose up -d
# open https://localhost:8443
```

The dashboard serves **HTTPS** with a self-signed certificate, so your browser
will show a one-time "not trusted" warning — choose *Advanced → proceed*. On your
**first visit** you'll be prompted to **create the admin account**; after that,
everyone signs in. Your links and users live in `./data/dashboard.db` on the host,
so they survive container rebuilds.

## Accounts & login

- **First run:** if no users exist, the app shows a one-time *Create admin* screen.
- **Login is always required** after that (username + password, hashed with pbkdf2).
- **Admins** can add/remove users and reset passwords via the **Users** dialog.
- **Any user** can change their own password via **Account**.
- The last remaining admin can't be deleted, and you can't delete your own account.

## HTTPS / certificate

- On first run the app generates a self-signed cert at **`/data/cert.pem`** +
  **`/data/key.pem`** (persisted on the volume) and serves TLS via uvicorn.
- It's self-signed, so browsers warn the first time — that's expected on a LAN box.
- To include your own hostname/IP in the cert's SAN list (cleaner warnings), set
  `DASH_TLS_HOSTS`. To use your own cert, mount it and point `DASH_TLS_CERT` /
  `DASH_TLS_KEY` at it (and delete the generated pair).

## Updates

The running version comes from the `VERSION` file baked into the image and is shown
in the gear menu (⚙). If you set `DASH_UPDATE_REPO` to a GitHub `owner/repo`, dash
does a best-effort daily check of that repo's latest release (and on demand via
*Check for updates*). When a newer release exists, the gear shows a dot and the menu
displays **"vX.Y.Z available"** with a copy-paste command (`DASH_UPDATE_COMMAND`,
default `docker compose pull && docker compose up -d`) and a link to the release notes.

The check is best-effort and fail-silent — if the box is offline or the repo is
unreachable, dash just keeps showing the running version. Applying the update is a
manual, explicit step (run the shown command); dash never touches the Docker host
itself. To publish updates, tag a release in the repo (and push a matching image if
your compose uses a registry).

## Configuration

| Variable             | Default              | Description                                              |
| -------------------- | -------------------- | -------------------------------------------------------- |
| `DASH_DB_PATH`       | `/data/dashboard.db` | SQLite file path inside the container                    |
| `DASH_INTERVAL`      | `30`                 | Seconds between background status checks                 |
| `DASH_CHECK_TIMEOUT` | `4`                  | Per-check timeout in seconds                             |
| `DASH_PORT`          | `8443`               | HTTPS port the app listens on (also map it in `ports`)   |
| `DASH_TLS_CERT`      | `/data/cert.pem`     | TLS certificate path (auto-generated if missing)         |
| `DASH_TLS_KEY`       | `/data/key.pem`      | TLS private key path (auto-generated if missing)         |
| `DASH_TLS_HOSTS`     | *(empty)*            | Extra SAN hosts for the self-signed cert (comma-sep.)    |
| `DASH_UPDATE_REPO`   | *(empty)*            | GitHub `owner/repo` to check for new releases. Off if unset. |
| `DASH_UPDATE_COMMAND`| `docker compose pull && docker compose up -d` | One-liner shown when an update is available |
| `DASH_UPDATE_URL`    | *(derived)*          | Override the release-check URL (defaults to the repo's GitHub releases API) |
| `DASH_UPDATE_INTERVAL`| `86400`             | Seconds between background update checks                 |

## Features

- **Add / edit / delete** services: name, description, host, port, tags,
  check type (`tcp` / `http`), and scheme (`http` / `https`).
- **Server-side status checks** with latency and last-checked time, refreshed
  every `DASH_INTERVAL` seconds, plus manual **Refresh** (all) and per-item re-check.
- **DNS discovery:** the dashboard resolves the counterpart of each host during
  checks and shows it under the address — a name for IP-entered hosts (reverse/PTR),
  or an IP for name-entered hosts (forward). Depends on your network's DNS.
- **Search** across name/description/host/tags/resolved and clickable **tag filter** chips.
- **Top-bar summary** counts (online / offline).
- **Tiles or rows** view and **Auto / light / dark** theme — chosen from the gear
  menu (⚙), persisted in your browser. *Auto* follows your OS preference.
- **Update notifications** (optional): when pointed at a GitHub repo, the gear menu
  shows the running version and flags when a newer release is available, with a
  copy-paste command to update.
- Clicking a card/row opens the service at `scheme://host:port`.

## Checks

- **tcp** — opens a TCP connection to `host:port`. Connects = **online**.
- **http** — sends `GET scheme://host:port` (TLS verification disabled, short
  timeout). **Any** HTTP response — including 401/403/404 — counts as **online**;
  only a connection error or timeout is **offline**.

## API

| Method | Path                    | Description                                  |
| ------ | ----------------------- | -------------------------------------------- |
| GET    | `/`                     | Serve the app                                |
| GET    | `/api/me`               | `{setup_required, authenticated, user}`      |
| POST   | `/api/setup`            | Create the first admin (only when no users)  |
| POST   | `/api/login`            | `{username, password}` → sets session cookie |
| POST   | `/api/logout`           | Clear the session                            |
| GET    | `/api/users`            | List users (admin)                           |
| POST   | `/api/users`            | Create a user (admin)                        |
| DELETE | `/api/users/{id}`       | Delete a user (admin)                        |
| POST   | `/api/users/{id}/password` | Set a password (admin, or self)           |
| GET    | `/api/links`            | All links with current status                |
| POST   | `/api/links`            | Create a link                                |
| PUT    | `/api/links/{id}`       | Update a link                                |
| DELETE | `/api/links/{id}`       | Delete a link                                |
| POST   | `/api/links/{id}/check` | Check one link now                           |
| POST   | `/api/check-all`        | Check all links now                          |

All `/api/links*`, `/api/check-all`, and `/api/users*` endpoints require a logged-in
session (`/api/users*` additionally require an admin).

## Ubuntu Server deployment

On a fresh Ubuntu Server VM:

```bash
# 1. Install Docker Engine + the Compose plugin
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"   # log out/in so this takes effect

# 2. Get the project onto the VM (clone, or scp/rsync this folder), then:
cd dashboard
mkdir -p data
# optional: trust the VM's name/IP in the cert:
#   echo 'DASH_TLS_HOSTS=dash.lan,192.168.1.10' set in docker-compose.yml
docker compose up -d

# 3. If the firewall is enabled, allow the HTTPS port:
sudo ufw allow 8443/tcp
```

Open `https://<vm-ip>:8443` and create the admin account on first visit.

**Backups:** state is one file — copy `./data/dashboard.db` (WAL mode may also
create `dashboard.db-wal` / `-shm`; stop the container for a fully consistent copy).
The cert lives alongside it (`./data/cert.pem` / `key.pem`).

**Updating:** `docker compose up -d --build` rebuilds and restarts. The `./data`
bind-mount keeps your links, users, and cert across rebuilds. `restart: unless-stopped`
brings it back after a reboot.

## Local development

```bash
pip install -r requirements.txt
# generate a cert + DB under ./data and run on https://localhost:8443
DASH_DB_PATH=./data/dashboard.db \
DASH_TLS_CERT=./data/cert.pem DASH_TLS_KEY=./data/key.pem \
python app.py
```

## Releasing (GHCR)

Images are published to GitHub Container Registry by `.github/workflows/docker-publish.yml`
when a version tag is pushed. To cut a release:

```bash
# 1. bump the version
echo 0.2.0 > VERSION && git commit -am "release 0.2.0"
# 2. tag + push — the Action builds & pushes ghcr.io/<owner>/dash:{0.2.0,latest}
git tag v0.2.0 && git push --tags
# 3. create a GitHub Release for v0.2.0 (this is what the update check reads)
```

On the server, point compose at the image (`image: ghcr.io/<owner>/dash:latest`) and set
`DASH_UPDATE_REPO=<owner>/dash`. Updating is then `docker compose pull && docker compose up -d`.
If the GHCR package is private, run `docker login ghcr.io` on the server once (token with
`read:packages`).

