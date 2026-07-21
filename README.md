# serviot-devices-api

Small CRUD API over a `devices` table. FastAPI + PostgreSQL, fronted by Nginx.
Built to exercise the **infrastructure and pipeline** around a service — the
business logic (one CRUD resource) is intentionally trivial.

- Application source: [`app/`](app/)
- DB schema / migrations: [`migrations/`](migrations/)
- Env template: [`.env.example`](.env.example)
- Infra reasoning: [`DEPLOYMENT.md`](DEPLOYMENT.md)

> **Scope note.** The assignment text mentions "both apps". Scope was set to a
> single app + single database for this submission. `docker-compose.yml`
> therefore brings up **app + database + Nginx**. `DEPLOYMENT.md` still covers
> the multi-app topics (per-app pipelines, database separation) as design
> reasoning so the decisions are on record.

## Run locally (Docker — no manual steps beyond the .env)

```bash
cp .env.example .env
docker compose up --build
```

Then:

| What            | URL                              |
|-----------------|----------------------------------|
| API (via Nginx) | http://localhost:8080            |
| Health          | http://localhost:8080/health     |
| OpenAPI docs    | http://localhost:8080/docs       |

## Endpoints

| Method | Path             | Purpose                              |
|--------|------------------|--------------------------------------|
| GET    | `/health`        | App + DB health (200 / 503)          |
| GET    | `/devices`       | List devices                         |
| POST   | `/devices`       | Create device                        |
| GET    | `/devices/{id}`  | Get one                              |
| PUT    | `/devices/{id}`  | Update (partial)                     |
| DELETE | `/devices/{id}`  | Delete                              |

### Quick check

```bash
curl -s localhost:8080/health | jq
curl -s -X POST localhost:8080/devices \
  -H 'content-type: application/json' \
  -d '{"name":"sensor-1","type":"temp","status":"online"}' | jq
curl -s localhost:8080/devices | jq
```

## Health semantics

`GET /health` returns `200` with `status: healthy` only when the app is serving
**and** a `SELECT 1` through the pool succeeds. If the DB is unreachable it
returns `503` with `status: unhealthy` so a load balancer / orchestrator drains
the instance.

## Tests

Stdlib-only smoke tests against a running stack:

```bash
docker compose up -d
BASE_URL=http://localhost:8080 pytest -q
```

## Data access — why raw SQL

App 1 uses **raw, parameterized SQL** via `psycopg` (see [`app/crud.py`](app/crud.py))
rather than an ORM. Justification:

- The domain is one table with trivial queries — an ORM's mapping/session layer
  is overhead with no payoff at this size.
- Fewer dependencies and no query-generation indirection = a smaller image and
  SQL that is exactly what runs.
- **Injection is not a concern here:** every value is passed as a bound
  parameter (`%s` placeholders + a values tuple); no string-built SQL anywhere.
- Column list and table are hard-coded constants, never user input.

If this grew to many related tables with complex joins/relations, an ORM or
query builder would earn its keep and the choice would flip.

## Open ports

Every inbound port is listed and justified (unexplained ports are a finding).

**Local (docker-compose):**

| Port | Bound by | Exposure | Why |
|------|----------|----------|-----|
| `8080` (host, overridable via `NGINX_HOST_PORT`) | Nginx → `:80` | Public (host) | Only public entry point. All traffic enters here. |
| `8000` | API (uvicorn) | Internal only (`expose`, not published) | App is reachable **only** from Nginx on the compose network, never from the host. |
| `5432` | Postgres | Internal only (no `ports:`) | DB reachable only from the API container. Not published to the host. |

**Production (design, per [`DEPLOYMENT.md`](DEPLOYMENT.md)):**

| Port | Exposure | Why |
|------|----------|-----|
| `443` | Public | TLS entry at Nginx. |
| `80` | Public | HTTP→HTTPS redirect only. |
| `22` (SSH) | Restricted to a specific admin IP range | Ops access; never open to `0.0.0.0/0`. |
| Jenkins port (non-default, **not** 8080) | Restricted | CI UI; not public. |
| `5432` (managed DB) | Security group: app subnet only | DB accepts connections from the app tier only, never the internet. |

## Migrations

`migrations/*.sql` are idempotent (`IF NOT EXISTS`) and applied on startup, and
are meant to be run as a dedicated pipeline step in real environments. See
[`DEPLOYMENT.md`](DEPLOYMENT.md#5-database).
