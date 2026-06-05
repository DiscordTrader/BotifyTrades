// Canada Market Channel Management JavaScript
// Handles TSX/CSE trading with Questrade broker

let canadaChannelCategory = 'EXECUTE';
const CANADA_BROKERS = ['QUESTRADE', 'QUESTRADE_PAPER'];

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

function renderCanadaBrokerBadges(enabledBrokers) {
    const brokers = parseEnabledBrokers(enabledBrokers);
    if (brokers.length === 0) {
        return '<span style="color: #6b7280; font-size: 11px;">No broker</span>';
    }
    return brokers.map(broker => {
        const isLive = !broker.includes('PAPER');
        const color = isLive ? '#00a651' : '#00ff88';
        const bg = isLive ? 'rgba(0, 166, 81, 0.15)' : 'rgba(0, 255, 136, 0.15)';
        const border = isLive ? 'rgba(0, 166, 81, 0.3)' : 'rgba(0, 255, 136, 0.3)';
        return `<span style="display: inline-block; padding: 2px 6px; background: ${bg}; border: 1px solid ${border}; border-radius: 4px; font-size: 9px; color: ${color}; font-weight: 600; margin: 1px;">${broker}</span>`;
    }).join(' ');
}

function initCanadaChannelManagement(category) {
    canadaChannelCategory = category;
    loadCanadaChannels();
    
    document.getElementById('add-channel-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        await addCanadaChannel();
    });
}

async function loadCanadaChannels() {
    const container = document.getElementById('channels-list');
    
    try {
        const response = await fetch(`/api/channels?category=${canadaChannelCategory}&market=CA`);
        const channels = await response.json();
        
        // Handle error responses (like auth required)
        if (channels.error || !Array.isArray(channels)) {
            console.error('API error:', channels.error || 'Invalid response');
            container.innerHTML = `
                <div style="text-align: center; padding: 60px 20px;">
                    <div style="font-size: 48px; margin-bottom: 16px;">🇨🇦</div>
                    <div style="font-size: 18px; color: #ff0000; font-weight: 600; margin-bottom: 8px;">No Canada Channels Yet</div>
                    <div style="color: #8E8E93; font-size: 14px;">Add your first Canada market channel to start trading TSX, CSE stocks!</div>
                </div>
            `;
            return;
        }
        
        if (channels.length === 0) {
            container.innerHTML = `
                <div style="text-align: center; padding: 60px 20px;">
                    <div style="font-size: 48px; margin-bottom: 16px;">🇨🇦</div>
                    <div style="font-size: 18px; color: #ff0000; font-weight: 600; margin-bottom: 8px;">No Canada Channels Yet</div>
                    <div style="color: #8E8E93; font-size: 14px;">Add your first Canada market channel to start trading TSX, CSE stocks!</div>
                </div>
            `;
            return;
        }
        
        container.innerHTML = `
            <table class="data-table" style="width: 100%; border-collapse: collapse;">
                <thead>
                    <tr>
                        <th style="text-align: left; padding: 12px 16px; font-size: 11px; color: #ff0000; text-transform: uppercase; font-weight: 600; letter-spacing: 0.5px;">Channel</th>
                        <th style="text-align: center; padding: 12px 16px; font-size: 11px; color: #ff0000; text-transform: uppercase; font-weight: 600;">Status</th>
                        <th style="text-align: center; padding: 12px 16px; font-size: 11px; color: #ff0000; text-transform: uppercase; font-weight: 600;">Broker</th>
                        <th style="text-align: center; padding: 12px 16px; font-size: 11px; color: #ff0000; text-transform: uppercase; font-weight: 600;">Signals</th>
                        <th style="text-align: center; padding: 12px 16px; font-size: 11px; color: #ff0000; text-transform: uppercase; font-weight: 600;">Today</th>
                        <th style="text-align: center; padding: 12px 16px; font-size: 11px; color: #ff0000; text-transform: uppercase; font-weight: 600;">Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${channels.map(channel => `
                        <tr style="border-bottom: 1px solid rgba(255, 0, 0, 0.1); transition: all 0.2s;" onmouseover="this.style.background='rgba(255, 0, 0, 0.05)'" onmouseout="this.style.background='transparent'">
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
                                ${renderCanadaBrokerBadges(channel.enabled_brokers)}
                            </td>
                            <td style="padding: 16px; text-align: center;">
                                <span style="font-weight: 700; font-size: 16px; color: #ff0000;">${channel.total_signals || 0}</span>
                            </td>
                            <td style="padding: 16px; text-align: center;">
                                <span style="font-weight: 700; font-size: 16px; color: ${channel.signals_today > 0 ? '#00ff88' : '#6b7280'};">${channel.signals_today || 0}</span>
                            </td>
                            <td style="padding: 16px; text-align: center;">
                                <div style="display: flex; gap: 4px; justify-content: center;">
                                    <button onclick="toggleCanadaBrokerSelection(${channel.id})" title="Select Brokers" style="background: rgba(255, 0, 0, 0.1); border: 1px solid rgba(255, 0, 0, 0.3); color: #ff0000; width: 28px; height: 28px; border-radius: 6px; cursor: pointer; font-size: 14px;">🔌</button>
                                    <button onclick="toggleCanadaRiskManagement(${channel.id})" title="Risk Management" style="background: rgba(255, 0, 0, 0.1); border: 1px solid rgba(255, 0, 0, 0.3); color: #ff0000; width: 28px; height: 28px; border-radius: 6px; cursor: pointer; font-size: 14px;">🛡️</button>
                                    <button onclick="toggleCanadaChannel(${channel.id}, ${channel.is_active})" title="${channel.is_active ? 'Disable' : 'Enable'}" style="background: rgba(255, 0, 0, 0.1); border: 1px solid rgba(255, 0, 0, 0.3); color: #ff0000; width: 28px; height: 28px; border-radius: 6px; cursor: pointer; font-size: 14px;">${channel.is_active ? '⏸️' : '▶️'}</button>
                                    <button onclick="deleteCanadaChannel(${channel.id}, '${channel.name}')" title="Delete" style="background: rgba(255, 107, 107, 0.1); border: 1px solid rgba(255, 107, 107, 0.3); color: #ff6b6b; width: 28px; height: 28px; border-radius: 6px; cursor: pointer; font-size: 14px;">🗑️</button>
                                </div>
                            </td>
                        </tr>
                        <tr id="canada-broker-row-${channel.id}" style="display: none; background: rgba(255, 0, 0, 0.03);">
                            <td colspan="6" style="padding: 20px;">
                                <h4 style="margin: 0 0 16px 0; font-size: 14px; color: #ff0000;">🔌 Canada Broker Selection</h4>
                                <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 16px;">
                                    <label style="display: flex; align-items: center; gap: 8px; padding: 12px; background: rgba(0, 166, 81, 0.1); border: 1px solid rgba(0, 166, 81, 0.3); border-radius: 8px; cursor: pointer;">
                                        <input type="checkbox" id="canada-broker-QUESTRADE-${channel.id}" value="QUESTRADE" ${getBrokerChecked(channel.enabled_brokers, 'QUESTRADE')}>
                                        <div>
                                            <div style="font-weight: 600; color: #00a651; font-size: 13px;">🍁 Questrade LIVE</div>
                                            <div style="font-size: 11px; color: #8E8E93;">Real money</div>
                                        </div>
                                    </label>
                                    <label style="display: flex; align-items: center; gap: 8px; padding: 12px; background: rgba(0, 255, 136, 0.1); border: 1px solid rgba(0, 255, 136, 0.3); border-radius: 8px; cursor: pointer;">
                                        <input type="checkbox" id="canada-broker-QUESTRADE_PAPER-${channel.id}" value="QUESTRADE_PAPER" ${getBrokerChecked(channel.enabled_brokers, 'QUESTRADE_PAPER')}>
                                        <div>
                                            <div style="font-weight: 600; color: #00ff88; font-size: 13px;">🍁 Questrade PAPER</div>
                                            <div style="font-size: 11px; color: #8E8E93;">Practice mode</div>
                                        </div>
                                    </label>
                                </div>
                                <button onclick="saveCanadaBrokerSelection(${channel.id})" style="padding: 8px 16px; background: linear-gradient(135deg, #ff0000, #cc0000); border: none; border-radius: 6px; color: white; font-size: 12px; font-weight: 600; cursor: pointer;">💾 Save Selection</button>
                            </td>
                        </tr>
                        <tr id="canada-risk-row-${channel.id}" style="display: none; background: rgba(255, 0, 0, 0.03);">
                            <td colspan="6" style="padding: 20px;">
                                <h4 style="margin: 0 0 16px 0; font-size: 14px; color: #ff0000;">🛡️ Risk Management ($ CAD)</h4>
                                <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px;">
                                    <div><label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Position Size %</label><input type="number" id="canada-risk-size-${channel.id}" value="${channel.position_size_pct || 5}" step="0.1" min="0.1" max="100" style="width: 100%; padding: 8px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;"></div>
                                    <div><label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Stop Loss %</label><input type="number" id="canada-risk-sl-${channel.id}" value="${channel.stop_loss_pct || 10}" step="0.1" style="width: 100%; padding: 8px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;"></div>
                                    <div><label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Default Shares</label><input type="number" id="canada-risk-qty-${channel.id}" value="${channel.default_quantity || 100}" min="1" style="width: 100%; padding: 8px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;"></div>
                                    <div><label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">PT1 %</label><input type="number" id="canada-risk-pt1-${channel.id}" value="${channel.profit_target_1_pct || 10}" step="0.1" style="width: 100%; padding: 8px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;"></div>
                                </div>
                                <button onclick="saveCanadaRiskSettings(${channel.id})" style="padding: 8px 16px; background: linear-gradient(135deg, #ff0000, #cc0000); border: none; border-radius: 6px; color: white; font-size: 12px; font-weight: 600; cursor: pointer;">💾 Save Risk Settings</button>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    } catch (error) {
        console.error('Error loading Canada channels:', error);
        container.innerHTML = '<div class="no-data" style="color: #ff6b6b;">Error loading channels. Please refresh.</div>';
    }
}

async function addCanadaChannel() {
    const name = document.getElementById('channel-name').value;
    const channelId = document.getElementById('channel-id').value;
    const channelType = document.getElementById('channel-type-select').value;
    
    const enabledBrokers = [];
    CANADA_BROKERS.forEach(broker => {
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
                market: 'CA'
            })
        });
        
        const result = await response.json();
        if (result.success || result.id) {
            document.getElementById('add-channel-form').reset();
            loadCanadaChannels();
            showToast('Canada channel added successfully!', 'success');
        } else {
            showToast(result.error || 'Failed to add channel', 'error');
        }
    } catch (error) {
        console.error('Error adding channel:', error);
        showToast('Error adding channel', 'error');
    }
}

function toggleCanadaBrokerSelection(channelId) {
    const row = document.getElementById(`canada-broker-row-${channelId}`);
    row.style.display = row.style.display === 'none' ? 'table-row' : 'none';
}

function toggleCanadaRiskManagement(channelId) {
    const row = document.getElementById(`canada-risk-row-${channelId}`);
    row.style.display = row.style.display === 'none' ? 'table-row' : 'none';
}

async function saveCanadaBrokerSelection(channelId) {
    const enabledBrokers = [];
    CANADA_BROKERS.forEach(broker => {
        const checkbox = document.getElementById(`canada-broker-${broker}-${channelId}`);
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
            loadCanadaChannels();
            showToast('Broker selection saved!', 'success');
        }
    } catch (error) {
        showToast('Error saving broker selection', 'error');
    }
}

async function saveCanadaRiskSettings(channelId) {
    try {
        const response = await fetch(`/api/channels/${channelId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                position_size_pct: parseFloat(document.getElementById(`canada-risk-size-${channelId}`).value) || 5,
                stop_loss_pct: parseFloat(document.getElementById(`canada-risk-sl-${channelId}`).value) || 10,
                default_quantity: parseInt(document.getElementById(`canada-risk-qty-${channelId}`).value) || 100,
                profit_target_1_pct: parseFloat(document.getElementById(`canada-risk-pt1-${channelId}`).value) || 10,
                risk_management_enabled: 1
            })
        });
        
        if (response.ok) {
            loadCanadaChannels();
            showToast('Risk settings saved!', 'success');
        }
    } catch (error) {
        showToast('Error saving risk settings', 'error');
    }
}

async function toggleCanadaChannel(channelId, currentStatus) {
    try {
        const response = await fetch(`/api/channels/${channelId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_active: currentStatus ? 0 : 1 })
        });
        
        if (response.ok) {
            loadCanadaChannels();
        }
    } catch (error) {
        showToast('Error toggling channel', 'error');
    }
}

async function deleteCanadaChannel(channelId, name) {
    if (!confirm(`Delete channel "${name}"? This cannot be undone.`)) return;
    
    try {
        const response = await fetch(`/api/channels/${channelId}`, { method: 'DELETE' });
        if (response.ok) {
            loadCanadaChannels();
            showToast('Channel deleted', 'success');
        }
    } catch (error) {
        showToast('Error deleting channel', 'error');
    }
}

async function loadCanadaBrokerStatus() {
    try {
        const response = await fetch('/api/broker/status');
        const data = await response.json();
        
        if (data.questrade) {
            const badge = document.getElementById('questrade-status-badge');
            const statusText = document.getElementById('questrade-status-text');
            
            if (data.questrade.connected) {
                badge.style.background = 'rgba(0, 255, 136, 0.2)';
                badge.style.color = '#00ff88';
                badge.textContent = 'CONNECTED';
                statusText.textContent = 'Connected to Questrade API';
                document.getElementById('questrade-buying-power').textContent = `$${(data.questrade.buying_power || 0).toLocaleString('en-CA', {minimumFractionDigits: 2})} CAD`;
                document.getElementById('questrade-equity').textContent = `$${(data.questrade.equity || 0).toLocaleString('en-CA', {minimumFractionDigits: 2})} CAD`;
                document.getElementById('questrade-positions').textContent = data.questrade.positions || 0;
            } else {
                badge.style.background = 'rgba(255, 107, 107, 0.2)';
                badge.style.color = '#ff6b6b';
                badge.textContent = 'DISCONNECTED';
                statusText.textContent = 'Not connected - Configure in Settings';
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
