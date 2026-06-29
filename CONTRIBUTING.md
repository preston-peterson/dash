# Contributing to dash

Thanks for your interest! dash is a small, self-hosted home-lab dashboard.

## Reporting bugs & requesting features

Please open a [GitHub issue](https://github.com/preston-peterson/dash/issues) using
the bug or feature template. Helpful details: your dash version (shown in the gear
menu), how you deployed it (installer / Compose / GHCR image), and clear steps to
reproduce.

## Security issues

Do **not** open a public issue for vulnerabilities — see [SECURITY.md](SECURITY.md).

## Pull requests

PRs for bug fixes and well-scoped improvements are welcome. For larger changes, open
an issue first so we can agree on the approach. Forks are encouraged.

- Keep the stack **vanilla**: Python + FastAPI backend, plain HTML/CSS/JS frontend —
  no build step, no CDN, no web fonts (dash must work fully offline on an internal box).
- Match the surrounding code style.
- Test locally before submitting (`docker compose up -d --build`).

## Development

See [docs/architecture.md](docs/architecture.md) for how it fits together and
[docs/getting-started.md](docs/getting-started.md) to run it.
