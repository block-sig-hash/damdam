import {
  render as renderWithoutIntl,
  type RenderOptions,
  type RenderResult,
} from "@testing-library/react";
import {NextIntlClientProvider} from "next-intl";
import type {ReactElement} from "react";

import messages from "@/messages/en.json";

export * from "@testing-library/react";

export function render(
  ui: ReactElement,
  options?: Omit<RenderOptions, "wrapper">,
): RenderResult {
  return renderWithoutIntl(
    <NextIntlClientProvider locale="en" messages={messages}>
      {ui}
    </NextIntlClientProvider>,
    options,
  );
}
