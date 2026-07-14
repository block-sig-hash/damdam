import {
  FamilyContactApiError,
  nominateFamilyContact,
  updateFamilyContact,
} from './familyContactClient';

function mockFetchOnce(status: number, body: unknown) {
  (global.fetch as jest.Mock).mockResolvedValueOnce({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  });
}

beforeEach(() => {
  global.fetch = jest.fn();
});

describe('family contact API client', () => {
  it('nominates a contact with pilgrim authentication (AC-03.1/03.2)', async () => {
    const contact = {
      id: 'contact-1',
      phone_number: '+2349012345678',
      name: 'Hauwa',
      notified_of_nomination: true,
    };
    mockFetchOnce(201, contact);

    await expect(
      nominateFamilyContact('access-token', '09012345678', 'Hauwa'),
    ).resolves.toEqual(contact);
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/me/family-contact'),
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer access-token' }),
        body: JSON.stringify({ phone_number: '09012345678', name: 'Hauwa' }),
      }),
    );
  });

  it('updates the existing contact instead of creating another (AC-03.3/03.4)', async () => {
    mockFetchOnce(200, {
      id: 'contact-1',
      phone_number: '+2348123456789',
      name: null,
      notified_of_nomination: true,
    });

    await updateFamilyContact('access-token', { phone_number: '08123456789' });

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/me/family-contact'),
      expect.objectContaining({ method: 'PATCH' }),
    );
  });

  it('surfaces WhatsApp outages as retryable API errors (AC-03.2)', async () => {
    mockFetchOnce(503, {
      error: 'notification_unavailable',
      message: 'WhatsApp is temporarily unavailable.',
    });

    const error = await nominateFamilyContact(
      'access-token',
      '09012345678',
    ).catch((caught) => caught);

    expect(error).toBeInstanceOf(FamilyContactApiError);
    expect(error.code).toBe('notification_unavailable');
  });

  it('maps network failures without losing a typed retry signal', async () => {
    (global.fetch as jest.Mock).mockRejectedValueOnce(new Error('offline'));

    await expect(
      updateFamilyContact('access-token', { name: 'Maryam' }),
    ).rejects.toMatchObject({ code: 'network_error' });
  });
});
