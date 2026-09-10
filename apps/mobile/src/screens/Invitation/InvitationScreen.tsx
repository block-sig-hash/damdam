import React, { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { ApiError } from '../../api/http';
import {
  acceptInvitation,
  previewInvitation,
  type InvitationPreview,
} from '../../api/invitationClient';
import { StateMessage } from '../../components/StateMessage/StateMessage';
import { color, space, typography } from '../../theme/tokens';

interface InvitationScreenProps {
  accessToken: string;
  token: string;
  /** The signed-in account's own address, for the wrong-account explanation. */
  currentEmail: string | null;
  /** Called once the membership exists, so the host can refresh its services. */
  onAccepted: () => void | Promise<void>;
  onDismiss: () => void;
  /** Sign out and return to sign-in with the invited address pre-filled. */
  onSwitchAccount: (invitedHint: string) => void;
}

type Screen =
  | { name: 'loading' }
  | { name: 'preview'; preview: InvitationPreview }
  | { name: 'accepted'; organization: string }
  | { name: 'error'; code: string };

/**
 * Redeeming an organization invitation (AC-37.3, AC-37.4).
 *
 * The binding is the point. An invitation names an address, and acceptance
 * succeeds only for an account that has *proved* it holds that address — so the
 * screen's job is to make the mismatch case legible before anything is claimed,
 * rather than surfacing a 403 after the customer has already tapped "join".
 *
 * Every terminal state here has a way onward: expired asks for a new one, used
 * says what to do if it was not you, wrong-account offers to switch. None of
 * them is a toast over a blank screen, which is what AC-37.3 means by "behave
 * correctly".
 */
export function InvitationScreen({
  accessToken,
  token,
  currentEmail,
  onAccepted,
  onDismiss,
  onSwitchAccount,
}: InvitationScreenProps): React.JSX.Element {
  const { t } = useTranslation('consumer');
  const [screen, setScreen] = useState<Screen>({ name: 'loading' });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    previewInvitation(accessToken, token)
      .then(preview => {
        if (active) {
          setScreen({ name: 'preview', preview });
        }
      })
      .catch(error => {
        if (active) {
          setScreen({
            name: 'error',
            code: error instanceof ApiError ? error.code : 'invitation_invalid',
          });
        }
      });
    return () => {
      active = false;
    };
  }, [accessToken, token]);

  const accept = useCallback(async () => {
    if (screen.name !== 'preview') {
      return;
    }
    const organization = screen.preview.organization_name;
    setBusy(true);
    try {
      await acceptInvitation(accessToken, token);
      setScreen({ name: 'accepted', organization });
      await onAccepted();
    } catch (error) {
      // A double tap lands here, and so does a link the customer had already
      // used on another device. Re-reading the invitation is what turns either
      // into an accurate screen instead of a generic failure.
      const preview = await previewInvitation(accessToken, token).catch(
        () => null,
      );
      if (preview) {
        setScreen({ name: 'preview', preview });
      } else {
        setScreen({
          name: 'error',
          code: error instanceof ApiError ? error.code : 'invitation_invalid',
        });
      }
    } finally {
      setBusy(false);
    }
  }, [accessToken, onAccepted, screen, token]);

  if (screen.name === 'loading') {
    return (
      <View style={styles.screen} testID="invitation-screen">
        <StateMessage
          variant="pending"
          title={t('invitation.title')}
          body={t('invitation.loading')}
          testID="invitation-loading-state"
        />
      </View>
    );
  }

  if (screen.name === 'error') {
    return (
      <View style={styles.screen} testID="invitation-screen">
        <StateMessage
          variant="error"
          title={t('invitation.invalidTitle')}
          body={t('invitation.invalidBody')}
          actionLabel={t('invitation.continue')}
          onAction={onDismiss}
          testID="invitation-invalid"
        />
      </View>
    );
  }

  if (screen.name === 'accepted') {
    return (
      <View style={styles.screen} testID="invitation-screen">
        <StateMessage
          variant="empty"
          title={t('invitation.acceptedTitle', {
            organization: screen.organization,
          })}
          body={t('invitation.acceptedBody')}
          actionLabel={t('invitation.continue')}
          onAction={onDismiss}
          testID="invitation-accepted"
        />
      </View>
    );
  }

  const { preview } = screen;
  const organization = preview.organization_name;

  return (
    <ScrollView contentContainerStyle={styles.screen} testID="invitation-screen">
      <Text style={styles.title}>{t('invitation.title')}</Text>

      {preview.already_a_member ? (
        <StateMessage
          variant="empty"
          title={t('invitation.alreadyMemberTitle', { organization })}
          body={t('invitation.alreadyMemberBody')}
          actionLabel={t('invitation.continue')}
          onAction={onDismiss}
          testID="invitation-already-member"
        />
      ) : preview.state === 'expired' ? (
        <StateMessage
          variant="blocked"
          title={t('invitation.expiredTitle')}
          body={t('invitation.expiredBody', { organization })}
          actionLabel={t('invitation.continue')}
          onAction={onDismiss}
          testID="invitation-expired"
        />
      ) : preview.state === 'accepted' ? (
        <StateMessage
          variant="blocked"
          title={t('invitation.usedTitle')}
          body={t('invitation.usedBody', { organization })}
          actionLabel={t('invitation.continue')}
          onAction={onDismiss}
          testID="invitation-used"
        />
      ) : preview.state === 'revoked' ? (
        <StateMessage
          variant="blocked"
          title={t('invitation.revokedTitle')}
          body={t('invitation.revokedBody', { organization })}
          actionLabel={t('invitation.continue')}
          onAction={onDismiss}
          testID="invitation-revoked"
        />
      ) : !preview.recipient_matches ? (
        // The binding, made visible. The masked address is all the server will
        // disclose, and it is enough for the invited person to recognize.
        <StateMessage
          variant="blocked"
          title={t('invitation.wrongAccountTitle')}
          body={t('invitation.wrongAccountBody', {
            email: preview.invited_value_masked,
            current: currentEmail ?? '—',
            organization,
          })}
          actionLabel={t('invitation.wrongAccountAction')}
          onAction={() => onSwitchAccount(preview.invited_value_masked)}
          secondaryActionLabel={t('invitation.decline')}
          onSecondaryAction={onDismiss}
          testID="invitation-wrong-account"
        />
      ) : (
        <StateMessage
          variant="empty"
          title={t('invitation.title')}
          body={t('invitation.body', {
            organization,
            email: preview.invited_value_masked,
            role: roleLabel(preview.role, t),
          })}
          actionLabel={t('invitation.accept', { organization })}
          onAction={accept}
          busy={busy}
          busyLabel={t('invitation.accepting')}
          secondaryActionLabel={t('invitation.decline')}
          onSecondaryAction={onDismiss}
          testID="invitation-accept"
        />
      )}
    </ScrollView>
  );
}

function roleLabel(role: string, t: (key: string) => string): string {
  switch (role) {
    case 'owner':
      return t('invitation.roleOwner');
    case 'administrator':
      return t('invitation.roleAdministrator');
    case 'billing':
      return t('invitation.roleBilling');
    default:
      return t('invitation.roleMember');
  }
}

const styles = StyleSheet.create({
  screen: {
    flexGrow: 1,
    padding: space.space5,
    gap: space.space4,
    backgroundColor: color.gray50,
  },
  title: {
    fontSize: typography.heading1.fontSize,
    lineHeight: typography.heading1.lineHeight,
    fontWeight: typography.heading1.fontWeight,
    color: color.gray900,
  },
});
