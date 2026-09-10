# Chunk 08 evidence

## What is here

| File | What it is |
|---|---|
| `gallery-en.html` | The dashboard `/gallery` route, server-rendered, English |
| `gallery-fr.html` | The same route with `Accept-Language: fr` |
| `gallery.css` | The stylesheet those pages load, exactly as served |

Captured **10 September 2026** from a production build:

```
cd apps/dashboard
npm run build
npx next start -p 3123
curl -s http://127.0.0.1:3123/gallery > gallery-en.html
curl -s -H 'Accept-Language: fr' http://127.0.0.1:3123/gallery > gallery-fr.html
```

Open either HTML file alongside `gallery.css` to see the rendered page. The two
differ only in language; both contain all five status-pill tones, all three
usage severities including `unknown`, and all five state messages.

`gallery.css` carries **55 token custom properties** — `--color-primary-500:
#0b6b66` and the rest. That is the end-to-end proof that
`design-tokens/tokens.json` reaches a browser, not merely a test.

## What is NOT here, and why

**No screenshots.** This environment has no browser and no emulator:

```
$ which chromium chromium-browser google-chrome firefox   # nothing
$ which emulator adb                                      # nothing
```

So the chunk's acceptance criterion — *"Render representative mobile and
dashboard views, including narrow screens, larger text and French. Return
screenshots with device/viewport details"* — is **NOT MET**, and nothing here is
offered as a substitute for it. Rendered HTML is not a screenshot: it cannot
show whether French wraps or clips at 320px, and that is precisely what the
criterion exists to check.

What has been done instead is to make the capture reproducible for whoever has
the hardware:

- **Mobile.** Five gallery flows are in `apps/mobile/maestro/screens/`, and the
  matrix derived from them names 26 images per platform. CI's
  `screenshot-mobile-android` job runs them on a real emulator. The harness
  *logic* is verified — `reset-matrix.test.ts` and `validateScreenshots.test.js`
  both pass locally — but no image has been produced here.
- **Dashboard.** `/gallery` is the surface to capture: 320px, 768px and 1280px,
  in both locales, and again at 200% text size.

Chunk 27 owns the release gate over the matrix. Its input,
`apps/mobile/screenshotHarness/reset-matrix.json`, exists and is tested; the
images it will gate on have not been taken.
