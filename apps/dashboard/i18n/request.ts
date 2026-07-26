import {cookies, headers} from "next/headers";
import {getRequestConfig} from "next-intl/server";

import {normalizeLocale} from "./locale";

export default getRequestConfig(async () => {
  const cookieStore = await cookies();
  const requestHeaders = await headers();
  const locale = normalizeLocale(
    cookieStore.get("damdam_locale")?.value ??
      requestHeaders.get("accept-language"),
  );
  return {
    locale,
    messages: (await import(`../messages/${locale}.json`)).default,
  };
});
