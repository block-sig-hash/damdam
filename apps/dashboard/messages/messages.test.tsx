import {render, screen} from "@testing-library/react";
import {NextIntlClientProvider} from "next-intl";
import {describe, expect, it, vi} from "vitest";

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
});
