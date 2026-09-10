import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const matrix = JSON.parse(
  fs.readFileSync(path.join(root, "screenshot-matrix.json"), "utf8"),
);
const outputDir = process.env.SCREENSHOT_OUTPUT_DIR
  ? path.resolve(process.env.SCREENSHOT_OUTPUT_DIR)
  : path.join(root, "screenshots", "gallery");
const baseUrl = process.env.GALLERY_BASE_URL || "http://127.0.0.1:3123";
const chrome = process.env.CHROME_BIN || "google-chrome";

function pngDimensions(file) {
  const bytes = fs.readFileSync(file);
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  if (bytes.length < 33 || !bytes.subarray(0, 8).equals(signature)) {
    throw new Error(`${file} is not a complete PNG`);
  }
  if (bytes.subarray(12, 16).toString("ascii") !== "IHDR") {
    throw new Error(`${file} has no PNG IHDR`);
  }
  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
}

async function main() {
  fs.mkdirSync(outputDir, { recursive: true });
  const snapshots = new Map();
  const stylesheetCache = new Map();

  // Materialize every server-rendered variant before starting Chrome. Hosted
  // runners may reclaim the small Next process while Chrome is rendering a
  // tall page; later captures must not depend on that process still existing.
  for (const capture of matrix.captures) {
    const snapshotKey = `${capture.locale}-${capture.textScale}`;
    if (snapshots.has(snapshotKey)) continue;

    const query = capture.textScale === 200 ? "?textScale=200" : "";
    const url = `${baseUrl}/gallery${query}`;
    let response;
    try {
      response = await fetch(url, {
        headers: { "accept-language": capture.locale },
      });
    } catch (error) {
      throw new Error(`${snapshotKey} could not reach ${url}`, { cause: error });
    }
    if (!response.ok) throw new Error(`${url} returned ${response.status}`);
    let html = await response.text();
    const languageMarker =
      capture.locale === "fr" ? "Galerie de composants" : "Component gallery";
    if (!html.includes(languageMarker)) {
      throw new Error(`${snapshotKey} did not render the requested ${capture.locale} catalog`);
    }

    const stylesheetLinks = (html.match(/<link\b[^>]*>/gi) || []).filter(link =>
      /\brel=["']stylesheet["']/i.test(link),
    );
    const styles = [];
    for (const link of stylesheetLinks) {
      const match = link.match(/\bhref=["']([^"']+)["']/i);
      if (!match) throw new Error(`${snapshotKey} has a stylesheet link without an href`);
      const stylesheetUrl = new URL(match[1], baseUrl).href;
      let css = stylesheetCache.get(stylesheetUrl);
      if (css === undefined) {
        const stylesheetResponse = await fetch(stylesheetUrl);
        if (!stylesheetResponse.ok) {
          throw new Error(`${stylesheetUrl} returned ${stylesheetResponse.status}`);
        }
        css = await stylesheetResponse.text();
        stylesheetCache.set(stylesheetUrl, css);
      }
      styles.push(css);
    }
    if (styles.length === 0) throw new Error(`${snapshotKey} contains no production stylesheet`);

    html = html
      .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "")
      .replace(/<link\b[^>]*\brel=["']stylesheet["'][^>]*>/gi, "")
      .replace("</head>", `<style>${styles.join("\n")}</style></head>`)
      .replace(
        "</body>",
        `<script>document.documentElement.dataset.horizontalOverflow = String(document.documentElement.scrollWidth > document.documentElement.clientWidth)</script></body>`,
      );
    const snapshot = path.join(outputDir, `${snapshotKey}.html`);
    fs.writeFileSync(snapshot, html);
    snapshots.set(snapshotKey, { file: snapshot, sourceUrl: url });
  }

  const observed = [];
  for (const capture of matrix.captures) {
    const snapshotKey = `${capture.locale}-${capture.textScale}`;
    const snapshot = snapshots.get(snapshotKey);
    if (!snapshot) throw new Error(`${capture.name} has no rendered source snapshot`);

    const file = path.join(outputDir, `${capture.name}.png`);
    const browserArgs = [
      "--headless=new",
      "--no-sandbox",
      "--disable-gpu",
      "--disable-dev-shm-usage",
      "--hide-scrollbars",
      `--window-size=${capture.width},${capture.height}`,
      `--lang=${capture.locale}`,
      `--accept-lang=${capture.locale}`,
    ];
    const snapshotUrl = pathToFileURL(snapshot.file).href;
    const overflowProbe = spawnSync(chrome, [...browserArgs, "--dump-dom", snapshotUrl], {
      encoding: "utf8",
    });
    if (overflowProbe.status !== 0) {
      throw new Error(
        `Chrome overflow probe failed for ${capture.name}: ${overflowProbe.stderr || overflowProbe.stdout}`,
      );
    }
    if (!overflowProbe.stdout.includes('data-horizontal-overflow="false"')) {
      throw new Error(`${capture.name} has content wider than its ${capture.width}px viewport`);
    }
    const result = spawnSync(
      chrome,
      [
        ...browserArgs,
        `--screenshot=${file}`,
        snapshotUrl,
      ],
      { encoding: "utf8" },
    );
    if (result.status !== 0) {
      throw new Error(
        `Chrome failed for ${capture.name}: ${result.stderr || result.stdout}`,
      );
    }
    const dimensions = pngDimensions(file);
    if (dimensions.width !== capture.width || dimensions.height !== capture.height) {
      throw new Error(
        `${capture.name} is ${dimensions.width}x${dimensions.height}; expected ${capture.width}x${capture.height}`,
      );
    }
    observed.push({
      ...capture,
      file: `${capture.name}.png`,
      sourceUrl: snapshot.sourceUrl,
      sourceSnapshot: path.basename(snapshot.file),
      ...dimensions,
    });
  }

  const version = spawnSync(chrome, ["--version"], { encoding: "utf8" });
  fs.writeFileSync(
    path.join(outputDir, "manifest.json"),
    `${JSON.stringify(
      {
        generatedAt: new Date().toISOString(),
        browser: version.stdout.trim(),
        note: "textScale 200 doubles the gallery typography tokens while preserving the requested viewport width",
        captures: observed,
      },
      null,
      2,
    )}\n`,
  );
  process.stdout.write(
    `Captured and validated ${observed.length} dashboard screenshots in ${outputDir}\n`,
  );
}

main().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
