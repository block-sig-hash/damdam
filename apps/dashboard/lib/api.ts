export type HTORegistration = {
  business_name: string;
  operator_name: string;
  email: string;
  password: string;
  phone_number: string;
  nahcon_licence_number: string;
};

type APIError = {
  error?: string;
  message?: string;
};

export type ManifestPreviewRow = {
  id: string;
  row_number: number;
  first_name: string;
  last_name: string;
  phone_number: string;
  passport_number: string | null;
  seat_number: string | null;
  validation_status: "valid" | "duplicate_warning";
  warning: string | null;
};

export type ManifestUploadResult = {
  total_rows: number;
  valid_rows: number;
  invalid_rows: Array<{ row_number: number; reason: string }>;
  preview: ManifestPreviewRow[];
};

export type HTOLoginResult = {
  access_token: string;
  refresh_token: string;
};

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/v1";

async function request(path: string, body: unknown): Promise<void> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const error = (await response.json().catch(() => ({}))) as APIError;
    throw new Error(error.message ?? "Something went wrong. Please try again.");
  }
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const error = (await response.json().catch(() => ({}))) as APIError;
    throw new Error(error.message ?? "Something went wrong. Please try again.");
  }
  return (await response.json()) as T;
}

function operatorHeaders(): HeadersInit {
  const token = window.localStorage.getItem("hto_access_token");
  if (!token) {
    throw new Error("Sign in to upload a manifest.");
  }
  return { Authorization: `Bearer ${token}` };
}

export async function registerHTO(payload: HTORegistration): Promise<void> {
  await request("/auth/hto/register", payload);
}

export async function verifyHTOEmail(token: string): Promise<void> {
  await request("/auth/hto/verify-email", { token });
}

export async function loginHTO(email: string, password: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/auth/hto/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const result = await parseResponse<HTOLoginResult>(response);
  window.localStorage.setItem("hto_access_token", result.access_token);
  window.localStorage.setItem("hto_refresh_token", result.refresh_token);
}

export async function createManifest(name?: string): Promise<string> {
  const response = await fetch(`${API_BASE_URL}/hto/manifests`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...operatorHeaders() },
    body: JSON.stringify({ name: name || null }),
  });
  const result = await parseResponse<{ manifest_id: string }>(response);
  return result.manifest_id;
}

export async function uploadManifest(
  manifestId: string,
  file: File,
): Promise<ManifestUploadResult> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(
    `${API_BASE_URL}/hto/manifests/${manifestId}/upload`,
    { method: "POST", headers: operatorHeaders(), body: form },
  );
  return parseResponse<ManifestUploadResult>(response);
}

export async function confirmManifest(manifestId: string): Promise<number> {
  const response = await fetch(
    `${API_BASE_URL}/hto/manifests/${manifestId}/confirm`,
    { method: "POST", headers: operatorHeaders() },
  );
  const result = await parseResponse<{ pilgrim_count: number }>(response);
  return result.pilgrim_count;
}
