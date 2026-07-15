import { useEffect, useState } from 'react';
import { EmergencyContact, getEmergencyContact } from '../../api/emergencyContactClient';

/**
 * The HTO operator row is a nice-to-have, not a blocking dependency of
 * this screen — a failed fetch just leaves that row hidden (see
 * EmergencyEssentials) rather than surfacing an error or retry UI.
 */
export function useEmergencyContact(accessToken: string): EmergencyContact | null {
  const [contact, setContact] = useState<EmergencyContact | null>(null);

  useEffect(() => {
    let cancelled = false;
    getEmergencyContact(accessToken)
      .then(result => {
        if (!cancelled) setContact(result);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [accessToken]);

  return contact;
}
