# Deployment notes

The reasoning behind how this is set up — what I chose and why. Kept short on
purpose; the READMEs cover the how-to.

## The shape of it

Two EC2 boxes and one database. One box runs both apps behind Nginx; the other
runs Jenkins and deploys to the first over SSH. The database is managed RDS
Postgres, sitting in a private subnet where only the app box can reach it.

Everything is Terraform (`serviot-terraform/`), so the whole thing is
reproducible and nothing was clicked together by hand.

## Instance sizing

I started small and let the workload argue for more, rather than guessing big.

- **App box — t3.medium (2 vCPU / 4 GB).** It runs two containerised apps plus a
  host Nginx. Both apps are I/O-bound (short DB round-trips), not CPU-bound, so
  this is comfortable. If traffic grew I'd add replicas before a bigger box.
- **Jenkins box — t3.small.** CI is bursty and only runs on a push. Keeping it
  off the app box matters more than its size: a heavy build can't starve the
  running apps if it's on its own instance.
- **RDS — db.t3.small, gp3.** The database is the hardest tier to scale sideways,
  so it gets the most breathing room and encrypted gp3 storage with autoscaling
  headroom.

Splitting Jenkins from the apps is the main sizing decision — separate failure
and load domains beat one larger shared box.

## Nginx

One Nginx on the app box, two `server` blocks keyed by hostname —
`crud.clothentic.in` and `mern.clothentic.in`. Each proxies to its app on a
different localhost port (8000 and 5000). The apps bind to `127.0.0.1` only, so
the single public surface is Nginx. TLS is per-subdomain via Let's Encrypt, and
port 80 just redirects to 443.

Two apps, one proxy, no port clashes, and cross-cutting concerns (TLS, headers,
timeouts) live in config instead of app code.

## Pipelines — one per app

Each app owns its own `Jenkinsfile` in its own repo, so they ship on their own
schedule and one app's red build never blocks the other. A GitHub push triggers:

**build → test → deploy → health check → rollback if unhealthy.**

Deploys are git-based: Jenkins SSHes in, the box pulls the new commit and
rebuilds with Docker Compose. App 2 also runs `prisma migrate deploy` before the
new container comes up, so schema changes land in order.

## Database separation

Both apps are Postgres, so they share **one RDS instance but with two separate
databases** (`serviot_app1`, `serviot_app2`), each owned by its own login role
that can't see the other's data.

One instance instead of two is a deliberate cost/simplicity call. The isolation
that actually matters — separate data, separate credentials, independent
migrations — is there at the database and role level. What I'm trading away is
independent failover and separate connection budgets; the day either app needs
that, it's a small Terraform change to split them.

The database is never a container and never public — private subnet, reachable
only from the app box's security group.

## Rollback

Rollback is tied to the health check, not to reversing migrations. Before
switching, the pipeline records the current commit. It deploys, then checks
health — App 1 must return 200 from `/health`, App 2 must respond on its port,
both within about 30 seconds. If that fails, the box resets to the recorded
commit and redeploys the last-known-good build. A bad deploy heals itself
instead of leaving the site down.

Migrations are written to be backward compatible, so rolling the code back
doesn't require unwinding the schema — the previous code still works against it.

## Security choices

- **Network:** only 443/80 are public on the app box; the apps listen on
  localhost behind Nginx; RDS is private and only the app box can reach 5432;
  SSH is limited to my IP plus the VPC (for Jenkins to deploy).
- **Secrets:** nothing real is committed. `.env`, Terraform state and tfvars,
  and the SSH/JWT keys are all gitignored; the app box holds its own `.env` that
  deploys never overwrite; DB passwords and JWT keys are injected as environment,
  not baked into images. Verified with gitleaks across both repos' history.
- **Least privilege:** the reviewer's IAM user is hand-scoped to read-only
  describe/log calls — not the broad managed ReadOnlyAccess. DB roles are scoped
  per app the same way. Containers run as a non-root user.
- **Jenkins:** on a non-default port; reviewer gets a view-only account via
  matrix security; pipeline credentials come from the credential store and are
  masked in logs.

## Honest gaps

- Jenkins UI is currently reachable from anywhere (so GitHub webhooks work) —
  fine for a demo, but I'd put it behind an IP allowlist or a proxy for real use.
- Automated RDS backups are wired in Terraform but left off by default to keep
  teardown clean; flip `enable_backups = true` for production.
