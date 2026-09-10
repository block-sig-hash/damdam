/**
 * Joins already-punctuated sentences into one accessibility label.
 *
 * Naive `parts.join('. ')` produces "38 lines are ready.. Retrying does not
 * charge you again." — the copy already ends its sentences, so adding another
 * full stop doubles it. A screen reader renders that as an extra pause, and a
 * label built from translated strings hits it in every locale at once.
 */
export function announce(...parts: (string | undefined | null)[]): string {
  return parts
    .filter((part): part is string => Boolean(part && part.trim()))
    .map(part => part.trim())
    .map(part => (/[.!?…:]$/.test(part) ? part : `${part}.`))
    .join(' ');
}
