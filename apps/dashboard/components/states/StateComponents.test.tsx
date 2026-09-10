/**
 * The dashboard's state components, held to the same promises as the mobile
 * ones — because the point of a shared design system is that "Not connected"
 * means the same thing and looks the same in both places.
 *
 * The enterprise angle is what shifts. A stale usage reading here is what a
 * budget decision gets made on, and a partial failure is forty people's
 * connectivity rather than one person's, so both are tested for saying enough
 * to act on rather than merely rendering.
 */

import { cleanup, render, screen } from "@/test-utils";
import { afterEach, describe, expect, it } from "vitest";

import {
  PartialFailureNotice,
  StateMessage,
  StatusPill,
  UsageMeter,
} from "./StateComponents";
import en from "@/messages/en.json";
import fr from "@/messages/fr.json";

// Renders accumulate in one document otherwise, and two components sharing a
// testId make getByTestId ambiguous rather than failing usefully.
afterEach(cleanup);

describe("StatusPill", () => {
  it("names the question it answers for anyone not looking at the column header", () => {
    render(<StatusPill family="Network" label="Not connected" tone="caution" testId="pill" />);
    // A table row of five pills is five unattached words to a screen reader.
    expect(screen.getByTestId("pill")).toHaveTextContent("Network: Not connected");
  });

  it("uses a tint fill for every tone, never a saturated fill with white text", () => {
    for (const tone of ["neutral", "progress", "positive", "caution", "negative"] as const) {
      render(<StatusPill family="f" label="x" tone={tone} testId={`pill-${tone}`} />);
      expect(screen.getByTestId(`pill-${tone}`).className).toContain(`status-pill-${tone}`);
    }
  });
});

describe("UsageMeter", () => {
  it("marks a never-reported reading as unknown rather than full", () => {
    // A full bar here is an invented number, and somebody budgets against it.
    render(
      <UsageMeter
        label="Data"
        remaining="—"
        total="1 TB"
        fraction={0}
        updatedLabel={null}
        testId="meter"
      />,
    );
    const fill = screen.getByTestId("meter-track").firstElementChild as HTMLElement;
    expect(fill.dataset.severity).toBe("unknown");
    expect(fill.style.width).toBe("0%");
  });

  it("escalates severity as the balance falls", () => {
    const cases: [number, string][] = [
      [0.8, "healthy"],
      [0.1, "low"],
      [0.02, "critical"],
    ];
    for (const [fraction, severity] of cases) {
      render(
        <UsageMeter
          label="Data"
          remaining="x"
          total="y"
          fraction={fraction}
          updatedLabel="Updated"
          testId={`meter-${severity}`}
        />,
      );
      const fill = screen.getByTestId(`meter-${severity}-track`).firstElementChild as HTMLElement;
      expect(fill.dataset.severity).toBe(severity);
    }
  });

  it("clamps an over-report rather than overflowing the track", () => {
    render(
      <UsageMeter
        label="Data"
        remaining="x"
        total="y"
        fraction={2}
        updatedLabel="Updated"
        testId="meter"
      />,
    );
    const fill = screen.getByTestId("meter-track").firstElementChild as HTMLElement;
    expect(fill.style.width).toBe("100%");
  });

  it("exposes its value to assistive technology", () => {
    render(
      <UsageMeter
        label="Data"
        remaining="412 GB"
        total="1 TB"
        fraction={0.41}
        updatedLabel="Updated"
        testId="meter"
      />,
    );
    const track = screen.getByTestId("meter-track");
    expect(track).toHaveAttribute("role", "progressbar");
    expect(track).toHaveAttribute("aria-valuenow", "41");
  });

  it("always states how old the reading is", () => {
    render(
      <UsageMeter
        label="Calls"
        remaining="140 min"
        total="4 000 min"
        fraction={0.035}
        updatedLabel="Last updated 3 h"
        stale
        explanation="Usage can take a little while to reach us."
        testId="meter"
      />,
    );
    expect(screen.getByTestId("meter-updated")).toHaveTextContent("Last updated 3 h");
    expect(screen.getByTestId("meter-updated").className).toContain("is-stale");
  });
});

describe("StateMessage", () => {
  it("keeps empty, pending, blocked and failed visually distinct", () => {
    for (const variant of ["empty", "pending", "blocked", "error"] as const) {
      render(<StateMessage variant={variant} title="t" body="b" testId={`state-${variant}`} />);
      expect(screen.getByTestId(`state-${variant}`).className).toContain(
        `state-message-${variant}`,
      );
    }
  });

  it("labels the region by its own heading", () => {
    // So a screen reader announces "Some phones cannot use an eSIM, region"
    // rather than landing the user in an unnamed box.
    render(<StateMessage variant="blocked" title="Blocked" body="b" testId="state" />);
    const region = screen.getByTestId("state");
    expect(region.getAttribute("aria-labelledby")).toBe("state-title");
    expect(document.getElementById("state-title")).toHaveTextContent("Blocked");
  });
});

describe("PartialFailureNotice", () => {
  it("says out loud that a retry does not charge again", () => {
    render(
      <PartialFailureNotice
        title="2 of 40 lines could not be set up"
        body="38 lines are ready and assigned."
        noChargeNote="Retrying does not charge the organization again."
        testId="partial"
      />,
    );
    expect(screen.getByTestId("partial-no-charge")).toHaveTextContent(
      "Retrying does not charge the organization again.",
    );
  });
});

describe("the copy behind these components", () => {
  it("states the no-double-charge promise in both locales", () => {
    // The single most expensive misunderstanding in a bulk retry, and the one
    // most likely to be dropped in translation.
    expect(en.states.partialFailure.noCharge).toMatch(/not charge/i);
    expect(fr.states.partialFailure.noCharge).toMatch(/ne débite pas/i);
  });

  it("explains what a stale reading means for a budget, not just that it is stale", () => {
    expect(en.states.usage.staleExplanation).toMatch(/budget/i);
    expect(fr.states.usage.staleExplanation).toMatch(/budget/i);
  });

  it("no longer titles the product as a Hajj tour-operator tool", () => {
    // prd.md §10 reset the product a chunk ago; the browser title and meta
    // description had not moved with it. Scoped to `common.metadata` on
    // purpose: the HTO/pilgrim copy still in `auth`, `home`, `manifests`,
    // `admin` and `reports` belongs to the screens chunks 22-24 rebuild, and
    // rewriting it here would break their tests to no benefit. Recorded in the
    // chunk 08 handoff as inherited scope rather than silently half-done.
    for (const catalog of [en, fr]) {
      expect(JSON.stringify(catalog.common.metadata)).not.toMatch(/hajj|pilgrim|operator/i);
    }
    expect(en.common.metadata.title).toBe("DamDam Organization Dashboard");
  });
});
