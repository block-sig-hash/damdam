"use client";

import {useLocale, useTranslations} from "next-intl";

import type {AppLocale} from "@/i18n/locale";

function persistAndReload(locale: AppLocale) {
  document.cookie = `damdam_locale=${locale}; Path=/; Max-Age=31536000; SameSite=Lax`;
  window.localStorage.setItem("damdam_locale", locale);
  window.location.reload();
}

export function LocaleSwitcher() {
  const locale = useLocale() as AppLocale;
  const t = useTranslations("common.language");

  return (
    <div aria-label={t("label")} role="group">
      {(["en", "fr"] as const).map((item) => (
        <button
          aria-pressed={locale === item}
          key={item}
          onClick={() => persistAndReload(item)}
          type="button"
        >
          {item === "en" ? t("english") : t("french")}
        </button>
      ))}
    </div>
  );
}
