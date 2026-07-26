import { setAppLocale } from '../i18n';
import { confirmCliVerification, startCliVerification } from './cliClient';

const fetchMock = jest.fn();
global.fetch = fetchMock;

beforeEach(() => {
  fetchMock.mockReset();
});

afterEach(async () => {
  await setAppLocale('en');
});

describe('cliClient', () => {
  it('sends the current app locale on every request, so a backend error renders in the selected language', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ id: 'identity-1', status: 'phone_verification_pending' }),
    });

    await startCliVerification('token', '08012345678');

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/voice/cli/verify'),
      expect.objectContaining({
        headers: expect.objectContaining({ 'Accept-Language': 'en' }),
      }),
    );
  });

  it('reflects a runtime language switch to French without any caller passing locale explicitly', async () => {
    await setAppLocale('fr');
    fetchMock.mockResolvedValue({
      ok: false,
      status: 429,
      json: async () => ({
        error: 'cli_verification_rate_limited',
        message: 'Trop de tentatives de vérification. Réessayez plus tard.',
      }),
    });

    await expect(
      confirmCliVerification('token', 'identity-1', '111111'),
    ).rejects.toMatchObject({ code: 'cli_verification_rate_limited' });

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/voice/cli/identity-1/confirm'),
      expect.objectContaining({
        headers: expect.objectContaining({ 'Accept-Language': 'fr' }),
      }),
    );
  });
});
