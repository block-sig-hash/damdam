# DamDam

A connectivity platform for consumers, enterprises and government organizations.
The approved target combines eSIM data, carrier native-dialer voice where proven,
and outbound internet calling from the mobile app and website. Internet calling
does not require an eSIM. See the [calling expansion plan](./docs/implementation/VOICE-EXPANSION.md)
for scope, dependencies and supplier gates; these are planned capabilities.

> **The product was reset on 8 September 2026** from a Hajj-pilgrim
> app to the description above. The specs in `/docs` have not been
> rewritten yet — read [`docs/prd.md`](./docs/prd.md) §10 for the
> reset scope and
> [`docs/implementation/`](./docs/implementation/) for the build
> sequence before working from any older spec text.

## New here? Start with SETUP.md

If you haven't set up WSL, GitHub, Claude Code, and Codex yet, start
with [`SETUP.md`](./SETUP.md) — a complete, non-technical, step-by-
step guide from zero to your first commit and first agent-built
feature. Everything below assumes that setup is already done.

## Documentation

All product, technical, security, and infrastructure specs live in
[`/docs`](./docs). Start with [`/docs/README.md`](./docs/README.md)
for the full index and recommended reading order.

## Working with Claude Code / Codex CLI

This repo has an [`AGENTS.md`](./AGENTS.md) at the root (with
`CLAUDE.md` symlinked to it), which both tools read automatically
at the start of every session — you don't need to paste spec
content into the terminal or tell the agent where files are each
time. It points to `/docs` for full context and lists build/test
commands and non-negotiable conventions. Keep it short; it's meant
to route the agent to the real specs, not duplicate them.

**The working split, since 8 September 2026: Claude implements,
Codex independently reviews and may refactor.** Work goes one chunk
at a time from
[`docs/implementation/chunks/`](./docs/implementation/chunks/);
Claude returns a handoff, Codex reviews and records acceptance, and
only then does the next chunk start. Claude never marks its own work
accepted.

## Repository structure

```
/apps
  /api          ← FastAPI (Python) backend
  /mobile       ← React Native app (iOS + Android)
  /dashboard    ← Next.js enterprise & internal web dashboard
/docs           ← All specs — read this first
  /implementation ← Build chunks, plan, status, decisions, handoffs
/scripts
  /db           ← Alembic migrations
  /deploy       ← Deployment scripts
/.github
  /workflows    ← CI and deploy pipelines
```

## Branch strategy

- `main` — production, protected, requires PR + passing CI
- `develop` — integration branch
- `feature/[name]` — cut from develop
- `fix/[issue-number]` — hotfixes

Commit convention: [Conventional Commits](https://www.conventionalcommits.org/)
(`feat:`, `fix:`, `docs:`, `chore:`).

## Local development

```bash
docker compose up
```

Brings up the full stack: FastAPI, Postgres, Redis, Celery
worker + beat. See `docs/infrastructure.md` §11.3 for the
production reference compose file this is based on.

## Status

Pre-MVP, rebaselining after the 8 September 2026 product reset. The
old Hajj-pilot target and its feature freeze are lifted; see
[`docs/pre-pilot-checklist.md`](./docs/pre-pilot-checklist.md)'s
closing amendment. No new launch date is set — it depends on the
external decisions D1–D6, all of which are open in
[`docs/implementation/DECISIONS.md`](./docs/implementation/DECISIONS.md).

CI is currently failing on `develop`. What is actually passing,
failing and merely historical is recorded in
[`docs/implementation/BASELINE.md`](./docs/implementation/BASELINE.md);
chunk 02 owns the repair.
