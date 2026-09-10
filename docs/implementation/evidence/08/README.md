# Chunk 08 evidence

The submitted branch contained three production-rendered snapshots:
`gallery-en.html`, `gallery-fr.html` and `gallery.css`. They are retained as the
historical submission evidence. Independent review found that HTML alone did
not satisfy the visual acceptance criterion, so CI evidence supersedes it.

## Accepted browser evidence

[CI run 34491797307](https://github.com/block-sig-hash/damdam/actions/runs/34491797307)
produced a `dashboard-gallery-screenshots` artifact with eight PNGs:

| Locale | Viewports and text scale |
|---|---|
| English | 320, 768 and 1280 pixels at 100%; 320 pixels at 200% text |
| French | 320, 768 and 1280 pixels at 100%; 320 pixels at 200% text |

The artifact manifest records Google Chrome 152.0.7977.82 and the exact capture
dimensions. CI validates PNG signatures and dimensions, scans the rendered DOM
for horizontal overflow, and fails before upload if any element exceeds the
viewport. Review included visual inspection of all viewport and large-text
variants.

The production `/gallery` route returns 404 by default. CI enables it with
`DESIGN_GALLERY_ENABLED=true` only for this evidence job and verifies both the
disabled and enabled behavior.

## Accepted Android evidence

The same run produced `mobile-screenshots-android`: **13 successful Maestro
flows, 0 failures and 26 PNGs** on the CI Android emulator. This covers English
and French for the five new gallery surfaces and the retained reset journey:
OTP, PIN setup/unlock, package selection, activation code, platform eSIM prompt,
QR installation and activation success. The validator derives the expected
names from the flow files and rejects missing, unexpected, empty, corrupt or
wrong-dimension images.

The reviewer inspected representative state, usage, calling and activation
captures in both locales. The review copies are stored outside the repository
at `/home/iadamu/artifacts/damdam-chunk08-dashboard-gallery-final-code` and
`/home/iadamu/artifacts/damdam-chunk08-mobile-android-final`.

## Remaining visual gate

iOS capture runs on the workflow's nightly/manual path and was not part of this
pull-request run. Chunk 27 still owns the signed-device release matrix and the
visual-regression policy; these accepted images establish real baselines for
that work without claiming physical-device proof.
