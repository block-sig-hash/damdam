import Contacts, { type Contact } from 'react-native-contacts';

export interface DialContact {
  id: string;
  name: string;
  phoneNumber: string;
}

export async function loadDialContacts(): Promise<DialContact[]> {
  // AC-14.2: this function is invoked only from the contact-icon tap. No
  // contact permission request is registered at app startup.
  let permission = await Contacts.checkPermission();
  if (permission !== 'authorized') permission = await Contacts.requestPermission();
  if (permission !== 'authorized') return [];
  const contacts = await Contacts.getAllWithoutPhotos();
  return contacts
    .flatMap((contact: Contact) => {
      const name = contact.displayName || [contact.givenName, contact.familyName].filter(Boolean).join(' ');
      return contact.phoneNumbers.map((phone, index) => ({
        id: `${contact.recordID}-${index}`,
        name: name || phone.number,
        phoneNumber: phone.number,
      }));
    })
    .sort((left, right) => left.name.localeCompare(right.name));
}
