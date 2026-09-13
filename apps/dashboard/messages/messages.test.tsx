import {cleanup, render, screen, within} from "@testing-library/react";
import {NextIntlClientProvider} from "next-intl";
import {describe, expect, it, vi} from "vitest";

import CallsPage from "@/app/calls/page";
import LoginPage from "@/app/login/page";
import en from "./en.json";
import fr from "./fr.json";

vi.mock("next/navigation", () => ({
  useRouter: () => ({push: vi.fn()}),
}));

function keys(value: unknown, prefix = ""): string[] {
  if (!value || typeof value !== "object") return [prefix];
  return Object.entries(value).flatMap(([key, nested]) =>
    keys(nested, prefix ? `${prefix}.${key}` : key),
  );
}

describe("dashboard locale catalogs", () => {
  it("keeps the French catalog structurally aligned with English", () => {
    expect(keys(fr).sort()).toEqual(keys(en).sort());
  });

  it("renders the same real route in English and French", () => {
    const english = render(
      <NextIntlClientProvider locale="en" messages={en}>
        <LoginPage />
      </NextIntlClientProvider>,
    );
    expect(screen.getByRole("heading", {name: "Sign in"})).toBeInTheDocument();
    english.unmount();

    render(
      <NextIntlClientProvider locale="fr" messages={fr}>
        <LoginPage />
      </NextIntlClientProvider>,
    );
    expect(
      screen.getByRole("heading", {name: "Se connecter"}),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Adresse e-mail")).toBeInTheDocument();
  });

  it("renders the consumer calling route in English and French (US-48)", async () => {
    // The signed-out state, which is what a new visitor meets and the one that
    // has to say — in both languages — that an operator or staff sign-in does
    // not open this page.
    //
    // Queries from `render` bind to `document.body`, not to the container, so a
    // leftover render from the test above would still match: both pages have an
    // "Adresse e-mail" field. `cleanup` plus `within(container)` is what keeps
    // this test about this route.
    cleanup();
    const english = render(
      <NextIntlClientProvider locale="en" messages={en}>
        <CallsPage />
      </NextIntlClientProvider>,
    );
    const inEnglish = within(english.container);
    expect(
      await inEnglish.findByRole("heading", {name: "Sign in to call"}),
    ).toBeInTheDocument();
    expect(inEnglish.getByLabelText("Email address")).toBeInTheDocument();
    english.unmount();

    const french = render(
      <NextIntlClientProvider locale="fr" messages={fr}>
        <CallsPage />
      </NextIntlClientProvider>,
    );
    const inFrench = within(french.container);
    expect(
      await inFrench.findByRole("heading", {
        name: "Connectez-vous pour appeler",
      }),
    ).toBeInTheDocument();
    expect(inFrench.getByLabelText("Adresse e-mail")).toBeInTheDocument();
  });
});
