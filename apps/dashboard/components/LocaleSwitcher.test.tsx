import {cleanup, render, screen} from "@testing-library/react";
import {NextIntlClientProvider} from "next-intl";
import {afterEach, describe, expect, it} from "vitest";

import en from "@/messages/en.json";
import fr from "@/messages/fr.json";

import {LocaleSwitcher} from "./LocaleSwitcher";

describe("LocaleSwitcher", () => {
  afterEach(cleanup);
  it.each([
    ["en", en, "Language"],
    ["fr", fr, "Langue"],
  ] as const)("renders the %s catalog", (locale, messages, label) => {
    render(
      <NextIntlClientProvider locale={locale} messages={messages}>
        <LocaleSwitcher />
      </NextIntlClientProvider>,
    );

    expect(screen.getByRole("group", {name: label})).toBeInTheDocument();
    expect(screen.getByRole("button", {name: "Français"})).toBeInTheDocument();
  });

});
