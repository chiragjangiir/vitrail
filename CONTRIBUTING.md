# Contributing to Vitrail

Thank you for helping. This document explains how to propose a change.

## Ground rules

- **Licence.** Vitrail is licensed under the AGPL-3.0-or-later. By contributing, you agree that
  your contribution is licensed under the same terms. You keep the copyright on your work. There
  is no copyright assignment and no CLA, so nobody, the maintainers included, can take the
  project closed-source.
- **Sign-off (DCO).** Every commit must carry a `Signed-off-by:` line certifying the
  [Developer Certificate of Origin](https://developercertificate.org/): that you wrote the change,
  or otherwise have the right to submit it under the project's licence. Add it with
  `git commit -s`.
- **Be kind.** Follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Workflow

1. Open an issue first for anything bigger than a small fix, so the approach can be discussed
   before you spend time on it.
2. Fork, then create a branch from `main`.
3. Keep the change focused: one topic per pull request.
4. Add or update tests. A test should **fail** on the code before your change and pass after it.
5. Make sure CI passes (backend pytest, frontend `tsc` / `eslint` / build / Playwright).
6. Open the pull request and describe **what** changes and **why**.

## Conventions that matter

- **Multi-tenancy.** Every tenant table is protected by PostgreSQL row-level security on
  `id_org`. A resource belonging to another organisation must answer **404**, never 403.
- **RBAC.** Permission checks use the `module:operation` pairs seeded by the migrations. Do not
  invent new operations in an endpoint without adding them to the catalogue.
- **Migrations.** Never edit a migration that has already been released. Add a new one.
- **Players connect to the server, never the reverse.** No feature may require an inbound port
  on the player's network.
- **Configuration.** A new environment variable must be declared in `backend/app/core/config.py`
  **and** in the `environment` of every docker-compose service that uses it.
- **Frontend.** Numeric inputs go through `components/ui/NumberField.tsx`. Every new UI string
  needs a key in all 5 locales (`frontend/messages/*.json`), placed in the right namespace.
- **Players show English only**; the web interface is translated.

## Development setup

See the *Quick start* section of the [README](README.md).

## Reporting bugs

Open an issue. Include the server version (shown in the sidebar), the player platform and
version if relevant, the steps to reproduce, and what you expected instead. For security
issues, follow [SECURITY.md](SECURITY.md) and do not open a public issue.
