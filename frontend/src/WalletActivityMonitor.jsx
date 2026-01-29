import React, { useState, useEffect, useRef } from 'react';
import { Bell, BellRing, X, Check, CheckCheck, ExternalLink, Clock, TrendingUp, ArrowUpRight } from 'lucide-react';
import walletActivityService from './WalletActivityService';

export default function WalletActivityMonitor() {
  const [notifications, setNotifications] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [showToast, setShowToast] = useState(false);
  const [latestNotification, setLatestNotification] = useState(null);
  const dropdownRef = useRef(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsOpen(false);
      }
    }

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isOpen]);

  // Subscribe to real-time updates
  useEffect(() => {
    // Start monitoring service
    walletActivityService.start();

    // Subscribe to updates
    const unsubscribe = walletActivityService.subscribe((data) => {
      if (data.type === 'new_notifications' && data.notifications.length > 0) {
        // Show toast for newest notification
        const newest = data.notifications[0];
        setLatestNotification(newest);
        setShowToast(true);

        // Auto-hide toast after 5 seconds
        setTimeout(() => {
          setShowToast(false);
        }, 5000);

        // Update notifications list
        loadNotifications();
      }
    });

    // Initial load
    loadNotifications();

    return () => {
      unsubscribe();
    };
  }, []);

  const loadNotifications = async () => {
    setIsLoading(true);
    const data = await walletActivityService.getAllNotifications(false);
    setNotifications(data.notifications);
    setUnreadCount(data.unread_count);
    setIsLoading(false);
  };

  const handleMarkAsRead = async (notificationId) => {
    const success = await walletActivityService.markAsRead(notificationId);
    if (success) {
      loadNotifications();
    }
  };

  const handleMarkAllAsRead = async () => {
    const success = await walletActivityService.markAllAsRead();
    if (success) {
      loadNotifications();
    }
  };

  const handleNotificationClick = (notification) => {
    // Mark as read
    if (!notification.read_at) {
      handleMarkAsRead(notification.id);
    }
  };

  const formatTime = (timestamp) => {
    const now = Date.now() / 1000;
    const diff = now - timestamp;

    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  };

  const formatUSD = (value) => {
    if (value >= 1000000) return `$${(value / 1000000).toFixed(2)}M`;
    if (value >= 1000) return `$${(value / 1000).toFixed(1)}K`;
    return `$${value.toFixed(2)}`;
  };

  return (
    <>
      {/* Toast Notification */}
      {showToast && latestNotification && (
        <div className="fixed top-20 right-6 z-50 animate-slide-in-right">
          <div className="bg-gradient-to-br from-purple-900 to-purple-950 border-2 border-purple-500/50 rounded-2xl shadow-2xl p-4 w-96 backdrop-blur-xl">
            <div className="flex items-start gap-3">
              <div className="p-2 bg-purple-500/20 rounded-lg">
                <BellRing className="text-purple-400 animate-pulse" size={20} />
              </div>

              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-bold text-white">🔔 Wallet Alert</span>
                  <button
                    onClick={() => setShowToast(false)}
                    className="ml-auto p-1 hover:bg-white/10 rounded transition"
                  >
                    <X size={14} />
                  </button>
                </div>

                <p className="text-sm text-gray-300 mb-2">
                  <span className="font-mono text-purple-300">
                    {latestNotification.wallet_address?.slice(0, 8)}...
                  </span>
                  {' '}just{' '}
                  <span className={latestNotification.side === 'buy' ? 'text-green-400' : 'text-red-400'}>
                    {latestNotification.side}
                  </span>
                  {' '}
                  <span className="font-bold text-white">
                    {formatUSD(latestNotification.usd_value)}
                  </span>
                  {' '}of{' '}
                  <span className="text-yellow-400">${latestNotification.token_ticker}</span>
                </p>

                <button
                  onClick={() => {
                    setShowToast(false);
                    setIsOpen(true);
                  }}
                  className="text-xs text-purple-400 hover:text-purple-300 transition flex items-center gap-1"
                >
                  View Details
                  <ArrowUpRight size={12} />
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Bell Icon Button */}
      <div className="relative" ref={dropdownRef}>
        <button
          onClick={() => setIsOpen(!isOpen)}
          className="relative p-2 hover:bg-white/10 rounded-lg transition"
        >
          {unreadCount > 0 ? (
            <BellRing className="text-purple-400 animate-pulse" size={20} />
          ) : (
            <Bell className="text-gray-400" size={20} />
          )}

          {unreadCount > 0 && (
            <span className="absolute -top-1 -right-1 bg-red-500 text-white text-xs font-bold rounded-full w-5 h-5 flex items-center justify-center animate-bounce">
              {unreadCount > 9 ? '9+' : unreadCount}
            </span>
          )}
        </button>

        {/* Notifications Dropdown */}
        {isOpen && (
          <div className="absolute right-0 top-12 w-96 max-h-[600px] bg-black border border-white/10 rounded-xl shadow-2xl overflow-hidden animate-fade-in z-50">
            {/* Header */}
            <div className="bg-gradient-to-r from-purple-900/50 to-purple-800/30 border-b border-white/10 p-4">
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-lg font-bold flex items-center gap-2">
                  <Bell size={18} className="text-purple-400" />
                  Wallet Alerts
                </h3>
                <button
                  onClick={() => setIsOpen(false)}
                  className="p-1 hover:bg-white/10 rounded transition"
                >
                  <X size={18} />
                </button>
              </div>

              {unreadCount > 0 && (
                <button
                  onClick={handleMarkAllAsRead}
                  className="text-xs text-purple-400 hover:text-purple-300 transition flex items-center gap-1"
                >
                  <CheckCheck size={14} />
                  Mark all as read
                </button>
              )}
            </div>

            {/* Notifications List */}
            <div className="overflow-y-auto max-h-[500px] custom-scrollbar">
              {isLoading ? (
                <div className="p-8 text-center">
                  <div className="w-8 h-8 border-2 border-white/30 border-t-purple-500 rounded-full animate-spin mx-auto mb-2" />
                  <p className="text-sm text-gray-400">Loading notifications...</p>
                </div>
              ) : notifications.length === 0 ? (
                <div className="p-8 text-center">
                  <Bell className="mx-auto mb-3 text-gray-400 opacity-50" size={48} />
                  <p className="text-gray-400 text-sm">No wallet alerts yet</p>
                  <p className="text-xs text-gray-500 mt-1">
                    Alerts will appear here when monitored wallets trade
                  </p>
                </div>
              ) : (
                <div className="divide-y divide-white/5">
                  {notifications.map((notification) => (
                    <div
                      key={notification.id}
                      onClick={() => handleNotificationClick(notification)}
                      className={`p-4 hover:bg-white/5 transition cursor-pointer ${
                        !notification.read_at ? 'bg-purple-500/5' : ''
                      }`}
                    >
                      <div className="flex items-start gap-3">
                        {/* Icon */}
                        <div className={`p-2 rounded-lg ${
                          notification.side === 'buy' 
                            ? 'bg-green-500/20' 
                            : 'bg-red-500/20'
                        }`}>
                          {notification.side === 'buy' ? (
                            <TrendingUp className="text-green-400" size={16} />
                          ) : (
                            <TrendingUp className="text-red-400 rotate-180" size={16} />
                          )}
                        </div>

                        {/* Content */}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-start justify-between gap-2 mb-1">
                            <div>
                              <span className="text-sm font-mono text-gray-300">
                                {notification.wallet_address?.slice(0, 8)}...
                              </span>
                              <span className={`ml-2 text-sm font-bold ${
                                notification.side === 'buy' ? 'text-green-400' : 'text-red-400'
                              }`}>
                                {notification.side.toUpperCase()}
                              </span>
                            </div>
                            {!notification.read_at && (
                              <div className="w-2 h-2 bg-purple-500 rounded-full flex-shrink-0" />
                            )}
                          </div>

                          <p className="text-sm text-gray-400 mb-1">
                            <span className="text-yellow-400 font-semibold">
                              ${notification.token_ticker}
                            </span>
                            {notification.token_name && (
                              <span className="text-xs text-gray-500 ml-1">
                                ({notification.token_name})
                              </span>
                            )}
                          </p>

                          <div className="flex items-center gap-3 text-xs text-gray-500">
                            <span className="font-bold text-white">
                              {formatUSD(notification.usd_value)}
                            </span>
                            <span className="flex items-center gap-1">
                              <Clock size={12} />
                              {formatTime(notification.sent_at)}
                            </span>
                          </div>

                          {notification.tx_hash && (
                            <a
                              href={`https://solscan.io/tx/${notification.tx_hash}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              className="text-xs text-purple-400 hover:text-purple-300 transition flex items-center gap-1 mt-2"
                            >
                              View on Solscan
                              <ExternalLink size={10} />
                            </a>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Footer */}
            {notifications.length > 0 && (
              <div className="border-t border-white/10 p-2 bg-white/5 text-center">
                <p className="text-xs text-gray-500">
                  Showing last {notifications.length} notification{notifications.length !== 1 ? 's' : ''}
                </p>
              </div>
            )}
          </div>
        )}
      </div>

      <style jsx>{`
        @keyframes slide-in-right {
          from {
            transform: translateX(100%);
            opacity: 0;
          }
          to {
            transform: translateX(0);
            opacity: 1;
          }
        }

        @keyframes fade-in {
          from {
            opacity: 0;
            transform: translateY(-10px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        .animate-slide-in-right {
          animation: slide-in-right 0.3s ease-out;
        }

        .animate-fade-in {
          animation: fade-in 0.2s ease-out;
        }

        .custom-scrollbar::-webkit-scrollbar {
          width: 6px;
        }

        .custom-scrollbar::-webkit-scrollbar-track {
          background: rgba(255, 255, 255, 0.05);
          border-radius: 3px;
        }

        .custom-scrollbar::-webkit-scrollbar-thumb {
          background: rgba(168, 85, 247, 0.4);
          border-radius: 3px;
        }

        .custom-scrollbar::-webkit-scrollbar-thumb:hover {
          background: rgba(168, 85, 247, 0.6);
        }
      `}</style>
    </>
  );
}