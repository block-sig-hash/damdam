export type HTORegistration = {
  business_name: string;
  operator_name: string;
  email: string;
  password: string;
  phone_number: string;
  nahcon_licence_number: string;
};

export type SOSAlert = {
  id: string;
  pilgrim_name: string;
  pilgrim_phone: string;
  timestamp: string;
  latitude: number | null;
  longitude: number | null;
  status: "active" | "resolved" | "cancelled";
};

export async function getSOSAlerts(
  status?: "active" | "resolved",
): Promise<SOSAlert[]> {
  const query = status ? `?status=${status}` : "?status=";
  const response = await fetch(`${API_BASE_URL}/hto/sos-alerts${query}`, {
    headers: operatorHeaders(),
  });
  return (await parseResponse<{alerts: SOSAlert[]}>(response)).alerts;
}

export async function resolveSOSAlert(id: string): Promise<void> {
  await parseResponse(
    await fetch(`${API_BASE_URL}/hto/sos-alerts/${id}/resolve`, {
      method: "POST",
      headers: operatorHeaders(),
    }),
  );
}

export async function subscribeToPushTopic(fcmToken: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/hto/push-subscriptions`, {
    method: "POST",
    headers: {...operatorHeaders(), "Content-Type": "application/json"},
    body: JSON.stringify({fcm_token: fcmToken}),
  });
  if (!response.ok) {
    const error = (await response.json().catch(() => ({}))) as APIError;
    throw new Error(error.message ?? "Could not enable browser alerts.");
  }
  // 204 No Content on success -- nothing to parse.
}

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
    throw new Error("Sign in to continue.");
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

export type UnorderedPilgrim = {
  id: string;
  name: string;
  phone_number: string;
  family_group_id: string | null;
};

export type PricingTier = {
  id: string;
  name: string;
  retail_price_ngn: number;
  wholesale_price_ngn: number;
  estimated_margin_ngn: number;
  is_group_tier: boolean;
  min_group_size: number | null;
  max_group_size: number | null;
};

export type ManifestOrder = {
  id: string;
  tier_name: string;
  pilgrim_count: number;
  total_ngn: number;
  status: "awaiting_payment" | "paid" | "provisioning" | "provisioned";
};

export async function getUnorderedPilgrims(
  manifestId: string,
): Promise<UnorderedPilgrim[]> {
  const response = await fetch(
    `${API_BASE_URL}/hto/manifests/${manifestId}/unordered-pilgrims`,
    { headers: operatorHeaders() },
  );
  return (await parseResponse<{ pilgrims: UnorderedPilgrim[] }>(response)).pilgrims;
}

export async function getPricingTiers(): Promise<PricingTier[]> {
  const response = await fetch(`${API_BASE_URL}/hto/pricing-tiers`, {
    headers: operatorHeaders(),
  });
  return (await parseResponse<{ tiers: PricingTier[] }>(response)).tiers;
}

export async function createFamilyGroup(
  manifestId: string,
  pilgrimIds: string[],
): Promise<string> {
  const response = await fetch(`${API_BASE_URL}/hto/manifests/${manifestId}/group`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...operatorHeaders() },
    body: JSON.stringify({ manifest_pilgrim_ids: pilgrimIds, group_size: pilgrimIds.length }),
  });
  return (await parseResponse<{ family_group_id: string }>(response)).family_group_id;
}

export async function updateFamilyGroup(
  manifestId: string,
  groupId: string,
  pilgrimIds: string[],
): Promise<void> {
  await parseResponse(
    await fetch(`${API_BASE_URL}/hto/manifests/${manifestId}/group/${groupId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...operatorHeaders() },
      body: JSON.stringify({ manifest_pilgrim_ids: pilgrimIds, group_size: pilgrimIds.length }),
    }),
  );
}

export async function deleteFamilyGroup(
  manifestId: string,
  groupId: string,
): Promise<void> {
  const response = await fetch(
    `${API_BASE_URL}/hto/manifests/${manifestId}/group/${groupId}`,
    { method: "DELETE", headers: operatorHeaders() },
  );
  if (!response.ok) await parseResponse(response);
}

export async function placeManifestOrder(
  manifestId: string,
  pricingTierId: string,
  pilgrimIds: string[],
): Promise<{ manifest_order_id: string; total_ngn: number; invoice_url: string }> {
  return parseResponse(
    await fetch(`${API_BASE_URL}/hto/manifests/${manifestId}/order`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...operatorHeaders() },
      body: JSON.stringify({
        pricing_tier_id: pricingTierId,
        manifest_pilgrim_ids: pilgrimIds,
      }),
    }),
  );
}

export async function getManifestOrders(manifestId: string): Promise<ManifestOrder[]> {
  const response = await fetch(`${API_BASE_URL}/hto/manifests/${manifestId}/orders`, {
    headers: operatorHeaders(),
  });
  return (await parseResponse<{ orders: ManifestOrder[] }>(response)).orders;
}

export type HtoPilgrim = {
  id: string;
  name: string;
  phone_number: string;
  tier: string | null;
  esim_status: string;
  activation_status: string;
  last_checkin_at: string | null;
  sos_status: string;
};

export async function getHtoPilgrims(manifestId: string): Promise<HtoPilgrim[]> {
  const query = new URLSearchParams({ manifest_id: manifestId });
  const response = await fetch(`${API_BASE_URL}/hto/pilgrims?${query}`, {
    headers: operatorHeaders(),
  });
  return (await parseResponse<{ pilgrims: HtoPilgrim[] }>(response)).pilgrims;
}

async function openPDF(path: string, headers: HeadersInit) {
  const response = await fetch(`${API_BASE_URL}${path}`, { headers });
  if (!response.ok) await parseResponse(response);
  const url = URL.createObjectURL(await response.blob());
  window.open(url, "_blank", "noopener,noreferrer");
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export async function openManifestInvoice(manifestId: string, orderId: string) {
  await openPDF(
    `/hto/manifests/${manifestId}/order/${orderId}/invoice`,
    operatorHeaders(),
  );
}

export type Manifest = {
  id: string;
  name: string | null;
  status: "draft" | "validated" | "partially_ordered" | "provisioned";
  valid_rows: number;
  created_at: string;
};

export async function getManifests(): Promise<Manifest[]> {
  const response = await fetch(`${API_BASE_URL}/hto/manifests`, {
    headers: operatorHeaders(),
  });
  return (await parseResponse<{ manifests: Manifest[] }>(response)).manifests;
}

export type ProvisioningReportFilter = {
  manifestId?: string;
  dateFrom?: string;
  dateTo?: string;
};

// AC-20.1: triggers a real browser file download (not a new tab, unlike
// openPDF above) since a CSV has no useful inline viewer to open into.
export async function downloadProvisioningReport(
  filter: ProvisioningReportFilter,
): Promise<void> {
  const query = new URLSearchParams();
  if (filter.manifestId) query.set("manifest_id", filter.manifestId);
  if (filter.dateFrom) query.set("date_from", filter.dateFrom);
  if (filter.dateTo) query.set("date_to", filter.dateTo);
  const response = await fetch(
    `${API_BASE_URL}/hto/reports/provisioning.csv?${query}`,
    { headers: operatorHeaders() },
  );
  if (!response.ok) await parseResponse(response);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = "provisioning-report.csv";
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

function adminHeaders(): HeadersInit {
  const token = window.localStorage.getItem("admin_access_token");
  if (!token) throw new Error("An administrator session is required.");
  return { Authorization: `Bearer ${token}` };
}

export type AdminManifestOrder = {
  id: string;
  hto_business_name: string;
  manifest_name: string | null;
  pilgrim_count: number;
  total_ngn: number;
  invoice_url: string;
  days_pending: number;
};

export async function getPendingManifestOrders(search = ""): Promise<AdminManifestOrder[]> {
  const query = new URLSearchParams({ status: "awaiting_payment" });
  if (search) query.set("search", search);
  const response = await fetch(`${API_BASE_URL}/admin/manifest-orders?${query}`, {
    headers: adminHeaders(),
  });
  return (await parseResponse<{ orders: AdminManifestOrder[] }>(response)).orders;
}

export async function confirmManifestPayment(orderId: string): Promise<void> {
  await parseResponse(
    await fetch(`${API_BASE_URL}/admin/manifest-orders/${orderId}/confirm-payment`, {
      method: "POST",
      headers: adminHeaders(),
    }),
  );
}

export async function openAdminInvoice(orderId: string): Promise<void> {
  await openPDF(`/admin/manifest-orders/${orderId}/invoice`, adminHeaders());
}

export type AdminPricingTier = {
  id: string;
  name: string;
  ngn_price: number;
  is_group_tier: boolean;
};

export type PricingTierUpdateResult = {
  id: string;
  name: string;
  old_ngn_price: number;
  new_ngn_price: number;
  percent_change: number;
  changed_at: string;
};

export async function getAdminPricingTiers(): Promise<AdminPricingTier[]> {
  const response = await fetch(`${API_BASE_URL}/admin/pricing-tiers`, {
    headers: adminHeaders(),
  });
  return (await parseResponse<{ tiers: AdminPricingTier[] }>(response)).tiers;
}

export async function updateAdminPricingTierPrice(
  tierId: string,
  ngnPrice: number,
): Promise<PricingTierUpdateResult> {
  return parseResponse(
    await fetch(`${API_BASE_URL}/admin/pricing-tiers/${tierId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...adminHeaders() },
      body: JSON.stringify({ ngn_price: ngnPrice }),
    }),
  );
}

export type HTOApprovalStatus = "pending" | "approved" | "rejected";

export type AdminHTOOperator = {
  id: string;
  business_name: string;
  operator_name: string;
  email: string;
  phone_number: string;
  nahcon_licence_number: string;
  email_verified: boolean;
  approval_status: HTOApprovalStatus;
  created_at: string;
};

export async function getAdminHTOOperators(
  status: HTOApprovalStatus = "pending",
): Promise<AdminHTOOperator[]> {
  const response = await fetch(`${API_BASE_URL}/admin/hto-operators?status=${status}`, {
    headers: adminHeaders(),
  });
  return (await parseResponse<{ operators: AdminHTOOperator[] }>(response)).operators;
}

export async function approveHTOOperator(operatorId: string): Promise<void> {
  await parseResponse(
    await fetch(`${API_BASE_URL}/admin/hto-operators/${operatorId}/approve`, {
      method: "POST",
      headers: adminHeaders(),
    }),
  );
}

export async function rejectHTOOperator(operatorId: string, reason: string): Promise<void> {
  await parseResponse(
    await fetch(`${API_BASE_URL}/admin/hto-operators/${operatorId}/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...adminHeaders() },
      body: JSON.stringify({ reason }),
    }),
  );
}

export type FailedSOSNotification = {
  id: string;
  pilgrim_name: string;
  channel: string;
  failure_reason: string | null;
  sos_timestamp: string;
  retry_count: number;
};

export async function getFailedSOSNotifications(): Promise<FailedSOSNotification[]> {
  const response = await fetch(`${API_BASE_URL}/admin/sos-notifications/failed`, {
    headers: adminHeaders(),
  });
  return (await parseResponse<{ notifications: FailedSOSNotification[] }>(response))
    .notifications;
}

export async function retrySOSNotification(id: string): Promise<void> {
  await parseResponse(
    await fetch(`${API_BASE_URL}/admin/sos-notifications/${id}/retry`, {
      method: "POST",
      headers: adminHeaders(),
    }),
  );
}

export async function retrySOSNotificationsBulk(ids: string[]): Promise<void> {
  await parseResponse(
    await fetch(`${API_BASE_URL}/admin/sos-notifications/retry-bulk`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...adminHeaders() },
      body: JSON.stringify({ notification_ids: ids }),
    }),
  );
}
