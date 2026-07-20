import { findActivePackageId, getMyPackages, PackagesApiError } from './packagesClient';

const fetchMock = jest.fn();
global.fetch = fetchMock;

beforeEach(() => fetchMock.mockReset());

describe('getMyPackages', () => {
  it('fetches the pilgrim\'s packages', async () => {
    const packages = [
      { id: 'p1', status: 'expired', expires_at: '2026-06-01T00:00:00Z' },
      { id: 'p2', status: 'active', expires_at: '2026-08-01T00:00:00Z' },
    ];
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ packages }) });

    await expect(getMyPackages('token')).resolves.toEqual(packages);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/me/packages'),
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({ Authorization: 'Bearer token' }),
      }),
    );
  });

  it('throws PackagesApiError on a network failure', async () => {
    fetchMock.mockRejectedValue(new Error('offline'));
    await expect(getMyPackages('token')).rejects.toThrow(PackagesApiError);
  });

  it('throws PackagesApiError on a non-ok response', async () => {
    fetchMock.mockResolvedValue({ ok: false, json: async () => ({}) });
    await expect(getMyPackages('token')).rejects.toThrow(PackagesApiError);
  });
});

describe('findActivePackageId', () => {
  it('returns the id of the single active package', () => {
    const packages = [
      { id: 'p1', status: 'superseded', expires_at: '2026-06-01T00:00:00Z' },
      { id: 'p2', status: 'active', expires_at: '2026-08-01T00:00:00Z' },
      { id: 'p3', status: 'expired', expires_at: '2026-05-01T00:00:00Z' },
    ];
    expect(findActivePackageId(packages)).toBe('p2');
  });

  it('returns undefined when no package is active', () => {
    const packages = [{ id: 'p1', status: 'expired', expires_at: '2026-05-01T00:00:00Z' }];
    expect(findActivePackageId(packages)).toBeUndefined();
  });

  it('returns undefined for an empty package list', () => {
    expect(findActivePackageId([])).toBeUndefined();
  });
});
