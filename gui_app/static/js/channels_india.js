// India Market Channel Management JavaScript
// Handles NSE/BSE/MCX trading with DhanQ, Upstox, Zerodha brokers

let indiaChannelCategory = 'EXECUTE';
const INDIA_BROKERS = ['DHANQ', 'UPSTOX', 'ZERODHA'];

// IST Timezone formatting helpers for India market pages
const IST_TIMEZONE = 'Asia/Kolkata';

function formatDateTimeIST(dateStr) {
    if (!dateStr) return 'N/A';
    try {
        // Database stores UTC - append Z if no timezone indicator present
        let normalizedStr = dateStr;
        if (!dateStr.includes('Z') && !dateStr.includes('+') && !dateStr.includes('T')) {
            // Format like "2026-01-06 08:04:21" - convert to ISO format with UTC
            normalizedStr = dateStr.replace(' ', 'T') + 'Z';
        } else if (dateStr.includes('T') && !dateStr.includes('Z') && !dateStr.includes('+')) {
            normalizedStr = dateStr + 'Z';
        }
        const date = new Date(normalizedStr);
        return date.toLocaleString('en-IN', { 
            timeZone: IST_TIMEZONE,
            year: 'numeric',
            month: 'numeric',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: true
        }) + ' IST';
    } catch (e) {
        return dateStr;
    }
}

function formatTimeIST(dateStr) {
    if (!dateStr) return 'N/A';
    try {
        // Database stores UTC - append Z if no timezone indicator present
        let normalizedStr = dateStr;
        if (!dateStr.includes('Z') && !dateStr.includes('+') && !dateStr.includes('T')) {
            normalizedStr = dateStr.replace(' ', 'T') + 'Z';
        } else if (dateStr.includes('T') && !dateStr.includes('Z') && !dateStr.includes('+')) {
            normalizedStr = dateStr + 'Z';
        }
        const date = new Date(normalizedStr);
        return date.toLocaleTimeString('en-IN', { 
            timeZone: IST_TIMEZONE,
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: true
        }) + ' IST';
    } catch (e) {
        return dateStr;
    }
}

function parseEnabledBrokers(enabledBrokers) {
    if (!enabledBrokers) return [];
    if (Array.isArray(enabledBrokers)) return enabledBrokers;
    try {
        const parsed = JSON.parse(enabledBrokers);
        return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
        return [];
    }
}

function getBrokerChecked(enabledBrokers, brokerName) {
    const brokers = parseEnabledBrokers(enabledBrokers);
    return brokers.includes(brokerName) ? 'checked' : '';
}

function renderIndiaBrokerBadges(enabledBrokers) {
    const brokers = parseEnabledBrokers(enabledBrokers);
    if (brokers.length === 0) {
        return '<span style="color: #6b7280; font-size: 11px;">No broker</span>';
    }
    const colors = {
        'DHANQ': { color: '#8a2be2', bg: 'rgba(138, 43, 226, 0.15)', border: 'rgba(138, 43, 226, 0.3)' },
        'UPSTOX': { color: '#00c853', bg: 'rgba(0, 200, 83, 0.15)', border: 'rgba(0, 200, 83, 0.3)' },
        'ZERODHA': { color: '#ff5722', bg: 'rgba(255, 87, 34, 0.15)', border: 'rgba(255, 87, 34, 0.3)' }
    };
    return brokers.map(broker => {
        const c = colors[broker] || { color: '#00d4ff', bg: 'rgba(0, 212, 255, 0.15)', border: 'rgba(0, 212, 255, 0.3)' };
        return `<span style="display: inline-block; padding: 2px 6px; background: ${c.bg}; border: 1px solid ${c.border}; border-radius: 4px; font-size: 9px; color: ${c.color}; font-weight: 600; margin: 1px;">${broker}</span>`;
    }).join(' ');
}

function initIndiaChannelManagement(category) {
    indiaChannelCategory = category;
    loadIndiaChannels();
    
    document.getElementById('add-channel-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        await addIndiaChannel();
    });
}

async function loadIndiaChannels() {
    const container = document.getElementById('channels-list');
    
    try {
        const response = await fetch(`/api/channels?category=${indiaChannelCategory}&market=IN`);
        const channels = await response.json();
        
        // Handle error responses (like auth required)
        if (channels.error || !Array.isArray(channels)) {
            console.error('API error:', channels.error || 'Invalid response');
            container.innerHTML = `
                <div style="text-align: center; padding: 60px 20px;">
                    <div style="font-size: 48px; margin-bottom: 16px;">🇮🇳</div>
                    <div style="font-size: 18px; color: #ff9900; font-weight: 600; margin-bottom: 8px;">No India Channels Yet</div>
                    <div style="color: #8E8E93; font-size: 14px;">Add your first India market channel to start trading NIFTY, BANKNIFTY, and more!</div>
                </div>
            `;
            return;
        }
        
        if (channels.length === 0) {
            container.innerHTML = `
                <div style="text-align: center; padding: 60px 20px;">
                    <div style="font-size: 48px; margin-bottom: 16px;">🇮🇳</div>
                    <div style="font-size: 18px; color: #ff9900; font-weight: 600; margin-bottom: 8px;">No India Channels Yet</div>
                    <div style="color: #8E8E93; font-size: 14px;">Add your first India market channel to start trading NIFTY, BANKNIFTY, and more!</div>
                </div>
            `;
            return;
        }
        
        container.innerHTML = `
            <table class="data-table" style="width: 100%; border-collapse: collapse;">
                <thead>
                    <tr>
                        <th style="text-align: left; padding: 12px 16px; font-size: 11px; color: #ff9900; text-transform: uppercase; font-weight: 600; letter-spacing: 0.5px;">Channel</th>
                        <th style="text-align: center; padding: 12px 16px; font-size: 11px; color: #ff9900; text-transform: uppercase; font-weight: 600;">Status</th>
                        <th style="text-align: center; padding: 12px 16px; font-size: 11px; color: #ff9900; text-transform: uppercase; font-weight: 600;">Broker</th>
                        <th style="text-align: center; padding: 12px 16px; font-size: 11px; color: #ff9900; text-transform: uppercase; font-weight: 600;">Signals</th>
                        <th style="text-align: center; padding: 12px 16px; font-size: 11px; color: #ff9900; text-transform: uppercase; font-weight: 600;">Today</th>
                        <th style="text-align: center; padding: 12px 16px; font-size: 11px; color: #ff9900; text-transform: uppercase; font-weight: 600;">Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${channels.map(channel => `
                        <tr style="border-bottom: 1px solid rgba(255, 153, 0, 0.1); transition: all 0.2s;" onmouseover="this.style.background='rgba(255, 153, 0, 0.05)'" onmouseout="this.style.background='transparent'">
                            <td style="padding: 16px; border-left: 3px solid ${channel.is_active ? '#00ff88' : '#ff6b6b'};">
                                <div style="font-weight: 700; font-size: 14px; color: #ffffff; margin-bottom: 4px;">${channel.name}</div>
                                <div style="font-size: 10px; color: #6b7280; font-family: 'Consolas', monospace;">ID: ${channel.discord_channel_id}</div>
                            </td>
                            <td style="padding: 16px; text-align: center;">
                                <span style="display: inline-flex; align-items: center; gap: 4px; padding: 6px 12px; background: ${channel.is_active ? 'rgba(0, 255, 136, 0.15)' : 'rgba(255, 107, 107, 0.15)'}; border: 1px solid ${channel.is_active ? 'rgba(0, 255, 136, 0.3)' : 'rgba(255, 107, 107, 0.3)'}; border-radius: 6px; font-size: 11px; color: ${channel.is_active ? '#00ff88' : '#ff6b6b'}; font-weight: 700;">
                                    ${channel.is_active ? 'ACTIVE' : 'INACTIVE'}
                                </span>
                            </td>
                            <td style="padding: 16px; text-align: center;">
                                ${renderIndiaBrokerBadges(channel.enabled_brokers)}
                            </td>
                            <td style="padding: 16px; text-align: center;">
                                <span style="font-weight: 700; font-size: 16px; color: #ff9900;">${channel.total_signals || 0}</span>
                            </td>
                            <td style="padding: 16px; text-align: center;">
                                <span style="font-weight: 700; font-size: 16px; color: ${channel.signals_today > 0 ? '#00ff88' : '#6b7280'};">${channel.signals_today || 0}</span>
                            </td>
                            <td style="padding: 16px; text-align: center;">
                                <div style="display: flex; gap: 4px; justify-content: center;">
                                    <button onclick="toggleIndiaBrokerSelection(${channel.id})" title="Select Brokers" style="background: rgba(255, 153, 0, 0.1); border: 1px solid rgba(255, 153, 0, 0.3); color: #ff9900; width: 28px; height: 28px; border-radius: 6px; cursor: pointer; font-size: 14px;">🔌</button>
                                    <button onclick="toggleIndiaRiskManagement(${channel.id})" title="Risk Management" style="background: rgba(255, 153, 0, 0.1); border: 1px solid rgba(255, 153, 0, 0.3); color: #ff9900; width: 28px; height: 28px; border-radius: 6px; cursor: pointer; font-size: 14px;">🛡️</button>
                                    <button onclick="toggleIndiaChannel(${channel.id}, ${channel.is_active})" title="${channel.is_active ? 'Disable' : 'Enable'}" style="background: rgba(255, 153, 0, 0.1); border: 1px solid rgba(255, 153, 0, 0.3); color: #ff9900; width: 28px; height: 28px; border-radius: 6px; cursor: pointer; font-size: 14px;">${channel.is_active ? '⏸️' : '▶️'}</button>
                                    <button onclick="deleteIndiaChannel(${channel.id}, '${channel.name}')" title="Delete" style="background: rgba(255, 107, 107, 0.1); border: 1px solid rgba(255, 107, 107, 0.3); color: #ff6b6b; width: 28px; height: 28px; border-radius: 6px; cursor: pointer; font-size: 14px;">🗑️</button>
                                </div>
                            </td>
                        </tr>
                        <tr id="india-broker-row-${channel.id}" style="display: none; background: rgba(255, 153, 0, 0.03);">
                            <td colspan="6" style="padding: 20px;">
                                <h4 style="margin: 0 0 16px 0; font-size: 14px; color: #ff9900;">🔌 India Broker Selection</h4>
                                <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 16px;">
                                    <label style="display: flex; align-items: center; gap: 8px; padding: 12px; background: rgba(138, 43, 226, 0.1); border: 1px solid rgba(138, 43, 226, 0.3); border-radius: 8px; cursor: pointer;">
                                        <input type="checkbox" id="india-broker-DHANQ-${channel.id}" value="DHANQ" ${getBrokerChecked(channel.enabled_brokers, 'DHANQ')}>
                                        <div>
                                            <div style="font-weight: 600; color: #8a2be2; font-size: 13px;">🔮 DhanQ</div>
                                            <div style="font-size: 11px; color: #8E8E93;">DhanHQ v2 API</div>
                                        </div>
                                    </label>
                                    <label style="display: flex; align-items: center; gap: 8px; padding: 12px; background: rgba(0, 200, 83, 0.1); border: 1px solid rgba(0, 200, 83, 0.3); border-radius: 8px; cursor: pointer;">
                                        <input type="checkbox" id="india-broker-UPSTOX-${channel.id}" value="UPSTOX" ${getBrokerChecked(channel.enabled_brokers, 'UPSTOX')}>
                                        <div>
                                            <div style="font-weight: 600; color: #00c853; font-size: 13px;">📈 Upstox</div>
                                            <div style="font-size: 11px; color: #8E8E93;">Upstox API</div>
                                        </div>
                                    </label>
                                    <label style="display: flex; align-items: center; gap: 8px; padding: 12px; background: rgba(255, 87, 34, 0.1); border: 1px solid rgba(255, 87, 34, 0.3); border-radius: 8px; cursor: pointer;">
                                        <input type="checkbox" id="india-broker-ZERODHA-${channel.id}" value="ZERODHA" ${getBrokerChecked(channel.enabled_brokers, 'ZERODHA')}>
                                        <div>
                                            <div style="font-weight: 600; color: #ff5722; font-size: 13px;">🔥 Zerodha</div>
                                            <div style="font-size: 11px; color: #8E8E93;">Kite Connect</div>
                                        </div>
                                    </label>
                                </div>
                                <button onclick="saveIndiaBrokerSelection(${channel.id})" style="padding: 8px 16px; background: linear-gradient(135deg, #ff9900, #ff6600); border: none; border-radius: 6px; color: white; font-size: 12px; font-weight: 600; cursor: pointer;">💾 Save Selection</button>
                            </td>
                        </tr>
                        <tr id="india-risk-row-${channel.id}" style="display: none; background: rgba(255, 153, 0, 0.03);">
                            <td colspan="6" style="padding: 20px;">
                                <h4 style="margin: 0 0 16px 0; font-size: 14px; color: #ff9900;">🛡️ Risk Management (₹ INR)</h4>
                                <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px;">
                                    <div><label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Position Size %</label><input type="number" id="india-risk-size-${channel.id}" value="${channel.position_size_pct || 5}" step="0.1" min="0.1" max="100" style="width: 100%; padding: 8px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;"></div>
                                    <div><label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Stop Loss %</label><input type="number" id="india-risk-sl-${channel.id}" value="${channel.stop_loss_pct || 20}" step="0.1" style="width: 100%; padding: 8px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;"></div>
                                    <div><label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Default Lots</label><input type="number" id="india-risk-lots-${channel.id}" value="${channel.default_quantity || 1}" min="1" style="width: 100%; padding: 8px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;"></div>
                                    <div><label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">PT1 %</label><input type="number" id="india-risk-pt1-${channel.id}" value="${channel.profit_target_1_pct || 15}" step="0.1" style="width: 100%; padding: 8px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;"></div>
                                </div>
                                <button onclick="saveIndiaRiskSettings(${channel.id})" style="padding: 8px 16px; background: linear-gradient(135deg, #ff9900, #ff6600); border: none; border-radius: 6px; color: white; font-size: 12px; font-weight: 600; cursor: pointer;">💾 Save Risk Settings</button>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    } catch (error) {
        console.error('Error loading India channels:', error);
        container.innerHTML = '<div class="no-data" style="color: #ff6b6b;">Error loading channels. Please refresh.</div>';
    }
}

async function addIndiaChannel() {
    const name = document.getElementById('channel-name').value;
    const channelId = document.getElementById('channel-id').value;
    const channelType = document.getElementById('channel-type-select').value;
    
    const enabledBrokers = [];
    INDIA_BROKERS.forEach(broker => {
        const checkbox = document.getElementById(`new-broker-${broker}`);
        if (checkbox && checkbox.checked) {
            enabledBrokers.push(broker);
        }
    });
    
    try {
        const response = await fetch('/api/channels', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                discord_channel_id: channelId,
                execute_enabled: channelType === 'EXECUTE' ? 1 : 0,
                track_enabled: channelType === 'TRACK' ? 1 : 0,
                enabled_brokers: enabledBrokers,
                market: 'IN'
            })
        });
        
        const result = await response.json();
        if (result.success || result.id) {
            document.getElementById('add-channel-form').reset();
            loadIndiaChannels();
            showToast('India channel added successfully!', 'success');
        } else {
            showToast(result.error || 'Failed to add channel', 'error');
        }
    } catch (error) {
        console.error('Error adding channel:', error);
        showToast('Error adding channel', 'error');
    }
}

function toggleIndiaBrokerSelection(channelId) {
    const row = document.getElementById(`india-broker-row-${channelId}`);
    row.style.display = row.style.display === 'none' ? 'table-row' : 'none';
}

function toggleIndiaRiskManagement(channelId) {
    const row = document.getElementById(`india-risk-row-${channelId}`);
    row.style.display = row.style.display === 'none' ? 'table-row' : 'none';
}

async function saveIndiaBrokerSelection(channelId) {
    const enabledBrokers = [];
    INDIA_BROKERS.forEach(broker => {
        const checkbox = document.getElementById(`india-broker-${broker}-${channelId}`);
        if (checkbox && checkbox.checked) {
            enabledBrokers.push(broker);
        }
    });
    
    try {
        const response = await fetch(`/api/channels/${channelId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled_brokers: enabledBrokers })
        });
        
        if (response.ok) {
            loadIndiaChannels();
            showToast('Broker selection saved!', 'success');
        }
    } catch (error) {
        showToast('Error saving broker selection', 'error');
    }
}

async function saveIndiaRiskSettings(channelId) {
    try {
        const response = await fetch(`/api/channels/${channelId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                position_size_pct: parseFloat(document.getElementById(`india-risk-size-${channelId}`).value) || 5,
                stop_loss_pct: parseFloat(document.getElementById(`india-risk-sl-${channelId}`).value) || 20,
                default_quantity: parseInt(document.getElementById(`india-risk-lots-${channelId}`).value) || 1,
                profit_target_1_pct: parseFloat(document.getElementById(`india-risk-pt1-${channelId}`).value) || 15,
                risk_management_enabled: 1
            })
        });
        
        if (response.ok) {
            loadIndiaChannels();
            showToast('Risk settings saved!', 'success');
        }
    } catch (error) {
        showToast('Error saving risk settings', 'error');
    }
}

async function toggleIndiaChannel(channelId, currentStatus) {
    try {
        const response = await fetch(`/api/channels/${channelId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_active: currentStatus ? 0 : 1 })
        });
        
        if (response.ok) {
            loadIndiaChannels();
        }
    } catch (error) {
        showToast('Error toggling channel', 'error');
    }
}

async function deleteIndiaChannel(channelId, name) {
    if (!confirm(`Delete channel "${name}"? This cannot be undone.`)) return;
    
    try {
        const response = await fetch(`/api/channels/${channelId}`, { method: 'DELETE' });
        if (response.ok) {
            loadIndiaChannels();
            showToast('Channel deleted', 'success');
        }
    } catch (error) {
        showToast('Error deleting channel', 'error');
    }
}

async function loadIndiaBrokerStatus() {
    try {
        const response = await fetch('/api/brokers/status');
        const data = await response.json();
        
        // Handle response format - status is nested in data.status
        const statusData = data.status || data;
        
        if (statusData.dhanq) {
            const badge = document.getElementById('dhanq-status-badge');
            if (statusData.dhanq.connected) {
                badge.style.background = 'rgba(0, 255, 136, 0.2)';
                badge.style.color = '#00ff88';
                badge.textContent = 'CONNECTED';
                document.getElementById('dhanq-balance').textContent = `₹${(statusData.dhanq.balance || 0).toLocaleString('en-IN')}`;
            } else {
                badge.style.background = 'rgba(255, 107, 107, 0.2)';
                badge.style.color = '#ff6b6b';
                badge.textContent = 'NOT CONNECTED';
            }
        }
        
        if (statusData.upstox) {
            const badge = document.getElementById('upstox-status-badge');
            const reconnectBtn = document.getElementById('upstox-reconnect-btn');
            const statusMsg = document.getElementById('upstox-status-msg');
            if (statusData.upstox.connected) {
                badge.style.background = 'rgba(0, 255, 136, 0.2)';
                badge.style.color = '#00ff88';
                badge.textContent = 'CONNECTED';
                document.getElementById('upstox-balance').textContent = `₹${(statusData.upstox.balance || 0).toLocaleString('en-IN')}`;
                if (reconnectBtn) reconnectBtn.style.display = 'none';
                if (statusMsg) statusMsg.innerHTML = '<span style="color: #00c853;">✓ Connected to Upstox</span>';
            } else {
                badge.style.background = 'rgba(255, 107, 107, 0.2)';
                badge.style.color = '#ff6b6b';
                badge.textContent = 'NOT CONNECTED';
                if (reconnectBtn) reconnectBtn.style.display = 'inline-block';
                if (statusMsg) statusMsg.innerHTML = '<span style="color: #ff6b6b;">Token may be expired. Click Reconnect or go to Settings → Upstox</span>';
            }
        } else {
            const badge = document.getElementById('upstox-status-badge');
            const reconnectBtn = document.getElementById('upstox-reconnect-btn');
            const statusMsg = document.getElementById('upstox-status-msg');
            badge.style.background = 'rgba(255, 107, 107, 0.2)';
            badge.style.color = '#ff6b6b';
            badge.textContent = 'NOT CONNECTED';
            if (reconnectBtn) reconnectBtn.style.display = 'inline-block';
            if (statusMsg) statusMsg.innerHTML = '<span style="color: #ffb700;">Upstox not configured. Go to Settings → Upstox</span>';
        }
        
        if (statusData.zerodha) {
            const badge = document.getElementById('zerodha-status-badge');
            if (statusData.zerodha.connected) {
                badge.style.background = 'rgba(0, 255, 136, 0.2)';
                badge.style.color = '#00ff88';
                badge.textContent = 'CONNECTED';
                document.getElementById('zerodha-balance').textContent = `₹${(statusData.zerodha.balance || 0).toLocaleString('en-IN')}`;
            } else {
                badge.style.background = 'rgba(255, 107, 107, 0.2)';
                badge.style.color = '#ff6b6b';
                badge.textContent = 'NOT CONNECTED';
            }
        }
    } catch (error) {
        console.error('Error loading broker status:', error);
    }
}

function showToast(message, type) {
    const toast = document.createElement('div');
    toast.style.cssText = `position: fixed; bottom: 20px; right: 20px; padding: 12px 24px; border-radius: 8px; color: white; font-weight: 600; z-index: 10000; animation: fadeIn 0.3s;`;
    toast.style.background = type === 'success' ? '#00c853' : '#ff5252';
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

async function reconnectUpstox() {
    const btn = document.getElementById('upstox-reconnect-btn');
    const originalText = btn.innerHTML;
    btn.innerHTML = '⏳ Connecting...';
    btn.disabled = true;
    
    try {
        const response = await fetch('/api/brokers/upstox/reconnect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await response.json();
        
        if (data.success) {
            showToast('Upstox reconnected successfully!', 'success');
            await loadIndiaBrokerStatus();
            await refreshUpstoxData();
        } else {
            showToast(data.error || 'Failed to reconnect Upstox', 'error');
            const statusMsg = document.getElementById('upstox-status-msg');
            if (statusMsg && data.error) {
                statusMsg.innerHTML = `<span style="color: #ff6b6b;">${data.error}</span>`;
            }
        }
    } catch (error) {
        showToast('Error reconnecting: ' + error.message, 'error');
    } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

// ============ UPSTOX DASHBOARD FUNCTIONS ============

let upstoxOrdersData = [];
let currentUpstoxOrderFilter = 'all';

async function refreshUpstoxData() {
    await Promise.all([
        loadUpstoxAccount(),
        loadUpstoxConditionalOrders(),
        loadAmoOrders(),
        loadAmoQueueStatus()
    ]);
}

async function loadUpstoxAccount() {
    try {
        const response = await fetch('/api/brokers/upstox/account');
        const data = await response.json();
        
        const badge = document.getElementById('upstox-status-badge');
        const reconnectBtn = document.getElementById('upstox-reconnect-btn');
        const statusMsg = document.getElementById('upstox-status-msg');
        
        if (!data.success || !data.connected) {
            badge.style.background = 'rgba(255, 107, 107, 0.2)';
            badge.style.color = '#ff6b6b';
            badge.textContent = 'NOT CONNECTED';
            document.getElementById('upstox-balance').textContent = '₹0.00';
            document.getElementById('upstox-positions').textContent = '0';
            document.getElementById('upstox-positions-body').innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 40px; color: #ff6b6b;">Upstox not connected - Click Reconnect above</td></tr>';
            document.getElementById('upstox-orders-body').innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 40px; color: #ff6b6b;">Upstox not connected</td></tr>';
            document.getElementById('upstox-trades-body').innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 40px; color: #ff6b6b;">Upstox not connected</td></tr>';
            if (reconnectBtn) reconnectBtn.style.display = 'inline-block';
            if (statusMsg) statusMsg.innerHTML = `<span style="color: #ff6b6b;">${data.error || 'Token expired or not configured'}</span>`;
            return;
        }
        
        // Update status badge - connected
        badge.style.background = 'rgba(0, 255, 136, 0.2)';
        badge.style.color = '#00ff88';
        badge.textContent = 'CONNECTED';
        if (reconnectBtn) reconnectBtn.style.display = 'none';
        if (statusMsg) statusMsg.innerHTML = '<span style="color: #00c853;">✓ Connected to Upstox</span>';
        
        // Update funds
        if (data.funds) {
            const available = data.funds.total_available || data.funds.equity?.available_margin || 0;
            document.getElementById('upstox-balance').textContent = `₹${available.toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
        }
        
        // Update positions count
        document.getElementById('upstox-positions').textContent = data.positions?.length || 0;
        
        // Render positions table
        renderUpstoxPositions(data.positions || []);
        
        // Store orders data and render (include ALL orders: open, filled, and cancelled/rejected)
        upstoxOrdersData = [
            ...(data.open_orders || []), 
            ...(data.filled_orders || []),
            ...(data.rejected_orders || [])
        ];
        console.log('[loadUpstoxAccount] Loaded orders:', upstoxOrdersData.length, 'orders');
        console.log('[loadUpstoxAccount] Open:', (data.open_orders || []).length, 'Filled:', (data.filled_orders || []).length, 'Cancelled:', (data.rejected_orders || []).length);
        renderUpstoxOrders(upstoxOrdersData);
        
        // Load trades separately
        await loadUpstoxTrades();
        
    } catch (error) {
        console.error('Error loading Upstox account:', error);
    }
}

function renderUpstoxPositions(positions) {
    const tbody = document.getElementById('upstox-positions-body');
    
    if (!positions || positions.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 40px; color: #8E8E93;">No open positions</td></tr>';
        return;
    }
    
    tbody.innerHTML = positions.map(p => {
        const pnl = parseFloat(p.pnl || 0);
        const pnlColor = pnl >= 0 ? '#00ff88' : '#ff6b6b';
        const pnlSign = pnl >= 0 ? '+' : '';
        const product = p.product === 'I' ? 'Intraday' : 'Delivery';
        
        return `
            <tr style="border-bottom: 1px solid rgba(0, 200, 83, 0.1);">
                <td style="padding: 12px; font-weight: 600; color: #ffffff;">${p.trading_symbol || 'N/A'}</td>
                <td style="padding: 12px; text-align: center; font-weight: 600; color: ${p.quantity >= 0 ? '#00ff88' : '#ff6b6b'};">${p.quantity || 0}</td>
                <td style="padding: 12px; text-align: right;">₹${parseFloat(p.average_price || 0).toFixed(2)}</td>
                <td style="padding: 12px; text-align: right;">₹${parseFloat(p.last_price || 0).toFixed(2)}</td>
                <td style="padding: 12px; text-align: right; font-weight: 600; color: ${pnlColor};">${pnlSign}₹${pnl.toLocaleString('en-IN', {minimumFractionDigits: 2})}</td>
                <td style="padding: 12px; text-align: center;"><span style="padding: 3px 8px; background: rgba(0, 200, 83, 0.1); border-radius: 4px; font-size: 11px; color: #00c853;">${product}</span></td>
            </tr>
        `;
    }).join('');
}

function renderUpstoxOrders(orders) {
    const tbody = document.getElementById('upstox-orders-body');
    
    // Helper functions for Upstox status matching
    function isOpenStatus(status) {
        if (!status) return false;
        const s = status.toLowerCase();
        return s.includes('open') || s.includes('pending') || s.includes('trigger') || 
               s.includes('validation') || s.includes('after market order req received');
    }
    
    function isFilledStatus(status) {
        if (!status) return false;
        const s = status.toLowerCase();
        return s.includes('complete') || s.includes('filled') || s.includes('traded');
    }
    
    function isRejectedStatus(status) {
        if (!status) return false;
        const s = status.toLowerCase();
        return s.includes('rejected') || s.includes('cancel');
    }
    
    // Filter based on current filter
    let filteredOrders = orders;
    if (currentUpstoxOrderFilter === 'open') {
        filteredOrders = orders.filter(o => isOpenStatus(o.status));
    } else if (currentUpstoxOrderFilter === 'filled') {
        filteredOrders = orders.filter(o => isFilledStatus(o.status));
    } else if (currentUpstoxOrderFilter === 'rejected') {
        filteredOrders = orders.filter(o => isRejectedStatus(o.status));
    }
    
    if (!filteredOrders || filteredOrders.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; padding: 40px; color: #8E8E93;">No ${currentUpstoxOrderFilter === 'all' ? '' : currentUpstoxOrderFilter + ' '}orders</td></tr>`;
        return;
    }
    
    tbody.innerHTML = filteredOrders.map(o => {
        const status = o.status || 'unknown';
        let statusColor = '#8E8E93';
        const isOpen = isOpenStatus(status);
        if (isFilledStatus(status)) statusColor = '#00ff88';
        else if (isOpen) statusColor = '#ffc107';
        else if (isRejectedStatus(status)) statusColor = '#ff6b6b';
        
        const sideColor = o.transaction_type === 'BUY' ? '#00ff88' : '#ff6b6b';
        const time = formatTimeIST(o.order_timestamp);
        
        // Cancel button for open orders
        const cancelBtn = isOpen ? `
            <button onclick="cancelUpstoxOrder('${o.order_id}')" 
                    style="padding: 4px 10px; background: rgba(255, 107, 107, 0.15); border: 1px solid rgba(255, 107, 107, 0.4); 
                           color: #ff6b6b; border-radius: 4px; font-size: 10px; font-weight: 600; cursor: pointer;
                           transition: all 0.2s ease;"
                    onmouseover="this.style.background='rgba(255, 107, 107, 0.3)'"
                    onmouseout="this.style.background='rgba(255, 107, 107, 0.15)'">
                CANCEL
            </button>
        ` : '';
        
        return `
            <tr style="border-bottom: 1px solid rgba(0, 200, 83, 0.1);">
                <td style="padding: 12px; font-size: 11px; color: #8E8E93; font-family: monospace;">${o.order_id || 'N/A'}</td>
                <td style="padding: 12px; font-weight: 600; color: #ffffff;">${o.trading_symbol || 'N/A'}</td>
                <td style="padding: 12px; text-align: center; font-weight: 600; color: ${sideColor};">${o.transaction_type || 'N/A'}</td>
                <td style="padding: 12px; text-align: center;">${o.quantity || 0}</td>
                <td style="padding: 12px; text-align: right;">₹${parseFloat(o.average_price || o.price || 0).toFixed(2)}</td>
                <td style="padding: 12px; text-align: center;"><span style="padding: 3px 8px; background: ${statusColor}22; border-radius: 4px; font-size: 11px; color: ${statusColor}; font-weight: 600;">${status.toUpperCase()}</span></td>
                <td style="padding: 12px; text-align: center; font-size: 11px; color: #8E8E93;">${time}</td>
                <td style="padding: 12px; text-align: center;">${cancelBtn}</td>
            </tr>
        `;
    }).join('');
}

async function cancelUpstoxOrder(orderId) {
    if (!confirm('Are you sure you want to cancel this order?')) return;
    
    try {
        const response = await fetch('/api/brokers/upstox/cancel-order', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ order_id: orderId })
        });
        
        const data = await response.json();
        if (data.success) {
            showToast('Order cancelled successfully', 'success');
            await refreshUpstoxData();
        } else {
            showToast(data.error || data.message || 'Failed to cancel order', 'error');
        }
    } catch (error) {
        console.error('Error cancelling order:', error);
        showToast('Error cancelling order', 'error');
    }
}

async function loadUpstoxTrades() {
    try {
        // Fetch both trades and timing data
        const [tradesResponse, timingResponse] = await Promise.all([
            fetch('/api/brokers/upstox/trades'),
            fetch('/api/brokers/upstox/execution-timing')
        ]);
        
        const tradesData = await tradesResponse.json();
        const timingData = await timingResponse.json();
        
        const tbody = document.getElementById('upstox-trades-body');
        
        // Update timing stats
        if (timingData.success && timingData.stats) {
            const stats = timingData.stats;
            document.getElementById('stat-avg-latency').textContent = formatLatency(stats.avg_latency_ms);
            document.getElementById('stat-min-latency').textContent = formatLatency(stats.min_latency_ms);
            document.getElementById('stat-max-latency').textContent = formatLatency(stats.max_latency_ms);
            document.getElementById('stat-total-trades').textContent = stats.total_trades || '0';
            
            // Show timeline if we have timing data
            if (timingData.trades && timingData.trades.length > 0) {
                renderExecutionTimeline(timingData.trades.slice(0, 10));
            }
        }
        
        if (!tradesData.success || !tradesData.trades || tradesData.trades.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 40px; color: #8E8E93;">No trades today</td></tr>';
            return;
        }
        
        tbody.innerHTML = tradesData.trades.map(t => {
            const sideColor = t.transaction_type === 'BUY' ? '#00ff88' : '#ff6b6b';
            const time = formatTimeIST(t.order_timestamp);
            
            return `
                <tr style="border-bottom: 1px solid rgba(0, 200, 83, 0.1);">
                    <td style="padding: 12px; font-size: 11px; color: #8E8E93; font-family: monospace;">${t.trade_id || 'N/A'}</td>
                    <td style="padding: 12px; font-weight: 600; color: #ffffff;">${t.trading_symbol || 'N/A'}</td>
                    <td style="padding: 12px; text-align: center; font-weight: 600; color: ${sideColor};">${t.transaction_type || 'N/A'}</td>
                    <td style="padding: 12px; text-align: center;">${t.quantity || 0}</td>
                    <td style="padding: 12px; text-align: right;">₹${parseFloat(t.price || 0).toFixed(2)}</td>
                    <td style="padding: 12px; text-align: center; font-size: 11px; color: #8E8E93;">${time}</td>
                </tr>
            `;
        }).join('');
        
    } catch (error) {
        console.error('Error loading Upstox trades:', error);
    }
}

function formatLatency(ms) {
    if (ms === null || ms === undefined || ms === 0) return '--';
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms/1000).toFixed(1)}s`;
    return `${(ms/60000).toFixed(1)}m`;
}

function renderExecutionTimeline(trades) {
    const container = document.getElementById('timeline-container');
    const section = document.getElementById('execution-timeline');
    const emptyState = document.getElementById('timing-empty-state');
    
    if (!trades || trades.length === 0) {
        section.style.display = 'none';
        if (emptyState) emptyState.style.display = 'block';
        return;
    }
    
    section.style.display = 'block';
    if (emptyState) emptyState.style.display = 'none';
    
    container.innerHTML = trades.map((t, i) => {
        const latencyMs = t.latency_ms;
        let latencyColor = '#00c853';
        if (latencyMs > 5000) latencyColor = '#ffc107';
        if (latencyMs > 30000) latencyColor = '#ff6b6b';
        
        const latencyWidth = Math.min(100, Math.max(5, (latencyMs || 100) / 100));
        const detected = formatTimeIST(t.signal_detected_at);
        const executed = formatTimeIST(t.executed_at);
        
        return `
            <div style="padding: 12px 16px; border-bottom: 1px solid rgba(0, 200, 83, 0.1); ${i % 2 === 0 ? 'background: rgba(0, 200, 83, 0.02);' : ''}">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <div style="display: flex; align-items: center; gap: 12px;">
                        <span style="font-weight: 600; color: #ffffff;">${t.symbol || 'N/A'}</span>
                        <span style="font-size: 11px; padding: 2px 8px; background: ${t.direction === 'BTO' ? 'rgba(0, 255, 136, 0.15)' : 'rgba(255, 107, 107, 0.15)'}; 
                                     color: ${t.direction === 'BTO' ? '#00ff88' : '#ff6b6b'}; border-radius: 4px; font-weight: 600;">${t.direction || 'N/A'}</span>
                        <span style="font-size: 11px; color: #8E8E93;">${t.channel_name || 'Unknown Channel'}</span>
                    </div>
                    <div style="display: flex; align-items: center; gap: 16px;">
                        <span style="font-size: 20px; font-weight: 700; color: ${latencyColor};">${t.latency_str || 'N/A'}</span>
                    </div>
                </div>
                <div style="display: flex; align-items: center; gap: 8px;">
                    <div style="display: flex; align-items: center; gap: 4px;">
                        <span style="width: 8px; height: 8px; background: #00d4ff; border-radius: 50%;"></span>
                        <span style="font-size: 10px; color: #8E8E93;">Signal: ${detected}</span>
                    </div>
                    <div style="flex: 1; height: 4px; background: rgba(0, 200, 83, 0.1); border-radius: 2px; position: relative; overflow: hidden;">
                        <div style="height: 100%; width: ${latencyWidth}%; background: linear-gradient(90deg, #00d4ff, ${latencyColor}); border-radius: 2px;"></div>
                    </div>
                    <div style="display: flex; align-items: center; gap: 4px;">
                        <span style="width: 8px; height: 8px; background: ${latencyColor}; border-radius: 50%;"></span>
                        <span style="font-size: 10px; color: #8E8E93;">Exec: ${executed}</span>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

async function loadConditionalMonitorStatus() {
    try {
        const response = await fetch('/api/conditional_orders/status');
        const data = await response.json();
        
        const statusContainer = document.getElementById('conditional-monitor-status');
        if (!statusContainer) return;
        
        if (!data.success) {
            statusContainer.innerHTML = '<div style="color: #ff6b6b; padding: 10px;">Error loading monitor status</div>';
            return;
        }
        
        const statusColor = data.thread_alive ? '#00ff88' : '#ff6b6b';
        const statusText = data.thread_alive ? 'RUNNING' : 'STOPPED';
        
        const logsHtml = (data.recent_logs || []).slice(-10).reverse().map(log => {
            let color = '#8E8E93';
            if (log.includes('Price:') || log.includes('Price update')) color = '#00d4ff';
            if (log.includes('Error') || log.includes('❌')) color = '#ff6b6b';
            if (log.includes('✓') || log.includes('Monitoring')) color = '#00ff88';
            if (log.includes('Starting')) color = '#ffc107';
            return `<div style="font-size: 11px; color: ${color}; padding: 2px 0; font-family: monospace;">${log}</div>`;
        }).join('');
        
        statusContainer.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="width: 8px; height: 8px; background: ${statusColor}; border-radius: 50%; animation: ${data.thread_alive ? 'pulse 2s infinite' : 'none'};"></span>
                    <span style="font-size: 12px; color: ${statusColor}; font-weight: 600;">Monitor: ${statusText}</span>
                </div>
                <div style="font-size: 11px; color: #8E8E93;">
                    Active: ${data.monitors_count} | Brokers: ${(data.registered_brokers || []).join(', ')}
                </div>
            </div>
            <div style="max-height: 150px; overflow-y: auto; background: rgba(0,0,0,0.3); border-radius: 4px; padding: 8px;">
                ${logsHtml || '<div style="color: #8E8E93; font-size: 11px;">No recent activity</div>'}
            </div>
        `;
    } catch (error) {
        console.error('Error loading monitor status:', error);
    }
}

async function loadUpstoxConditionalOrders() {
    try {
        loadConditionalMonitorStatus();
        
        const response = await fetch('/api/conditional_orders?market=IN');
        const data = await response.json();
        
        const tbody = document.getElementById('upstox-conditional-body');
        
        if (!data.success || !data.orders || data.orders.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; padding: 40px; color: #8E8E93;">No conditional orders for India market</td></tr>';
            return;
        }
        
        tbody.innerHTML = data.orders.map(o => {
            const statusColors = {
                'PENDING': '#ffc107',
                'ACTIVE_MONITORING': '#00d4ff',
                'TRIGGERED': '#00ff88',
                'EXECUTING': '#ff9900',
                'TRACKING': '#8a2be2',
                'TERMINATED': '#8E8E93',
                'CANCELLED': '#ff6b6b',
                'CANCELED': '#ff6b6b',
                'ERROR': '#ff5722',
                'EXPIRED': '#8E8E93'
            };
            const statusColor = statusColors[o.status] || '#8E8E93';
            const triggerType = o.trigger_type || o.trigger_condition || 'over';
            const triggerText = (triggerType === 'above' || triggerType === 'over') ? `Above ₹${o.trigger_price}` : `Below ₹${o.trigger_price}`;
            const slpt = `SL: ₹${o.stop_loss_value || 'N/A'} | PT: ${o.take_profit_targets || 'N/A'}`;
            const created = formatDateTimeIST(o.created_at);
            const currentPrice = o.current_price ? `₹${parseFloat(o.current_price).toFixed(2)}` : '-';
            const priceColor = o.current_price >= o.trigger_price ? '#00ff88' : '#00d4ff';
            
            return `
                <tr style="border-bottom: 1px solid rgba(0, 200, 83, 0.1);">
                    <td style="padding: 12px; font-weight: 600; color: #ffffff;">${o.symbol || 'N/A'} ${o.strike || ''} ${o.opt_type || ''}</td>
                    <td style="padding: 12px; text-align: center; color: #ffc107;">${triggerText}</td>
                    <td style="padding: 12px; text-align: center;"><span style="font-weight: 700; color: ${priceColor}; animation: ${o.status === 'ACTIVE_MONITORING' ? 'pulse 1s infinite' : 'none'};">${currentPrice}</span></td>
                    <td style="padding: 12px; text-align: center;"><span style="padding: 3px 8px; background: ${statusColor}22; border-radius: 4px; font-size: 11px; color: ${statusColor}; font-weight: 600;">${o.status}</span></td>
                    <td style="padding: 12px; text-align: center; font-size: 11px; color: #8E8E93;">${slpt}</td>
                    <td style="padding: 12px; text-align: center;"><span style="padding: 2px 6px; background: rgba(0, 200, 83, 0.15); border-radius: 4px; font-size: 10px; color: #00c853; font-weight: 600;">${o.broker_primary || o.broker || 'UPSTOX'}</span></td>
                    <td style="padding: 12px; text-align: center; font-size: 11px; color: #8E8E93;">${created}</td>
                    <td style="padding: 12px; text-align: center;">
                        ${!['TERMINATED', 'CANCELLED', 'CANCELED', 'ERROR', 'EXPIRED'].includes(o.status) ? `<button onclick="cancelConditionalOrder(${o.id})" style="background: rgba(255, 107, 107, 0.1); border: 1px solid rgba(255, 107, 107, 0.3); color: #ff6b6b; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 11px;">Cancel</button>` : '-'}
                    </td>
                </tr>
            `;
        }).join('');
        
    } catch (error) {
        console.error('Error loading conditional orders:', error);
    }
}

let conditionalStatusInterval = null;

function switchUpstoxTab(tabName) {
    // Hide all tabs
    document.querySelectorAll('.upstox-tab-content').forEach(el => el.style.display = 'none');
    
    // Remove active class from all tab buttons
    document.querySelectorAll('.upstox-tab').forEach(el => {
        el.style.background = 'transparent';
        el.style.color = '#8E8E93';
        el.style.border = '1px solid rgba(0, 200, 83, 0.2)';
    });
    
    // Show selected tab
    document.getElementById(`upstox-${tabName}-tab`).style.display = 'block';
    
    // Activate tab button
    const activeBtn = document.getElementById(`tab-${tabName}`);
    activeBtn.style.background = 'rgba(0, 200, 83, 0.2)';
    activeBtn.style.color = '#00c853';
    activeBtn.style.border = '1px solid rgba(0, 200, 83, 0.4)';
    
    // Start/stop auto-refresh for conditional tab (status + orders every 2s)
    if (conditionalStatusInterval) {
        clearInterval(conditionalStatusInterval);
        conditionalStatusInterval = null;
    }
    if (tabName === 'conditional') {
        loadUpstoxConditionalOrders();
        conditionalStatusInterval = setInterval(loadUpstoxConditionalOrders, 2000);
    }
}

function filterUpstoxOrders(filter) {
    currentUpstoxOrderFilter = filter;
    
    // Update filter button styles
    document.querySelectorAll('.order-filter').forEach(btn => {
        btn.style.background = 'transparent';
        btn.classList.remove('active');
    });
    
    event.target.style.background = 'rgba(0, 200, 83, 0.2)';
    event.target.classList.add('active');
    
    // Re-render orders with filter
    renderUpstoxOrders(upstoxOrdersData);
}

async function cancelConditionalOrder(orderId) {
    if (!confirm('Are you sure you want to cancel this conditional order?')) return;
    
    try {
        const response = await fetch(`/api/conditional_orders/${orderId}/cancel`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ reason: 'Cancelled via GUI' })
        });
        
        const data = await response.json();
        if (data.success) {
            showToast('Conditional order cancelled', 'success');
            await loadUpstoxConditionalOrders();
        } else {
            showToast(data.error || 'Failed to cancel order', 'error');
        }
    } catch (error) {
        showToast('Error cancelling order', 'error');
    }
}

// AMO (After Market Orders) Functions
let amoOrdersData = [];
let currentAmoFilter = 'all';

async function loadAmoQueueStatus() {
    try {
        const response = await fetch('/api/upstox/amo-queue-enabled');
        const data = await response.json();
        if (data.success) {
            const toggle = document.getElementById('amo-queue-toggle');
            if (toggle) {
                toggle.checked = data.enabled;
                updateToggleStyle(toggle);
            }
        }
    } catch (error) {
        console.error('Error loading AMO queue status:', error);
    }
}

function updateToggleStyle(toggle) {
    const slider = toggle.nextElementSibling;
    if (toggle.checked) {
        slider.style.backgroundColor = '#9c27b0';
        slider.innerHTML = '<span style="position: absolute; right: 8px; top: 50%; transform: translateY(-50%); font-size: 10px; color: white;"></span>';
    } else {
        slider.style.backgroundColor = '#3a3a3c';
        slider.innerHTML = '';
    }
    // Add the circle
    const circleStyle = toggle.checked ? 'left: 26px;' : 'left: 2px;';
    slider.innerHTML += `<span style="position: absolute; ${circleStyle} top: 2px; width: 22px; height: 22px; background: white; border-radius: 50%; transition: .3s;"></span>`;
}

async function toggleAmoQueue(enabled) {
    try {
        const response = await fetch('/api/upstox/amo-queue-enabled', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: enabled })
        });
        
        const data = await response.json();
        if (data.success) {
            showToast(`AMO queue ${enabled ? 'enabled' : 'disabled'}`, 'success');
            updateToggleStyle(document.getElementById('amo-queue-toggle'));
        } else {
            showToast(data.error || 'Failed to update AMO queue setting', 'error');
            // Revert toggle
            document.getElementById('amo-queue-toggle').checked = !enabled;
        }
    } catch (error) {
        console.error('Error toggling AMO queue:', error);
        showToast('Error updating AMO queue setting', 'error');
        document.getElementById('amo-queue-toggle').checked = !enabled;
    }
}

async function loadAmoOrders() {
    try {
        const response = await fetch('/api/upstox/pending-orders');
        const data = await response.json();
        
        if (data.success) {
            amoOrdersData = data.orders || [];
            renderAmoOrders(amoOrdersData);
        }
    } catch (error) {
        console.error('Error loading AMO orders:', error);
    }
}

function renderAmoOrders(orders) {
    const tbody = document.getElementById('upstox-amo-body');
    const emptyState = document.getElementById('amo-empty-state');
    
    if (!tbody) return;
    
    // Apply filter
    let filteredOrders = orders;
    if (currentAmoFilter !== 'all') {
        filteredOrders = orders.filter(o => o.status === currentAmoFilter);
    }
    
    if (filteredOrders.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; padding: 40px; color: #8E8E93;">No AMO orders found</td></tr>`;
        if (emptyState && orders.length === 0) {
            emptyState.style.display = 'block';
        }
        return;
    }
    
    if (emptyState) emptyState.style.display = 'none';
    
    const statusColors = {
        'PENDING': '#ffc107',
        'SUBMITTED': '#00ff88',
        'CANCELLED': '#ff6b6b',
        'FAILED': '#ff5722'
    };
    
    tbody.innerHTML = filteredOrders.map(o => {
        const statusColor = statusColors[o.status] || '#8E8E93';
        const queuedAt = formatDateTimeIST(o.created_at);
        const sideColor = o.side === 'BUY' ? '#00ff88' : '#ff6b6b';
        
        return `
            <tr style="border-bottom: 1px solid rgba(156, 39, 176, 0.1);">
                <td style="padding: 12px; font-weight: 600; color: #ffffff;">${o.symbol || 'N/A'}</td>
                <td style="padding: 12px; text-align: center;"><span style="color: ${sideColor}; font-weight: 600;">${o.side || 'BUY'}</span></td>
                <td style="padding: 12px; text-align: center; color: #ffffff;">${o.quantity || 0}</td>
                <td style="padding: 12px; text-align: center; color: #8E8E93;">${o.order_type || 'MARKET'}</td>
                <td style="padding: 12px; text-align: right; color: #ffffff;">${o.price ? '₹' + o.price : 'MKT'}</td>
                <td style="padding: 12px; text-align: center;"><span style="padding: 3px 8px; background: ${statusColor}22; border-radius: 4px; font-size: 11px; color: ${statusColor}; font-weight: 600;">${o.status}</span></td>
                <td style="padding: 12px; text-align: center; font-size: 11px; color: #8E8E93;">${queuedAt}</td>
                <td style="padding: 12px; text-align: center;">
                    ${o.status === 'PENDING' ? `<button onclick="cancelAmoOrder('${o.id}')" style="background: rgba(255, 107, 107, 0.1); border: 1px solid rgba(255, 107, 107, 0.3); color: #ff6b6b; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 11px;">Cancel</button>` : 
                      o.order_id ? `<span style="font-size: 10px; color: #00c853;">${o.order_id}</span>` : '-'}
                </td>
            </tr>
        `;
    }).join('');
}

function filterAmoOrders(filter) {
    currentAmoFilter = filter;
    
    // Update filter button styles
    document.querySelectorAll('.amo-filter').forEach(btn => {
        btn.style.background = 'transparent';
        btn.classList.remove('active');
    });
    
    event.target.style.background = 'rgba(156, 39, 176, 0.2)';
    event.target.classList.add('active');
    
    // Re-render orders with filter
    renderAmoOrders(amoOrdersData);
}

async function cancelAmoOrder(orderId) {
    if (!confirm('Are you sure you want to cancel this AMO order?')) return;
    
    try {
        const response = await fetch(`/api/upstox/pending-orders/${orderId}`, {
            method: 'DELETE'
        });
        
        const data = await response.json();
        if (data.success) {
            showToast('AMO order cancelled', 'success');
            await loadAmoOrders();
        } else {
            showToast(data.error || 'Failed to cancel AMO order', 'error');
        }
    } catch (error) {
        console.error('Error cancelling AMO order:', error);
        showToast('Error cancelling AMO order', 'error');
    }
}

// Initialize Upstox data on page load
document.addEventListener('DOMContentLoaded', function() {
    setTimeout(() => {
        refreshUpstoxData();
    }, 1000);
    
    // Auto-refresh every 30 seconds
    setInterval(refreshUpstoxData, 30000);
});
