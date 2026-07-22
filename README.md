# CRUD API (serviot-devices-api)

A small FastAPI service over a `devices` table in Postgres. It's intentionally
simple — the interesting part is the infra and pipeline around it, written up in
[DEPLOYMENT.md](DEPLOYMENT.md).

Live: **https://crud.clothentic.in** · DB: `serviot_app1` on RDS.

## Endpoints

| Method | Path | |
|--------|------|--|
| GET | `/health` | app **and** DB health — 200 healthy / 503 if the DB is down |
| GET | `/devices` | list |
| POST | `/devices` | create |
| GET | `/devices/{id}` | fetch one |
| PUT | `/devices/{id}` | update |
| DELETE | `/devices/{id}` | delete |

`/docs` has the interactive OpenAPI UI.

## Run it locally

Everything comes up with Docker; the only manual step is the env file.

```bash
cp .env.example .env
docker compose up --build      # api + Postgres + nginx
curl localhost:8080/health
```

## How it's wired

- **Config** is all environment (`app/config.py`) — same image everywhere, only
  the injected env changes.
- **Migrations** are plain SQL in `migrations/`, applied on startup and written
  to be safe to re-run (`CREATE TABLE IF NOT EXISTS`). In production the pipeline
  runs the same SQL.
- **DB access** is raw parameterised SQL via psycopg (`app/crud.py`) — no ORM,
  because one table doesn't need one, and every value is bound (no injection).
- **Health** actually checks the database with `SELECT 1`, so a green `/health`
  means the app *and* its DB are up — that's what the pipeline and load balancer
  rely on.

## Files

- `app/` — the service · `migrations/` — schema · `tests/` — smoke tests
- `Dockerfile` — multi-stage, runs as non-root
- `docker-compose.yml` — local dev (api + db + nginx)
- `docker-compose.prod.yml` — production (api only, points at RDS)
- `docker-compose.ci.yml` — ephemeral stack the pipeline tests against
- `Jenkinsfile` — build → test → deploy → health check → auto-rollback
- `deploy/nginx-app.conf` — the reverse-proxy block used on the server

## Pipeline in one line

Push to GitHub → Jenkins builds the image, runs the tests against a throwaway
Postgres, ships it to the server, checks `/health`, and rolls back to the last
good commit if the check fails.
