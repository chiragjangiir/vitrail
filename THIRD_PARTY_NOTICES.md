# Third-party notices

Vitrail is licensed under the AGPL-3.0-or-later (see `LICENSE`). It builds on third-party
components that keep their own licences. All of them are compatible with the AGPL. This file
lists the notices the project ships with its source.

## Code and assets vendored in this repository

| Component | Where | Licence |
|---|---|---|
| `@noble/ed25519` v2.1.0, © Paul Miller | `frontend/public/player-chromeos/**/ed25519.js`, `player-extension/player/ed25519.js` | MIT (notice kept in each file header) |
| Fira Mono, © The Mozilla Corporation and Telefonica S.A. | `frontend/public/fonts/ui/` | SIL OFL 1.1, Reserved Font Name "Fira" (see `OFL.txt` there) |
| Inter, Montserrat, Oswald, Playfair Display, Poppins, Bebas Neue | `frontend/public/fonts/promo/`, `backend/app/services/promo/fonts/` | SIL OFL 1.1 (see `OFL.txt` in each folder) |

## Backend (Python)

The main dependencies are FastAPI, SQLAlchemy, Pydantic, Celery, httpx, boto3, LiteLLM (the MIT
SDK only), ReportLab, Pillow and cryptography. Their licences are permissive (MIT, BSD,
Apache-2.0, HPND/MIT-CMU). Some use weak copyleft:

- `psycopg2-binary` and `ldap3`: LGPL-3.0. Their wheels bundle `libpq` and OpenSSL, which carry
  their own notices.
- `certifi`: MPL-2.0.

Vitrail uses only the MIT-licensed LiteLLM SDK. Do not import `litellm.proxy.enterprise`, which
is under a commercial licence.

## Frontend (npm, production dependencies)

Notes:
- `sharp` / `@img/sharp-libvips-*`: Apache-2.0 for sharp, LGPL-3.0-or-later for the bundled
  libvips.
- `caniuse-lite`: CC-BY-4.0, attribution to the Can I Use project (https://caniuse.com).
- `jszip`: dual MIT OR GPL-3.0; Vitrail uses it under MIT.

| Package | Version | Licence | Author |
|---|---|---|---|
| `@formatjs/ecma402-abstract` | 2.3.6 | MIT | Long Ho |
| `@formatjs/fast-memoize` | 2.2.7 | MIT | Long Ho |
| `@formatjs/icu-messageformat-parser` | 2.11.4 | MIT |  |
| `@formatjs/icu-skeleton-parser` | 1.8.16 | MIT |  |
| `@formatjs/intl-localematcher` | 0.5.10 | MIT | Long Ho |
| `@formatjs/intl-localematcher` | 0.6.2 | MIT | Long Ho |
| `@img/colour` | 1.1.0 | MIT |  |
| `@img/sharp-win32-x64` | 0.34.5 | Apache-2.0 AND LGPL-3.0-or-later | Lovell Fuller |
| `@next/env` | 15.5.19 | MIT | Next.js Team |
| `@next/swc-win32-x64-msvc` | 15.5.19 | MIT |  |
| `@playwright/test` | 1.60.0 | Apache-2.0 | Microsoft Corporation |
| `@swc/helpers` | 0.5.15 | Apache-2.0 | 강동윤 |
| `@tanstack/query-core` | 5.100.14 | MIT | tannerlinsley |
| `@tanstack/react-query` | 5.100.14 | MIT | tannerlinsley |
| `@types/react` | 19.2.15 | MIT |  |
| `agent-base` | 6.0.2 | MIT | Nathan Rajlich |
| `asynckit` | 0.4.0 | MIT | Alex Indigo |
| `axios` | 1.16.1 | MIT | Matt Zabriskie |
| `call-bind-apply-helpers` | 1.0.2 | MIT | Jordan Harband |
| `caniuse-lite` | 1.0.30001793 | CC-BY-4.0 | Ben Briggs |
| `client-only` | 0.0.1 | MIT |  |
| `clsx` | 2.1.1 | MIT | Luke Edwards |
| `combined-stream` | 1.0.8 | MIT | Felix Geisendörfer |
| `core-util-is` | 1.0.3 | MIT | Isaac Z. Schlueter |
| `csstype` | 3.2.3 | MIT | Fredrik Nicol |
| `debug` | 4.4.3 | MIT | Josh Junon |
| `decimal.js` | 10.6.0 | MIT | Michael Mclaughlin |
| `delayed-stream` | 1.0.0 | MIT | Felix Geisendörfer |
| `detect-libc` | 2.1.2 | Apache-2.0 | Lovell Fuller |
| `dunder-proto` | 1.0.1 | MIT | Jordan Harband |
| `es-define-property` | 1.0.1 | MIT | Jordan Harband |
| `es-errors` | 1.3.0 | MIT | Jordan Harband |
| `es-object-atoms` | 1.1.2 | MIT | Jordan Harband |
| `es-set-tostringtag` | 2.1.0 | MIT | Jordan Harband |
| `follow-redirects` | 1.16.0 | MIT | Ruben Verborgh |
| `form-data` | 4.0.6 | MIT | Felix Geisendörfer |
| `function-bind` | 1.1.2 | MIT | Raynos |
| `get-intrinsic` | 1.3.0 | MIT | Jordan Harband |
| `get-proto` | 1.0.1 | MIT | Jordan Harband |
| `gopd` | 1.2.0 | MIT | Jordan Harband |
| `has-symbols` | 1.1.0 | MIT | Jordan Harband |
| `has-tostringtag` | 1.0.2 | MIT | Jordan Harband |
| `hasown` | 2.0.4 | MIT | Jordan Harband |
| `https-proxy-agent` | 5.0.1 | MIT | Nathan Rajlich |
| `immediate` | 3.0.6 | MIT |  |
| `inherits` | 2.0.4 | ISC |  |
| `intl-messageformat` | 10.7.18 | BSD-3-Clause | Eric Ferraiuolo |
| `isarray` | 1.0.0 | MIT | Julian Gruber |
| `jszip` | 3.10.1 | (MIT OR GPL-3.0-or-later) | Stuart Knightley |
| `jwt-decode` | 4.0.0 | MIT | Jose F. Romaniello |
| `lie` | 3.3.0 | MIT |  |
| `lucide-react` | 0.400.0 | ISC | Eric Fennis |
| `math-intrinsics` | 1.1.0 | MIT | Jordan Harband |
| `mime-db` | 1.52.0 | MIT |  |
| `mime-types` | 2.1.35 | MIT |  |
| `ms` | 2.1.3 | MIT |  |
| `nanoid` | 3.3.12 | MIT | Andrey Sitnik |
| `negotiator` | 1.0.0 | MIT |  |
| `next-intl` | 3.26.5 | MIT | Jan Amann |
| `next` | 15.5.19 | MIT |  |
| `pako` | 1.0.11 | (MIT AND Zlib) |  |
| `picocolors` | 1.1.1 | ISC | Alexey Raspopov |
| `playwright-core` | 1.60.0 | Apache-2.0 | Microsoft Corporation |
| `playwright` | 1.60.0 | Apache-2.0 | Microsoft Corporation |
| `postcss` | 8.4.31 | MIT | Andrey Sitnik |
| `process-nextick-args` | 2.0.1 | MIT |  |
| `proxy-from-env` | 2.1.0 | MIT | Rob Wu |
| `qrcode.react` | 4.2.0 | ISC | Paul O’Shannessy |
| `react-dom` | 19.2.6 | MIT |  |
| `react` | 19.2.6 | MIT |  |
| `readable-stream` | 2.3.8 | MIT |  |
| `safe-buffer` | 5.1.2 | MIT | Feross Aboukhadijeh |
| `scheduler` | 0.27.0 | MIT |  |
| `semver` | 7.8.1 | ISC | GitHub Inc. |
| `setimmediate` | 1.0.5 | MIT | YuzuJS |
| `sharp` | 0.34.5 | Apache-2.0 | Lovell Fuller |
| `source-map-js` | 1.2.1 | BSD-3-Clause | Valentin 7rulnik Semirulnik |
| `string_decoder` | 1.1.1 | MIT |  |
| `styled-jsx` | 5.1.6 | MIT |  |
| `tslib` | 2.8.1 | 0BSD | Microsoft Corp. |
| `use-intl` | 3.26.5 | MIT | Jan Amann |
| `use-sync-external-store` | 1.6.0 | MIT |  |
| `util-deprecate` | 1.0.2 | MIT | Nathan Rajlich |
| `zustand` | 4.5.7 | MIT | Paul Henschel |

## Players

- **Electron players** (Linux, Windows, Raspberry Pi): Electron (MIT) bundles Chromium (BSD-style
  and others) and an LGPL build of FFmpeg. Distributed builds include Electron's `LICENSE` and
  `LICENSES.chromium.html`.
- **Android player**: AndroidX, Media3/ExoPlayer, OkHttp, kotlinx-coroutines (Apache-2.0),
  NanoHTTPD (BSD-3-Clause), Bouncy Castle (MIT-style Bouncy Castle licence). Apache-2.0
  components are compatible with GPLv3/AGPLv3; their NOTICE files go with distributed APKs.
- **Field installer**: requests (Apache-2.0), qrcode (BSD), pywinrm (MIT). PyInstaller builds
  bundle the Python runtime (PSF licence).

## Container images pulled at install time (not redistributed by this repository)

- PostgreSQL and pgvector: PostgreSQL licence. MinIO: AGPL-3.0. Caddy: Apache-2.0.
  Mailpit and Ollama: MIT.
- **Redis**: versions 7.4 and later are under RSALv2/SSPL, which are not open-source licences.
  Redis 7.2 (BSD) and Valkey (BSD) are drop-in alternatives if you need a fully free stack.
- The backend image installs `ffmpeg` (LGPL/GPL), `poppler-utils` (GPL) and LibreOffice
  (MPL-2.0). These run as separate processes. It also installs the Debian non-free package
  `intel-media-va-driver-non-free` for Intel hardware encoding; remove it from the Dockerfile
  if you need an image made only of free software.
