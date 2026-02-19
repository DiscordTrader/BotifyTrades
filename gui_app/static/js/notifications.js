(function() {
    'use strict';
    
    const NotificationSystem = {
        lastSeenTimestamp: null,
        seenNotifications: new Set(),
        pollInterval: 3000,
        enabled: true,
        soundEnabled: true,
        popupEnabled: true,
        desktopEnabled: true,
        toastQueue: [],
        toastContainer: null,
        audioContext: null,
        maxToasts: 5,
        initialLoadDone: false,
        userHasInteracted: false,
        isPolling: false,
        lastSoundTime: 0,
        soundCooldownMs: 3000,
        
        init: function() {
            this.loadSettings();
            this.loadSeenState();
            this.createToastContainer();
            this.createSettingsPanel();
            this.startPolling();
            this.setupClickOutside();
            this.setupUserGestureListeners();
            console.log('[Notifications] System initialized');
        },
        
        loadSettings: function() {
            try {
                const saved = localStorage.getItem('botify_notification_settings');
                if (saved) {
                    const s = JSON.parse(saved);
                    this.enabled = s.enabled !== undefined ? s.enabled : true;
                    this.soundEnabled = s.soundEnabled !== undefined ? s.soundEnabled : true;
                    this.popupEnabled = s.popupEnabled !== undefined ? s.popupEnabled : true;
                    this.desktopEnabled = s.desktopEnabled !== undefined ? s.desktopEnabled : true;
                }
            } catch(e) {}
        },
        
        saveSettings: function() {
            try {
                localStorage.setItem('botify_notification_settings', JSON.stringify({
                    enabled: this.enabled,
                    soundEnabled: this.soundEnabled,
                    popupEnabled: this.popupEnabled,
                    desktopEnabled: this.desktopEnabled
                }));
            } catch(e) {}
        },
        
        loadSeenState: function() {
            try {
                const saved = localStorage.getItem('botify_seen_notifications');
                if (saved) {
                    const data = JSON.parse(saved);
                    this.lastSeenTimestamp = data.lastSeenTimestamp || null;
                    const ids = data.seenIds || [];
                    ids.forEach(id => this.seenNotifications.add(id));
                }
            } catch(e) {}
        },
        
        saveSeenState: function() {
            try {
                const ids = Array.from(this.seenNotifications).slice(-200);
                localStorage.setItem('botify_seen_notifications', JSON.stringify({
                    lastSeenTimestamp: this.lastSeenTimestamp,
                    seenIds: ids
                }));
            } catch(e) {}
        },
        
        setupUserGestureListeners: function() {
            const self = this;
            function onFirstInteraction() {
                self.userHasInteracted = true;
                if (!self.audioContext) {
                    try {
                        self.audioContext = new (window.AudioContext || window.webkitAudioContext)();
                    } catch(e) {}
                }
                if (self.audioContext && self.audioContext.state === 'suspended') {
                    self.audioContext.resume();
                }
                if ('Notification' in window && Notification.permission === 'default' && self.desktopEnabled) {
                    Notification.requestPermission();
                }
                document.removeEventListener('click', onFirstInteraction);
                document.removeEventListener('keydown', onFirstInteraction);
            }
            document.addEventListener('click', onFirstInteraction);
            document.addEventListener('keydown', onFirstInteraction);
        },
        
        ensureAudio: function() {
            if (!this.audioContext) {
                try {
                    this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
                } catch(e) { return; }
            }
            if (this.audioContext.state === 'suspended') {
                this.audioContext.resume();
            }
        },
        
        playSound: function(type) {
            if (!this.soundEnabled) return;
            
            const timestamp = Date.now();
            if (timestamp - this.lastSoundTime < this.soundCooldownMs) return;
            this.lastSoundTime = timestamp;
            
            this.ensureAudio();
            if (!this.audioContext) return;
            
            try {
                const ctx = this.audioContext;
                const now = ctx.currentTime;
                
                const gainNode = ctx.createGain();
                gainNode.connect(ctx.destination);
                gainNode.gain.setValueAtTime(0.15, now);
                
                if (type === 'order_failed' || type === 'stop_loss_triggered' || type === 'broker_disconnect') {
                    const osc = ctx.createOscillator();
                    osc.connect(gainNode);
                    osc.type = 'sine';
                    osc.frequency.setValueAtTime(880, now);
                    osc.frequency.setValueAtTime(660, now + 0.1);
                    osc.frequency.setValueAtTime(440, now + 0.2);
                    gainNode.gain.exponentialRampToValueAtTime(0.001, now + 0.5);
                    osc.start(now);
                    osc.stop(now + 0.5);
                } else if (type === 'conditional_created') {
                    const osc = ctx.createOscillator();
                    osc.connect(gainNode);
                    osc.type = 'sine';
                    osc.frequency.setValueAtTime(392, now);
                    osc.frequency.setValueAtTime(494, now + 0.1);
                    osc.frequency.setValueAtTime(587, now + 0.2);
                    gainNode.gain.exponentialRampToValueAtTime(0.001, now + 0.4);
                    osc.start(now);
                    osc.stop(now + 0.4);
                } else if (type === 'conditional_triggered') {
                    const osc = ctx.createOscillator();
                    osc.connect(gainNode);
                    osc.type = 'square';
                    osc.frequency.setValueAtTime(440, now);
                    osc.frequency.setValueAtTime(660, now + 0.06);
                    osc.frequency.setValueAtTime(880, now + 0.12);
                    gainNode.gain.exponentialRampToValueAtTime(0.001, now + 0.35);
                    osc.start(now);
                    osc.stop(now + 0.35);
                } else if (type === 'conditional_failed' || type === 'conditional_expired' || type === 'conditional_cancelled') {
                    const osc = ctx.createOscillator();
                    osc.connect(gainNode);
                    osc.type = 'sine';
                    osc.frequency.setValueAtTime(440, now);
                    osc.frequency.setValueAtTime(330, now + 0.15);
                    gainNode.gain.exponentialRampToValueAtTime(0.001, now + 0.35);
                    osc.start(now);
                    osc.stop(now + 0.35);
                } else if (type === 'order_placed_bto' || type === 'order_placed_stc') {
                    const osc = ctx.createOscillator();
                    osc.connect(gainNode);
                    osc.type = 'sine';
                    osc.frequency.setValueAtTime(440, now);
                    osc.frequency.setValueAtTime(523, now + 0.1);
                    gainNode.gain.exponentialRampToValueAtTime(0.001, now + 0.3);
                    osc.start(now);
                    osc.stop(now + 0.3);
                } else if (type === 'order_filled_bto' || type === 'order_filled_stc' || type === 'profit_target_hit') {
                    const osc = ctx.createOscillator();
                    osc.connect(gainNode);
                    osc.type = 'sine';
                    osc.frequency.setValueAtTime(523, now);
                    osc.frequency.setValueAtTime(659, now + 0.08);
                    osc.frequency.setValueAtTime(784, now + 0.16);
                    gainNode.gain.exponentialRampToValueAtTime(0.001, now + 0.4);
                    osc.start(now);
                    osc.stop(now + 0.4);
                } else {
                    const osc = ctx.createOscillator();
                    osc.connect(gainNode);
                    osc.type = 'sine';
                    osc.frequency.setValueAtTime(600, now);
                    osc.frequency.setValueAtTime(800, now + 0.1);
                    gainNode.gain.exponentialRampToValueAtTime(0.001, now + 0.3);
                    osc.start(now);
                    osc.stop(now + 0.3);
                }
            } catch(e) {
                console.error('[Notifications] Sound error:', e);
            }
        },
        
        createToastContainer: function() {
            if (document.getElementById('toast-container')) {
                this.toastContainer = document.getElementById('toast-container');
                return;
            }
            const container = document.createElement('div');
            container.id = 'toast-container';
            document.body.appendChild(container);
            this.toastContainer = container;
        },
        
        createSettingsPanel: function() {
            const bellContainer = document.getElementById('notification-bell-container');
            if (!bellContainer) return;
            
            const panel = document.getElementById('notification-panel');
            if (!panel) return;
            
            const header = panel.querySelector('.notification-panel-header');
            if (!header) return;
            
            const existingControls = header.querySelector('.notif-header-controls');
            if (existingControls) return;
            
            const controlsDiv = document.createElement('div');
            controlsDiv.className = 'notif-header-controls';
            controlsDiv.innerHTML = `
                <button id="notif-settings-btn" class="notif-icon-btn" onclick="NotificationSystem.toggleSettingsPanel()" title="Notification Settings">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="12" r="3"></circle>
                        <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06A1.65 1.65 0 0019.32 9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z"></path>
                    </svg>
                </button>
                <button id="notif-sound-toggle" class="notif-icon-btn ${this.soundEnabled ? 'active' : 'muted'}" onclick="NotificationSystem.toggleSound()" title="${this.soundEnabled ? 'Mute Sounds' : 'Unmute Sounds'}">
                    <svg id="notif-sound-on-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="display:${this.soundEnabled ? 'block' : 'none'}">
                        <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon>
                        <path d="M19.07 4.93a10 10 0 010 14.14M15.54 8.46a5 5 0 010 7.07"></path>
                    </svg>
                    <svg id="notif-sound-off-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="display:${this.soundEnabled ? 'none' : 'block'}">
                        <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon>
                        <line x1="23" y1="9" x2="17" y2="15"></line>
                        <line x1="17" y1="9" x2="23" y2="15"></line>
                    </svg>
                </button>
            `;
            
            const clearBtn = header.querySelector('.notification-panel-clear');
            header.insertBefore(controlsDiv, clearBtn);
            
            const settingsPanel = document.createElement('div');
            settingsPanel.id = 'notif-settings-panel';
            settingsPanel.className = 'notif-settings-panel';
            settingsPanel.style.display = 'none';
            settingsPanel.innerHTML = `
                <div class="notif-settings-title">Notification Settings</div>
                <div class="notif-setting-row">
                    <div class="notif-setting-info">
                        <span class="notif-setting-label">Notifications</span>
                        <span class="notif-setting-desc">Enable or disable all notifications</span>
                    </div>
                    <label class="notif-toggle-switch">
                        <input type="checkbox" id="notif-enabled-toggle" ${this.enabled ? 'checked' : ''} onchange="NotificationSystem.toggleEnabled(this.checked)">
                        <span class="notif-toggle-slider"></span>
                    </label>
                </div>
                <div class="notif-setting-row">
                    <div class="notif-setting-info">
                        <span class="notif-setting-label">Pop-up Toasts</span>
                        <span class="notif-setting-desc">Show alerts on screen automatically</span>
                    </div>
                    <label class="notif-toggle-switch">
                        <input type="checkbox" id="notif-popup-toggle" ${this.popupEnabled ? 'checked' : ''} onchange="NotificationSystem.togglePopup(this.checked)">
                        <span class="notif-toggle-slider"></span>
                    </label>
                </div>
                <div class="notif-setting-row">
                    <div class="notif-setting-info">
                        <span class="notif-setting-label">Desktop Notifications</span>
                        <span class="notif-setting-desc">Browser native notifications</span>
                    </div>
                    <label class="notif-toggle-switch">
                        <input type="checkbox" id="notif-desktop-toggle" ${this.desktopEnabled ? 'checked' : ''} onchange="NotificationSystem.toggleDesktop(this.checked)">
                        <span class="notif-toggle-slider"></span>
                    </label>
                </div>
                <div class="notif-setting-row">
                    <div class="notif-setting-info">
                        <span class="notif-setting-label">Sound Alerts</span>
                        <span class="notif-setting-desc">Play sound for new notifications</span>
                    </div>
                    <label class="notif-toggle-switch">
                        <input type="checkbox" id="notif-sound-toggle-check" ${this.soundEnabled ? 'checked' : ''} onchange="NotificationSystem.toggleSound(this.checked)">
                        <span class="notif-toggle-slider"></span>
                    </label>
                </div>
                <div class="notif-setting-row">
                    <div class="notif-setting-info">
                        <span class="notif-setting-label">Test Alert</span>
                        <span class="notif-setting-desc">Send a test notification</span>
                    </div>
                    <button class="notif-test-btn" onclick="NotificationSystem.sendTestToast()">Test</button>
                </div>
            `;
            
            const panelBody = panel.querySelector('.notification-panel-body');
            panel.insertBefore(settingsPanel, panelBody);
        },
        
        toggleSettingsPanel: function() {
            const panel = document.getElementById('notif-settings-panel');
            if (panel) {
                panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
            }
        },
        
        toggleEnabled: function(val) {
            if (val !== undefined) {
                this.enabled = val;
            } else {
                this.enabled = !this.enabled;
            }
            this.saveSettings();
            const toggle = document.getElementById('notif-enabled-toggle');
            if (toggle) toggle.checked = this.enabled;
        },
        
        togglePopup: function(val) {
            if (val !== undefined) {
                this.popupEnabled = val;
            } else {
                this.popupEnabled = !this.popupEnabled;
            }
            this.saveSettings();
            const toggle = document.getElementById('notif-popup-toggle');
            if (toggle) toggle.checked = this.popupEnabled;
        },
        
        toggleDesktop: function(val) {
            if (val !== undefined) {
                this.desktopEnabled = val;
            } else {
                this.desktopEnabled = !this.desktopEnabled;
            }
            this.saveSettings();
            const toggle = document.getElementById('notif-desktop-toggle');
            if (toggle) toggle.checked = this.desktopEnabled;
            
            if (this.desktopEnabled && this.userHasInteracted && 'Notification' in window && Notification.permission === 'default') {
                Notification.requestPermission();
            }
        },
        
        toggleSound: function(val) {
            if (val !== undefined) {
                this.soundEnabled = val;
            } else {
                this.soundEnabled = !this.soundEnabled;
            }
            this.saveSettings();
            
            const btn = document.getElementById('notif-sound-toggle');
            const onIcon = document.getElementById('notif-sound-on-icon');
            const offIcon = document.getElementById('notif-sound-off-icon');
            const checkbox = document.getElementById('notif-sound-toggle-check');
            
            if (btn) {
                btn.classList.toggle('active', this.soundEnabled);
                btn.classList.toggle('muted', !this.soundEnabled);
                btn.title = this.soundEnabled ? 'Mute Sounds' : 'Unmute Sounds';
            }
            if (onIcon) onIcon.style.display = this.soundEnabled ? 'block' : 'none';
            if (offIcon) offIcon.style.display = this.soundEnabled ? 'none' : 'block';
            if (checkbox) checkbox.checked = this.soundEnabled;
        },
        
        setupClickOutside: function() {
            document.addEventListener('click', (e) => {
                const panel = document.getElementById('notification-panel');
                const container = document.getElementById('notification-bell-container');
                if (panel && container && !container.contains(e.target)) {
                    panel.style.display = 'none';
                    const settingsPanel = document.getElementById('notif-settings-panel');
                    if (settingsPanel) settingsPanel.style.display = 'none';
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
            const bellBtn = document.getElementById('notification-bell-btn');
            if (bellBtn) {
                bellBtn.classList.toggle('has-notifications', count > 0);
            }
        },
        
        startPolling: function() {
            this.poll();
            setInterval(() => this.poll(), this.pollInterval);
        },
        
        poll: async function() {
            if (!this.enabled) return;
            if (this.isPolling) return;
            this.isPolling = true;
            
            try {
                const response = await fetch('/api/notifications');
                if (!response.ok) return;
                
                const data = await response.json();
                if (!data.success) return;
                
                const notifications = data.notifications || [];
                let newCount = 0;
                let newNotifs = [];
                
                const isFirstLoad = !this.initialLoadDone;
                this.initialLoadDone = true;
                
                for (const notif of notifications) {
                    const notifId = notif.id || (notif.datetime + notif.title);
                    if (!this.seenNotifications.has(notifId)) {
                        this.seenNotifications.add(notifId);
                        newCount++;
                        
                        if (!isFirstLoad) {
                            newNotifs.push(notif);
                        }
                    }
                }
                
                if (newNotifs.length > 0) {
                    let soundPlayed = false;
                    for (const notif of newNotifs) {
                        if (this.popupEnabled) {
                            this.showToast(notif);
                        }
                        
                        if (this.soundEnabled && !soundPlayed) {
                            this.playSound(notif.type);
                            soundPlayed = true;
                        }
                        
                        if (this.desktopEnabled) {
                            this.showDesktopNotification(notif);
                        }
                    }
                }
                
                this.saveSeenState();
                this.updateNotificationList(notifications);
                
                if (newCount > 0) {
                    const badge = document.getElementById('notification-badge');
                    const currentBadge = parseInt(badge?.textContent || '0');
                    this.updateBadge(currentBadge + newCount);
                }
                
            } catch (err) {
                console.error('[Notifications] Poll error:', err);
            } finally {
                this.isPolling = false;
            }
        },
        
        getTypeConfig: function(type) {
            const configs = {
                order_failed: { icon: '❌', color: '#ef4444', label: 'ORDER FAILED', accent: 'rgba(239, 68, 68, 0.15)', border: 'rgba(239, 68, 68, 0.4)' },
                stop_loss_triggered: { icon: '🛑', color: '#ef4444', label: 'STOP LOSS', accent: 'rgba(239, 68, 68, 0.15)', border: 'rgba(239, 68, 68, 0.4)' },
                order_placed_bto: { icon: '📤', color: '#f59e0b', label: 'BTO PLACED', accent: 'rgba(245, 158, 11, 0.15)', border: 'rgba(245, 158, 11, 0.4)' },
                order_placed_stc: { icon: '📤', color: '#f59e0b', label: 'STC PLACED', accent: 'rgba(245, 158, 11, 0.15)', border: 'rgba(245, 158, 11, 0.4)' },
                conditional_created: { icon: '📋', color: '#6366f1', label: 'CONDITIONAL', accent: 'rgba(99, 102, 241, 0.15)', border: 'rgba(99, 102, 241, 0.4)' },
                conditional_triggered: { icon: '⚡', color: '#eab308', label: 'TRIGGERED', accent: 'rgba(234, 179, 8, 0.15)', border: 'rgba(234, 179, 8, 0.4)' },
                conditional_expired: { icon: '⏰', color: '#9ca3af', label: 'EXPIRED', accent: 'rgba(156, 163, 175, 0.15)', border: 'rgba(156, 163, 175, 0.4)' },
                conditional_failed: { icon: '❌', color: '#ef4444', label: 'COND. FAILED', accent: 'rgba(239, 68, 68, 0.15)', border: 'rgba(239, 68, 68, 0.4)' },
                conditional_cancelled: { icon: '🚫', color: '#9ca3af', label: 'CANCELLED', accent: 'rgba(156, 163, 175, 0.15)', border: 'rgba(156, 163, 175, 0.4)' },
                order_filled_bto: { icon: '🟢', color: '#22c55e', label: 'BTO FILLED', accent: 'rgba(34, 197, 94, 0.15)', border: 'rgba(34, 197, 94, 0.4)' },
                order_filled_stc: { icon: '🔵', color: '#3b82f6', label: 'STC FILLED', accent: 'rgba(59, 130, 246, 0.15)', border: 'rgba(59, 130, 246, 0.4)' },
                profit_target_hit: { icon: '🎯', color: '#22c55e', label: 'PROFIT TARGET', accent: 'rgba(34, 197, 94, 0.15)', border: 'rgba(34, 197, 94, 0.4)' },
                trailing_stop: { icon: '📊', color: '#f97316', label: 'TRAILING STOP', accent: 'rgba(249, 115, 22, 0.15)', border: 'rgba(249, 115, 22, 0.4)' },
                giveback_guard: { icon: '🛡️', color: '#a855f7', label: 'GIVEBACK GUARD', accent: 'rgba(168, 85, 247, 0.15)', border: 'rgba(168, 85, 247, 0.4)' },
                broker_disconnect: { icon: '🔌', color: '#ef4444', label: 'DISCONNECTED', accent: 'rgba(239, 68, 68, 0.15)', border: 'rgba(239, 68, 68, 0.4)' },
                broker_reconnect: { icon: '✅', color: '#22c55e', label: 'RECONNECTED', accent: 'rgba(34, 197, 94, 0.15)', border: 'rgba(34, 197, 94, 0.4)' },
                early_trailing: { icon: '📈', color: '#06b6d4', label: 'EARLY TRAIL', accent: 'rgba(6, 182, 212, 0.15)', border: 'rgba(6, 182, 212, 0.4)' },
                risk_monitoring: { icon: '🔍', color: '#00f5ff', label: 'RISK ENGINE', accent: 'rgba(0, 245, 255, 0.12)', border: 'rgba(0, 245, 255, 0.3)' },
                profit_locked: { icon: '🔒', color: '#22c55e', label: 'PROFIT LOCK', accent: 'rgba(34, 197, 94, 0.12)', border: 'rgba(34, 197, 94, 0.35)' },
                profit_target: { icon: '🎯', color: '#30d158', label: 'TARGET HIT', accent: 'rgba(48, 209, 88, 0.12)', border: 'rgba(48, 209, 88, 0.35)' },
                dynamic_sl: { icon: '📊', color: '#ff9500', label: 'SL ESCALATED', accent: 'rgba(255, 149, 0, 0.12)', border: 'rgba(255, 149, 0, 0.35)' },
                position_closing: { icon: '🚪', color: '#ff3b30', label: 'CLOSING', accent: 'rgba(255, 59, 48, 0.12)', border: 'rgba(255, 59, 48, 0.35)' }
            };
            return configs[type] || { icon: '🔔', color: '#00F5FF', label: 'ALERT', accent: 'rgba(0, 245, 255, 0.15)', border: 'rgba(0, 245, 255, 0.4)' };
        },
        
        showToast: function(notif) {
            if (!this.toastContainer) return;
            
            const existingToasts = this.toastContainer.querySelectorAll('.toast-notification');
            if (existingToasts.length >= this.maxToasts) {
                const oldest = existingToasts[0];
                this.dismissToast(oldest);
            }
            
            const config = this.getTypeConfig(notif.type);
            
            const toast = document.createElement('div');
            toast.className = 'toast-notification';
            toast.setAttribute('data-type', notif.type);
            toast.style.setProperty('--toast-accent', config.color);
            toast.style.setProperty('--toast-bg', config.accent);
            toast.style.setProperty('--toast-border', config.border);
            
            toast.innerHTML = `
                <div class="toast-accent-bar"></div>
                <div class="toast-content">
                    <div class="toast-header">
                        <div class="toast-type-badge">
                            <span class="toast-icon">${config.icon}</span>
                            <span class="toast-label" style="color: ${config.color}">${config.label}</span>
                        </div>
                        <button class="toast-close" onclick="NotificationSystem.dismissToast(this.closest('.toast-notification'))">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                                <line x1="18" y1="6" x2="6" y2="18"></line>
                                <line x1="6" y1="6" x2="18" y2="18"></line>
                            </svg>
                        </button>
                    </div>
                    <div class="toast-title">${this.escapeHtml(notif.title)}</div>
                    <div class="toast-message">${this.escapeHtml(notif.message)}</div>
                    <div class="toast-meta">
                        <span class="toast-time">${notif.timestamp || 'Just now'}</span>
                        ${notif.broker ? `<span class="toast-broker">${this.escapeHtml(notif.broker)}</span>` : ''}
                    </div>
                    <div class="toast-progress"><div class="toast-progress-bar"></div></div>
                </div>
            `;
            
            this.toastContainer.appendChild(toast);
            
            requestAnimationFrame(() => {
                toast.classList.add('toast-visible');
            });
            
            const isCritical = ['order_failed', 'stop_loss_triggered', 'broker_disconnect'].includes(notif.type);
            const duration = isCritical ? 12000 : 7000;
            
            setTimeout(() => {
                this.dismissToast(toast);
            }, duration);
        },
        
        dismissToast: function(toast) {
            if (!toast || !toast.parentNode) return;
            toast.classList.add('toast-exiting');
            setTimeout(() => {
                if (toast.parentNode) toast.parentNode.removeChild(toast);
            }, 400);
        },
        
        sendTestToast: function() {
            this.ensureAudio();
            const testNotif = {
                type: 'order_filled_bto',
                title: 'BTO Filled: SPY $500C 03/21',
                message: '1 contract filled @ $3.45 on Webull',
                timestamp: new Date().toLocaleTimeString(),
                broker: 'Webull',
                datetime: 'test_' + Date.now().toString()
            };
            this.showToast(testNotif);
            this.playSound('order_filled_bto');
        },
        
        showDesktopNotification: function(notif) {
            if (!this.desktopEnabled) return;
            if (!('Notification' in window)) return;
            if (Notification.permission !== 'granted') return;
            
            const config = this.getTypeConfig(notif.type);
            const options = {
                body: notif.message,
                icon: '/static/img/logo.png',
                tag: notif.datetime,
                requireInteraction: notif.type === 'order_failed' || notif.type === 'stop_loss_triggered'
            };
            
            try {
                const n = new Notification(`${config.icon} ${notif.title}`, options);
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
                list.innerHTML = '<div class="notification-empty"><svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="margin-bottom:12px;opacity:0.3"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg><br>No notifications yet</div>';
                return;
            }
            
            let html = '';
            for (const notif of notifications.slice(0, 50)) {
                const config = this.getTypeConfig(notif.type);
                html += `
                    <div class="notification-item notification-type-${notif.type}">
                        <div class="notification-item-header">
                            <span class="notification-item-icon">${config.icon}</span>
                            <span class="notification-item-badge" style="background: ${config.accent}; color: ${config.color}; border: 1px solid ${config.border}">${config.label}</span>
                        </div>
                        <div class="notification-item-title">${this.escapeHtml(notif.title)}</div>
                        <div class="notification-item-message">${this.escapeHtml(notif.message)}</div>
                        <div class="notification-item-time">${notif.timestamp}${notif.broker ? ' &middot; ' + this.escapeHtml(notif.broker) : ''}</div>
                    </div>
                `;
            }
            list.innerHTML = html;
        },
        
        escapeHtml: function(text) {
            if (!text) return '';
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        },
        
        clearAll: async function() {
            try {
                await fetch('/api/notifications/clear', { method: 'POST' });
                this.seenNotifications.clear();
                this.saveSeenState();
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
