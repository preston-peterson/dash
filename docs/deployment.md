# Deployment

## Docker Compose

```bash
docker compose up -d        # build + start
docker compose logs -f      # watch logs
docker compose down         # stop
```

`docker-compose.yml` maps port **8443**, bind-mounts `./data:/data`, and sets
`restart: unless-stopped` so dash comes back after a reboot.

## HTTPS / certificate

On first run dash generates a self-signed certificate at `/data/cert.pem` +
`/data/key.pem` (persisted on the volume) and serves TLS via uvicorn.

- Because it's self-signed, browsers warn the first time — expected on a LAN box.
- To put your server's hostname/IP in the certificate's SAN list (so the host
  matches and you only see the "untrusted issuer" prompt), set `DASH_TLS_HOSTS`:

  ```yaml
  environment:
    - DASH_TLS_HOSTS=dash.example.lan,192.168.1.10
  ```

- To use your own certificate, mount it and point `DASH_TLS_CERT` / `DASH_TLS_KEY`
  at it (and remove the generated pair).

## Ubuntu Server

```bash
# Install Docker Engine + the Compose plugin
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"   # log out/in for this to apply

# Get the project onto the box, then:
cd dash
mkdir -p data
docker compose up -d

# Open the firewall if ufw is enabled:
sudo ufw allow 8443/tcp
```

Browse `https://<server>:8443` and create the admin on first visit.

## Backups

State is essentially one file. Copy `./data/dashboard.db` (WAL mode may also create
`dashboard.db-wal` / `-shm`; stop the container for a fully consistent copy). The
certificate lives alongside it (`./data/cert.pem` / `key.pem`).

## Running the published image (GHCR)

Instead of building locally you can run the image published to GitHub Container
Registry. Replace `build: .` in `docker-compose.yml` with:

```yaml
    image: ghcr.io/preston-peterson/dash:latest
```

Then updates are pull-only:

```bash
docker compose pull && docker compose up -d
```

If the package is private, run `docker login ghcr.io` on the server once (with a
token that has `read:packages`). See [Updates](./updates.md) for the release flow.

## Uninstall

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/preston-peterson/dash/main/uninstall.sh)
```

Stops and removes the container (it auto-detects the install directory from the running
container) and **keeps your data** by default. Flags: `--purge` also deletes `./data`
and the install directory, `--rmi` removes the image, `--dir <path>` if auto-detect
fails, `-y` for non-interactive. From a clone, `docker compose down` also works.
