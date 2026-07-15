import { EmergencyContactApiError, getEmergencyContact } from './emergencyContactClient';

const fetchMock = jest.fn();
global.fetch = fetchMock;

beforeEach(() => fetchMock.mockReset());

describe('emergencyContactClient', () => {
  it('AC-12.2: fetches the HTO operator contact for the current pilgrim', async () => {
    const contact = {
      hto_operator_name: 'Kano Pilgrims Welfare HTO',
      hto_operator_phone_number: '+2348012345678',
    };
    fetchMock.mockResolvedValue({ ok: true, json: async () => contact });

    await expect(getEmergencyContact('token')).resolves.toEqual(contact);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/me/emergency-contact'),
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({ Authorization: 'Bearer token' }),
      }),
    );
  });

  it('resolves with null fields for a direct/retail pilgrim with no HTO', async () => {
    const contact = { hto_operator_name: null, hto_operator_phone_number: null };
    fetchMock.mockResolvedValue({ ok: true, json: async () => contact });

    await expect(getEmergencyContact('token')).resolves.toEqual(contact);
  });

  it('throws EmergencyContactApiError on a network failure', async () => {
    fetchMock.mockRejectedValue(new Error('offline'));

    await expect(getEmergencyContact('token')).rejects.toThrow(EmergencyContactApiError);
  });

  it('throws EmergencyContactApiError on a non-ok response', async () => {
    fetchMock.mockResolvedValue({ ok: false, json: async () => ({}) });

    await expect(getEmergencyContact('token')).rejects.toThrow(EmergencyContactApiError);
  });
});
