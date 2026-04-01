import ApiClient from '../src/services/ApiClient';

declare const global: any;

describe('ApiClient', () => {
  beforeEach(() => {
    global.fetch = jest.fn();
    ApiClient.authToken = null;
  });

  test('get sends correct headers', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ status: 'healthy' }),
    });

    await ApiClient.getHealth();

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/health'),
      expect.objectContaining({
        headers: expect.objectContaining({ Accept: 'application/json' }),
      })
    );
  });

  test('includes auth token when set', async () => {
    ApiClient.setAuthToken('test-token');
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({}),
    });

    await ApiClient.getElite100();

    expect(global.fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
      })
    );
  });

  test('throws on non-ok response', async () => {
    global.fetch.mockResolvedValueOnce({ ok: false, status: 500 });
    await expect(ApiClient.getHealth()).rejects.toThrow('API 500');
  });

  test('post sends body as JSON', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ success: true }),
    });

    await ApiClient.post('/api/test', { key: 'value' });

    expect(global.fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ key: 'value' }),
      })
    );
  });
});
