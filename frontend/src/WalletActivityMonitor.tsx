import React, { useEffect, useRef, useState } from 'react';
import {
  ArrowUpRight,
  Bell,
  BellRing,
  CheckCheck,
  Clock,
  ExternalLink,
  TrendingUp,
  X,
} from 'lucide-react';
import walletActivityService from './WalletActivityService';
import { useAuth } from './contexts/AuthContext';

function formatTime(iso) {
  if (!iso) return '';
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function formatUSD(value) {
  if (value == null) return '$0';
  if (value >= 1000000) return `$${(value / 1000000).toFixed(2)}M`;
  if (value >= 1000) return `$${(value / 1000).toFixed(1)}K`;
  return `$${Number(value).toFixed(2)}`;
}

function SourceBadge({ source }) {
  if (source === 'elite15') {
    return <span className="ml-1 text-xs font-bold text-yellow-400 bg-yellow-400/10 px-1.5 py-0.5 rounded">ELITE</span>;
  }
  if (source === 'external') {
    return <span className="ml-1 text-xs font-bold text-blue-400 bg-blue-400/10 px-1.5 py-0.5 rounded">EXT</span>;
  }
  return null;
}

export default function WalletActivityMonitor() {
  const { user } = useAuth();
  const [notifications, setNotifications] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [showToast, setShowToast] = useState(false);
  const [latestNotification, setLatestNotification] = useState(null);
  const dropdownRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsOpen(false);
      }
    };

    if (isOpen) document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen]);

  useEffect(() => {
    if (!user?.id) return undefined;

    walletActivityService.start(user.id);
    const unsubscribe = walletActivityService.subscribe((data) => {
      if (data.has_new && data.notifications?.length > 0) {
        setLatestNotification(data.notifications[0]);
        setShowToast(true);
        setTimeout(() => setShowToast(false), 6000);
      }
      setNotifications(data.notifications || []);
      setUnreadCount(data.unread_count || 0);
    });

    loadNotifications();

    return () => {
      unsubscribe?.();
      walletActivityService.stop();
    };
  }, [user?.id]);

  const loadNotifications = async () => {
    if (!user?.id) return;
    setIsLoading(true);
    const data = await walletActivityService.getAllNotifications(user.id, false);
    setNotifications(data.notifications);
    setUnreadCount(data.unread_count);
    setIsLoading(false);
  };

  const handleMarkAsRead = async (notificationId) => {
    const success = await walletActivityService.markAsRead(notificationId);
    if (success) loadNotifications();
  };

  const handleMarkAllAsRead = async () => {
    const success = await walletActivityService.markAllAsRead();
    if (success) loadNotifications();
  };

  const handleNotificationClick = (notification) => {
    if (!notification.is_read) handleMarkAsRead(notification.id);
  };

  return (
    <>
      {showToast && latestNotification && (
        <div className="fixed top-20 left-2 right-2 sm:left-auto sm:right-6 z-50 animate-slide-in-right">
          <div className="bg-gradient-to-br from-purple-900 to-purple-950 border-2 border-purple-500/50 rounded-2xl shadow-2xl p-3 sm:p-4 w-full sm:w-96 backdrop-blur-xl">
            <div className="flex items-start gap-3">
              <div className="p-2 bg-purple-500/20 rounded-lg">
                <BellRing className="text-purple-400 animate-pulse" size={20} />
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-bold text-white">
                    {latestNotification._isElite15
                      ? 'Elite 15 Signal'
                      : latestNotification._source === 'external'
                        ? 'Exchange Alert'
                        : 'Wallet Alert'}
                  </span>
                  <button onClick={() => setShowToast(false)} className="ml-auto p-1 hover:bg-white/10 rounded">
                    <X size={14} />
                  </button>
                </div>
                <p className="text-sm text-gray-300 mb-2">
                  <code className="font-mono text-xs text-purple-300 cursor-pointer truncate inline-block max-w-[200px] align-bottom" onClick={() => navigator.clipboard.writeText(latestNotification.wallet_address || '')} title={latestNotification.wallet_address || ''}>{latestNotification.wallet_address}</code>
                  {' '}just{' '}
                  <span className={latestNotification._side === 'buy' ? 'text-green-400' : 'text-red-400'}>
                    {latestNotification._side}
                  </span>
                  {' '}<span className="font-bold text-white">{formatUSD(latestNotification._usdValue)}</span>
                  {' '}of{' '}<span className="text-yellow-400">${latestNotification._ticker}</span>
                </p>
                <button onClick={() => { setShowToast(false); setIsOpen(true); }} className="text-xs text-purple-400 hover:text-purple-300 flex items-center gap-1">
                  View <ArrowUpRight size={12} />
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="relative" ref={dropdownRef}>
        <button onClick={() => setIsOpen(!isOpen)} className="relative p-2 hover:bg-white/10 rounded-lg transition">
          {unreadCount > 0
            ? <BellRing className="text-purple-400 animate-pulse" size={20} />
            : <Bell className="text-gray-400" size={20} />}
          {unreadCount > 0 && (
            <span className="absolute -top-1 -right-1 bg-red-500 text-white text-xs font-bold rounded-full w-5 h-5 flex items-center justify-center animate-bounce">
              {unreadCount > 9 ? '9+' : unreadCount}
            </span>
          )}
        </button>

        {isOpen && (
          <div
            className="fixed sm:absolute left-2 right-2 sm:left-auto sm:right-0 top-16 sm:top-12 w-auto sm:w-96 max-h-[80vh] sm:max-h-[600px] rounded-xl shadow-2xl overflow-hidden animate-fade-in z-50"
            style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-color-strong)', color: 'var(--text-primary)' }}
          >
            <div className="bg-gradient-to-r from-purple-900/50 to-purple-800/30 p-4" style={{ borderBottom: '1px solid var(--border-color-strong)' }}>
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-lg font-bold flex items-center gap-2">
                  <Bell size={18} className="text-purple-400" /> Wallet Alerts
                </h3>
                <button onClick={() => setIsOpen(false)} className="p-1 hover:bg-white/10 rounded">
                  <X size={18} />
                </button>
              </div>
              {unreadCount > 0 && (
                <button onClick={handleMarkAllAsRead} className="text-xs text-purple-400 hover:text-purple-300 flex items-center gap-1">
                  <CheckCheck size={14} /> Mark all as read ({unreadCount})
                </button>
              )}
            </div>

            <div className="overflow-y-auto max-h-[500px]">
              {isLoading ? (
                <div className="p-8 text-center">
                  <div className="w-8 h-8 border-2 border-white/30 border-t-purple-500 rounded-full animate-spin mx-auto mb-2" />
                  <p className="text-sm text-gray-400">Loading...</p>
                </div>
              ) : notifications.length === 0 ? (
                <div className="p-8 text-center">
                  <Bell className="mx-auto mb-3 text-gray-400 opacity-50" size={48} />
                  <p className="text-gray-400 text-sm">No alerts yet</p>
                  <p className="text-gray-500 text-xs mt-1">Watchlist, external wallet, and Elite 15 alerts will appear here.</p>
                </div>
              ) : (
                notifications.map((notification) => {
                  const isBuy = notification._side === 'buy';
                  return (
                    <div
                      key={notification.id}
                      onClick={() => handleNotificationClick(notification)}
                      className={`p-4 hover:bg-white/5 transition cursor-pointer ${!notification.is_read ? 'bg-purple-500/5' : ''}`}
                      style={{ borderBottom: '1px solid var(--border-color)' }}
                    >
                      <div className="flex items-start gap-3">
                        <div className={`p-2 rounded-lg ${isBuy ? 'bg-green-500/20' : 'bg-red-500/20'}`}>
                          <TrendingUp className={isBuy ? 'text-green-400' : 'text-red-400 rotate-180'} size={16} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-start justify-between gap-2 mb-1">
                            <div className="flex items-center flex-wrap gap-1">
                              <code className="font-mono text-xs text-gray-300 cursor-pointer truncate inline-block max-w-[200px]" onClick={(e) => { e.stopPropagation(); navigator.clipboard.writeText(notification.wallet_address || ''); }} title={notification.wallet_address || ''}>{notification.wallet_address}</code>
                              <span className={`text-sm font-bold ${isBuy ? 'text-green-400' : 'text-red-400'}`}>
                                {notification._side?.toUpperCase()}
                              </span>
                              <SourceBadge source={notification._source} />
                            </div>
                            {!notification.is_read && <div className="w-2 h-2 bg-purple-500 rounded-full flex-shrink-0 mt-1" />}
                          </div>

                          <p className="text-sm text-gray-400 mb-1">
                            <span className="text-yellow-400 font-semibold">${notification._ticker}</span>
                            {notification._name && <span className="text-xs text-gray-500 ml-1">({notification._name})</span>}
                          </p>

                          <div className="flex items-center gap-3 text-xs text-gray-500">
                            <span className="font-bold text-white">{formatUSD(notification._usdValue)}</span>
                            <span className="flex items-center gap-1">
                              <Clock size={12} />{formatTime(notification.sent_at)}
                            </span>
                          </div>

                          {notification._solscanUrl && (
                            <a
                              href={notification._solscanUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={(event) => event.stopPropagation()}
                              className="text-xs text-purple-400 hover:text-purple-300 flex items-center gap-1 mt-2"
                            >
                              Solscan <ExternalLink size={10} />
                            </a>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
