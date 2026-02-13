import { supabase } from './lib/supabase';

class WalletActivityService {
  constructor() {
    this.apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:5000';
    this.pollInterval = null;
    this.userId = null;
    this.listeners = new Set();
    this.notifications = [];
    this.unreadCount = 0;
    this.isPolling = false;
  }

  async getHeaders() {
    const { data: { session } } = await supabase.auth.getSession();
    return {
      'Content-Type': 'application/json',
      ...(session?.access_token ? { 'Authorization': `Bearer ${session.access_token}` } : {})
    };
  }

  async start(userId) {
    if (!userId) return;
    this.userId = userId;
    await this.fetchNotifications();

    if (!this.isPolling) {
      this.isPolling = true;
      this.pollInterval = setInterval(() => this.fetchNotifications(), 100000);
      console.log('[WalletActivity] Started polling for:', userId);
    }
  }

  stop() {
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
      this.isPolling = false;
    }
  }

  async fetchNotifications() {
    if (!this.userId) return;
    try {
      const data = await this.getAllNotifications(this.userId, false);
      const hasNew = data.unread_count > this.unreadCount;
      
      this.notifications = data.notifications;
      this.unreadCount = data.unread_count;

      this.notifyListeners({
        notifications: this.notifications,
        unread_count: this.unreadCount,
        has_new: hasNew
      });
    } catch (error) {
      console.error('[WalletActivity] Fetch error:', error);
    }
  }

  async getAllNotifications(userId, unreadOnly = false) {
    if (userId) this.userId = userId;
    if (!this.userId) return { notifications: [], unread_count: 0 };

    try {
      const params = new URLSearchParams({
        user_id: this.userId,
        unread_only: unreadOnly ? 'true' : 'false',
        limit: '50'
      });
      const headers = await this.getHeaders();
      const response = await fetch(`${this.apiUrl}/api/wallets/notifications?${params}`, { headers });
      const data = await response.json();
      
      return data.success ? { 
        notifications: data.notifications || [], 
        unread_count: data.unread_count || 0 
      } : { notifications: [], unread_count: 0 };
    } catch (error) {
      return { notifications: [], unread_count: 0 };
    }
  }

  async markAsRead(notificationId) {
    try {
      const headers = await this.getHeaders();
      const response = await fetch(`${this.apiUrl}/api/wallets/notifications/mark-read`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ user_id: this.userId, notification_id: notificationId })
      });
      const data = await response.json();
      if (data.success) await this.fetchNotifications();
      return data.success;
    } catch (error) { return false; }
  }

  async markAllAsRead() {
    try {
      const headers = await this.getHeaders();
      const response = await fetch(`${this.apiUrl}/api/wallets/notifications/mark-read`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ user_id: this.userId, mark_all: true })
      });
      const data = await response.json();
      if (data.success) await this.fetchNotifications();
      return data.success;
    } catch (error) { return false; }
  }

  subscribe(callback) {
    this.listeners.add(callback);
    return () => this.listeners.delete(callback);
  }

  notifyListeners(data) {
    this.listeners.forEach(listener => listener(data));
  }
}

export const walletActivityService = new WalletActivityService();
export default walletActivityService;