(function() {
    'use strict';
    
    const NotificationSystem = {
        lastCheck: null,
        seenNotifications: new Set(),
        pollInterval: 5000,
        enabled: true,
        
        init: function() {
            this.requestPermission();
            this.startPolling();
            this.createNotificationBell();
            console.log('[Notifications] System initialized');
        },
        
        requestPermission: async function() {
            if (!('Notification' in window)) {
                console.log('[Notifications] Browser does not support notifications');
                return false;
            }
            
            if (Notification.permission === 'granted') {
                return true;
            }
            
            if (Notification.permission !== 'denied') {
                const permission = await Notification.requestPermission();
                return permission === 'granted';
            }
            
            return false;
        },
        
        createNotificationBell: function() {
            const bell = document.createElement('div');
            bell.id = 'notification-bell';
            bell.innerHTML = `
                <div class="notification-bell-icon" onclick="NotificationSystem.showPanel()">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path>
                        <path d="M13.73 21a2 2 0 0 1-3.46 0"></path>
                    </svg>
                    <span class="notification-badge" style="display: none;">0</span>
                </div>
            `;
            bell.style.cssText = `
                position: fixed;
                top: 15px;
                right: 180px;
                z-index: 999;
                cursor: pointer;
            `;
            
            const style = document.createElement('style');
            style.textContent = `
                .notification-bell-icon {
                    background: var(--primary-color, #2c82c9);
                    padding: 10px;
                    border-radius: 50%;
                    color: white;
                    position: relative;
                    transition: transform 0.2s;
                }
                .notification-bell-icon:hover {
                    transform: scale(1.1);
                }
                .notification-badge {
                    position: absolute;
                    top: -5px;
                    right: -5px;
                    background: #e74c3c;
                    color: white;
                    border-radius: 50%;
                    width: 20px;
                    height: 20px;
                    font-size: 12px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-weight: bold;
                }
                #notification-panel {
                    position: fixed;
                    top: 60px;
                    right: 130px;
                    width: 350px;
                    max-height: 500px;
                    background: var(--card-bg, #1e2030);
                    border: 1px solid var(--border-color, #2a2d45);
                    border-radius: 12px;
                    box-shadow: 0 10px 40px rgba(0,0,0,0.3);
                    z-index: 10000;
                    display: none;
                    overflow: hidden;
                }
                .notification-panel-header {
                    padding: 15px;
                    border-bottom: 1px solid var(--border-color, #2a2d45);
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                }
                .notification-panel-title {
                    font-weight: 600;
                    color: var(--text-primary, #fff);
                }
                .notification-panel-body {
                    max-height: 400px;
                    overflow-y: auto;
                }
                .notification-item {
                    padding: 12px 15px;
                    border-bottom: 1px solid var(--border-color, #2a2d45);
                    cursor: pointer;
                    transition: background 0.2s;
                }
                .notification-item:hover {
                    background: var(--hover-bg, #252840);
                }
                .notification-item-title {
                    font-weight: 600;
                    color: var(--text-primary, #fff);
                    margin-bottom: 4px;
                }
                .notification-item-message {
                    font-size: 13px;
                    color: var(--text-secondary, #8b8fa3);
                }
                .notification-item-time {
                    font-size: 11px;
                    color: var(--text-muted, #5a5e73);
                    margin-top: 4px;
                }
                .notification-empty {
                    padding: 40px 20px;
                    text-align: center;
                    color: var(--text-muted, #5a5e73);
                }
                .notification-type-order_failed .notification-item-title,
                .notification-type-stop_loss_triggered .notification-item-title,
                .notification-type-stop_loss_failed .notification-item-title {
                    color: #e74c3c;
                }
                .notification-type-order_filled_bto .notification-item-title,
                .notification-type-profit_target_hit .notification-item-title {
                    color: #27ae60;
                }
                .notification-type-order_filled_stc .notification-item-title {
                    color: #f39c12;
                }
            `;
            document.head.appendChild(style);
            document.body.appendChild(bell);
            
            const panel = document.createElement('div');
            panel.id = 'notification-panel';
            panel.innerHTML = `
                <div class="notification-panel-header">
                    <span class="notification-panel-title">Notifications</span>
                    <button onclick="NotificationSystem.clearAll()" style="background: none; border: none; color: #8b8fa3; cursor: pointer; font-size: 12px;">Clear All</button>
                </div>
                <div class="notification-panel-body" id="notification-list">
                    <div class="notification-empty">No notifications</div>
                </div>
            `;
            document.body.appendChild(panel);
            
            document.addEventListener('click', (e) => {
                const panel = document.getElementById('notification-panel');
                const bell = document.getElementById('notification-bell');
                if (panel && !panel.contains(e.target) && !bell.contains(e.target)) {
                    panel.style.display = 'none';
                }
            });
        },
        
        showPanel: function() {
            const panel = document.getElementById('notification-panel');
            if (panel) {
                panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
                if (panel.style.display === 'block') {
                    this.updateBadge(0);
                }
            }
        },
        
        updateBadge: function(count) {
            const badge = document.querySelector('.notification-badge');
            if (badge) {
                badge.textContent = count > 99 ? '99+' : count;
                badge.style.display = count > 0 ? 'flex' : 'none';
            }
        },
        
        startPolling: function() {
            this.poll();
            setInterval(() => this.poll(), this.pollInterval);
        },
        
        poll: async function() {
            if (!this.enabled) return;
            
            try {
                const response = await fetch('/api/notifications');
                if (!response.ok) return;
                
                const data = await response.json();
                if (!data.success) return;
                
                const notifications = data.notifications || [];
                let newCount = 0;
                
                for (const notif of notifications) {
                    const notifId = notif.datetime + notif.title;
                    if (!this.seenNotifications.has(notifId)) {
                        this.seenNotifications.add(notifId);
                        newCount++;
                        this.showDesktopNotification(notif);
                    }
                }
                
                this.updateNotificationList(notifications);
                
                if (newCount > 0) {
                    const currentBadge = parseInt(document.querySelector('.notification-badge')?.textContent || '0');
                    this.updateBadge(currentBadge + newCount);
                }
                
            } catch (err) {
                console.error('[Notifications] Poll error:', err);
            }
        },
        
        showDesktopNotification: function(notif) {
            if (Notification.permission !== 'granted') return;
            
            const options = {
                body: notif.message,
                icon: '/static/img/logo.png',
                tag: notif.datetime,
                requireInteraction: notif.type === 'order_failed' || notif.type === 'stop_loss_triggered'
            };
            
            try {
                const n = new Notification(notif.title, options);
                n.onclick = () => {
                    window.focus();
                    this.showPanel();
                    n.close();
                };
                
                if (notif.type !== 'order_failed' && notif.type !== 'stop_loss_triggered') {
                    setTimeout(() => n.close(), 8000);
                }
            } catch (err) {
                console.error('[Notifications] Desktop notification error:', err);
            }
        },
        
        updateNotificationList: function(notifications) {
            const list = document.getElementById('notification-list');
            if (!list) return;
            
            if (notifications.length === 0) {
                list.innerHTML = '<div class="notification-empty">No notifications</div>';
                return;
            }
            
            let html = '';
            for (const notif of notifications.slice(0, 50)) {
                html += `
                    <div class="notification-item notification-type-${notif.type}">
                        <div class="notification-item-title">${this.escapeHtml(notif.title)}</div>
                        <div class="notification-item-message">${this.escapeHtml(notif.message)}</div>
                        <div class="notification-item-time">${notif.timestamp} ${notif.broker ? '| ' + notif.broker : ''}</div>
                    </div>
                `;
            }
            list.innerHTML = html;
        },
        
        escapeHtml: function(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        },
        
        clearAll: async function() {
            try {
                await fetch('/api/notifications/clear', { method: 'POST' });
                this.seenNotifications.clear();
                this.updateBadge(0);
                this.updateNotificationList([]);
            } catch (err) {
                console.error('[Notifications] Clear error:', err);
            }
        }
    };
    
    window.NotificationSystem = NotificationSystem;
    
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => NotificationSystem.init());
    } else {
        NotificationSystem.init();
    }
})();
