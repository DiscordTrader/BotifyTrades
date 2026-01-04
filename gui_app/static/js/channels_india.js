// India Market Channel Management JavaScript
// Handles NSE/BSE/MCX trading with DhanQ, Upstox, Zerodha brokers

let indiaChannelCategory = 'EXECUTE';
const INDIA_BROKERS = ['DHANQ', 'UPSTOX', 'ZERODHA'];

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
        const response = await fetch('/api/broker/status');
        const data = await response.json();
        
        if (data.dhanq) {
            const badge = document.getElementById('dhanq-status-badge');
            if (data.dhanq.connected) {
                badge.style.background = 'rgba(0, 255, 136, 0.2)';
                badge.style.color = '#00ff88';
                badge.textContent = 'CONNECTED';
                document.getElementById('dhanq-balance').textContent = `₹${(data.dhanq.balance || 0).toLocaleString('en-IN')}`;
            } else {
                badge.style.background = 'rgba(255, 107, 107, 0.2)';
                badge.style.color = '#ff6b6b';
                badge.textContent = 'DISCONNECTED';
            }
        }
        
        if (data.upstox) {
            const badge = document.getElementById('upstox-status-badge');
            if (data.upstox.connected) {
                badge.style.background = 'rgba(0, 255, 136, 0.2)';
                badge.style.color = '#00ff88';
                badge.textContent = 'CONNECTED';
                document.getElementById('upstox-balance').textContent = `₹${(data.upstox.balance || 0).toLocaleString('en-IN')}`;
            } else {
                badge.textContent = 'NOT CONNECTED';
            }
        }
        
        if (data.zerodha) {
            const badge = document.getElementById('zerodha-status-badge');
            if (data.zerodha.connected) {
                badge.style.background = 'rgba(0, 255, 136, 0.2)';
                badge.style.color = '#00ff88';
                badge.textContent = 'CONNECTED';
                document.getElementById('zerodha-balance').textContent = `₹${(data.zerodha.balance || 0).toLocaleString('en-IN')}`;
            } else {
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
