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

export async function registerHTO(payload: HTORegistration): Promise<void> {
  await request("/auth/hto/register", payload);
}

export async function verifyHTOEmail(token: string): Promise<void> {
  await request("/auth/hto/verify-email", { token });
}
