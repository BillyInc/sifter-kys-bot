import { supabase } from './lib/supabase';

function normalise(raw) {
  const metadata = raw?.metadata || {};
  const source = raw?.source || metadata.source || 'watchlist';
  return {
    ...raw,
    is_read: raw?.is_read === true,
    _side: raw?.side || metadata.side || raw?.notification_type || 'trade',
    _ticker: raw?.token_ticker || metadata.token_ticker || 'UNKNOWN',
    _name: raw?.token_name || metadata.token_name,
    _tokenAddress: raw?.token_address || metadata.token_address,
    _usdValue: raw?.usd_value ?? metadata.usd_value,
    _txHash: raw?.tx_hash || metadata.tx_hash,
    _source: source,
    _isElite15: source === 'elite15',
    _solscanUrl: metadata.solscan_url || (raw?.tx_hash ? `https://solscan.io/tx/${raw.tx_hash}` : undefined),
  };
}

class WalletActivityService {
  constructor() {
    this.apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:5000';
    this.userId = null;
    this.notifications = [];
    this.unreadCount = 0;
    this.listeners = new Set();
    this.elite15Listeners = new Set();
    this.realtimeChannel = null;
    this.eventSource = null;
    this.pollHandle = null;
    this.isPolling = false;
  }

  async getHeaders() {
    const { data: { session } } = await supabase.auth.getSession();
    return {
      'Content-Type': 'application/json',
      ...(session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {}),
    };
  }

  async start(userId) {
    if (!userId) return;
    if (this.userId === userId && (this.realtimeChannel || this.eventSource || this.isPolling)) return;

    this.stop();
    this.userId = userId;
    await this.fetchAll();

    const realtimeOk = await this.startRealtime();
    if (!realtimeOk) {
      const sseOk = this.startSSE();
      if (!sseOk) this.startPolling();
    }
  }

  stop() {
    if (this.realtimeChannel) {
      supabase.removeChannel(this.realtimeChannel);
      this.realtimeChannel = null;
    }
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
    if (this.pollHandle) {
      clearInterval(this.pollHandle);
      this.pollHandle = null;
    }
    this.isPolling = false;
  }

  async startRealtime() {
    if (!this.userId) return false;
    try {
      const channel = supabase
        .channel(`wallet_notifications:${this.userId}`)
        .on('postgres_changes', {
          event: 'INSERT',
          schema: 'sifter_dev',
          table: 'wallet_notifications',
          filter: `user_id=eq.${this.userId}`,
        }, ({ new: row }) => this.onIncoming(normalise(row)))
        .on('postgres_changes', {
          event: 'UPDATE',
          schema: 'sifter_dev',
          table: 'wallet_notifications',
          filter: `user_id=eq.${this.userId}`,
        }, ({ new: row }) => {
          const updated = normalise(row);
          this.notifications = this.notifications.map((item) => item.id === updated.id ? updated : item);
          this.unreadCount = this.notifications.filter((item) => !item.is_read).length;
          this.notify({ notifications: this.notifications, unread_count: this.unreadCount });
        })
        .subscribe((status) => {
          if (status === 'CHANNEL_ERROR' || status === 'TIMED_OUT') {
            this.stopRealtimeOnly();
            if (!this.startSSE()) this.startPolling();
          }
        });

      this.realtimeChannel = channel;
      return true;
    } catch {
      return false;
    }
  }

  stopRealtimeOnly() {
    if (this.realtimeChannel) {
      supabase.removeChannel(this.realtimeChannel);
      this.realtimeChannel = null;
    }
  }

  startSSE() {
    if (!this.userId || typeof EventSource === 'undefined') return false;
    try {
      const source = new EventSource(`${this.apiUrl}/api/wallets/notifications/stream?user_id=${encodeURIComponent(this.userId)}`);

      source.addEventListener('snapshot', (event) => {
        const payload = JSON.parse(event.data);
        this.notifications = (payload.notifications || []).map(normalise);
        this.unreadCount = payload.unread_count || 0;
        this.notify({ notifications: this.notifications, unread_count: this.unreadCount });
      });

      source.addEventListener('notification', (event) => {
        const payload = JSON.parse(event.data);
        this.onIncoming(normalise(payload.notification), payload.unread_count);
      });

      source.addEventListener('done', () => {
        source.close();
        this.eventSource = null;
        if (this.userId) {
          setTimeout(() => {
            if (this.userId && !this.eventSource) this.startSSE();
          }, 5000);
        }
      });

      source.onerror = () => {
        source.close();
        this.eventSource = null;
        if (!this.isPolling) this.startPolling();
      };

      this.eventSource = source;
      return true;
    } catch {
      return false;
    }
  }

  startPolling() {
    if (this.isPolling) return;
    this.isPolling = true;
    this.pollHandle = setInterval(() => this.fetchAll(), 60000);
  }

  async fetchAll() {
    if (!this.userId) return;
    const data = await this.getAllNotifications(this.userId, false);
    const hasNew = data.unread_count > this.unreadCount;
    this.notifications = data.notifications;
    this.unreadCount = data.unread_count;
    this.notify({ notifications: this.notifications, unread_count: this.unreadCount, has_new: hasNew });
  }

  async getAllNotifications(userId, unreadOnly = false) {
    if (userId) this.userId = userId;
    if (!this.userId) return { notifications: [], unread_count: 0 };

    try {
      const params = new URLSearchParams({
        unread_only: String(unreadOnly),
        limit: '50',
      });
      const headers = await this.getHeaders();
      const response = await fetch(`${this.apiUrl}/api/wallets/notifications?${params.toString()}`, { headers });
      if (response.status === 429) {
        return { notifications: this.notifications, unread_count: this.unreadCount };
      }
      const data = await response.json();
      if (!data.success) return { notifications: [], unread_count: 0 };
      return {
        notifications: (data.notifications || []).map(normalise),
        unread_count: data.unread_count || 0,
      };
    } catch (error) {
      console.error('[WalletActivity] Error fetching notifications:', error);
      return { notifications: [], unread_count: 0 };
    }
  }

  onIncoming(notification, unreadCountFromServer) {
    this.notifications = [notification, ...this.notifications.filter((item) => item.id !== notification.id)];
    this.unreadCount = unreadCountFromServer ?? this.notifications.filter((item) => !item.is_read).length;
    this.notify({ notifications: this.notifications, unread_count: this.unreadCount, has_new: true });

    if (notification._isElite15 && notification._tokenAddress) {
      const signal = {
        notification,
        token_address: notification._tokenAddress,
        side: notification._side || 'buy',
        usd_value: notification._usdValue || 0,
        wallet_tier: notification.wallet_tier || 'S',
      };
      this.elite15Listeners.forEach((listener) => {
        try {
          listener(signal);
        } catch (error) {
          console.error('[WalletActivity] Elite15 listener error:', error);
        }
      });
    }
  }

  async markAsRead(id) {
    try {
      const headers = await this.getHeaders();
      const response = await fetch(`${this.apiUrl}/api/wallets/notifications/mark-read`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ notification_id: id }),
      });
      const data = await response.json();
      if (data.success) {
        this.notifications = this.notifications.map((item) => item.id === id ? { ...item, is_read: true } : item);
        this.unreadCount = this.notifications.filter((item) => !item.is_read).length;
        this.notify({ notifications: this.notifications, unread_count: this.unreadCount });
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
        body: JSON.stringify({ mark_all: true }),
      });
      const data = await response.json();
      if (data.success) {
        this.notifications = this.notifications.map((item) => ({ ...item, is_read: true }));
        this.unreadCount = 0;
        this.notify({ notifications: this.notifications, unread_count: 0 });
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

  onElite15Signal(callback) {
    this.elite15Listeners.add(callback);
    return () => this.elite15Listeners.delete(callback);
  }

  notify(data) {
    this.listeners.forEach((listener) => {
      try {
        listener(data);
      } catch (error) {
        console.error('[WalletActivity] Listener error:', error);
      }
    });
  }

  async refresh() {
    await this.fetchAll();
  }
}

export const walletActivityService = new WalletActivityService();
export default walletActivityService;
