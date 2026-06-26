# Getting started

## Requirements

- **Docker Engine** + the **Docker Compose plugin**. Nothing else — Python and all
  dependencies live inside the container.

## Install it (one line)

On any Linux host, the installer checks for Docker (and offers to install it),
writes a compose file, starts dash, and prints where to open it:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/preston-peterson/dash/main/install.sh)
```

Useful flags: `--dir <path>`, `--port <n>`, `--tls-hosts <host,ip>`,
`--update-repo <owner/repo>`, `-y` (non-interactive). Run with `--help` for the full
list. *(The one-liner needs the repo to be public; until then, clone it and run
`./install.sh` locally, or use Compose below.)*

## Or run it with Compose

```bash
docker compose up -d
# open https://localhost:8443
```

dash serves **HTTPS** with a self-signed certificate, so your browser shows a
one-time "not trusted" warning — choose *Advanced → proceed*. (See
[Deployment → HTTPS](./deployment.md#https--certificate) to reduce the warning.)

Your data — links, users, and the generated certificate — lives in `./data` on the
host, so it survives container rebuilds.

## First run: create the admin

On the very first visit (no users yet) dash shows a one-time setup screen. Choose an
admin username and password (minimum 8 characters, entered twice).

![First-run admin setup](./screenshots/setup.png)

After that the dashboard starts empty, with a prompt to add your first service.

![Empty state](./screenshots/empty-state.png)

## Signing in

Once the admin exists, every visit requires a login. Any additional users you create
sign in the same way.

![Login](./screenshots/login.png)

## Next steps

- [Add and monitor services](./user-guide.md)
- [Create more users](./administration.md)
- [Deploy to a server](./deployment.md)
