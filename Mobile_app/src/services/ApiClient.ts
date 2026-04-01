const API_BASE = process.env.API_BASE_URL || 'https://sifter-kys.duckdns.org';

class ApiClient {
  private baseUrl: string;
  authToken: string | null;

  constructor() {
    this.baseUrl = API_BASE;
    this.authToken = null;
  }

  setAuthToken(token: string): void {
    this.authToken = token;
  }

  async get(path: string): Promise<any> {
    const headers: Record<string, string> = { 'Accept': 'application/json' };
    if (this.authToken) headers['Authorization'] = `Bearer ${this.authToken}`;
    const res = await fetch(`${this.baseUrl}${path}`, { headers });
    if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
    return res.json();
  }

  async post(path: string, body: any): Promise<any> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json', 'Accept': 'application/json' };
    if (this.authToken) headers['Authorization'] = `Bearer ${this.authToken}`;
    const res = await fetch(`${this.baseUrl}${path}`, {
      method: 'POST', headers, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
    return res.json();
  }

  // Convenience methods matching backend endpoints
  async getHealth(): Promise<any> { return this.get('/health'); }
  async getElite100(): Promise<any> { return this.get('/api/wallets/elite-100'); }
  async getTrending(timeframe: string = '7d'): Promise<any> { return this.get(`/api/wallets/trending/runners?timeframe=${timeframe}`); }
  async getWatchlist(): Promise<any> { return this.get('/api/wallets/watchlist/table'); }
  async addToWatchlist(walletData: any): Promise<any> { return this.post('/api/wallets/watchlist/add', { wallet: walletData }); }
  async getNotifications(): Promise<any> { return this.get('/api/wallets/notifications?unread_only=false&limit=50'); }
  async analyzeWallet(tokens: string[]): Promise<any> { return this.post('/api/wallets/analyze', { tokens }); }
  async getJobProgress(jobId: string): Promise<any> { return this.get(`/api/wallets/jobs/${jobId}/progress`); }
}

export default new ApiClient();
