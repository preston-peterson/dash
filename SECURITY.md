# Security Policy

## Supported versions

dash is pre-1.0; only the latest release receives security fixes.

| Version | Supported |
|---------|-----------|
| latest  | ✅        |
| older   | ❌        |

## Reporting a vulnerability

Please report security issues **privately** — do not open a public issue.

- Preferred: GitHub **Security → Report a vulnerability** (private advisory) on this
  repository.
- Include the affected version, impact, and steps to reproduce.

You'll get an acknowledgement as soon as possible, and credit on the fix unless you
prefer otherwise.

## Posture notes

- dash serves HTTPS with a **self-signed** certificate by default. For exposure
  beyond a trusted LAN, front it with a reverse proxy holding a real certificate.
- Passwords are stored as pbkdf2-HMAC-SHA256 hashes; sessions are HttpOnly + Secure
  cookies. There is no shared-password mode.
- dash is designed for internal/home-lab use, **not** direct exposure to the public
  internet.
