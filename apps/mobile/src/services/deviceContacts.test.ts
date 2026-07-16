import Contacts from 'react-native-contacts';
import { loadDialContacts } from './deviceContacts';

jest.mock('react-native-contacts', () => ({
  __esModule: true,
  default: {
    checkPermission: jest.fn(),
    requestPermission: jest.fn(),
    getAllWithoutPhotos: jest.fn(),
  },
}));

const mocked = Contacts as jest.Mocked<typeof Contacts>;

beforeEach(() => jest.clearAllMocks());

it('AC-14.2: requests contacts permission only when the picker loader is invoked', async () => {
  mocked.checkPermission.mockResolvedValue('undefined');
  mocked.requestPermission.mockResolvedValue('authorized');
  mocked.getAllWithoutPhotos.mockResolvedValue([
    {
      recordID: '1',
      displayName: 'Amina Yusuf',
      givenName: 'Amina',
      familyName: 'Yusuf',
      phoneNumbers: [{ label: 'mobile', number: '08012345678' }],
    } as never,
  ]);

  const contacts = await loadDialContacts();

  expect(mocked.requestPermission).toHaveBeenCalledTimes(1);
  expect(contacts).toEqual([{ id: '1-0', name: 'Amina Yusuf', phoneNumber: '08012345678' }]);
});

it('AC-14.2: denied permission yields an empty contextual picker', async () => {
  mocked.checkPermission.mockResolvedValue('denied');
  mocked.requestPermission.mockResolvedValue('denied');
  await expect(loadDialContacts()).resolves.toEqual([]);
  expect(mocked.getAllWithoutPhotos).not.toHaveBeenCalled();
});
