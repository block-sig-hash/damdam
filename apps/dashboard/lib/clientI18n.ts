import en from "@/messages/en.json";
import fr from "@/messages/fr.json";

type ClientMessageKey =
  | "common.errors.adminRequired"
  | "common.errors.generic"
  | "common.errors.push"
  | "common.errors.sosTitle"
  | "common.errors.signInRequired";

const catalogs = {en, fr} as const;

export function getClientLocale(): "en" | "fr" {
  if (typeof window === "undefined") return "en";
  return window.localStorage.getItem("damdam_locale") === "fr" ? "fr" : "en";
}

export function clientMessage(key: ClientMessageKey): string {
  let value: unknown = catalogs[getClientLocale()];
  for (const segment of key.split(".")) {
    value = typeof value === "object" && value !== null
      ? (value as Record<string, unknown>)[segment]
      : undefined;
  }
  return typeof value === "string" ? value : key;
}

export function localeHeader(): {"Accept-Language": "en" | "fr"} {
  return {"Accept-Language": getClientLocale()};
}
