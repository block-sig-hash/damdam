import { apiRequest } from './http';

/**
 * Reading and accepting an organization invitation (US-37 AC-37.4).
 *
 * `preview` exists so the app can answer "is this link mine" *before* it binds
 * anything. Without it the only way to find out is to attempt acceptance, and a
 * person who holds two accounts discovers the mistake after the membership has
 * been created on the wrong one.
 */

export type InvitationPreviewState =
  | 'pending'
  | 'expired'
  | 'accepted'
  | 'revoked';

export interface InvitationPreview {
  state: InvitationPreviewState;
  organization_name: string;
  role: string;
  invited_kind: string;
  /** `i•••d@acme.test` — never the address itself. */
  invited_value_masked: string;
  expires_at: string | null;
  recipient_matches: boolean;
  already_a_member: boolean;
}

export interface AcceptedMembership {
  organization_id: string;
  user_id: string;
  role: string;
  status: string;
}

export function previewInvitation(
  accessToken: string,
  token: string,
): Promise<InvitationPreview> {
  return apiRequest<InvitationPreview>('/invitations/preview', {
    method: 'POST',
    accessToken,
    body: { token },
  });
}

export function acceptInvitation(
  accessToken: string,
  token: string,
): Promise<AcceptedMembership> {
  return apiRequest<AcceptedMembership>('/invitations/accept', {
    method: 'POST',
    accessToken,
    body: { token },
  });
}
