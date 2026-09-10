import { apiRequest } from './http';

/**
 * Mirrors apps/api/app/consumer/schemas.py.
 *
 * The shapes are copied rather than derived because a generated client would
 * hide the one thing worth reading here: `installation_state` and
 * `activation_state` are nullable, and null does not mean "not installed". It
 * means there is no profile and no line, which is what an internet-calling
 * service looks like.
 */

export type ServiceState = 'none' | 'pending' | 'active';
export type ServiceDelivery = 'carrier_esim' | 'internet';
export type ServiceOwner = 'personal' | 'organization';

export interface ServiceSummary {
  order_item_id: string;
  order_id: string;
  order_reference: string;
  product_name: string;
  delivery: ServiceDelivery;
  owner: ServiceOwner;
  organization_id: string | null;
  organization_name: string | null;
  payment_state: string;
  provisioning_state: string;
  installation_state: string | null;
  activation_state: string | null;
  requires_installation: boolean;
  ready_to_use: boolean;
  granted_at: string | null;
  expires_at: string | null;
  expired: boolean;
}

export interface ServicesResponse {
  service_state: ServiceState;
  services: ServiceSummary[];
}

export interface OrganizationMembershipSummary {
  organization_id: string;
  name: string;
  role: string;
}

export interface ConsumerSession {
  user_id: string;
  locale: 'en' | 'fr';
  verified_emails: string[];
  verified_phone_numbers: string[];
  service_state: ServiceState;
  organizations: OrganizationMembershipSummary[];
  pending_invitations: number;
}

export function getConsumerSession(accessToken: string): Promise<ConsumerSession> {
  return apiRequest<ConsumerSession>('/me/session', { accessToken });
}

export function getServices(accessToken: string): Promise<ServicesResponse> {
  return apiRequest<ServicesResponse>('/me/services', { accessToken });
}

/**
 * The one service the app should open by default.
 *
 * A usable service wins over one that is still coming, and a carrier line that
 * needs installing wins over one that does not need anything — the customer
 * with an uninstalled profile has a job to do, and it is the reason they opened
 * the app.
 */
export function primaryService(
  services: ServiceSummary[],
): ServiceSummary | null {
  if (services.length === 0) {
    return null;
  }
  const needsInstalling = services.find(
    service =>
      !service.expired &&
      service.requires_installation &&
      !service.ready_to_use &&
      service.provisioning_state === 'provisioned',
  );
  if (needsInstalling) {
    return needsInstalling;
  }
  return services.find(service => service.ready_to_use) ?? services[0];
}
