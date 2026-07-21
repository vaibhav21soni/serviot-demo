# Deployment & Infrastructure Design

This document explains **why** the infrastructure is shaped the way it is, not
just what it is. The application (one CRUD resource) is deliberately trivial;
the reasoning below is the actual deliverable.

Target picture:

```
        Internet
           │  443 (TLS)
     ┌──────▼───────┐
     │    Nginx     │  reverse proxy / TLS termination / rate limit
     └──────┬───────┘
            │  http :8000 (private)
     ┌──────▼───────┐
     │  API (uvicorn)│  stateless, N replicas
     └──────┬───────┘
            │  :5432 (private)
     ┌──────▼───────┐
     │  PostgreSQL   │  managed / dedicated instance, private subnet
     └───────────────┘
```

---

## 1. Instance sizing

**Principle: size to the bottleneck, start small, scale on evidence.**

This workload is I/O-bound (each request is a short DB round-trip), not
CPU-bound. So the app tier trades on request concurrency, and the DB tier trades
on connections + IOPS.

| Tier      | Start with            | Why                                                                 |
|-----------|-----------------------|---------------------------------------------------------------------|
| Nginx     | 1 vCPU / 1 GB (shared) | Proxying is cheap; it moves bytes, holds no state. One small box (or two for HA) saturates a link long before CPU. |
| API       | 2 × (1 vCPU / 1 GB)   | Two small replicas > one big box: gives rolling deploys and survives one node dying. uvicorn is async, so a single vCPU already handles hundreds of concurrent I/O-bound requests. |
| PostgreSQL| 2 vCPU / 4 GB, gp3 SSD | DB is the hardest tier to scale horizontally, so give it the most headroom. RAM matters most — it caches the working set. gp3 gives provisioned IOPS decoupled from disk size. |

**Why not one large instance for everything?** Co-locating app + DB couples
their failure and scaling domains: a deploy that pins CPU starves the DB, and
you can't scale the stateless tier without dragging the stateful one along.
Separation is the point (see §4).

**Scaling path (in order):** (1) add API replicas behind Nginx — they're
stateless, this is free; (2) add a read replica and route reads to it; (3) vertically
bump the DB. Right-sizing is a follow-up driven by real p95 latency and CPU/IO
metrics, not a guess made up front.

---

## 2. Nginx architecture

**Role: single public edge. TLS, routing, and a shock absorber in front of the app.**

Decisions and reasons:

- **Reverse proxy, app never faces the internet.** The API binds to a private
  port (`expose`, not `ports`, in compose; a private subnet in prod). Only Nginx
  is reachable. Shrinks the attack surface to one hardened component.
- **TLS terminates at Nginx.** One place to manage certs (Let's Encrypt / ACM),
  one place to enforce TLS version and ciphers. App speaks plain HTTP on the
  private network, so it stays simple and cert-unaware.
- **`upstream` block with keepalive.** Connection reuse to the app avoids a TCP
  handshake per request and lets us add replicas by listing more `server` lines
  (or a DNS name that resolves to all of them).
- **Dedicated `/health` location with `access_log off`.** Uptime and LB probes
  hit this constantly; logging every probe is noise and I/O. We proxy it through
  so the check reflects the *real* app+DB path, not just "is Nginx up".
- **`server_tokens off`, `client_max_body_size`, timeouts.** Don't advertise the
  version, cap request bodies (this API has no large payloads), and bound
  upstream timeouts so a stuck app connection can't pile up.
- **Rate limiting** belongs here (`limit_req`) — the edge is the cheapest place
  to shed abusive traffic before it costs an app worker or a DB connection.

**Why Nginx and not the app directly?** The app should do one thing (serve the
API). Cross-cutting edge concerns — TLS, rate limiting, compression, static
error pages, header hygiene — are configuration, not code, and Nginx does them
faster and without a redeploy.

---

## 3. Pipeline design (per app)

**Principle: each app owns an independent pipeline; deployable units deploy on
their own cadence.** Even with one app today, the pipeline is designed so a
second app slots in as a parallel, identical lane — no shared "big bang" deploy.

Stages for **each** app:

1. **Lint / typecheck** — fast fail on style + obvious type errors (ruff, mypy).
2. **Unit + smoke tests** — spin up an ephemeral Postgres service in CI, run the
   suite ([`tests/`](tests/)) against a real DB. No mocked database — the DB is
   part of what we're validating.
3. **Build image** — the multi-stage [`Dockerfile`](Dockerfile). Tag with the
   **git SHA** (immutable) plus a moving `latest`/env tag. SHA tags are what make
   rollback trivial (§6).
4. **Scan** — image vuln scan (Trivy) + dependency audit. Fail on high/critical.
5. **Push** to registry.
6. **Migrate** — run `migrations/*.sql` as a **separate, ordered pre-deploy job**
   against the target DB, *before* new app code rolls. Migrations are backward
   compatible so old and new code can both run during the rollout (§5, §6).
7. **Deploy** — rolling update: bring up new replicas, wait for `/health` to pass,
   then drain old ones. Nginx only routes to healthy upstreams.
8. **Post-deploy verify** — hit `/health` and a canary request; auto-rollback on
   failure.

**Why per-app pipelines and not one monorepo-wide deploy?** Independent lanes
mean one app's failing test never blocks another's release, blast radius per
deploy is one service, and each team owns its cadence. The tradeoff — duplicated
pipeline config — is solved with a shared reusable workflow/template, not by
merging the deploys.

**Why migrations as their own stage?** Schema changes and code changes have
different rollback semantics (you roll code back instantly; you do *not* casually
roll a migration back). Separating them forces migrations to be
forward-and-backward compatible and keeps a bad migration from being entangled
with a code deploy.

---

## 4. Database separation rationale

**Rule: one database per service. Services never share a schema.**

Reasons:

- **Independent failure domains.** A query storm or lock in service A's DB must
  not degrade service B. Separate instances (or at least separate databases with
  separate credentials) contain the blast radius.
- **Independent scaling.** A write-heavy service and a read-heavy one want
  different instance shapes, replica topologies, and IOPS. Shared DB forces a
  lowest-common-denominator.
- **Clear ownership + safe migrations.** If two services write the same tables,
  neither can migrate schema without coordinating with the other — migrations
  become cross-team negotiations. One-DB-per-service makes the owning pipeline
  the sole writer of its schema.
- **Least-privilege credentials.** Each app gets a role scoped to its own DB.
  A leaked credential exposes one service's data, not the whole estate.
- **Data coupling is forced through APIs, not the DB.** If service B needs
  service A's data, it calls A's API. This keeps the service boundary real
  instead of quietly eroding into a shared-table monolith.

The cost — no cross-service JOINs, eventual consistency across services — is
accepted deliberately; it's the price of decoupling.

In this submission there is one app and therefore one database; the structure
(dedicated DB, scoped role, app-owned migrations) is already what each service
in a multi-service estate would get.

---

## 5. Database schema & migrations

- Schema lives in [`migrations/`](migrations/) as ordered, plain `.sql` files.
- Every migration is **idempotent** (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX
  IF NOT EXISTS`) and **backward compatible** — additive changes only in a given
  release (add column/table/index; never drop-in-place in the same deploy that
  ships code depending on the change).
- **Expand → migrate → contract** for breaking changes: add the new shape, ship
  code that writes both / reads new, backfill, then remove the old shape in a
  *later* release once no running code needs it. This is what lets rolling
  deploys and rollbacks stay safe.
- In dev the app applies migrations on startup for zero-step parity; in prod the
  pipeline runs the same SQL as the dedicated stage in §3 so schema changes are
  auditable and decoupled from app boot.

---

## 6. Rollback approach

**Two independent axes, because code and data roll back differently.**

**Code rollback — fast and boring.**
- Images are tagged by immutable git SHA. Rollback = redeploy the previous SHA;
  no rebuild, no waiting on CI.
- Rolling strategy means the old version's replicas are only drained after the
  new ones pass `/health`. If the new version fails its health/canary check,
  post-deploy verify aborts and leaves the old replicas serving — a failed
  deploy is a no-op, not an outage.
- Keep the last N images in the registry so rollback targets always exist.

**Data / schema rollback — avoided by design, not by "down" migrations.**
- Because migrations are additive and backward compatible (§5), the previous
  code version keeps working against the new schema. So a **code** rollback
  needs **no** schema rollback — the usual rollback is code-only.
- Destructive changes only ship in a later release after the old code is fully
  gone (contract phase). This means we rarely need to reverse a migration under
  pressure.
- For genuine data corruption: point-in-time recovery from automated backups /
  WAL, restored to a new instance, then repoint. Reversing a migration on a live
  primary is the last resort, not the plan.

**One line to remember:** roll code back freely; never let a rollback depend on
reversing a migration.

---

## 7. Security choices

**Network / edge**
- Only Nginx is public; app and DB live on a private network/subnet.
- TLS terminated at the edge; HTTP only on the private hop.
- `server_tokens off`, bounded body size and timeouts, rate limiting at the edge.

**Container**
- Multi-stage build → slim runtime image (smaller = fewer CVEs, faster pulls).
- Runs as a **non-root** user (`appuser`, uid 10001).
- Only the venv + source are copied in; build tooling stays in the builder stage.
- Image + dependency scanning is a pipeline gate (§3).
- `HEALTHCHECK` in the image so the orchestrator can detect and replace sick
  containers.

**Secrets & config**
- No secrets in the image or repo. `.env` is git-ignored; only `.env.example`
  (placeholders) is committed.
- Config is 12-factor: same image everywhere, behavior set by injected env. In
  prod, secrets come from a secrets manager (SSM / Secrets Manager / Vault), not
  a `.env` file on disk.

**Database**
- Least-privilege, per-service role scoped to its own database (§4).
- Never internet-exposed; reachable only from the app subnet.
- Automated backups + PITR enabled (see §6).

**Application**
- All input validated by Pydantic models before it reaches SQL.
- **Parameterized queries everywhere** — no string-built SQL, so no injection.
- `/health` returns booleans only; it never leaks connection strings, versions,
  or stack traces.

**What's deliberately out of scope for this demo** (but named so it's a
conscious omission, not an oversight): authn/authz on the API, WAF, mTLS between
tiers, and audit logging. In production these sit at the Nginx edge and in the
app's middleware.
