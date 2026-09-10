# Design tokens

`tokens.json` is the source of truth for every colour, space, radius and type
step in DamDam. Both apps are **generated** from it:

| Generated file | Consumed by |
|---|---|
| `apps/mobile/src/theme/tokens.ts` | React Native |
| `apps/dashboard/app/tokens.css` | Next.js, as CSS custom properties |

```
node design-tokens/build.js          # regenerate both
node design-tokens/build.js --check   # verify, exit 1 on drift
```

`docs/design-system.md` remains the human source of truth for *why* each value
is what it is. This directory is its machine-readable half.

## Why generate instead of documenting

Before chunk 08 the two apps had two palettes. The dashboard used `#17623e`
where the mobile app used `primary-500` `#0B6B66`, `#17211b` where it used
`gray-900` `#14181A`, and about twenty more. Neither was wrong on its own —
nothing compared them, so nothing could be.

The green mattered most. `design-system.md` §1 reserves green for the
healthy/success semantic *specifically* so it never competes with the brand
colour for meaning, and the dashboard had adopted a green as its brand.

## Contrast is computed, never recorded

`tokens.json` deliberately stores **no** contrast ratios. It stores what each
colour is *allowed to be used for*, and the tests compute the ratio from the hex
and check the classification holds:

- `bodyTextOnWhite` — must clear 4.5:1 (WCAG 2.1 AA body text)
- `largeTextOrIconOnly` — must clear 3:1 **and must fail 4.5:1**, so a colour
  that quietly became body-safe gets promoted deliberately rather than sitting
  mis-filed
- `tintBackground` — must be light enough for `gray-900` body text on top
- `filledButton` — the fill and its label must clear 4.5:1 together

A hand-maintained ratio table goes stale the first time somebody nudges a hex,
and the rule it justifies goes stale with it silently. Writing this check found
that `accent-500` is **2.97:1** on white — under even the 3:1 non-text floor —
so it may never be an icon, a border or text on a white surface. It is a filled
badge with `gray-900` on top, and nothing else.

`contrast.js` implements WCAG 2.1's relative luminance and contrast ratio.
`contrast.vectors.js` holds published reference values it must reproduce,
because a contrast helper that agrees only with itself will certify an
illegible palette without complaint.

## Adding or changing a token

1. Edit `tokens.json`.
2. Run `node design-tokens/build.js`.
3. Commit the generated files alongside it — the diff is the review.
4. Run both apps' suites. If a new colour is mis-classified, they fail.

Never edit a generated file. Each app's token test compares it against a fresh
render and fails on any hand-edit.
