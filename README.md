# DamDam

Connectivity, verified caller ID, and travel safety for Nigerian
travelers — launching with Hajj & Umrah pilgrims, expanding to
general travelers and enterprise/government contracts.

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

## Repository structure

```
/apps
  /api          ← FastAPI (Python) backend
  /mobile       ← React Native app (iOS + Android)
  /dashboard    ← Next.js HTO & Admin web dashboard
/docs           ← All specs — read this first
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

Pre-MVP. Spec-complete as of July 2026, entering build phase.
Target: HTO pilot onboarding by February 2027, ahead of Hajj 2027
(~May 14, 2027).

<!-- CI path-filter verification: docs-only change, 2026-07-17T20:20:14Z -->
