/**
 * WalletActivityService.js
 * Manages WebSocket connection and real-time wallet activity notifications
 * Polls the backend API since WebSocket isn't implemented on backend yet
 */

class WalletActivityService {
  constructor() {
    this.apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:5000';
    this.userId = null;
    this.accessToken = null;
    this.listeners = new Set();
    this.pollInterval = null;
    this.isRunning = false;
    this.lastNotificationCheck = 0;
    this.pollIntervalMs = 30000; // 30 seconds
  }

  /**
   * Configure the service with user credentials
   */
  configure(userId, accessToken = null) {
    this.userId = userId;
    this.accessToken = accessToken;
  }

  /**
   * Start monitoring for new notifications
   */
  start() {
    if (this.isRunning) {
      console.log('[WalletActivity] Already running');
      return;
    }

    if (!this.userId) {
      console.log('[WalletActivity] No user configured, skipping start');
      return;
    }

    this.isRunning = true;
    console.log('[WalletActivity] Starting notification monitoring...');

    // Initial check
    this.checkForNotifications();

    // Poll every 30 seconds
    this.pollInterval = setInterval(() => {
      this.checkForNotifications();
    }, this.pollIntervalMs);
  }

  /**
   * Stop monitoring
   */
  stop() {
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
    }
    this.isRunning = false;
    console.log('[WalletActivity] Stopped notification monitoring');
  }

  /**
   * Get auth headers for API calls
   */
  getHeaders() {
    const headers = { 'Content-Type': 'application/json' };
    if (this.accessToken) {
      headers['Authorization'] = `Bearer ${this.accessToken}`;
    }
    return headers;
  }

  /**
   * Check for new notifications from the backend
   */
  async checkForNotifications() {
    try {
      const response = await fetch(
        `${this.apiUrl}/api/wallets/notifications?user_id=${this.userId}&unread_only=true`,
        { headers: this.getHeaders() }
      );

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();

      if (data.success && data.notifications && data.notifications.length > 0) {
        // Find truly new notifications (ones we haven't seen yet)
        const newNotifications = data.notifications.filter(
          notif => notif.sent_at > this.lastNotificationCheck
        );

        if (newNotifications.length > 0) {
          console.log(`[WalletActivity] ${newNotifications.length} new notification(s)`);
          
          // Update last check time
          this.lastNotificationCheck = Math.max(
            ...newNotifications.map(n => n.sent_at)
          );

          // Notify all listeners
          this.notifyListeners({
            type: 'new_notifications',
            notifications: newNotifications,
            unread_count: data.unread_count
          });
        }
      }
    } catch (error) {
      console.error('[WalletActivity] Error checking notifications:', error);
    }
  }

  /**
   * Subscribe to wallet activity updates
   * @param {Function} callback - Function to call when new activity arrives
   * @returns {Function} Unsubscribe function
   */
  subscribe(callback) {
    this.listeners.add(callback);
    
    // Return unsubscribe function
    return () => {
      this.listeners.delete(callback);
    };
  }

  /**
   * Notify all listeners of new activity
   */
  notifyListeners(data) {
    this.listeners.forEach(callback => {
      try {
        callback(data);
      } catch (error) {
        console.error('[WalletActivity] Listener error:', error);
      }
    });
  }

  /**
   * Mark notification as read
   */
  async markAsRead(notificationId) {
    try {
      const response = await fetch(`${this.apiUrl}/api/wallets/notifications/mark-read`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: this.userId,
          notification_id: notificationId
        })
      });

      const data = await response.json();
      return data.success;
    } catch (error) {
      console.error('[WalletActivity] Error marking as read:', error);
      return false;
    }
  }

  /**
   * Mark all notifications as read
   */
  async markAllAsRead() {
    try {
      const response = await fetch(`${this.apiUrl}/api/wallets/notifications/mark-read`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: this.userId,
          mark_all: true
        })
      });

      const data = await response.json();
      return data.success;
    } catch (error) {
      console.error('[WalletActivity] Error marking all as read:', error);
      return false;
    }
  }

  /**
   * Get all notifications (cached and fresh)
   */
  async getAllNotifications(unreadOnly = false) {
    try {
      const params = new URLSearchParams({
        user_id: this.userId,
        unread_only: unreadOnly ? 'true' : 'false',
        limit: '50'
      });

      const response = await fetch(
        `${this.apiUrl}/api/wallets/notifications?${params}`
      );

      const data = await response.json();
      
      if (data.success) {
        return {
          notifications: data.notifications || [],
          unread_count: data.unread_count || 0
        };
      }

      return { notifications: [], unread_count: 0 };
    } catch (error) {
      console.error('[WalletActivity] Error fetching notifications:', error);
      return { notifications: [], unread_count: 0 };
    }
  }

  /**
   * Get recent wallet activity
   */
  async getRecentActivity(walletAddress = null, limit = 50) {
    try {
      const params = new URLSearchParams({ limit: limit.toString() });
      if (walletAddress) {
        params.append('wallet_address', walletAddress);
      }

      const response = await fetch(
        `${this.apiUrl}/api/wallets/activity/recent?${params}`
      );

      const data = await response.json();
      
      if (data.success) {
        return data.activities || [];
      }

      return [];
    } catch (error) {
      console.error('[WalletActivity] Error fetching activity:', error);
      return [];
    }
  }

  /**
   * Update alert settings for a wallet
   */
  async updateAlertSettings(walletAddress, settings) {
    try {
      const response = await fetch(`${this.apiUrl}/api/wallets/alerts/update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: this.userId,
          wallet_address: walletAddress,
          settings: settings
        })
      });

      const data = await response.json();
      return data.success;
    } catch (error) {
      console.error('[WalletActivity] Error updating alert settings:', error);
      return false;
    }
  }
}

// Create singleton instance
const walletActivityService = new WalletActivityService();

export default walletActivityService;