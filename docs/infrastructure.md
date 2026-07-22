# Infrastructure & DevOps Specification
# DamDam — Version 0.1

> **Scope note:** This document covers MVP infrastructure only —
> a single OCI instance, Saudi Arabia launch, Hajj 2027 timeline.
> For the post-MVP multi-region architecture, global payments
> strategy (Stripe/Adyen alongside Paystack), and AI-assisted
> development tooling split, see
> [`scaling-infrastructure.md`](./scaling-infrastructure.md).
> That document also recommends a **specific launch region (OCI
> Jeddah or UAE)** based on VoIP latency considerations — more
> specific than the unspecified-region plan below, and worth
> confirming free-tier availability against before finalizing.

## 11.1 Environment Definitions

| Environment | Purpose | Infrastructure |
|---|---|---|
| Local | Individual developer machines | Docker Compose, full stack runs locally including Postgres/Redis containers |
| Staging | Pre-production testing, HTO pilot demos | Separate OCI free-tier account (fully isolated from production, avoiding any risk of test data touching real pilgrim records) |
| Production | Live pilgrim and HTO traffic | OCI (2 OCPU/12GB), self-hosted Postgres in Docker (see §11.3 — matches Local exactly, no managed DB service), Cloudflare (Tunnel, Workers, R2, Email Routing) |

---

## 11.2 Hosting Architecture

```
                    ┌─────────────────────┐
                    │   Cloudflare Edge     │
                    │  (DNS, WAF, Tunnel)   │
                    └──────────┬────────────┘
                               │
            ┌──────────────────┼──────────────────┐
            │                                       │
   ┌────────▼─────────┐                  ┌─────────▼─────────┐
   │ Cloudflare Workers │                  │  Cloudflare Tunnel │
   │  (Next.js HTO/      │                  │  (outbound only)    │
   │   Admin Dashboard)   │                  └─────────┬─────────┘
   └─────────┬────────────┘                            │
             │  calls same API                         │
             └───────────────────┬────────────────────┘
                                  │
                       ┌──────────▼──────────┐
                       │   OCI Ampere A1       │
                       │  (2 OCPU / 12GB)      │
                       │                        │
                       │  ┌──────────────────┐ │
                       │  │  FastAPI (api)     │ │
                       │  └────────┬───────────┘ │
                       │           │              │
                       │  ┌────────▼───────────┐ │
                       │  │  Postgres            │ │
                       │  │  (self-hosted; auth  │ │
                       │  │  is custom-built in  │ │
                       │  │  FastAPI, not a      │ │
                       │  │  managed auth        │ │
                       │  │  service — see        │ │
                       │  │  api-spec.md §7.1)   │ │
                       │  └────────┬───────────┘ │
                       │           │              │
                       │  ┌────────▼───────────┐ │
                       │  │  Redis               │ │
                       │  └────────┬───────────┘ │
                       │           │              │
                       │  ┌────────▼───────────┐ │
                       │  │  Celery worker(s)    │ │
                       │  └──────────────────────┘ │
                       │                        │
                       │  ┌──────────────────┐ │
                       │  │ cloudflared         │ │
                       │  │ (tunnel daemon)      │ │
                       │  └──────────────────┘ │
                       └────────────────────────┘

   External services (not hosted by DamDam):
   Paystack/Flutterwave │ Termii/Twilio │ Telnyx │
   Monty Mobile/eSIM Access/1Global │ WhatsApp Business API │
   Resend │ Apple/Google push services
```

**React Native mobile app (iOS + Android):** distributed via
Google Play Store and Apple App Store, no server-side hosting
component beyond the API it calls.

---

## 11.3 Docker Compose — Production Reference

**Implementation status (July 2026):** the executable source is now
[`/docker-compose.yml`](../docker-compose.yml). The block below is the original
six-service architecture sketch; the root file is authoritative and now has a
seventh `walg` backup companion. During
extraction, four omissions in this sketch were corrected rather than copied:
`depends_on` now waits for healthy Postgres/Redis instead of only container
startup, Postgres and Redis have real health checks, Redis uses AOF persistence,
and the API/worker/beat receive container-network database and Redis URLs. The
root file also gives all three Python services the same commit-tagged image so
deployment rollback can atomically restore the prior application version.
The production Postgres image includes WAL-G because `archive_command` runs
inside the database container; the separate `walg` container uses that same
image and data volume for daily physical base backups and retention.

For local validation, copy `compose.env.example` to an untracked environment
file or pass it with `docker compose --env-file compose.env.example ...`.
Production and staging use `.env.production` and `.env.staging` respectively on
their hosts; neither file is committed.

```yaml
services:
  api:
    build: ./apps/api
    restart: unless-stopped
    depends_on: [postgres, redis]
    env_file: .env.production
    deploy:
      resources:
        limits:
          memory: 2G
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    networks: [damdam]

  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    volumes:
      - postgres_data:/var/lib/postgresql/data
    env_file: .env.production
    deploy:
      resources:
        limits:
          memory: 1.5G
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    networks: [damdam]
    # Self-hosted, not a managed service (e.g. Supabase) — matches
    # the Local environment exactly (§11.1), removing any future
    # "migrate to self-hosted at scale" step. Auth is custom-built
    # in FastAPI (api-spec.md §7.1), so no managed auth layer is
    # needed here either. Backup strategy: §11.7's WAL-G continuous
    # archiving to R2, run from day one — not a plain pg_dump cron.

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    volumes:
      - redis_data:/data
    deploy:
      resources:
        limits:
          memory: 512M
    networks: [damdam]

  worker:
    build: ./apps/api
    command: ["celery", "-A", "app.worker", "worker", "--loglevel=info"]
    restart: unless-stopped
    depends_on: [postgres, redis]
    env_file: .env.production
    deploy:
      resources:
        limits:
          memory: 1G
    networks: [damdam]
    # Handles all background/async jobs described across the
    # feature specs in prd.md §5:
    #   - eSIM issuance + retry (§5.4)
    #   - WhatsApp dispatch, rate-limited (§5.2, §5.6)
    #   - Usage polling, 15-min interval (§5.7)
    #   - SOS/check-in notification fan-out + retry (§5.6)
    #   - Daily FX pricing job, 09:00 WAT cron (§5.9)
    #   - Manifest bulk-provisioning job (§5.2)

  beat:
    build: ./apps/api
    command: ["celery", "-A", "app.worker", "beat", "--loglevel=info"]
    restart: unless-stopped
    depends_on: [postgres, redis]
    env_file: .env.production
    deploy:
      resources:
        limits:
          memory: 256M
    networks: [damdam]
    # Celery Beat: the scheduler process for periodic tasks
    # (daily FX pricing job, usage polling cadence). Separated
    # from the worker process per Celery's standard pattern —
    # a single beat instance prevents duplicate scheduled task
    # firing if worker replicas are ever scaled beyond one.

  tunnel:
    image: cloudflare/cloudflared:latest
    restart: unless-stopped
    command: tunnel run
    environment:
      TUNNEL_TOKEN: ${CF_TUNNEL_TOKEN}
    networks: [damdam]

networks:
  damdam:
    driver: bridge

volumes:
  postgres_data:
  redis_data:
```

**Seven containers in production:** `api`, `postgres`, `walg`, `redis`,
`worker`, `beat`, `tunnel` — Postgres added as a self-hosted
container rather than a managed service (Supabase was considered
and dropped; see the reasoning this replaced, previously in this
section, now superseded). Total memory footprint at idle is
roughly 2.5–3GB, still leaving comfortable headroom on the 12GB
instance. Celery with Redis as the broker is the standard FastAPI
pairing — introduced explicitly here rather than discovered
mid-build, since Section 5 of the PRD describes multiple async
jobs that don't belong crammed into the request-response cycle of
the API service itself.

---

## 11.4 CI/CD Pipeline (GitHub Actions)

**On every PR (`ci.yml`):**
```yaml
- Lint (ruff for Python, eslint for TypeScript)
- Type-check (mypy for Python, tsc for TypeScript)
- Unit tests (pytest, jest)
- Build check (does the Docker image build successfully)
- Export OpenAPI spec from FastAPI, diff against committed
  docs/api-spec.yaml — fails the check if they've drifted,
  keeping the human-readable api-spec.md and the generated
  spec honest against each other
```

**On merge to `develop`:**
```yaml
- All of the above, plus:
- Validate that the separate `staging` GitHub Environment contains
  STAGING_OCI_HOST, STAGING_OCI_DEPLOY_USER, STAGING_OCI_SSH_KEY, and
  STAGING_API_BASE_URL; fail with a named missing-secret error until it does
- SSH deploy the commit-tagged six-service Compose stack to staging
- Poll the dependency-aware `/health` readiness endpoint
- Restore the prior application image if deploy/readiness fails and a prior
  staging release exists (the first bootstrap has no prior image)
```

**On merge to `main` (production release):**
```yaml
- All of the above, plus:
- Tag release (semver, driven by Conventional Commits)
- SSH deploy to OCI production instance:
    - fetch and detach at the exact `origin/main` commit
    - tag the currently running application image with its source commit
    - build the target commit-tagged image
    - docker compose up -d (rolling restart; brief downtime
      acceptable at MVP scale — zero-downtime deploys are a
      post-MVP concern, not Kubernetes territory yet)
    - run Alembic migrations
    - dependency-aware health check (`/health`) before marking deploy
      successful
    - on deploy, migration, or readiness failure, restore the previous
      commit-tagged API/worker/beat image and source checkout, verify readiness,
      and fail the workflow visibly
```

Application rollback intentionally does **not** run `alembic downgrade`: an
automatic schema downgrade can destroy data and is less trustworthy than
requiring backward-compatible migrations. Every production migration must
therefore remain compatible with the previous application release. If a failed
release requires a data/schema restore, stop automation and use §11.7's backup
recovery procedure. The very first production Compose bootstrap is also a
manual Ibrahim-owned operation: the workflow refuses to deploy without a
running/prior image it can tag as a rollback target.

**Mobile app release — two parallel tracks, both built via EAS
(see §11.9 for why EAS rather than local/runner-side compilation):**

```yaml
# Android track (eas build --platform android)
- EAS Build compiles a signed AAB on Expo's cloud infrastructure
- eas submit uploads to Google Play Console
  - Internal testing track → pilot HTOs
  - Production track → public launch

# iOS track (new — added scope from the dual-platform decision)
- EAS Build compiles a signed IPA, no local or CI-runner macOS
  needed — resolves the founder's Windows/Linux local machine
  constraint (§11.9.1), requires:
    - Apple Developer Program enrollment (see §11.8 for cost)
    - Credentials configured once via `eas credentials`
      (EAS manages provisioning profiles/signing, stored against
      the Expo account rather than Fastlane Match)
- eas submit uploads to TestFlight → pilot HTOs
- Submit for App Store review → production
  - Budget real buffer here: App Store review timing is less
    predictable than Google Play's, and a rejection late in the
    7-month runway (prd.md §6) is a genuine schedule risk —
    submit the first build for review well before the February
    HTO-onboarding deadline, not right up against it
```

---

## 11.5 Monitoring & Alerting

| Metric | Tool | Alert threshold |
|---|---|---|
| API uptime/health | Self-hosted Uptime Kuma sending `GET https://api.damdam.app/health` (readiness, not a liveness-only route) | 2 consecutive failed checks (Kuma's own configurable retries), Telegram notification on the Down/Up transition |
| API process liveness | Container health diagnostics can use `/health/live` when dependency state must be excluded | Restart/inspect only when the process itself is unresponsive; dependency outages are reported by readiness instead |
| WAL-G backup completion | Self-hosted Uptime Kuma, push/heartbeat monitor called by `docker/postgres-walg/backup-loop.sh` on each successful `wal-g backup-push` | No heartbeat within ~30 hours of the last one (daily backups have a 24h cadence; the ~6h slack absorbs normal timing jitter without false alarms) |
| Error rate | PostHog Error Tracking (free tier), covering the FastAPI backend and both React Native app builds | Alert on an error-rate spike, not absolute count |
| Failed SOS notifications | Direct DB query, surfaced in Admin Dashboard (Failed Notification Queue) — doubles as both the fix screen and the monitoring signal | Real-time, visible on the screen itself |
| Celery worker/beat health | `docker stats` + `restart: unless-stopped` | Container restart loops flagged via Uptime Kuma detecting sustained task backlog symptoms (e.g., stale usage_polls) |
| OCI instance resource usage | OCI's built-in monitoring console | Alert if sustained >85% memory or CPU |
| Postgres health/disk usage | OCI's built-in monitoring console + `docker stats` on the `postgres` container | Alert if disk usage sustained >80% of allocated volume, or connection count approaching pool limits |
| App Store / Play Store crash reports | Native platform crash reporting (Play Console, Xcode Organizer / App Store Connect) alongside PostHog | Review both — platform-native reports can surface issues a cross-platform SDK misses |

**Why PostHog rather than Sentry:** this is a deliberate
consolidation decision. PostHog provides dedicated error tracking
now and can provide mobile/product analytics later through the same
SDK and project, avoiding a second analytics vendor and integration;
its free tier is also more generous for the expected MVP volume.
The trade-off is real: PostHog's dedicated error-tracking UI is less
mature than Sentry's, and PostHog has a documented incident history,
including a [February 2026 US Logs database-corruption incident](https://isdown.app/status/posthog-us/incidents/538631-logs-ingestion-delayed-in-us-cloud)
that caused customer log data loss. That incident affected the newer,
isolated Logs product rather than analytics events or replays, but it
is still relevant evidence about operational maturity and is an
accepted consolidation trade-off, not a risk to omit from the vendor
record. Keep native Play Console and App Store Connect crash reports
enabled as an independent signal.

**PostHog configuration:** create one PostHog Cloud project in the
chosen data-residency region, enable Error Tracking in that project's
settings, and copy its project API key into `POSTHOG_API_KEY`. Set
`POSTHOG_HOST` to the matching ingestion host
(`https://us.i.posthog.com` or `https://eu.i.posthog.com`). The API
reads both values at runtime from `.env.production`; mobile release
builds read the same names at bundle time. Blank keys deliberately
disable capture in local and test environments. Placeholder values
are recorded in `compose.env.example`, `apps/api/.env.example`, and
`apps/mobile/.env.example`; never commit Ibrahim's real value.

**Why self-hosted Uptime Kuma rather than UptimeRobot:** a single
tool covers both monitoring needs this document lists above (API
readiness *and* the WAL-G backup heartbeat, the latter a genuinely
new capability UptimeRobot's free tier has no equivalent for — it
has no push/heartbeat monitor type), at zero incremental cost, on
infrastructure the team is already comfortable self-hosting given
this session's WAL-G/Postgres/Compose work. UptimeRobot's free tier
was the original MVP plan and remains a reasonable fallback if
Hermes (below) ever becomes unavailable, but Kuma's push-monitor
type is the deciding factor: UptimeRobot can only poll a URL, it
cannot receive a heartbeat, so it structurally cannot cover the
backup-completion signal at all.

**Deployment — isolation is the non-negotiable requirement.** Kuma
runs on Hermes (`88.96.53.229`, the founder's existing Ampere A1
host — `scaling-infrastructure.md` §12.1), a separate host from
DamDam's own API/Postgres/Redis stack, not a container alongside
them. **Monitoring must never share a host with the thing it
monitors** — this is a known, well-documented failure pattern (the
monitor going dark in exactly the same outage it exists to catch,
rather than surviving to report it), not a stylistic preference.
Concretely on Hermes:

- Own Docker container (`uptime-kuma`, image `louislam/uptime-kuma:1`),
  its own bridge network (not `network_mode: host`, unlike the
  `hermes` gateway container), and its own bind-mounted volume
  (`/opt/kuma-data`) for its embedded SQLite database — no shared
  state with Hermes' existing 5 services (the `hermes` gateway
  container, `hermes-vnc`, `hermes-voice-relay`, `hermes-xvfb`, and
  `tailscaled`).
- Published **only** on Hermes' Tailscale interface
  (`100.72.59.74:3001`), not on the public interface
  (`88.96.53.229`) and not behind new public DNS/TLS. Hermes is
  already on Ibrahim's tailnet (confirmed via `tailscale status`
  listing both `hermes` and his phone), so this reaches the
  dashboard privately with zero new infrastructure — deliberately
  not a Cloudflare Tunnel hostname, since none of Hermes' existing
  services use one and adding one is unjustified extra surface area
  for an internal-only dashboard.
- **Access for Ibrahim:** `http://100.72.59.74:3001` from any device
  on the tailnet. To add a further monitor later: log in, "Add New
  Monitor," pick a type (HTTP(s), Keyword, Push, etc.) — no
  redeploy needed, Kuma's own UI is the ongoing interface.

**What's configured:**

1. **`DamDam API readiness`** — HTTP(s)-Keyword monitor, `GET
   https://api.damdam.app/health`, keyword `"status":"ready"` (the
   real field the endpoint returns — not `"status":"ok"`, which was
   never what `app/health.py`'s `ReadinessResponse` actually sends;
   corrected here rather than propagated forward). 60-second
   interval, 2 retries at 30-second spacing before Down is
   confirmed. Do not use `/health/live`. This monitor will
   legitimately show Down/Pending until production (and later
   staging) actually resolve — that's accurate, not a
   misconfiguration, until deployment happens.
2. **`WAL-G backup heartbeat`** — Push monitor. `backup-loop.sh`
   calls its push URL after every successful `wal-g backup-push`
   (`KUMA_PUSH_URL` in `docker-compose.yml`/`compose.env.example`,
   optional and a no-op when unset, e.g. in local/dev/test).
   Heartbeat window set to 30 hours against a 24-hour backup
   cadence — deliberately more than 24h so ordinary timing jitter
   never false-alarms, deliberately less than 48h so a genuinely
   silently-dead backup loop is caught well before a second cycle
   would also be missed.
3. **Notification channel: Telegram**, reusing the same
   `TELEGRAM_BOT_TOKEN`/`TELEGRAM_HOME_CHANNEL` already configured
   and in active use on Hermes for the `hermes` gateway's own
   messages to Ibrahim — not a new credential. Email/SMTP was the
   original plan, but no SMTP or transactional-email credential
   exists anywhere on Hermes or in DamDam's committed config (only
   placeholders in `apps/api/.env.example`'s Resend variables);
   Telegram is real, already working, and already how Ibrahim
   receives messages from this same host, so it was used instead
   of blocking on a new credential he'd have to supply. Adding a
   second (e.g. email) notification method later is a five-minute
   change in Kuma's own UI once real SMTP credentials exist.

Failed SOS notifications remain owned by the existing Admin
Dashboard Failed Notification Queue. Celery worker/beat health
remains `docker stats` plus container restart behavior, OCI resource
usage remains in the OCI console, and Postgres health/disk usage
remains OCI-console-native plus `docker stats`; none of those signals
belongs in this application integration.

**Hajj-season-specific monitoring note:** During the actual travel
season (May 2027), tighten alert thresholds and increase check
frequency — this is the one period where downtime has the highest
real-world consequence.

---

## 11.6 Secrets Management

- `.env.production` lives only on the OCI instance, never
  committed, `chmod 600`, owned by the deploy user only
- GitHub Actions secrets (CI/CD deploy credentials, Cloudflare
  Tunnel token, SSH key, **Apple App Store Connect API key**,
  **Google Play service account JSON**) stored in GitHub's
  encrypted repository secrets, scoped to protected-branch deploy
  workflows only
- Rotation policy: Termii, Twilio, Telnyx, Paystack, and
  Flutterwave API keys rotated every 90 days as baseline hygiene;
  immediate rotation on any suspected exposure
- No secrets baked into Docker image layers — environment
  variables at runtime only
- WAL-G uses a dedicated Cloudflare R2 bucket and credentials, separate from
  any application object-storage identity: `WALG_R2_BUCKET`,
  `WALG_R2_PREFIX`, `WALG_R2_ENDPOINT`, `WALG_R2_REGION`,
  `WALG_R2_ACCESS_KEY_ID`, and `WALG_R2_SECRET_ACCESS_KEY`. The R2 token must
  be scoped only to read/write the backup bucket. The committed
  `compose.env.example` values are placeholders; Ibrahim creates the bucket
  and injects real staging/production values into their host-only env files.

---

## 11.7 Backup & Disaster Recovery

**Implementation status (July 2026): implemented and restore-tested.** The
custom multi-architecture Postgres image in `docker/postgres-walg/` pins WAL-G
v3.0.8, while the executable root Compose file applies
`archive_mode=on`, `archive_command=wal-g wal-push %p`, and
`archive_timeout=60s`. The adjacent `walg` service takes a physical
`backup-push` immediately when it starts and every 86,400 seconds thereafter.
After each successful base backup it runs WAL-G's native
`delete retain FULL 1 --after <30-day-cutoff> --confirm`, which removes older
base backups and obsolete WAL while retaining at least one usable full backup
chain. There is no custom R2 object-pruning code.

| Data | Backup method | RPO | Retention |
|---|---|---|---|
| Postgres | **WAL-G** — continuous WAL archiving to Cloudflare R2, plus a daily base backup, run from day one (self-hosted from the start, no managed-service phase to migrate away from — see §11.2/§11.3) | ~1 minute (governed by `archive_timeout`), true point-in-time recovery — not "nearest snapshot" | 30 days, pruned automatically by WAL-G's retention policy |
| R2-stored files | R2's own durability | N/A | N/A |
| Docker Compose configuration | Version-controlled in GitHub | N/A | Indefinite |

**Why WAL-G over `pg_dump`, decided rather than deferred:** an
earlier draft of this section planned daily `pg_dump` with a
same-day tradeoff note flagging its up-to-24-hour RPO as a known
risk to revisit "before Hajj season." That gap has been closed
directly instead of deferred — WAL-G is a single additional
lightweight process (no new vendor, no new environment), and given
this system handles safety-critical check-in/SOS data, closing a
known data-loss risk now is worth the modest setup cost rather than
carrying it as accepted debt into the highest-stakes period.

**Implemented shape:**
1. Postgres config: `archive_mode = on`, `archive_command` set to
   WAL-G's push command, targeting an R2 bucket via WAL-G's native
   S3-compatible storage support
2. `archive_timeout` set to 60s — bounds the worst-case RPO to
   roughly one minute of uncommitted-to-archive data, not hours
3. A daily `wal-g backup-push` gives WAL-G a base backup to replay
   forward from — this is a *physical* base backup (via
   `pg_basebackup` semantics), a different mechanism from the
   logical `pg_dump` approach this replaces, not just "the same
   thing run more often"
4. Recovery: restore the latest base backup, replay archived WAL
   segments from R2 up to any target timestamp
   (`recovery_target_time`) — genuine point-in-time recovery to any
   moment, not just the nearest scheduled dump
5. WAL-G runs as a lightweight process alongside the `postgres`
   container (§11.3), using the same image and Postgres data volume — it is
   not separately provisioned infrastructure

`scripts/test-walg-pitr.sh` is the executable disaster-recovery proof. Its
local/CI-only Compose overlay starts MinIO as an S3-compatible R2 substitute,
asserts the three live Postgres settings, takes a real physical base backup,
waits for a low-traffic segment to be archived by the 60-second timeout,
deletes the isolated Postgres volume, fetches the latest base backup, replays
WAL to a recorded `recovery_target_time`, and verifies both sides of the PITR
boundary: a post-backup/pre-target row exists and a post-target row does not.
Run it from the repository root with `./scripts/test-walg-pitr.sh`. Its
committed MinIO credentials are deliberately fake and local-only.

**Incident restore runbook (production):**

**Volume naming is guaranteed, not assumed:** every command below that
names `damdam_postgres_data` relies on the top-level `name: damdam` key in
`docker-compose.yml` (present since the deploy pipeline's introduction),
which pins the Compose project name for every invocation of this file
regardless of the working directory's basename. Production and staging both
happen to deploy from a directory literally named `damdam` (`/opt/damdam`,
per `deploy.yml`/`ci.yml`'s `cd /opt/damdam`), so the two would agree even
without this key — but the `name:` key is what makes that agreement a
guarantee instead of a coincidence one directory rename away from breaking.
If a future change ever restructures the deploy layout, confirm the actual
volume name first with `docker volume ls | grep postgres_data` rather than
trusting this document blindly.

1. **Determine the recovery target and stop traffic.** This is the single
   highest-consequence decision in this procedure — recovering too early
   silently discards legitimate pilgrim data (check-ins, SOS events,
   payments) that were committed after the target; recovering too late may
   restore the corruption or incident itself. Do not guess; triangulate from
   at least two independent signals before committing to a timestamp:
   - **Application error signal:** check PostHog Error Tracking (§11.5) for
     the first occurrence of whatever error/anomaly triggered this incident
     — its first-seen timestamp is a strong upper bound on "last known good."
   - **Uptime/availability signal:** cross-reference Uptime Kuma's (§11.5)
     alert history for when `/health` first started failing or degrading, if
     the incident correlates with an outage rather than silent corruption.
   - **WAL archive bound:** recovery cannot go past the last successfully
     archived segment. Confirm what's actually available and gap-free with
     `docker compose --env-file .env.production run --rm --no-deps walg wal-g wal-verify integrity timeline --json`
     before committing to a target near the current time — this surfaces
     archive gaps or timeline mismatches that `backup-list` alone won't
     show. A clean result looks like
     `{"integrity":{"status":"OK",...},"timeline":{"status":"OK",...}}`;
     anything else means the WAL chain has a hole before it, and the
     recovery target must be chosen to land before that hole, not after it.
   - If the incident's actual start time is still ambiguous after checking
     the above, prefer the earlier candidate timestamp: a small amount of
     legitimate lost data is recoverable from the affected pilgrim/HTO
     directly if needed; recovering into the incident is not.

   Record the chosen timestamp in UTC, then stop all traffic/writers:
   `docker compose --env-file .env.production stop tunnel api worker beat walg postgres`.

   **Preserve the damaged volume before changing anything** — never destroy
   the only copy during diagnosis. This copies the live damaged volume into a
   separate, independently named Docker volume that nothing else references:
   ```
   snapshot_ts="$(date -u +%Y%m%dT%H%M%SZ)"
   docker volume create "damdam_postgres_data_incident_${snapshot_ts}"
   docker run --rm \
     -v damdam_postgres_data:/from:ro \
     -v "damdam_postgres_data_incident_${snapshot_ts}:/to" \
     alpine cp -a /from/. /to/
   ```
   Confirm the copy actually has content (`docker run --rm -v "damdam_postgres_data_incident_${snapshot_ts}:/d" alpine ls /d` should show `base`, `pg_wal`, etc.) before proceeding — an empty snapshot is worse than no snapshot, because it creates false confidence that a rollback path exists.
2. Confirm `.env.production` contains the dedicated WAL-G R2 values and that
   the target is within the 30-day retention window. Inspect available backups
   with `docker compose --env-file .env.production run --rm --no-deps walg wal-g backup-list`.
3. After the damaged volume has been preserved and confirmed non-empty, and
   the incident commander has approved replacement, run
   `docker compose --env-file .env.production rm -f postgres walg`, then
   `docker volume rm damdam_postgres_data` and
   `docker volume create damdam_postgres_data`. These commands replace only
   the Compose Postgres volume and make the restore destination empty. Do not
   run the helper against a non-empty directory; it refuses that condition
   deliberately.
4. Prepare PITR with
   `docker compose --env-file .env.production run --rm --no-deps walg walg-restore 2026-07-19T21:15:00Z`.
   Omit the timestamp only when the incident decision is to replay all
   available WAL. This fetches `LATEST`, writes
   `restore_command='wal-g wal-fetch %f %p'`, creates `recovery.signal`, and
   configures promotion at the target.
5. Start only Postgres, follow its logs through recovery, and validate the
   selected business records and `SELECT pg_is_in_recovery()` (must be false):
   `docker compose --env-file .env.production up -d postgres` followed by
   `docker compose --env-file .env.production logs -f postgres`.
6. Once the incident owner accepts the recovered boundary, run
   `docker compose --env-file .env.production up -d redis api worker beat walg`,
   verify `/health`, and only then start `tunnel` to reopen traffic. Retain the
   preserved damaged volume until the incident review is complete.

The code and MinIO proof are real; the production R2 bucket, restricted token,
host env values, and first live restore drill still require Ibrahim. No real
Cloudflare credentials or production data are present in this repository.

**Disaster recovery target:** For MVP, an acceptable RTO (time to
actually restore and be back online) is a few hours — not a system
requiring 99.99% uptime guarantees at pilot scale. The RPO
improvement above (WAL-G) is a separate, already-closed concern
from RTO; RTO specifically is still worth revisiting explicitly
before Hajj season 2027, when real uptime during a two-week window
carries real safety weight.

---

## 11.8 Cost Summary (Monthly, at MVP/Pilot Scale)

| Line item | Cost |
|---|---|
| OCI Always Free (2 OCPU/12GB) | $0 |
| Cloudflare (Workers paid tier if free limits exceeded) | $0–5 |
| Cloudflare R2 | $0 (within free tier at MVP volume) |
| Uptime Kuma | $0 (self-hosted on Hermes, existing infrastructure — no new hosting cost) |
| PostHog | $0 (free tier sufficient for MVP error tracking and initial product analytics) |
| Resend | $0 (within 3,000 emails/month free tier) |
| **Fixed infrastructure subtotal** | **~$0–5/month** — Postgres self-hosted on the already-free OCI instance means no managed-DB line item at all |
| Apple Developer Program | **$99/year (~$8.25/month amortised)** — new line item from dual-platform decision |
| Google Play Developer account | $25 one-time (not recurring) |
| Termii (usage-based) | Variable — scales with OTP send volume (primary provider) |
| Twilio (usage-based) | Variable — scales with secondary-provider OTP failover volume and Telnyx-independent Verify usage; expected low relative to Termii given it's a fallback |
| Telnyx (usage-based) | Variable — scales with call volume (voice/PSTN termination) |
| Paystack (transaction fees) | Variable — 1.5% + ₦100 per transaction, passed through in the pricing model |
| Flutterwave (transaction fees) | Variable, comparable fee structure to Paystack — automatic fallback only (`data-model.md` §6.7), so actual cost impact is near-zero in normal operation; budgeted here for completeness, not because meaningful volume is expected to route through it |
| Monty Mobile + eSIM Access + 1Global (usage-based, three-way redundancy per `data-model.md` §6.6) | Variable — scales with eSIM issuance volume |
| WhatsApp Business API | Variable — per-conversation pricing after free tier |
| Expo EAS Build | Free tier: 30 builds/month on the shared queue — likely sufficient at MVP build frequency; EAS Production plan (~$99/month) only needed if build volume or priority-queue speed becomes a bottleneck — start free, upgrade if it's actually limiting |

---

## 11.9 Development Environment — Kept Deliberately Simple

**This section exists because the founder's local machine is
Windows/Linux, not macOS.** An earlier draft of this section
over-reached on the fix — recommending the full Expo framework and
a dedicated third OCI cloud instance for active development. Both
were reconsidered and simplified; this is the corrected version.

### 11.9.1 The Mac constraint — solved narrowly, not by adopting a framework

Building an iOS app requires Xcode, which only runs on macOS, even
when targeting a physical device rather than the simulator — there
is no way around this for compilation specifically. But the fix
doesn't require adopting the Expo framework (managed workflow,
config plugins, Expo SDK). **EAS Build — Expo's cloud compilation
service — works with a standard bare React Native project just as
well**, as long as an `eas.json` config exists; it doesn't require
the app to be built the "Expo way."

**Decision: bare React Native CLI (standard `ios/`/`android/`
project structure, direct native code access), with EAS Build used
only as the cloud compiler that removes the local-Mac requirement.**
This is narrower than an earlier draft's recommendation, and
deliberately so — DamDam's core features (eSIM `EuiccManager`
access per `prd.md` §5.4, the Telnyx Voice SDK per `prd.md` §5.5,
CallKit/ConnectionService per `frontend-mobile.md` §8.3) are all
native-module-heavy, and Telnyx doesn't publish an official Expo
config plugin. Since these aren't edge features but the actual
product, bare RN's direct native code access is simpler than
translating every native change through Expo's config-plugin
abstraction for modules that don't already have one. The CI
workflow in `.github/workflows/deploy.yml` (`eas build` / `eas
submit`) works identically either way — no change needed there.

**A rented cloud Mac (MacStadium/MacinCloud) remains a rare, useful
fallback**, not a standing resource — specifically for deep
native-side debugging (Xcode's Instruments/Console.app) when
something iOS-specific breaks in a way EAS Build's logs don't fully
explain.

### 11.9.2 Development environment — all local, no dedicated dev cloud instance

**Decision: all interactive development happens on the founder's
local machine**, using the `docker compose up` local environment
already defined in §11.1 for backend/dashboard, and the local
Android emulator / physical devices plus EAS-built dev clients for
mobile (iOS testing via a connected device or, where unavoidable, a
rented cloud Mac session).

An earlier draft of this document recommended a third, dedicated
OCI instance for active backend development — reconsidered and
dropped for two reasons:

- **The "always-on, don't need to keep a laptop open" benefit is
  already covered by Codex's own cloud task execution** (the
  `@codex`-on-GitHub-issue flow in `AGENTS.md`), which runs on
  OpenAI's infrastructure, not a box the founder has to host. A
  separate persistent OCI instance would have been solving an
  already-solved problem.
- **The "catch `aarch64` compatibility issues early" benefit is
  better achieved as a CI check than as a development-environment
  requirement** — see §11.4's CI pipeline, which should include a
  multi-arch Docker build (`docker buildx build --platform
  linux/amd64,linux/arm64`) on every PR. This catches the same
  class of bug automatically without requiring the founder's
  day-to-day loop to run on ARM hardware.

This keeps the environment count at three (Local, Staging,
Production, per §11.1) rather than four, avoids a third set of OCI
credentials to manage, and removes the SSH-round-trip overhead of
developing against a remote box for no offsetting benefit once the
two justifications above are addressed more simply elsewhere.

**Total fixed monthly cost, including the iOS platform fee:**
approximately $8–13/month before any usage-based costs — down
from an earlier estimate of $33–48/month, almost entirely because
self-hosting Postgres removes what would have been the single
largest fixed line item (Supabase Pro, ~$25–35/month). The dual-
platform decision still adds a real but small fixed cost — the
larger cost of that decision remains engineering and QA time
(building, testing, and maintaining two release pipelines) rather
than the infrastructure line items themselves.

---

## 11.10 Domain Strategy

**Both `damdam.im` and `damdam.ng` are used, for different
audiences — not a redundant pair, a deliberate split.** `.com`,
`.net`, and other common gTLDs were unavailable at the time this
decision was made.

**`damdam.ng` — consumer-facing.** App store listings, in-app
content, HTO-facing materials, local marketing. For DamDam's actual
near-term audience (Nigerian pilgrims, HTOs), a Nigerian ccTLD is a
trust asset, not a liability — it reinforces the "local,
HTO-endorsed" positioning that's been central to distribution
throughout `prd.md` and the go-to-market strategy.

**`damdam.im` — business/vendor/investor-facing.** The sending
domain for the vendor RFP emails (Telnyx, IDT Express, Monty,
1GLOBAL, eSIM Access), investor materials, developer/API
documentation shared with vendor engineering teams, and any future
external-hire careers page.

**Why the split, not just `.ng` everywhere:** the risk isn't a
blanket SEO or spam-filter penalty on `.ng` domains — Google's
algorithm treats ccTLD choice mainly as a geotargeting signal, not
a trust penalty, and modern spam filtering runs on domain-specific
sending history and SPF/DKIM/DMARC authentication, not a blanket
TLD blocklist. The real, narrower risk is human first-impression
skepticism specifically in **unsolicited cold outreach to people
who don't know DamDam yet** — Nigeria's association with advance-
fee fraud is well-documented enough that an unfamiliar `.ng` domain
in a first-contact vendor RFP carries a small but real credibility
cost that doesn't exist once a relationship is established. That
risk is narrow and specific, so the mitigation (holding `.im` for
exactly that context) is proportionate — not a reason to avoid
`.ng` everywhere else, where it's actually an asset.

**DNS authentication matters more than the TLD choice itself.**
Whichever domain sends vendor/business email needs SPF, DKIM, and
DMARC records configured properly — this affects actual
deliverability more than the TLD does, and it's a one-time DNS
configuration that fits naturally into the Cloudflare DNS
management already specified in §11.2. A well-authenticated `.ng`
domain with clean sending history will outperform a `.im` domain
with sloppy DNS setup; the domain split is a secondary lever, not
the primary one.

**Cloudflare zone management:** both domains sit in Cloudflare
(consistent with §11.2's existing DNS/CDN approach) — `damdam.ng`
as the primary consumer zone, `damdam.im` as a secondary zone for
business-facing subdomains and email. `.com`/`.net` acquisition is
deferred until revenue allows, per the founder's own framing —
not a blocker to launch.

---

## 11.11 Amendment — Executable Compose and Deployment Safety

**What changed:** §11.3's six-service design now exists as the executable root
`docker-compose.yml`; `/health` is a real Postgres+Redis readiness probe and
`/health/live` is the cheap process-only probe; `ci.yml` now deploys successful
`develop` pushes to the isolated staging environment; and `deploy.yml` tags and
restores the previous application/Postgres images and checkout when production
deploy or readiness verification fails. Both deployment workflows validate
their named environment secrets before entering an SSH action.

**Why:** the earlier document and workflows described these controls but did
not implement them. A fixed sleep followed by a liveness-only response could
mark a release healthy while its database or task broker was unreachable, and
there was no executable rollback path.

**What is real and locally/CI verifiable:** Compose parsing and API image builds,
dependency health ordering, a Compose smoke test against real Postgres and
Redis (including a forced Redis outage returning 503), staging secret preflight,
exact commit image tagging, readiness polling, and API/Postgres-image rollback logic.
Legacy GB-only eSIM package-code configuration remains subject to §6.36's
separate deploy migration warning.

**What still requires Ibrahim and real infrastructure:** provision the isolated
staging OCI host, create `/opt/damdam/.env.staging`, configure the four named
staging GitHub Environment secrets, manually bootstrap the first production
Compose release so an initial rollback target exists, configure Cloudflare
tunnel/DNS, and supply production secrets. No OCI instance, DNS record, or real
secret is provisioned or injected by this amendment. Database downgrade remains
a deliberate manual recovery decision under §11.7 rather than an automated
rollback action.

---

## 11.12 Amendment — WAL-G Continuous Archiving and PITR

**What changed:** the production Postgres image now contains pinned,
multi-architecture WAL-G; Postgres continuously archives WAL to its configured
Cloudflare R2 bucket with a 60-second archive timeout; the adjacent Compose
service takes daily physical base backups and applies native 30-day retention;
and `walg-restore` prepares timestamp-targeted WAL replay from the latest base.
Both API and Postgres/WAL-G images are tagged with the deployed commit and are
built/restored together by the staging and production rollback workflows.

**Why:** the earlier §11.7 decision was fully specified but had no executable
configuration, scheduler, credential contract, or proven recovery path. A
logical dump or nearest snapshot would not meet the safety-data RPO or genuine
point-in-time recovery requirement.

**What it is for:** `scripts/test-walg-pitr.sh` provides repeatable evidence
against local MinIO that the active Postgres settings archive real WAL, loss of
the database volume is recoverable, and `recovery_target_time` includes the
intended transaction while excluding a later one. The same S3-compatible
contract targets R2 in staging/production.

**Explicitly still out of scope:** provisioning the R2 bucket, issuing or
injecting its restricted credentials, selecting a real incident recovery
timestamp, and authorising replacement of a damaged production volume all
require Ibrahim/the incident owner. This amendment does not claim a production
restore drill has occurred; it supplies the tested mechanism and pressure-ready
runbook for one.

---

## 11.13 Amendment — Self-Hosted Uptime Kuma Replaces the UptimeRobot Plan

**What changed:** §11.5's monitoring plan now uses self-hosted Uptime Kuma
instead of UptimeRobot, deployed on Hermes (`88.96.53.229`) as its own
isolated Docker container — separate bridge network and volume from Hermes'
existing 5 services, published only on Hermes' Tailscale interface
(`100.72.59.74:3001`), never on the public interface. It covers two monitors:
the API readiness check §11.5's UptimeRobot plan already specified, and a new
push/heartbeat monitor for the WAL-G backup loop that UptimeRobot's free tier
had no mechanism for at all. `docker/postgres-walg/backup-loop.sh` calls the
heartbeat's push URL after each successful `wal-g backup-push`, via the
optional `KUMA_PUSH_URL` (`docker-compose.yml`/`compose.env.example`) — a
no-op, not an error, when unset. Notifications go to Telegram, reusing
Hermes' existing `TELEGRAM_BOT_TOKEN`/`TELEGRAM_HOME_CHANNEL`, since no
SMTP/email credential exists anywhere on Hermes or in DamDam's committed
config to satisfy the original email-notification plan.

**Why:** one tool instead of two closes the WAL-G heartbeat gap (nothing
previously would have alerted if the backup loop silently died) at zero
incremental cost, on infrastructure the team is already comfortable
self-hosting. The isolation requirement is not a preference: a monitor
sharing a host with what it monitors goes dark in exactly the outage it
exists to catch.

**What is real and directly verified, not just configured:** Hermes' 5
pre-existing services (the `hermes` gateway container, `hermes-vnc`,
`hermes-voice-relay`, `hermes-xvfb`, `tailscaled`) were confirmed unaffected
before and after deployment via direct process/resource checks (`systemctl
is-active`, `docker stats`, `free`, `df`) — resource headroom was 9.2GB RAM
and 28GB disk free both before and after, Kuma itself uses ~115MB.
Both alert paths were proven with real induced failures, not configuration
review: a real HTTP monitor was pointed at a controllable test target,
stopped, and confirmed to transition to Down with Kuma's `important` flag
set (its actual internal notification trigger) and zero errors in Kuma's
logs, while the exact same Telegram bot token/chat ID Kuma is configured
with was independently confirmed to deliver a real message
(`{"ok":true}`, real `message_id`). A push monitor was left to time out
with no heartbeat and confirmed to transition Up → Pending → Down
(`important=true`, "No heartbeat in the time window") on the same
mechanism the real 30-hour WAL-G monitor uses, just at a shorter interval
so the test didn't require waiting 30 real hours. The exact
`backup-loop.sh` heartbeat call was extracted and run for real against the
live push monitor from Hermes (where it is genuinely reachable) and
confirmed to register. All temporary test monitors/containers were removed
afterward; only the 2 real monitors remain.

**What still requires Ibrahim:** the production/staging `DamDam API
readiness` monitor will show Down/Pending until `api.damdam.app` actually
resolves — that reflects reality (per §11.11, staging still needs to be
provisioned), not a Kuma misconfiguration. A second notification channel
(e.g. email) can be added once real SMTP credentials exist; none are
required for this amendment, since Telegram already satisfies "Ibrahim
receives alerts" with a channel that was already live.

---

## 11.14 Amendment — Three-Branch Promotion and Release Signoff Gate

**What changed:** formalizes the `develop` → `staging` → `main`
promotion convention that §11.4 already assumed (it describes what
happens once code reaches `main`, but never specified how code gets
there) and adds a real branch plus a CI-enforced gate in front of it.

- **`develop`** — integration branch, unchanged. Every push runs the
  full CI suite and (§11.4) attempts a `staging` environment deploy.
- **`staging`** — a real branch (not just an environment name) that
  now exists in the repository. `ci.yml`'s `deploy-staging` job
  fast-forwards it to the just-deployed commit immediately after that
  commit's staging health check passes — never before, and never by
  force-push. This makes `staging` mean something specific: "the
  commit currently confirmed healthy on the staging environment," not
  just "wherever `develop` happens to be." A `staging → main` PR is
  therefore always promoting something that was actually deployed and
  came back healthy, not an arbitrary later `develop` commit.
- **`main`** — production. Nothing pushes to it automatically.
  `deploy.yml`'s existing production job (§11.4) still triggers on
  push to `main` and still fails fast on missing OCI secrets exactly
  as it did before this amendment — this amendment does not build a
  real production deploy target (none is provisioned yet, per §11.2),
  it only makes sure `main`'s role is genuinely wired for when one
  is, rather than a branch nothing ever reaches.

**The promotion gate:** a `staging → main` PR must add exactly one new
file at `docs/release-signoffs/<commit-sha>.md` (template:
`docs/release-signoffs/TEMPLATE.md`), and
`.github/workflows/release-promotion.yml` runs
`scripts/validate-release-signoff.sh` on every PR targeting `main` to
enforce it. The script fails the check (and, via `main`'s required
status check in branch protection, actually blocks the merge button —
not just a red X someone could ignore) if:

1. No signoff artifact was added by this promotion.
2. The declared commit SHA doesn't resolve to a real commit, isn't an
   ancestor of the PR's head commit, or doesn't match its own filename
   — this is the anti-staleness check: it catches a signoff
   copy-pasted forward from an earlier, already-promoted release
   rather than one covering what's actually in this PR. (It
   deliberately checks *ancestor-of-head* rather than *exact-match*
   with the PR head: the natural sequence is test the current
   `staging` tip, then commit the signoff file on top of it, which by
   construction advances the tip by one commit past the SHA that was
   actually tested.)
3. Any required field is missing or still a `<placeholder>` — tester
   name, date, the full device-matrix table (mapped against
   `pre-pilot-checklist.md` §6's real-device list), every row of the
   required critical-scenario table (incoming call wake from
   killed/backgrounded state on both platforms, CallKit lock-screen
   UI, PushKit delivery, offline check-in/SOS survival through
   force-quit/reboot), and the HTO usability signoff section.
4. The signoff's date is more than 7 days old at promotion time.

Photo/video evidence of device testing is **not** required by this
gate yet. Per the note carried in `docs/release-signoffs/TEMPLATE.md`
itself: it becomes mandatory the first time someone other than the
founder is authorized to promote to `main`, or 3 months before the
Hajj 2027 pilot launch, whichever comes first — at that point add a
required `evidence_links` field to the template and extend the
validator to enforce it.

**Why an ancestor check instead of requiring the artifact's SHA to
equal the PR head exactly:** the alternative forces an awkward
self-referential commit (you can't know a commit's own SHA before
creating it, so matching the PR head exactly would require a
compute-then-amend dance every time). Requiring the declared SHA to be
a real ancestor of the PR head gets the same guarantee — this signoff
genuinely covers a commit that's part of what's being promoted, not
something unrelated — without that friction.

**What is real and directly verified, not self-reported:** the
`staging` branch was created for real (bootstrapped to `develop`'s
HEAD at the time of this amendment) and confirmed to exist via
`git ls-remote`. The validator script was run against both a
deliberately broken case (missing signoff, and separately a
SHA-mismatched one) and a correctly filled-in one, via real PRs
against `main` in this repository, and `main`'s branch protection was
configured to require `Validate release signoff artifact` as a status
check — confirmed by attempting to merge the broken PRs and observing
GitHub's merge button genuinely refuse, not just a failing check
sitting next to an available "Merge" button.

**What still depends on infrastructure that doesn't exist yet:**
`deploy-staging`'s health check (and therefore the `staging` branch's
auto-advance step) cannot succeed until the `staging` GitHub
Environment has real `STAGING_OCI_HOST`/`STAGING_OCI_DEPLOY_USER`/
`STAGING_OCI_SSH_KEY`/`STAGING_API_BASE_URL` secrets — it currently
does not (verified directly: `staging` and `production` GitHub
Environments both exist with zero secrets configured in either), so
in the repository's current state `staging` will not actually advance
past its bootstrap commit until a real staging host is provisioned.
This is the same "wired but not yet resourced" state §11.11 already
documents for production, extended honestly to staging rather than
implied to already work.
