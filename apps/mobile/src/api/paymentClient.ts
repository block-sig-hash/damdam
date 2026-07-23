import { API_BASE_URL } from '../config/env';
import {i18n} from '../i18n';

export interface PurchaseCheckout {
  package_id: string;
  processor: 'paystack' | 'flutterwave';
  processor_reference: string;
  checkout_url: string;
}

export interface PackagePaymentStatus {
  status: 'pending' | 'active' | 'expired';
  data_gb_total: number;
  data_gb_remaining: number;
  pstn_minutes_total: number;
  pstn_minutes_remaining: number;
}

export interface PackageGeofence {
  latitude: number;
  longitude: number;
  radius_meters: number;
  request_id: string;
}

export class PaymentApiError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'PaymentApiError';
  }
}

async function request<T>(url: string, accessToken: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${url}`, {
      ...init,
      headers: {
        Authorization: `Bearer ${accessToken}`,
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...init?.headers,
      },
    });
  } catch {
    throw new PaymentApiError(i18n.t('errors.network', {ns: 'auth'}));
  }
  if (!response.ok) {
    throw new PaymentApiError(i18n.t('purchase.failedDefault', {ns: 'payments'}));
  }
  return (await response.json()) as T;
}

export function initializePurchase(
  accessToken: string,
  pricingTierId: string,
  groupSize?: number,
): Promise<PurchaseCheckout> {
  return request<PurchaseCheckout>('/packages/purchase', accessToken, {
    method: 'POST',
    body: JSON.stringify({
      pricing_tier_id: pricingTierId,
      ...(groupSize === undefined ? {} : { group_size: groupSize }),
    }),
  });
}

export function getPackageStatus(
  accessToken: string,
  packageId: string,
): Promise<PackagePaymentStatus> {
  return request<PackagePaymentStatus>(`/packages/${packageId}/status`, accessToken);
}

export function getPackageGeofence(
  accessToken: string,
  packageId: string,
): Promise<PackageGeofence> {
  return request<PackageGeofence>(`/packages/${packageId}/geofence`, accessToken);
}
