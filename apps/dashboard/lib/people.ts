import { clientMessage, localeHeader } from "./clientI18n";

/**
 * Organization people, teams, cost centres and imports (US-39, chunk 22).
 *
 * Mirrors `apps/api/app/people/schemas.py`. Two things are deliberately absent
 * from every type here, and their absence is the point:
 *
 * **A person has no role.** The API does not send one because a person does not
 * have one — access is a membership, which lives on a different screen behind a
 * different permission. A `role` field on `Person` would be the first step
 * towards an import that grants it.
 *
 * **An import returns codes, not sentences.** `error_codes` is localized by the
 * dashboard, so an administrator reading a failed row gets it in their own
 * language, and a new failure reason added by the server does not ship as
 * untranslated English.
 */

export type PersonStatus = "active" | "archived";

export type Person = {
  person_id: string;
  full_name: string;
  email: string | null;
  phone_number: string | null;
  external_reference: string | null;
  job_title: string | null;
  team_id: string | null;
  cost_centre_id: string | null;
  status: PersonStatus;
  /** Whether they have claimed an account — never a claim about the address. */
  has_account: boolean;
};

export type Team = {
  team_id: string;
  name: string;
  cost_centre_id: string | null;
  archived_at: string | null;
};

export type CostCentre = {
  cost_centre_id: string;
  code: string;
  name: string;
  archived_at: string | null;
};

export type ImportState =
  | "previewed"
  | "applying"
  | "applied"
  | "cancelled"
  | "rejected";

export type ImportSummary = {
  import_id: string;
  state: ImportState;
  filename: string;
  row_count: number;
  valid_count: number;
  invalid_count: number;
  created_count: number;
  updated_count: number;
  rejection_code: string | null;
  created_at: string;
  applied_at: string | null;
};

export type ImportRow = {
  row_number: number;
  state: string;
  error_codes: string[];
  payload: Record<string, unknown>;
};

export type ImportPreview = {
  summary: ImportSummary;
  sample_rows: ImportRow[];
  ignored_columns: string[];
};

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/v1";

type APIError = { error?: string; message?: string };

function authHeaders(): HeadersInit {
  const token = window.localStorage.getItem("hto_access_token");
  if (!token) {
    throw new Error(clientMessage("common.errors.signInRequired"));
  }
  return { Authorization: `Bearer ${token}`, ...localeHeader() };
}

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const error = (await response.json().catch(() => ({}))) as APIError;
    throw new Error(error.message ?? clientMessage("common.errors.generic"));
  }
  return (await response.json()) as T;
}

export async function fetchPeople(
  organizationId: string,
  options: { teamId?: string; includeArchived?: boolean } = {},
): Promise<Person[]> {
  const query = new URLSearchParams();
  if (options.teamId) query.set("team_id", options.teamId);
  if (options.includeArchived) query.set("include_archived", "true");
  const suffix = query.toString() ? `?${query}` : "";
  const response = await fetch(
    `${API_BASE_URL}/organizations/${organizationId}/people${suffix}`,
    { headers: authHeaders() },
  );
  const result = await parse<{ people: Person[] }>(response);
  return result.people;
}

export async function fetchTeams(organizationId: string): Promise<Team[]> {
  const response = await fetch(
    `${API_BASE_URL}/organizations/${organizationId}/teams`,
    { headers: authHeaders() },
  );
  const result = await parse<{ teams: Team[] }>(response);
  return result.teams;
}

export async function createTeam(
  organizationId: string,
  name: string,
  costCentreId?: string,
): Promise<Team> {
  const response = await fetch(
    `${API_BASE_URL}/organizations/${organizationId}/teams`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({
        name,
        cost_centre_id: costCentreId ?? null,
      }),
    },
  );
  return parse<Team>(response);
}

export async function fetchCostCentres(
  organizationId: string,
): Promise<CostCentre[]> {
  const response = await fetch(
    `${API_BASE_URL}/organizations/${organizationId}/cost-centres`,
    { headers: authHeaders() },
  );
  const result = await parse<{ cost_centres: CostCentre[] }>(response);
  return result.cost_centres;
}

export async function createCostCentre(
  organizationId: string,
  code: string,
  name: string,
): Promise<CostCentre> {
  const response = await fetch(
    `${API_BASE_URL}/organizations/${organizationId}/cost-centres`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ code, name }),
    },
  );
  return parse<CostCentre>(response);
}

/**
 * Upload a file for preview. Creates nobody.
 *
 * The same bytes uploaded twice come back as the same import, so a double click
 * or a lost response does not leave an administrator choosing between two
 * previews of their own staff.
 */
export async function uploadPeopleFile(
  organizationId: string,
  file: File,
): Promise<ImportPreview> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(
    `${API_BASE_URL}/organizations/${organizationId}/people/imports`,
    { method: "POST", headers: authHeaders(), body: form },
  );
  return parse<ImportPreview>(response);
}

export async function applyPeopleImport(
  organizationId: string,
  importId: string,
): Promise<ImportSummary> {
  const response = await fetch(
    `${API_BASE_URL}/organizations/${organizationId}/people/imports/${importId}/apply`,
    { method: "POST", headers: authHeaders() },
  );
  return parse<ImportSummary>(response);
}

export async function cancelPeopleImport(
  organizationId: string,
  importId: string,
): Promise<ImportSummary> {
  const response = await fetch(
    `${API_BASE_URL}/organizations/${organizationId}/people/imports/${importId}/cancel`,
    { method: "POST", headers: authHeaders() },
  );
  return parse<ImportSummary>(response);
}

export async function fetchImportRows(
  organizationId: string,
  importId: string,
  onlyInvalid = false,
): Promise<ImportRow[]> {
  const suffix = onlyInvalid ? "?only_invalid=true" : "";
  const response = await fetch(
    `${API_BASE_URL}/organizations/${organizationId}/people/imports/${importId}/rows${suffix}`,
    { headers: authHeaders() },
  );
  const result = await parse<{ rows: ImportRow[] }>(response);
  return result.rows;
}

/**
 * The download URL for this organization's people.
 *
 * Built rather than navigated to directly, because the export needs the
 * Authorization header — a plain `<a href>` would send the browser without it
 * and produce a 401 that looks like a broken button.
 */
export async function downloadPeopleCsv(
  organizationId: string,
): Promise<Blob> {
  const response = await fetch(
    `${API_BASE_URL}/organizations/${organizationId}/people.csv`,
    { headers: authHeaders() },
  );
  if (!response.ok) {
    throw new Error(clientMessage("common.errors.generic"));
  }
  return response.blob();
}
