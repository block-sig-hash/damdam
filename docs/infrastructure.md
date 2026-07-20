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
six-service architecture sketch; the root file is authoritative. During
extraction, four omissions in this sketch were corrected rather than copied:
`depends_on` now waits for healthy Postgres/Redis instead of only container
startup, Postgres and Redis have real health checks, Redis uses AOF persistence,
and the API/worker/beat receive container-network database and Redis URLs. The
root file also gives all three Python services the same commit-tagged image so
deployment rollback can atomically restore the prior application version.

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

**Six containers in production:** `api`, `postgres`, `redis`,
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
| API uptime/health | UptimeRobot (free tier) sending `GET https://api.damdam.app/health` (readiness, not a liveness-only route) | 2 consecutive failed checks for network failures via UptimeRobot's built-in confirmation; see the HTTP-error caveat below |
| API process liveness | Container health diagnostics can use `/health/live` when dependency state must be excluded | Restart/inspect only when the process itself is unresponsive; dependency outages are reported by readiness instead |
| Error rate | PostHog Error Tracking (free tier), covering the FastAPI backend and both React Native app builds | Alert on an error-rate spike, not absolute count |
| Failed SOS notifications | Direct DB query, surfaced in Admin Dashboard (Failed Notification Queue) — doubles as both the fix screen and the monitoring signal | Real-time, visible on the screen itself |
| Celery worker/beat health | `docker stats` + `restart: unless-stopped` | Container restart loops flagged via Uptime Robot detecting sustained task backlog symptoms (e.g., stale usage_polls) |
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

**Exact UptimeRobot free-tier setup for Ibrahim:**

1. Create an **API monitor** named `DamDam API readiness`, method
   `GET`, URL `https://api.damdam.app/health`, with the free-tier
   interval of 5 minutes. Do not use `/health/live`.
2. Require HTTP `200` and add the JSON assertion `$.status` equals
   `ok`; attach Ibrahim's verified email alert contact for both Down
   and Up/recovery notifications.
3. Leave authentication, request body, and custom headers empty;
   enable redirect following and use the default request timeout.
4. Treat Down as confirmed only after UptimeRobot's built-in retry
   flow: its free tier retries an initial network failure before
   opening an incident, satisfying the intent of the existing
   two-consecutive-failures rule for transient connection failures.
   UptimeRobot does **not** expose a configurable consecutive-failure
   count or notification delay on the free plan, and an explicit HTTP
   error response may be marked Down immediately. If an exact,
   configurable two-check threshold is mandatory for every failure
   mode, that requires a paid notification delay or a different
   monitor; do not claim the free-tier UI has a threshold field.

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

---

## 11.7 Backup & Disaster Recovery

| Data | Backup method | RPO | Retention |
|---|---|---|---|
| Postgres | **WAL-G** — continuous WAL archiving to Cloudflare R2, plus a daily base backup, run from day one (self-hosted from the start, no managed-service phase to migrate away from — see §11.2/§11.3) | ~1–5 minutes (governed by `archive_timeout`), true point-in-time recovery — not "nearest snapshot" | 30 days, pruned automatically by WAL-G's retention policy |
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

**Implementation shape:**
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
   container (§11.3) — implementation detail for the build phase,
   not a new service to provision separately

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
| Uptime Robot | $0 |
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
restores the previous application image and checkout when production deploy or
readiness verification fails. Both deployment workflows validate their named
environment secrets before entering an SSH action.

**Why:** the earlier document and workflows described these controls but did
not implement them. A fixed sleep followed by a liveness-only response could
mark a release healthy while its database or task broker was unreachable, and
there was no executable rollback path.

**What is real and locally/CI verifiable:** Compose parsing and API image builds,
dependency health ordering, a Compose smoke test against real Postgres and
Redis (including a forced Redis outage returning 503), staging secret preflight,
exact commit image tagging, readiness polling, and application-image rollback logic.
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
