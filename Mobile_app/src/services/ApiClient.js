const API_BASE = process.env.API_BASE_URL || 'https://sifter-kys.duckdns.org';

class ApiClient {
  constructor() {
    this.baseUrl = API_BASE;
    this.authToken = null;
  }

  setAuthToken(token) {
    this.authToken = token;
  }

  async get(path) {
    const headers = { 'Accept': 'application/json' };
    if (this.authToken) headers['Authorization'] = `Bearer ${this.authToken}`;
    const res = await fetch(`${this.baseUrl}${path}`, { headers });
    if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
    return res.json();
  }

  async post(path, body) {
    const headers = { 'Content-Type': 'application/json', 'Accept': 'application/json' };
    if (this.authToken) headers['Authorization'] = `Bearer ${this.authToken}`;
    const res = await fetch(`${this.baseUrl}${path}`, {
      method: 'POST', headers, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
    return res.json();
  }

  // Convenience methods matching backend endpoints
  async getHealth() { return this.get('/health'); }
  async getElite100() { return this.get('/api/wallets/elite-100'); }
  async getTrending(timeframe = '7d') { return this.get(`/api/wallets/trending/runners?timeframe=${timeframe}`); }
  async getWatchlist() { return this.get('/api/wallets/watchlist/table'); }
  async addToWatchlist(walletData) { return this.post('/api/wallets/watchlist/add', { wallet: walletData }); }
  async getNotifications() { return this.get('/api/wallets/notifications?unread_only=false&limit=50'); }
  async analyzeWallet(tokens) { return this.post('/api/wallets/analyze', { tokens }); }
  async getJobProgress(jobId) { return this.get(`/api/wallets/jobs/${jobId}/progress`); }
}

export default new ApiClient();
