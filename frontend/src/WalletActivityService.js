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
    
    // Initial fetch
    await this.fetchNotifications();

    // Start polling every 30 seconds (reduced from 2 seconds to avoid rate limiting)
    if (!this.isPolling) {
      this.isPolling = true;
      this.pollInterval = setInterval(() => this.fetchNotifications(), 30000); // 30 seconds
      console.log('[WalletActivity] Started polling (30s interval) for:', userId);
    }
  }

  stop() {
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
      this.isPolling = false;
      console.log('[WalletActivity] Stopped polling');
    }
  }

  async fetchNotifications() {
    if (!this.userId) return;
    
    try {
      const data = await this.getAllNotifications(this.userId, false);
      const hasNew = data.unread_count > this.unreadCount;
      
      this.notifications = data.notifications;
      this.unreadCount = data.unread_count;

      // Notify all listeners
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
      
      // Handle rate limiting gracefully
      if (response.status === 429) {
        console.warn('[WalletActivity] Rate limited - will retry on next poll');
        return { notifications: this.notifications, unread_count: this.unreadCount };
      }
      
      const data = await response.json();
      
      return data.success ? { 
        notifications: data.notifications || [], 
        unread_count: data.unread_count || 0 
      } : { notifications: [], unread_count: 0 };
    } catch (error) {
      console.error('[WalletActivity] Error fetching notifications:', error);
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
      if (data.success) {
        await this.fetchNotifications();
      }
      return data.success;
    } catch (error) {
      console.error('[WalletActivity] Error marking as read:', error);
      return false;
    }
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
      if (data.success) {
        await this.fetchNotifications();
      }
      return data.success;
    } catch (error) {
      console.error('[WalletActivity] Error marking all as read:', error);
      return false;
    }
  }

  subscribe(callback) {
    this.listeners.add(callback);
    return () => this.listeners.delete(callback);
  }

  notifyListeners(data) {
    this.listeners.forEach(listener => {
      try {
        listener(data);
      } catch (error) {
        console.error('[WalletActivity] Listener error:', error);
      }
    });
  }

  // Manual refresh method
  async refresh() {
    console.log('[WalletActivity] Manual refresh triggered');
    await this.fetchNotifications();
  }
}

// Export singleton instance
export const walletActivityService = new WalletActivityService();
export default walletActivityService;