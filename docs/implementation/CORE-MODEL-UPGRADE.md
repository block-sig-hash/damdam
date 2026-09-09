# Core model upgrade and roll-forward plan

Produced by [chunk 05](chunks/05-core-schema.md) (US-28) on 9 September 2026,
against base `12582f101e4ca7e6a6c6d55d93470444b7ec7cd3`.

Revision `0027_core_domain_model` is **additive only**: nine new tables, six new
enum types, no `ALTER`, no `DROP`, no `UPDATE`. The new tables start empty and
stay empty until the chunks that use them land.

## Why nothing is backfilled yet

The obvious next step — translate every legacy `packages` row into an `orders`
row, an `order_items` row and an `entitlements` row — is the one thing this
chunk deliberately does not do.

A backfill is a translation, and a translation is only correct with respect to
how the result will be read. Nothing reads these tables yet. Writing the
translation now would mean writing it against an imagined consumer, shipping it
unexercised, and discovering in chunk 09 or 11 that the mapping was wrong — by
which time the wrong rows are in production and the fix is a second migration
over data the first one invented.

Concretely, the questions a `packages` backfill has to answer and cannot yet:

- **Which legal entity sold it?** D3 is open, so `legal_entities` has no rows.
  Every legacy order would need a seller that does not exist. Inventing a
  placeholder entity would put a false answer in the column whose entire purpose
  is to record the true one.
- **What product was it?** `pricing_tiers` is destination-scoped and NGN-only,
  and the catalog that replaces it is chunk 09's. Minting one `products` row per
  legacy tier presumes that mapping.
- **What currency, at what scale?** NGN with two places, trivially. But
  `product_prices` versioning — which version was in force on a given purchase
  date — is chunk 09's model, and back-dating versions is inventing history.
- **Which state was it in?** `packages.status` conflates payment, provisioning
  and lifecycle. Splitting `active` into `payment_state=paid` plus
  `provisioning_state=provisioned` is a guess for any row where the two
  genuinely differed — which is exactly the class of row the split exists for.

So: the schema lands now, the translation lands with its consumer.

## Phases

### Phase A — additive (this chunk, revision 0027)

New tables and enums. Every column that will eventually be mandatory but cannot
be filled for a legacy row is **nullable now**:

| Column | Nullable because | Constrained in |
|---|---|---|
| `order_items.recipient_user_id` | a bulk order has no recipient until assigned | stays nullable — assignment is a real state |
| `entitlements.holder_user_id` | same | stays nullable |
| `order_items.operation_reference` | written just before supplier dispatch | Phase C, unique already enforced |
| `carrier_lines.iccid` | not known until the profile is issued | Phase C |
| `esim_installations.esim_profile_id` | only migrated rows have a legacy profile | stays nullable |

Constraints that **are** enforced from day one, because they never depend on a
backfill: exactly one payer per order, non-negative amounts and entitlements,
exactly one provisionable line per order item, ISO 4217 currency shape, E.164
number shape, one live
assignment per number, and every foreign key. Order items are bound to the
parent order by both id and currency, so mixed-currency totals cannot be
constructed. Charge and settlement are separate amount/currency pairs;
settlement remains null until both values are known.

### Phase B — backfill (chunks 09–11, with their consumers)

Run per legacy `packages` row, idempotently, keyed on the package id so a
re-run cannot duplicate. Requires, in order: a decided `legal_entities` row
(D3), the chunk 09 catalog mapping from `pricing_tiers` to `products`, and the
chunk 11 order state machine to say what `payment_state`/`provisioning_state`
each legacy `status` becomes.

Each backfilled row records its origin — `esim_installations.esim_profile_id`
exists for exactly this — so a migrated record can be traced to what it came
from rather than appearing to have arrived from nowhere.

### Phase C — constrain (after Phase B verifies)

Tighten the columns above to `NOT NULL` once the backfill has filled them, in a
separate revision, after a count proves there are no remaining nulls. Never in
the same migration as the backfill: a constraint that fails mid-migration on
production data leaves the schema half-applied.

### Phase D — retire legacy schema (not scheduled here)

Dropping `packages`, `pricing_tiers` or the NGN columns happens only after
compatibility requirements end, per
[IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md) §7 Phase 1. Chunk 05 drops
nothing, and neither should the chunk that finishes the backfill.

## Rollback

`alembic downgrade 0026_i18n_locales` drops the nine tables and six enums this
revision created, and nothing else. Because nothing is backfilled, **the
downgrade is lossless**: the only rows it removes are ones written after the
upgrade by code that does not exist yet.

`tests/test_core_model_upgrade_postgres.py` proves this against a populated
database — upgrade, downgrade, and a full snapshot comparison either side — and
separately proves the upgrade can be reapplied after a downgrade, which is the
recovery path an operator actually takes.

Once Phase B has run, the downgrade stops being lossless: it would drop
backfilled rows. The revision that performs the backfill must say so in its own
docstring and must not claim this one's rollback guarantee.

## Irreversible steps

**There are none in this chunk.** That is worth stating plainly, because it is
the property that makes revision 0027 safe to deploy ahead of the work that uses
it. The first irreversible step in this sequence is Phase D.
