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
            this.setupClickOutside();
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
        
        setupClickOutside: function() {
            document.addEventListener('click', (e) => {
                const panel = document.getElementById('notification-panel');
                const container = document.getElementById('notification-bell-container');
                if (panel && container && !container.contains(e.target)) {
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
            const badge = document.getElementById('notification-badge');
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
                    const badge = document.getElementById('notification-badge');
                    const currentBadge = parseInt(badge?.textContent || '0');
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
                        <div class="notification-item-time">${notif.timestamp}${notif.broker ? ' | ' + notif.broker : ''}</div>
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
