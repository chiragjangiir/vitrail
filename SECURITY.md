# Security Policy

## Reporting a vulnerability

**Do not open a public issue.**

Report it privately through GitHub: open the repository's **Security** tab and click
**Report a vulnerability** (GitHub private vulnerability reporting). Please include:

- a description of the problem and its impact;
- the steps to reproduce it, or a proof of concept;
- the affected version (server version, player platform and version).

Please allow a reasonable time for a fix before any public disclosure.

## Scope

- The CMS server (FastAPI backend, Next.js frontend, advertiser portal);
- the players (Linux, Windows, Raspberry Pi, Android, ChromeOS, Chrome extension, BrightSign);
- the `signflow-provision` field tool and the server installer.

Design principles worth knowing before you report:
- connections always go from the player to the server, and no inbound port is opened on the
  player side;
- tenants are isolated by PostgreSQL row-level security: a resource of another organisation
  answers **404**, never 403;
- per-organisation AI keys are encrypted at rest (Fernet, `CMS_VAULT_KEY`).

## Supported versions

Security fixes go to the **latest published release** only.
