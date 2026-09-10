/**
 * The dashboard's half of the shared design system.
 *
 * Two things are guarded here, and the second is the one that matters over
 * time:
 *
 * 1. `tokens.css` still matches what `design-tokens/build.js` would write, so
 *    a hand-edit to the generated file is caught rather than silently becoming
 *    the dashboard's private palette again.
 * 2. `globals.css` contains **no raw colour literals**. Before chunk 08 it
 *    carried around twenty of them, none documented anywhere. A second palette
 *    never reappears all at once — it reappears one "just this once" hex at a
 *    time, and only a mechanical check notices that happening.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { contrastRatio, AA_BODY_TEXT } from "../../../design-tokens/contrast.js";
import { dashboardTokens } from "../../../design-tokens/build.js";
import source from "../../../design-tokens/tokens.json";

const APP_DIR = join(__dirname);
const read = (file: string) => readFileSync(join(APP_DIR, file), "utf8");

describe("the generated stylesheet has not drifted from its source", () => {
  it("matches what design-tokens/build.js would write today", () => {
    expect(read("tokens.css")).toBe(dashboardTokens());
  });

  it("declares a custom property for every colour in the source", () => {
    const css = read("tokens.css");
    for (const name of Object.keys(source.color)) {
      const property = `--color-${name
        .replace(/([a-z])(\d)/g, "$1-$2")
        .replace(/([a-z])([A-Z])/g, "$1-$2")
        .toLowerCase()}`;
      expect(css).toContain(`${property}: ${source.color[name as keyof typeof source.color]};`);
    }
  });
});

describe("globals.css uses tokens and nothing else", () => {
  const css = read("globals.css");

  it("declares no raw hex colour", () => {
    // Comments are stripped first: the header explains the migration by naming
    // the hexes it removed, and quoting them there is the point.
    const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, "");
    const literals = withoutComments.match(/#[0-9a-fA-F]{3,8}\b/g) ?? [];
    expect(literals).toEqual([]);
  });

  it("declares no raw rgb/rgba/hsl colour either", () => {
    const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, "");
    const functional = withoutComments.match(/\b(rgba?|hsla?)\s*\(/g) ?? [];
    expect(functional).toEqual([]);
  });

  it("imports the generated tokens", () => {
    expect(css).toContain('@import "./tokens.css";');
  });

  it("references only custom properties that are actually declared", () => {
    const declarations = new Set(
      [...`${read("tokens.css")}\n${css}`.matchAll(/(--[a-z0-9-]+)\s*:/gi)].map(
        match => match[1],
      ),
    );
    const references = [...css.matchAll(/var\((--[a-z0-9-]+)/gi)].map(match => match[1]);
    expect([...new Set(references)].filter(name => !declarations.has(name))).toEqual([]);
  });

  it("gives interactive controls a real touch target", () => {
    expect(css).toContain("min-height: var(--min-touch-target)");
    expect(css).toContain("min-height: var(--min-input-height)");
  });

  it("keeps a visible focus ring at full brand saturation", () => {
    // A pale tint ring is the common regression here, and it is unusable for
    // exactly the people who depend on it.
    expect(css).toMatch(/:focus-visible[^}]*outline:\s*3px solid var\(--color-primary-500\)/);
  });
});

describe("the pairings globals.css actually uses clear AA", () => {
  const { color } = source;

  it.each([
    ["body text on the page background", color.gray900, color.gray50],
    ["body text on a card", color.gray900, color.white],
    ["secondary/hint text on a card", color.gray600, color.white],
    ["a link on a card", color.primary500, color.white],
    ["a primary button label", color.white, color.primary500],
    ["a secondary button label on its tint", color.primary500, color.primary100],
    ["an error message on a card", color.error700, color.white],
    ["a warning message on a card", color.warning700, color.white],
    ["a neutral status pill", color.gray900, color.gray100],
    ["a provisioned status pill", color.gray900, color.success100],
    ["a rejected status pill", color.gray900, color.error100],
    ["a follow-up status pill", color.warning700, color.warning100],
    ["an overdue row", color.gray900, color.warning100],
  ])("%s", (_label, foreground, background) => {
    expect(contrastRatio(foreground, background)).toBeGreaterThanOrEqual(AA_BODY_TEXT);
  });
});
