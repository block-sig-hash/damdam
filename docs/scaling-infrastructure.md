# Multi-Region Infrastructure & Global Payments — Scaling Roadmap
# DamDam — Version 0.1

## 12.1 Scope and Relationship to `infrastructure.md`

This document is **forward-looking**, not an MVP requirement. It
covers how DamDam scales from the Hajj 2027 wedge launch (single
OCI instance, Saudi Arabia only, as specified in
[`infrastructure.md`](./infrastructure.md)) toward a global
traveler product across EU/UK, North America, South America, and
Middle East/Asia corridors.

**Core principle:** Build the abstraction layer for global scale
now. Physically deploy only where real users are today. Expansion
should be "turn on a new region," not "rebuild the system."

**Reconciliation note with `infrastructure.md` §11.2:** the MVP
infra spec describes a single OCI Always Free instance without
naming a specific region. This document recommends **OCI Jeddah or
UAE as the launch region specifically**, given the VoIP latency
case study in §12.2 below. This is a more specific decision than
what's currently written in `infrastructure.md` and should be
treated as superseding it — confirm the free-tier Ampere A1
allocation is actually available in Jeddah/UAE before committing,
since free-tier region availability can vary.

---

## 12.2 Container & Deployment Portability

### Build for portability from day one
- **Multi-arch Docker images** — always build with `docker buildx`
  targeting both `linux/amd64` and `linux/arm64`. OCI's free tier
  is ARM (Ampere A1); Hetzner/AWS default to x86. Without
  multi-arch images, moving between providers means a rebuild, not
  a redeploy.
- **Boring, portable orchestration** — Docker Compose now (per
  `infrastructure.md` §11.3), k3s (lightweight Kubernetes) if/when
  scale demands it. Avoid provider-proprietary orchestration (OCI
  Container Instances, AWS ECS-specific features) that locks you
  in.
- **Infrastructure as code** — Terraform modules per provider so
  environments are reproducible, not hand-configured. This is what
  makes adding a new region a deployment task instead of a
  redesign.

### Where the real portability friction lives

| Layer | Friction | Mitigation |
|---|---|---|
| Container image | Low (if multi-arch) | Build multi-arch from day one |
| Object storage | Low | Use S3-compatible API only (works across OCI, Hetzner, R2) — never provider-specific SDKs |
| Stateful data (Postgres/Redis) | **High** | Self-host in containers where practical; plan explicit migration windows (dump/restore or replication cutover) when moving managed DB services |
| Networking (VPC, load balancers, security groups) | Medium | Terraform-defined, but expect real rework per provider |
| IAM / secrets | Medium | Prefer portable secret management (self-hosted Vault, or env vars via CI/CD) over provider-locked systems |
| CI/CD & registries | Low | Config change only if pipeline is provider-agnostic |

### ARM (Ampere A1) vs x86

- **Default to ARM (Ampere A1)** on OCI — free up to 4 OCPU/24GB
  per tenancy on qualifying account types (see
  `infrastructure.md` §11.1 for the current 2 OCPU/12GB Always
  Free reality as of mid-2026), and already validated by the
  founder's Hermes system running faster-whisper (CTranslate2) and
  a Discord voice patch on the same Ampere architecture. Strong
  performance-per-watt; competitive on highly parallel,
  many-small-request workloads (a typical FastAPI backend).
- **x86 remains the default elsewhere** (Hetzner, AWS, GCP) unless
  deliberately opting into their ARM lines (Hetzner CAX, AWS
  Graviton) — still ahead on single-core peak performance and on
  workloads relying on x86-specific SIMD (AVX-512).
- **Compatibility check:** most modern Python packages ship
  `aarch64` wheels (manylinux_aarch64 is standard on PyPI); VoIP/
  media codec libraries (Opus, WebRTC-adjacent) have NEON-optimized
  builds alongside x86 SSE/AVX. The real risk is a future native
  C/C++ dependency (e.g., a fraud-detection or ML library) that
  only ships x86 pre-built wheels — check `aarch64` wheel
  availability before committing to any new heavy dependency.
- **Practical rule:** always build multi-arch images regardless of
  target, default ARM on OCI, accept x86 by default elsewhere, and
  give Terraform modules an explicit per-region architecture
  parameter rather than assuming one everywhere. Benchmark ARM vs
  x86 specifically for the VoIP media relay once at real call
  volume — that's the one workload category where x86's more
  mature codec/SIMD support might still edge out ARM.

---

## 12.3 Region Strategy

### Default: single provider first, multi-cloud only where it earns its place

OCI's global footprint already covers all four target corridors:

| Corridor | OCI Region(s) |
|---|---|
| Middle East (launch priority) | Jeddah, UAE |
| EU/UK | Amsterdam, Frankfurt, London, Marseille |
| North America | Ashburn, Phoenix, Chicago |
| South America | São Paulo, Santiago |
| Asia | Mumbai, Singapore, Tokyo, Seoul |

**Recommendation:** Default to OCI everywhere first. One IAM
system, one Terraform provider, one billing relationship, one
support channel — a materially lighter ops burden for a small team
than genuine multi-cloud from day one.

**Bring in a second provider only where there's a proven gap:**

- **EU/UK → Hetzner**, once EU traffic is real. Cheaper compute,
  EU-native infrastructure (Falkenstein/Nuremberg/Helsinki), and
  simplifies GDPR data-residency arguments by keeping EU user data
  in EU-domiciled infrastructure. **Cost caveat (verify before
  committing):** Hetzner's pricing changed significantly in 2026 —
  an April 2026 portfolio-wide increase of 30–37%, followed by a
  further June 2026 repricing where the CCX (dedicated vCPU) and
  CPX (shared AMD) lines roughly doubled to nearly tripled, while
  the CX (Intel/AMD shared, cost-optimized) and CAX (ARM) lines
  rose a comparatively modest ~30%. **The practical implication:
  if choosing Hetzner for EU expansion, default to the CX or CAX
  lines specifically** — they remain genuinely cheap (CX23 at
  ~€3.99/month, CAX11 at ~€3.79–5.99/month depending on source and
  timing) and align with the "default ARM where possible" rule
  above. Avoid CPX/CCX unless dedicated-vCPU performance is a
  proven, specific requirement, since those lines no longer carry
  the historical price advantage that made Hetzner attractive in
  the first place. Existing instances keep their price at time of
  provisioning — rescaling or placing new orders after a price
  adjustment date pays the new rate, so this is worth timing
  deliberately rather than treating Hetzner pricing as a fixed
  reference point.
- **North America → AWS/GCP**, if deep ecosystem integrations are
  needed (US-based SIP trunking, Stripe-adjacent tooling). OCI
  Ashburn is a fine starting point otherwise.
- **South America** → OCI São Paulo by default; Hetzner has no
  LatAm presence.

### Data model: home-region assignment, not multi-master replication

Avoid trying to make every region an interchangeable read-write
copy of all data (hard consistency problems, split-brain risk,
overkill for this use case).

- Each user gets a **home region** based on where their account/
  travel corridor originates (e.g., a Nigerian pilgrim → Middle
  East/Jeddah).
- **Stateless/read-heavy** services (API gateway, static assets,
  config) replicate across all active regions, served from
  whichever is closest.
- **Stateful account data** lives in one primary region; the
  routing layer sends that user's requests back home regardless of
  which edge they hit.
- **VoIP/eSIM signaling** — the genuinely latency-critical piece —
  gets its own regional relay per active region. This is where
  call setup quality is actually won or lost.

### Routing layer

Use a **cloud-agnostic** latency-based router, not a single-cloud
tool (e.g., AWS Global Accelerator only routes to AWS endpoints).
**Cloudflare Load Balancing** fits well since Cloudflare Tunnel/R2
are already in the stack (`infrastructure.md` §11.2) — latency-
based steering, health checks, and failover across origins
regardless of underlying provider.

### Case study: VoIP relay placement for a Nigeria↔Saudi Arabia call

For a pilgrim in Saudi Arabia calling home to Nigeria, the relay/
signaling server should sit **next to the active app user (Jeddah),
not the call recipient (Lagos)**:

- The pilgrim's device is the leg actually controlled in real time
  (mic capture, jitter buffering, call setup) — the Nigeria-side
  recipient is typically just a phone ringing on the PSTN with no
  app-side optimization possible.
- The hop into Nigeria's telecom network is handled by the voice
  termination/SIP trunk provider (Twilio, per `prd.md` §5.5),
  whose own carrier network already optimizes that route — the
  relay server's location barely affects it.
- Jeddah and Lagos are both landing points on the **2Africa
  submarine cable**, and Jeddah hosts STC's MENA Gateway (MG1)
  carrier-neutral data center and the JEDIX exchange — strong,
  direct backbone capacity toward Nigeria without routing through
  Europe.
- Lagos isn't an available OCI region at all — using it would
  require a separate provider for a location that doesn't reduce
  the latency that actually matters.

This case study is the specific justification for the Jeddah/UAE
launch-region recommendation in §12.1 above.

---

## 12.4 Development Tooling — AI-Assisted Build Split

**Superseded note:** an earlier version of this section
recommended splitting Claude/Codex by whole codebase area
(frontend app vs. backend app). That's been replaced by a
finer-grained, concern-based split — documented as the source of
truth in [`AGENTS.md`](../AGENTS.md) at the repo root — after
weighing a documented real-world gap: Codex is reported as weaker
than Claude specifically at frontend UI/visual work, which matters
for `apps/mobile` (a trust-critical, visually-sensitive consumer
surface) but doesn't matter for `apps/dashboard` (explicitly speced
as "functional, not polished" in `frontend-dashboard.md` §9.5).

**Current split (see `AGENTS.md` for the authoritative, maintained
version):**

- **Claude** produces the mobile app's design system once
  (`docs/design-system.md`), directly implements a small, explicitly
  named set of the highest-stakes screens (SOS confirm/sent,
  onboarding), and acts as the QA/review layer across the entire
  codebase — including reviewing the *rendered* output of every
  other mobile screen against the design system, not just its code.
- **Codex** implements everything else: the remaining
  `apps/mobile` screens/components (built against the design
  system rather than improvised), the mobile app's logic layer
  (hooks, services, state management), the entire `apps/dashboard`,
  all of `apps/api`, and infrastructure/Terraform.

This is a deliberately narrower Claude footprint than an earlier
draft of this split (which had Claude implementing the entire
`apps/mobile/src/screens`/`components` tree directly) — the design-
system approach targets the actual root cause (Codex lacks taste/
judgment on ambiguous design calls, not the ability to assemble an
explicit system precisely) rather than routing around it by giving
Claude more surface area than the problem requires, which matters
given Claude's real per-task API cost against Codex's flat
subscription cost (see below).

**Cost mechanics worth noting here, since they weren't settled when
this section was first written:** Claude Code runs on direct
Anthropic API billing for this project (not the Claude.ai
subscription) — chosen over OpenRouter because, for Claude
specifically, OpenRouter's markup over Anthropic's own price is
close to zero when routed to Anthropic directly, so the gateway
choice itself isn't a cost lever; the real levers are model-tier
discipline (default Sonnet, escalate to Opus only when justified)
and prompt caching (achieved by letting Claude read `/docs` via its
own file tools rather than pasting spec content into prompts).
Codex runs under the founder's existing ChatGPT Plus subscription
with no comparable marginal cost per task — which is *why* the
split above defaults as much work as possible to Codex, reserving
Claude for the specific areas (mobile UI, safety-critical review)
where its usage is worth the real API spend.

**Automated review:** a `claude-review.yml` GitHub Action runs
Claude automatically on PR open and on `@claude` mentions, scoped
to Sonnet with a turn limit for cost predictability. Codex's own
automatic PR review feature can run in parallel as a fast P0/P1
filter but isn't a substitute for Claude's review on anything
`AGENTS.md`'s table assigns to Claude.

### Practical notes on running a split-tool workflow

- **Keep a shared source of truth outside either tool** — the
  spec suite in this `/docs` folder should remain the canonical
  reference both tools work from, so the API contract between
  frontend and backend doesn't drift depending on which tool
  touched it last.
- **Treat the API spec as the seam.** Since Claude and Codex both
  touch `apps/mobile` now (UI vs. logic layer respectively) in
  addition to Claude reviewing Codex's backend work, `api-spec.md`
  (and its generated `api-spec.yaml` companion, per
  `infrastructure.md` §11.4) is the actual interface contract
  everyone works from — keep it versioned and update it
  deliberately rather than letting either tool infer the contract
  from the other's code.
- **CI should validate the seam automatically** — the API-spec-
  drift check already specified in `infrastructure.md` §11.4 serves
  double duty here: it catches drift between what Claude's UI
  expects, what Codex's mobile logic layer provides, and what
  Codex's backend actually returns.
- **Multi-arch and Terraform conventions (§12.2 above) apply
  regardless of which tool generates the code** — bake these
  constraints into whatever prompts/instructions each tool works
  from, so infra code stays portable no matter which assistant
  wrote it.

---

## 12.5 Sequencing / Rollout Plan

1. **Now:** Build the abstraction layer — multi-arch images,
   S3-compatible storage, Terraform-defined infra, Cloudflare
   routing designed for multiple origins, payment abstraction
   layer (§12.6 below).
2. **Launch (Hajj 2027):** Deploy only to OCI Jeddah/UAE as
   primary (superseding the unspecified-region MVP plan, per
   §12.1). Optionally Hetzner EU (CX/CAX line only, per the cost
   caveat in §12.3) for the non-latency-sensitive admin dashboard,
   if there's a reason to run it outside OCI at all — otherwise
   Cloudflare Workers (already specified in `infrastructure.md`
   §11.2) remains sufficient for the dashboard and no second
   provider is needed yet.
3. **Expansion:** Light up each additional corridor (EU/UK, NA,
   South America, Asia) as real user demand justifies the added
   regional ops burden — monitoring, patching, backups, and on-call
   attention all scale per region.

---

## 12.6 Global Payments

Paystack (per `infrastructure.md` and the business model canvas)
is Africa-focused and won't serve travelers from other corridors
well. As the user base broadens, payments need the same
"home-region" logic as infrastructure.

### Recommended split

| Corridor | Payment rail | Why |
|---|---|---|
| Nigeria / Africa | **Paystack** (already planned) | Naira rails, local cards, bank transfer, USSD — best conversion for this market |
| EU/UK, North America, South America, Middle East/Asia | **Stripe** (or Adyen as alternative) | Global card acceptance, broad currency support, mature APIs, strong fraud tooling |

### Design now, even though not urgent yet

- Build a **payment abstraction layer** in the backend (a single
  internal interface for "charge user," "issue refund," "handle
  webhook") so the actual processor is swappable per user/region
  without touching business logic. This sits alongside the
  existing Paystack webhook handling in `api-spec.md` §7.9 —
  future Stripe webhooks should implement the same internal
  interface, not a parallel one-off integration.
- Route each transaction to the correct processor based on the
  user's registered corridor/currency, mirroring the infrastructure
  home-region model in §12.3.
- Keep the Nigeria OpCo as the legal seller-of-record for Paystack
  transactions (per the entity structure in
  [`corporate-structure.md`](./corporate-structure.md)); a separate
  entity or the UAE parent may need to be seller-of-record for
  Stripe
  transactions depending on where funds settle — confirm with
  counsel once non-Africa revenue becomes real, not before.

---

## 12.7 Summary Recommendation

- **Portability:** multi-arch containers, S3-compatible storage,
  Terraform everywhere, no provider-proprietary orchestration.
  Default ARM (Ampere A1) on OCI, x86 elsewhere unless deliberately
  opting into ARM lines.
- **Regions:** default to OCI's global footprint across all four
  corridors; add Hetzner (EU/UK, CX/CAX lines only given 2026
  pricing changes) or AWS/GCP (North America) only where cost,
  latency, or compliance clearly justifies it. VoIP relays sit next
  to the active app user (e.g., Jeddah for the Nigeria–Saudi Arabia
  corridor), not the call recipient.
- **Data:** home-region assignment per user, not multi-master
  replication; regional VoIP/eSIM relays where call quality matters
  most.
- **Routing:** Cloudflare Load Balancing for cloud-agnostic
  latency-based steering.
- **Development tooling:** Claude implements `apps/mobile`'s UI
  layer (screens/components) and reviews everything else; Codex
  implements the mobile logic layer, the full dashboard, and all
  backend/infra — split by concern (UI vs. logic/backend), not by
  whole codebase area. See `AGENTS.md` for the authoritative,
  maintained version and §12.4 for the reasoning.
- **Payments:** Paystack for Africa, Stripe/Adyen for everywhere
  else, unified behind an internal payment abstraction layer.
- **Sequencing:** build for global scale, deploy only where users
  actually are, expand region-by-region as demand proves out.

---

## 12.8 Open Items Requiring Founder Decision

- **Confirm OCI Always Free (or PAYG-equivalent) Ampere A1
  availability specifically in the Jeddah or UAE region** before
  treating §12.1's region recommendation as final — free-tier
  availability varies by region and by account type (see the
  founder's existing Hermes account distinction between strict
  Always Free and PAYG-with-free-allowance).
- **Re-verify Hetzner CX/CAX pricing at the time of actual EU
  expansion**, not at planning time — Hetzner repriced twice in
  2026 (April and June) and the June adjustment was announced as
  driven by hardware procurement costs, meaning further changes are
  plausible before EU expansion is actually on the roadmap.
- **Development tooling split is now finalized, not open** — the
  concern-based Claude/Codex split in §12.4 and `AGENTS.md` is a
  committed workflow decision, not a default awaiting revisit.
  Monitor whether the `apps/mobile` UI/logic boundary (screens+
  components vs. hooks+services+store) holds up in practice as
  the app grows — revisit the exact folder boundary, not the
  underlying principle, if it starts creating awkward hand-offs
  between the two tools on a specific feature.

---

## 12.9 Self-Hosted Telephony at Scale — FreeSWITCH + Wholesale SIP Trunking

**Two distinct paths exist here, at different levels of commitment
— worth keeping separate, not treating as one decision.**

### 12.9.1 Nearer-term, lower-risk: BYOC wholesale trunk underneath Telnyx (or Twilio)

**Not needed at MVP, but a real, much smaller step than full
self-hosting** — once call volume is real enough that wholesale
termination pricing would meaningfully beat the chosen CPaaS
vendor's own rates. This keeps the entire application-facing layer
(APIs, webhooks, SIP number management, programmable voice,
Twilio/Telnyx Verify for CLI) exactly as already speced in
`api-spec.md` §7.5 — only the underlying PSTN termination path
changes, via Bring Your Own Carrier (BYOC), which both Twilio and
Telnyx support natively. This is a configuration/commercial change
more than an engineering one, and it's the recommended first step
if termination costs become a real optimization target — well
before considering the full FreeSWITCH path below.

**Realistic BYOC wholesale partner for this step: IDT Express**,
specifically because it's self-service/SMB-accessible (per the
table below) and already positions itself as a BYOC backend
*underneath* Twilio and Plivo — meaning this integration path is
something the vendor has already built for, not something DamDam
would be first to attempt.

### 12.9.2 Further out, higher commitment: full self-hosted FreeSWITCH

**Not needed now.** This is a Year 2+/at-scale consideration,
flagged here so it's documented rather than lost as conversation —
not a recommendation to act on before real call volume justifies
the ops burden, and a meaningfully bigger step than §12.9.1 above.

**The idea:** once Twilio's (or Telnyx's — see `api-spec.md` §7.5's
provisional vendor flag) per-minute usage-based pricing at real
scale exceeds what self-hosting a telephony switch plus a wholesale
SIP trunk relationship would cost — beyond what BYOC alone captures
— self-hosting the application layer itself becomes worth
revisiting. **FreeSWITCH** is the open-source softswitch/PBX that
would run the actual media relay and call routing; it has no
carrier relationships of its own, so it needs a wholesale voice
termination provider behind it to actually reach real phone
networks. This is a categorically bigger ops commitment than
anything else in this document, including the BYOC step above —
media relay tuning, NAT traversal, SIP trunk failover, and carrier
interconnect management are all real, ongoing operational work, not
a one-time setup — and is explicitly *not* recommended for the
MVP/pilot phase given the "keep it simple" principle applied
throughout `infrastructure.md`.

**Wholesale carrier options, applicable to either path above** —
these split into two real accessibility tiers, not one
interchangeable category, and this distinction matters regardless
of which path (BYOC-under-Telnyx or full FreeSWITCH) is eventually
pursued:

| Provider | Accessibility tier | Notes |
|---|---|---|
| DIDLogic | Self-service, SMB-accessible | Owns its own network (ASN AS13006, 12 PoPs), 130+ country DID coverage — but a customer review specifically flagged weak Gulf/Saudi Arabia coverage, and its account-tier model includes non-waivable minimum monthly commitments (a real contractual risk pattern for uncertain-volume usage). Also lacks a mobile SDK layer entirely — using it means building the WebRTC/SIP integration yourself, not getting one from the vendor (relevant to §12.9.2 only; irrelevant to §12.9.1, which keeps Twilio/Telnyx's SDK layer regardless). |
| IDT Express | Self-service, SMB-accessible | Explicitly built for this tier — self-serve portal, SMB-oriented, STIR/SHAKEN A-level attestation support, and notably already offers itself as a BYOC backend *underneath* Twilio and Plivo specifically. The most realistic candidate for **both** paths above given its accessibility and existing CPaaS-integration positioning. |
| BICS | Enterprise/carrier-to-carrier only | Proximus subsidiary, historically operator-to-operator sales, not self-service. Reachable indirectly via IDT Express's "BICS Easy Connect" product rather than a direct relationship at DamDam's likely scale. |
| Tata Communications | Enterprise/carrier-to-carrier only | One of the largest global wholesale voice carriers; explicitly positioned around managed services and strategic sourcing with account-managed enterprise relationships. **Not a symmetric "secondary" option alongside IDT Express** — an external analysis of this section proposed IDT and Tata as parallel primary/secondary wholesale carriers, but that glosses over a real accessibility gap: IDT is reachable via self-service signup today, Tata requires an enterprise sales process and likely substantial minimum commitments that aren't realistic at DamDam's current stage. Treat as a later-stage option only, not a near-term redundant pairing with IDT. |
| Orange (International Carriers/Wholesale) | Enterprise/carrier-to-carrier only, inferred not directly confirmed | A Tier-1 telecom operator's wholesale carrier division; reasonable to expect the same enterprise/operator sales model as BICS/Tata based on how this category consistently operates, but this wasn't directly verified in the research behind this table — confirm before treating as settled if this path is ever pursued. |

**Practical implication if/when either path becomes relevant:** IDT
Express is the more realistic starting point for both §12.9.1 and
§12.9.2 given its self-service accessibility and existing
positioning as a CPaaS-adjacent BYOC backend — DIDLogic's Gulf
coverage gap is a specific, disqualifying concern given Saudi
Arabia is DamDam's core market, not a peripheral one. BICS, Tata,
and (likely) Orange only become relevant once DamDam has real
enough volume and commercial standing to support an actual
enterprise carrier sales relationship — a later-stage question for
either path, not a Phase 0 one, and not something to pair
symmetrically with IDT Express before that standing exists.
