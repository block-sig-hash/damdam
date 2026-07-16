import { getCallHistory, getVoiceEligibility, getVoiceToken, VoiceApiError } from './voiceClient';

beforeEach(() => {
  global.fetch = jest.fn();
});

it('AC-14.7/9: requests eligibility, a scoped token, and at most 20 history entries', async () => {
  (global.fetch as jest.Mock)
    .mockResolvedValueOnce({ ok: true, json: async () => ({ allowed: true, call_type: 'pstn' }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ token: 'jwt', destination: '+234801' }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ calls: [] }) });

  await getVoiceEligibility('access', '0801 234 5678');
  await getVoiceToken('access', '08012345678');
  await getCallHistory('access', 50);

  expect(global.fetch).toHaveBeenNthCalledWith(
    1,
    expect.stringContaining('/voice/eligibility?phone_number=0801%20234%205678'),
    expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer access' }) }),
  );
  expect(global.fetch).toHaveBeenNthCalledWith(
    2,
    expect.stringContaining('/voice/token'),
    expect.objectContaining({ method: 'POST', body: JSON.stringify({ to_number: '08012345678' }) }),
  );
  expect(global.fetch).toHaveBeenNthCalledWith(
    3,
    expect.stringContaining('/me/calls?limit=20'),
    expect.anything(),
  );
});

it('AC-14.6: maps a transport failure to connectivity copy', async () => {
  (global.fetch as jest.Mock).mockRejectedValue(new Error('offline'));
  await expect(getVoiceToken('access', '08012345678')).rejects.toEqual(
    new VoiceApiError('Calling requires an internet connection'),
  );
});
