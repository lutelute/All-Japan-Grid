# Security Policy / セキュリティ方針

## Intended use / 想定利用
All-Japan-Grid is a research dataset plus a **local** interactive editor/viewer.
The editor backend (`src/server/app.py`, default port 8080/8088) is intended to
run on **localhost only**, operated by a single trusted user. The publicly
distributed artifact is the GitHub Pages site — a **static, read-only** map with
no server-side endpoints.

## Trust boundary / 信頼境界 — do NOT expose the editor server publicly
The editor's state-changing endpoints have **no authentication, CORS, or
rate-limiting**:
- `POST /api/issue/{region}` runs `gh issue create` under the host's GitHub
  login, so it can open public issues in the repository.
- `POST /api/adopt`, `POST /api/edits`, and the `DELETE` routes persist writes
  to `data/*.geojson` (model state).

Therefore: **bind to `127.0.0.1`, never `0.0.0.0`**, and never place this server
behind a public URL or reverse proxy without first adding authentication and
CSRF protection. A future hardening step is to require an auth token / CSRF
token on all state-changing routes and default `/api/issue` to `dry_run=true`.

## Out-of-scope use / 適切でない利用
This is OpenStreetMap-derived, machine-extracted data — **not** official utility
information (see the README disclaimer). It must not be relied upon as
authoritative operational data for grid control, dispatch, protection, or safety
decisions.

Critical-infrastructure / dual-use note: every published feature is traceable to
public sources (OpenStreetMap, 国土数値情報 P03, WRI Global Power Plant Database).
No restricted operational data is redistributed — utility per-line ratings and
flows (TEPCO, 関西電力送配電) are used only for **private** validation and are
published as **aggregate metrics only** (see NOTICE and docs/reports/).

## Reporting a vulnerability / 脆弱性の報告
Please open a GitHub issue prefixed with **[security]**, or contact the
repository owner directly. This is a research project; there is no formal
disclosure SLA.
