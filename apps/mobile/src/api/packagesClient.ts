import { API_BASE_URL } from '../config/env';
import {i18n} from '../i18n';

/**
 * Mirrors docs/api-spec.md's `GET /me/packages` response shape --
 * deliberately only the fields this client actually uses.
 */
export interface MePackage {
  id: string;
  status: string;
  expires_at: string;
}

export class PackagesApiError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'PackagesApiError';
  }
}

export async function getMyPackages(accessToken: string): Promise<MePackage[]> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/me/packages`, {
      method: 'GET',
      headers: { Authorization: `Bearer ${accessToken}` },
    });
  } catch {
    throw new PackagesApiError(i18n.t('errors.network', {ns: 'auth'}));
  }
  if (!response.ok) {
    throw new PackagesApiError(i18n.t('packages.unavailable', {ns: 'payments'}));
  }
  const body = (await response.json()) as { packages: MePackage[] };
  return body.packages;
}

/**
 * "Exactly one ACTIVE package per user at a time" is a data-model
 * invariant (US-25's chaining design supersedes rather than allows a
 * second concurrently-active package) -- so there is never more than
 * one match here. Returns undefined if the account currently has no
 * active package at all (e.g. between purchases, or never purchased).
 */
export function findActivePackageId(packages: MePackage[]): string | undefined {
  return packages.find((pkg) => pkg.status === 'active')?.id;
}
