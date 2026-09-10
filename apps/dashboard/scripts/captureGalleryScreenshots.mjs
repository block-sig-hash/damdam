import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

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
  const observed = [];
  for (const capture of matrix.captures) {
    const query = capture.textScale === 200 ? "?textScale=200" : "";
    const url = `${baseUrl}/gallery${query}`;
    let response;
    try {
      response = await fetch(url, {
        headers: { "accept-language": capture.locale },
      });
    } catch (error) {
      throw new Error(`${capture.name} could not reach ${url}`, { cause: error });
    }
    if (!response.ok) throw new Error(`${url} returned ${response.status}`);
    const html = await response.text();
    const languageMarker =
      capture.locale === "fr" ? "Galerie de composants" : "Component gallery";
    if (!html.includes(languageMarker)) {
      throw new Error(
        `${capture.name} did not render the requested ${capture.locale} catalog`,
      );
    }

    const file = path.join(outputDir, `${capture.name}.png`);
    const result = spawnSync(
      chrome,
      [
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--hide-scrollbars",
        `--window-size=${capture.width},${capture.height}`,
        `--lang=${capture.locale}`,
        `--accept-lang=${capture.locale}`,
        `--screenshot=${file}`,
        url,
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
    observed.push({ ...capture, file: `${capture.name}.png`, url, ...dimensions });
  }

  const version = spawnSync(chrome, ["--version"], { encoding: "utf8" });
  fs.writeFileSync(
    path.join(outputDir, "manifest.json"),
    `${JSON.stringify(
      {
        generatedAt: new Date().toISOString(),
        browser: version.stdout.trim(),
        note: "textScale 200 uses CSS zoom on the gallery to exercise layout at browser-equivalent 200% scaling",
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
