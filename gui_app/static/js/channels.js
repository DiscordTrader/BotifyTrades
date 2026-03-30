// Channel Management JavaScript

let channelCategory = 'EXECUTE';

// All available broker options
const ALL_BROKERS = ['WEBULL', 'ALPACA', 'ALPACA_PAPER', 'IBKR', 'IBKR_PAPER', 'SCHWAB', 'SCHWAB_PAPER', 'TASTYTRADE_LIVE', 'TASTYTRADE_PAPER', 'ROBINHOOD', 'TRADING212', 'TRADING212_PAPER'];

// Helper function to parse enabled_brokers (handles both JSON string and array)
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

// Helper function to check if broker is enabled
function getBrokerChecked(enabledBrokers, brokerName) {
    const brokers = parseEnabledBrokers(enabledBrokers);
    return brokers.includes(brokerName) ? 'checked' : '';
}

// Helper function to render broker badges
function renderBrokerBadges(enabledBrokers) {
    const brokers = parseEnabledBrokers(enabledBrokers);
    if (brokers.length === 0) {
        return '<span style="color: #6b7280; font-size: 11px;">Default</span>';
    }
    return brokers.map(broker => {
        const isLive = !broker.includes('PAPER');
        const color = isLive ? '#ff6b6b' : '#00ff88';
        const bgColor = isLive ? 'rgba(255, 107, 107, 0.15)' : 'rgba(0, 255, 136, 0.15)';
        const borderColor = isLive ? 'rgba(255, 107, 107, 0.3)' : 'rgba(0, 255, 136, 0.3)';
        return `<span style="display: inline-block; padding: 2px 6px; background: ${bgColor}; border: 1px solid ${borderColor}; border-radius: 4px; font-size: 9px; color: ${color}; font-weight: 600; margin: 1px;">${broker}</span>`;
    }).join(' ');
}

function initChannelManagement(category) {
    channelCategory = category;
    loadChannels();
    
    // Setup form submission
    document.getElementById('add-channel-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        await addChannel();
    });
}

async function loadChannels() {
    const container = document.getElementById('channels-list');
    
    try {
        const channels = await fetch(`/api/channels?category=${channelCategory}`).then(r => r.json());
        
        if (channels.length === 0) {
            container.innerHTML = '<div class="no-data">No channels added yet. Add one below!</div>';
            return;
        }
        
        container.innerHTML = `
            <table class="data-table" style="width: 100%; border-collapse: collapse;">
                <thead>
                    <tr>
                        <th style="text-align: left; padding: 12px 16px; font-size: 11px; color: #6b7280; text-transform: uppercase; font-weight: 600; letter-spacing: 0.5px;">Channel</th>
                        <th style="text-align: center; padding: 12px 16px; font-size: 11px; color: #6b7280; text-transform: uppercase; font-weight: 600; letter-spacing: 0.5px;">Status</th>
                        <th style="text-align: center; padding: 12px 16px; font-size: 11px; color: #6b7280; text-transform: uppercase; font-weight: 600; letter-spacing: 0.5px;">Broker</th>
                        <th style="text-align: center; padding: 12px 16px; font-size: 11px; color: #6b7280; text-transform: uppercase; font-weight: 600; letter-spacing: 0.5px;">Total Signals</th>
                        <th style="text-align: center; padding: 12px 16px; font-size: 11px; color: #6b7280; text-transform: uppercase; font-weight: 600; letter-spacing: 0.5px;">Cond. Orders</th>
                        <th style="text-align: center; padding: 12px 16px; font-size: 11px; color: #6b7280; text-transform: uppercase; font-weight: 600; letter-spacing: 0.5px;">Today</th>
                        <th style="text-align: left; padding: 12px 16px; font-size: 11px; color: #6b7280; text-transform: uppercase; font-weight: 600; letter-spacing: 0.5px;">Last Signal</th>
                        <th style="text-align: center; padding: 12px 16px; font-size: 11px; color: #6b7280; text-transform: uppercase; font-weight: 600; letter-spacing: 0.5px;">Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${channels.map(channel => `
                        <tr style="border-bottom: 1px solid rgba(255, 255, 255, 0.05); transition: all 0.2s;" onmouseover="this.style.background='rgba(0, 212, 255, 0.05)'" onmouseout="this.style.background='transparent'">
                            <td style="padding: 16px; border-left: 3px solid ${channel.is_active ? '#00ff88' : '#ff6b6b'};">
                                <div style="display: flex; align-items: center; gap: 8px;">
                                    <div>
                                        <div style="font-weight: 700; font-size: 14px; color: #ffffff; margin-bottom: 4px;">${channel.name}</div>
                                        <div style="font-size: 10px; color: #6b7280; font-family: 'Consolas', monospace;">ID: ${channel.discord_channel_id}</div>
                                    </div>
                                </div>
                            </td>
                            <td style="padding: 16px; text-align: center;">
                                <span style="display: inline-flex; align-items: center; gap: 4px; padding: 6px 12px; background: ${channel.is_active ? 'rgba(0, 255, 136, 0.15)' : 'rgba(255, 107, 107, 0.15)'}; border: 1px solid ${channel.is_active ? 'rgba(0, 255, 136, 0.3)' : 'rgba(255, 107, 107, 0.3)'}; border-radius: 6px; font-size: 11px; color: ${channel.is_active ? '#00ff88' : '#ff6b6b'}; font-weight: 700; text-transform: uppercase; letter-spacing: 0.3px; white-space: nowrap;">
                                    ${channel.is_active ? 'ACTIVE' : 'INACTIVE'}
                                </span>
                            </td>
                            <td style="padding: 16px; text-align: center;">
                                ${renderBrokerBadges(channel.enabled_brokers)}
                            </td>
                            <td style="padding: 16px; text-align: center;">
                                <span style="font-weight: 700; font-size: 16px; color: #00d4ff;">${channel.total_signals || 0}</span>
                            </td>
                            <td style="padding: 16px; text-align: center;">
                                <span style="font-weight: 700; font-size: 16px; color: ${channel.conditional_order_count > 0 ? '#ffb300' : '#6b7280'};">${channel.conditional_order_count || 0}</span>
                            </td>
                            <td style="padding: 16px; text-align: center;">
                                <span style="font-weight: 700; font-size: 16px; color: ${channel.signals_today > 0 ? '#00ff88' : '#6b7280'};">${channel.signals_today || 0}</span>
                            </td>
                            <td style="padding: 16px;">
                                <span style="font-size: 12px; color: #b4b8c5;">
                                    ${channel.last_signal_at ? new Date(channel.last_signal_at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : 'Never'}
                                </span>
                            </td>
                            <td style="padding: 16px; text-align: center;">
                                <div style="display: flex; gap: 4px; justify-content: center;">
                                    <button onclick="toggleBrokerSelection('${channel.id}')" title="Select Brokers" style="background: rgba(0, 212, 255, 0.1); border: 1px solid rgba(0, 212, 255, 0.3); color: #00d4ff; width: 28px; height: 28px; border-radius: 6px; cursor: pointer; font-size: 14px; transition: all 0.2s; display: flex; align-items: center; justify-content: center;" onmouseover="this.style.background='rgba(0, 212, 255, 0.25)'; this.style.transform='scale(1.1)'" onmouseout="this.style.background='rgba(0, 212, 255, 0.1)'; this.style.transform='scale(1)'">🔌</button>
                                    <button onclick="toggleRiskManagement('${channel.id}')" title="Risk Management" style="background: rgba(0, 212, 255, 0.1); border: 1px solid rgba(0, 212, 255, 0.3); color: #00d4ff; width: 28px; height: 28px; border-radius: 6px; cursor: pointer; font-size: 14px; transition: all 0.2s; display: flex; align-items: center; justify-content: center;" onmouseover="this.style.background='rgba(0, 212, 255, 0.25)'; this.style.transform='scale(1.1)'" onmouseout="this.style.background='rgba(0, 212, 255, 0.1)'; this.style.transform='scale(1)'">🛡️</button>
                                    <button onclick="toggleTickerFilter('${channel.id}')" title="Ticker Filter${channel.ticker_filter_mode && channel.ticker_filter_mode !== 'off' ? ' (Active)' : ''}" style="background: ${channel.ticker_filter_mode && channel.ticker_filter_mode !== 'off' ? 'rgba(255, 179, 0, 0.15)' : 'rgba(0, 212, 255, 0.1)'}; border: 1px solid ${channel.ticker_filter_mode && channel.ticker_filter_mode !== 'off' ? 'rgba(255, 179, 0, 0.3)' : 'rgba(0, 212, 255, 0.3)'}; color: ${channel.ticker_filter_mode && channel.ticker_filter_mode !== 'off' ? '#ffb300' : '#00d4ff'}; width: 28px; height: 28px; border-radius: 6px; cursor: pointer; font-size: 14px; transition: all 0.2s; display: flex; align-items: center; justify-content: center;" onmouseover="this.style.background='${channel.ticker_filter_mode && channel.ticker_filter_mode !== 'off' ? 'rgba(255, 179, 0, 0.25)' : 'rgba(0, 212, 255, 0.25)'}'; this.style.transform='scale(1.1)'" onmouseout="this.style.background='${channel.ticker_filter_mode && channel.ticker_filter_mode !== 'off' ? 'rgba(255, 179, 0, 0.15)' : 'rgba(0, 212, 255, 0.1)'}'; this.style.transform='scale(1)'">🎯</button>
                                    ${channelCategory === 'TRACK' ? `<button onclick="togglePaperTradeSection('${channel.id}')" title="Paper Trading Settings" style="background: ${channel.paper_trade_enabled ? 'rgba(0, 255, 136, 0.15)' : 'rgba(0, 212, 255, 0.1)'}; border: 1px solid ${channel.paper_trade_enabled ? 'rgba(0, 255, 136, 0.3)' : 'rgba(0, 212, 255, 0.3)'}; color: ${channel.paper_trade_enabled ? '#00ff88' : '#00d4ff'}; width: 28px; height: 28px; border-radius: 6px; cursor: pointer; font-size: 14px; transition: all 0.2s; display: flex; align-items: center; justify-content: center;" onmouseover="this.style.background='${channel.paper_trade_enabled ? 'rgba(0, 255, 136, 0.25)' : 'rgba(0, 212, 255, 0.25)'}'; this.style.transform='scale(1.1)'" onmouseout="this.style.background='${channel.paper_trade_enabled ? 'rgba(0, 255, 136, 0.15)' : 'rgba(0, 212, 255, 0.1)'}'; this.style.transform='scale(1)'">📄</button>` : ''}
                                    <button onclick="toggleAllowedUsers('${channel.id}')" title="Manage Users" style="background: rgba(0, 212, 255, 0.1); border: 1px solid rgba(0, 212, 255, 0.3); color: #00d4ff; width: 28px; height: 28px; border-radius: 6px; cursor: pointer; font-size: 14px; transition: all 0.2s; display: flex; align-items: center; justify-content: center;" onmouseover="this.style.background='rgba(0, 212, 255, 0.25)'; this.style.transform='scale(1.1)'" onmouseout="this.style.background='rgba(0, 212, 255, 0.1)'; this.style.transform='scale(1)'">👥</button>
                                    <button onclick="showUserPerformance('${channel.id}', '${channel.name}')" title="User Performance" style="background: rgba(0, 212, 255, 0.1); border: 1px solid rgba(0, 212, 255, 0.3); color: #00d4ff; width: 28px; height: 28px; border-radius: 6px; cursor: pointer; font-size: 14px; transition: all 0.2s; display: flex; align-items: center; justify-content: center;" onmouseover="this.style.background='rgba(0, 212, 255, 0.25)'; this.style.transform='scale(1.1)'" onmouseout="this.style.background='rgba(0, 212, 255, 0.1)'; this.style.transform='scale(1)'">📈</button>
                                    <button onclick="window.location.href='/signals?channel_id=${channel.id}&channel_name=${encodeURIComponent(channel.name)}'" title="View Signals" style="background: rgba(0, 212, 255, 0.1); border: 1px solid rgba(0, 212, 255, 0.3); color: #00d4ff; width: 28px; height: 28px; border-radius: 6px; cursor: pointer; font-size: 14px; transition: all 0.2s; display: flex; align-items: center; justify-content: center;" onmouseover="this.style.background='rgba(0, 212, 255, 0.25)'; this.style.transform='scale(1.1)'" onmouseout="this.style.background='rgba(0, 212, 255, 0.1)'; this.style.transform='scale(1)'">📊</button>
                                    <button onclick="resetChannelTracking('${channel.id}', '${channel.name}')" title="Reset" style="background: rgba(0, 212, 255, 0.1); border: 1px solid rgba(0, 212, 255, 0.3); color: #00d4ff; width: 28px; height: 28px; border-radius: 6px; cursor: pointer; font-size: 14px; transition: all 0.2s; display: flex; align-items: center; justify-content: center;" onmouseover="this.style.background='rgba(0, 212, 255, 0.25)'; this.style.transform='scale(1.1)'" onmouseout="this.style.background='rgba(0, 212, 255, 0.1)'; this.style.transform='scale(1)'">🔄</button>
                                    <button onclick="toggleChannel('${channel.id}', ${channel.is_active})" title="${channel.is_active ? 'Disable' : 'Enable'}" style="background: rgba(0, 212, 255, 0.1); border: 1px solid rgba(0, 212, 255, 0.3); color: #00d4ff; width: 28px; height: 28px; border-radius: 6px; cursor: pointer; font-size: 14px; transition: all 0.2s; display: flex; align-items: center; justify-content: center;" onmouseover="this.style.background='rgba(0, 212, 255, 0.25)'; this.style.transform='scale(1.1)'" onmouseout="this.style.background='rgba(0, 212, 255, 0.1)'; this.style.transform='scale(1)'">${channel.is_active ? '⏸️' : '▶️'}</button>
                                    <button onclick="deleteChannel('${channel.id}', '${channel.name}')" title="Delete" style="background: rgba(255, 107, 107, 0.1); border: 1px solid rgba(255, 107, 107, 0.3); color: #ff6b6b; width: 28px; height: 28px; border-radius: 6px; cursor: pointer; font-size: 14px; transition: all 0.2s; display: flex; align-items: center; justify-content: center;" onmouseover="this.style.background='rgba(255, 107, 107, 0.25)'; this.style.transform='scale(1.1)'" onmouseout="this.style.background='rgba(255, 107, 107, 0.1)'; this.style.transform='scale(1)'">🗑️</button>
                                </div>
                            </td>
                        </tr>
                        <tr id="broker-selection-row-${channel.id}" style="display: none; background: rgba(0, 212, 255, 0.03);">
                            <td colspan="8" style="padding: 20px;">
                                <h4 style="margin: 0 0 16px 0; font-size: 14px; color: var(--primary-blue); display: flex; align-items: center; gap: 8px;">🔌 Multi-Broker ${channelCategory === 'EXECUTE' ? 'Execution' : 'Tracking'}</h4>
                                <p style="margin: 0 0 16px 0; font-size: 12px; color: #8E8E93;">Select which brokerage accounts should ${channelCategory === 'EXECUTE' ? 'execute trades' : 'track signals'} from this channel. When enabled, signals will ${channelCategory === 'EXECUTE' ? 'execute on ALL selected accounts simultaneously' : 'be tracked across selected accounts'}.</p>
                                <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 16px;">
                                    <label style="display: flex; align-items: center; gap: 8px; padding: 12px; background: rgba(0, 0, 0, 0.3); border: 1px solid #3A3A3C; border-radius: 8px; cursor: pointer; transition: all 0.2s;" onmouseover="this.style.borderColor='#00d4ff'" onmouseout="this.style.borderColor='#3A3A3C'">
                                        <input type="checkbox" id="broker-WEBULL-${channel.id}" value="WEBULL" style="width: 18px; height: 18px; cursor: pointer;" ${getBrokerChecked(channel.enabled_brokers, 'WEBULL')}>
                                        <div>
                                            <div style="font-weight: 600; color: #ff6b6b; font-size: 13px;">🔥 Webull LIVE</div>
                                            <div style="font-size: 11px; color: #8E8E93;">Real money trading</div>
                                        </div>
                                    </label>
                                    <!-- Webull Paper disabled - hidden from channel broker selection -->
                                    <label style="display: flex; align-items: center; gap: 8px; padding: 12px; background: rgba(0, 0, 0, 0.3); border: 1px solid #3A3A3C; border-radius: 8px; cursor: pointer; transition: all 0.2s;" onmouseover="this.style.borderColor='#00d4ff'" onmouseout="this.style.borderColor='#3A3A3C'">
                                        <input type="checkbox" id="broker-ALPACA-${channel.id}" value="ALPACA" style="width: 18px; height: 18px; cursor: pointer;" ${getBrokerChecked(channel.enabled_brokers, 'ALPACA')}>
                                        <div>
                                            <div style="font-weight: 600; color: #ff6b6b; font-size: 13px;">🦙 Alpaca LIVE</div>
                                            <div style="font-size: 11px; color: #8E8E93;">Real money trading</div>
                                        </div>
                                    </label>
                                    <label style="display: flex; align-items: center; gap: 8px; padding: 12px; background: rgba(0, 0, 0, 0.3); border: 1px solid #3A3A3C; border-radius: 8px; cursor: pointer; transition: all 0.2s;" onmouseover="this.style.borderColor='#00d4ff'" onmouseout="this.style.borderColor='#3A3A3C'">
                                        <input type="checkbox" id="broker-ALPACA_PAPER-${channel.id}" value="ALPACA_PAPER" style="width: 18px; height: 18px; cursor: pointer;" ${getBrokerChecked(channel.enabled_brokers, 'ALPACA_PAPER')}>
                                        <div>
                                            <div style="font-weight: 600; color: #00ff88; font-size: 13px;">🦙 Alpaca PAPER</div>
                                            <div style="font-size: 11px; color: #8E8E93;">Paper trading</div>
                                        </div>
                                    </label>
                                    <label style="display: flex; align-items: center; gap: 8px; padding: 12px; background: rgba(0, 0, 0, 0.3); border: 1px solid #3A3A3C; border-radius: 8px; cursor: pointer; transition: all 0.2s;" onmouseover="this.style.borderColor='#00d4ff'" onmouseout="this.style.borderColor='#3A3A3C'">
                                        <input type="checkbox" id="broker-IBKR-${channel.id}" value="IBKR" style="width: 18px; height: 18px; cursor: pointer;" ${getBrokerChecked(channel.enabled_brokers, 'IBKR')}>
                                        <div>
                                            <div style="font-weight: 600; color: #ff6b6b; font-size: 13px;">🏛️ IBKR LIVE</div>
                                            <div style="font-size: 11px; color: #8E8E93;">Real money trading</div>
                                        </div>
                                    </label>
                                    <label style="display: flex; align-items: center; gap: 8px; padding: 12px; background: rgba(0, 0, 0, 0.3); border: 1px solid #3A3A3C; border-radius: 8px; cursor: pointer; transition: all 0.2s;" onmouseover="this.style.borderColor='#00d4ff'" onmouseout="this.style.borderColor='#3A3A3C'">
                                        <input type="checkbox" id="broker-IBKR_PAPER-${channel.id}" value="IBKR_PAPER" style="width: 18px; height: 18px; cursor: pointer;" ${getBrokerChecked(channel.enabled_brokers, 'IBKR_PAPER')}>
                                        <div>
                                            <div style="font-weight: 600; color: #00ff88; font-size: 13px;">🏛️ IBKR PAPER</div>
                                            <div style="font-size: 11px; color: #8E8E93;">Paper trading</div>
                                        </div>
                                    </label>
                                    <label style="display: flex; align-items: center; gap: 8px; padding: 12px; background: rgba(0, 0, 0, 0.3); border: 1px solid #3A3A3C; border-radius: 8px; cursor: pointer; transition: all 0.2s;" onmouseover="this.style.borderColor='#00d4ff'" onmouseout="this.style.borderColor='#3A3A3C'">
                                        <input type="checkbox" id="broker-SCHWAB-${channel.id}" value="SCHWAB" style="width: 18px; height: 18px; cursor: pointer;" ${getBrokerChecked(channel.enabled_brokers, 'SCHWAB')}>
                                        <div>
                                            <div style="font-weight: 600; color: #ff6b6b; font-size: 13px;">🏦 Schwab LIVE</div>
                                            <div style="font-size: 11px; color: #8E8E93;">Real money trading</div>
                                        </div>
                                    </label>
                                    <label style="display: flex; align-items: center; gap: 8px; padding: 12px; background: rgba(0, 0, 0, 0.3); border: 1px solid #3A3A3C; border-radius: 8px; cursor: pointer; transition: all 0.2s;" onmouseover="this.style.borderColor='#00d4ff'" onmouseout="this.style.borderColor='#3A3A3C'">
                                        <input type="checkbox" id="broker-TASTYTRADE_LIVE-${channel.id}" value="TASTYTRADE_LIVE" style="width: 18px; height: 18px; cursor: pointer;" ${getBrokerChecked(channel.enabled_brokers, 'TASTYTRADE_LIVE')}>
                                        <div>
                                            <div style="font-weight: 600; color: #ff6b6b; font-size: 13px;">🍒 Tastytrade LIVE</div>
                                            <div style="font-size: 11px; color: #8E8E93;">Real money trading</div>
                                        </div>
                                    </label>
                                    <label style="display: flex; align-items: center; gap: 8px; padding: 12px; background: rgba(0, 0, 0, 0.3); border: 1px solid #3A3A3C; border-radius: 8px; cursor: pointer; transition: all 0.2s;" onmouseover="this.style.borderColor='#00d4ff'" onmouseout="this.style.borderColor='#3A3A3C'">
                                        <input type="checkbox" id="broker-TASTYTRADE_PAPER-${channel.id}" value="TASTYTRADE_PAPER" style="width: 18px; height: 18px; cursor: pointer;" ${getBrokerChecked(channel.enabled_brokers, 'TASTYTRADE_PAPER')}>
                                        <div>
                                            <div style="font-weight: 600; color: #00ff88; font-size: 13px;">🍒 Tastytrade PAPER</div>
                                            <div style="font-size: 11px; color: #8E8E93;">Sandbox testing</div>
                                        </div>
                                    </label>
                                    <label style="display: flex; align-items: center; gap: 8px; padding: 12px; background: rgba(26, 47, 26, 0.5); border: 1px solid rgba(0, 200, 83, 0.4); border-radius: 8px; cursor: pointer; transition: all 0.2s;" onmouseover="this.style.borderColor='#00c853'" onmouseout="this.style.borderColor='rgba(0, 200, 83, 0.4)'">
                                        <input type="checkbox" id="broker-ROBINHOOD-${channel.id}" value="ROBINHOOD" style="width: 18px; height: 18px; cursor: pointer;" ${getBrokerChecked(channel.enabled_brokers, 'ROBINHOOD')}>
                                        <div>
                                            <div style="font-weight: 600; color: #00c853; font-size: 13px;">🪶 Robinhood (LIVE ONLY)</div>
                                            <div style="font-size: 11px; color: #ff6b6b;">⚠️ No paper trading!</div>
                                        </div>
                                    </label>
                                    <label style="display: flex; align-items: center; gap: 8px; padding: 12px; background: rgba(0, 82, 255, 0.15); border: 1px solid rgba(0, 163, 255, 0.4); border-radius: 8px; cursor: pointer; transition: all 0.2s;" onmouseover="this.style.borderColor='#00A3FF'" onmouseout="this.style.borderColor='rgba(0, 163, 255, 0.4)'">
                                        <input type="checkbox" id="broker-TRADING212-${channel.id}" value="TRADING212" style="width: 18px; height: 18px; cursor: pointer;" ${getBrokerChecked(channel.enabled_brokers, 'TRADING212')}>
                                        <div>
                                            <div style="font-weight: 600; color: #00A3FF; font-size: 13px;">📊 Trading 212 LIVE</div>
                                            <div style="font-size: 11px; color: #8E8E93;">Stocks only (UK/EU)</div>
                                        </div>
                                    </label>
                                    <label style="display: flex; align-items: center; gap: 8px; padding: 12px; background: rgba(0, 82, 255, 0.1); border: 1px solid rgba(0, 163, 255, 0.3); border-radius: 8px; cursor: pointer; transition: all 0.2s;" onmouseover="this.style.borderColor='#00A3FF'" onmouseout="this.style.borderColor='rgba(0, 163, 255, 0.3)'">
                                        <input type="checkbox" id="broker-TRADING212_PAPER-${channel.id}" value="TRADING212_PAPER" style="width: 18px; height: 18px; cursor: pointer;" ${getBrokerChecked(channel.enabled_brokers, 'TRADING212_PAPER')}>
                                        <div>
                                            <div style="font-weight: 600; color: #00ff88; font-size: 13px;">📊 Trading 212 PAPER</div>
                                            <div style="font-size: 11px; color: #8E8E93;">Demo account</div>
                                        </div>
                                    </label>
                                </div>
                                <div style="padding: 12px; background: rgba(255, 165, 0, 0.1); border: 1px solid rgba(255, 165, 0, 0.3); border-radius: 8px; font-size: 12px; color: #ffb700; margin-bottom: 12px;">
                                    <strong>⚠️ Multi-Broker ${channelCategory === 'EXECUTE' ? 'Execution' : 'Tracking'}:</strong> When multiple brokers are selected, the same signal will ${channelCategory === 'EXECUTE' ? 'execute on ALL selected accounts' : 'be tracked across selected accounts'}. 🔴 LIVE = Real Money, 🟢 PAPER = Testing
                                </div>
                                <div style="padding: 12px; background: rgba(138, 43, 226, 0.1); border: 1px solid rgba(138, 43, 226, 0.3); border-radius: 8px; margin-bottom: 12px;">
                                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                                        <div style="display: flex; align-items: center; gap: 8px;">
                                            <span style="font-size: 16px;">🔄</span>
                                            <label style="font-size: 13px; font-weight: 600; color: #b388ff;">NDX → QQQ Conversion</label>
                                        </div>
                                        <label class="toggle-switch" title="Convert NDX options to QQQ with target delta">
                                            <input type="checkbox" id="ndx-to-qqq-${channel.id}" ${channel.ndx_to_qqq_enabled ? 'checked' : ''}>
                                            <span class="toggle-slider"></span>
                                        </label>
                                    </div>
                                    <p style="font-size: 11px; color: #8E8E93; margin: 0 0 8px 0;">When enabled, NDX option signals are automatically converted to QQQ with ~0.3 delta (OTM +1/+2 strikes). QQQ is less volatile - expect ~60% of NDX gains.</p>
                                    <div style="display: flex; align-items: center; gap: 12px;">
                                        <label style="font-size: 11px; color: #8E8E93; white-space: nowrap;">Target Delta:</label>
                                        <input type="number" id="ndx-delta-${channel.id}" value="${channel.ndx_to_qqq_delta || 0.3}" placeholder="0.3" step="0.05" min="0.1" max="0.9" style="width: 70px; padding: 6px 10px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white; text-align: center;">
                                    </div>
                                </div>
                                <button onclick="saveBrokerSelection('${channel.id}')" style="padding: 8px 16px; background: var(--accent-gradient); border: none; border-radius: 6px; color: white; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.2s;" onmouseover="this.style.transform='scale(1.05)'" onmouseout="this.style.transform='scale(1)'">💾 Save Broker Selection</button>
                            </td>
                        </tr>
                        <tr id="risk-management-row-${channel.id}" style="display: none; background: rgba(0, 212, 255, 0.03);">
                            <td colspan="8" style="padding: 20px;">
                                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
                                    <h4 style="margin: 0; font-size: 14px; color: var(--primary-blue); display: flex; align-items: center; gap: 8px;">
                                        🛡️ Risk Management Settings
                                        <span id="risk-status-badge-${channel.id}" style="font-size: 11px; padding: 2px 8px; background: ${channel.risk_management_enabled ? 'rgba(0, 255, 136, 0.15)' : 'rgba(142, 142, 147, 0.15)'}; border: 1px solid ${channel.risk_management_enabled ? 'rgba(0, 255, 136, 0.3)' : 'rgba(142, 142, 147, 0.3)'}; border-radius: 4px; color: ${channel.risk_management_enabled ? '#00ff88' : '#8E8E93'}; font-weight: 600;">${channel.risk_management_enabled ? '✓ ENABLED' : '✗ DISABLED'}</span>
                                    </h4>
                                    <label class="toggle-switch" title="Enable per-channel risk management for this channel">
                                        <input type="checkbox" id="risk-enabled-${channel.id}" ${channel.risk_management_enabled ? 'checked' : ''} onchange="toggleChannelRisk('${channel.id}', this.checked)">
                                        <span class="toggle-slider"></span>
                                    </label>
                                </div>
                                <div id="risk-settings-panel-${channel.id}" style="display: ${channel.risk_management_enabled ? 'block' : 'none'};">
                                <div id="risk-summary-rail-${channel.id}" style="margin-bottom: 14px; padding: 8px 12px; background: rgba(15,240,179,0.07); border-radius: 8px; border: 1px solid rgba(15,240,179,0.18); display: flex; flex-wrap: wrap; gap: 6px; align-items: center; min-height: 30px;">
                                    <span style="color: #8E8E93; font-size: 11px; margin-right: 4px;">Active:</span>
                                    <span id="risk-summary-pills-${channel.id}"></span>
                                </div>
                                <div style="margin-bottom: 14px;">
                                    <label style="font-size: 11px; color: #8E8E93; display: block; margin-bottom: 6px;">Quick Presets</label>
                                    <div style="display: flex; flex-wrap: wrap; gap: 8px;">
                                        <button type="button" class="risk-preset-btn-${channel.id}" onclick="applyRiskPreset('${channel.id}', 'scalp')" style="padding: 4px 12px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.12); background: rgba(255,255,255,0.04); color: #8E8E93; font-size: 11px; cursor: pointer; transition: all 0.15s;">Scalp</button>
                                        <button type="button" class="risk-preset-btn-${channel.id}" onclick="applyRiskPreset('${channel.id}', 'swing')" style="padding: 4px 12px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.12); background: rgba(255,255,255,0.04); color: #8E8E93; font-size: 11px; cursor: pointer; transition: all 0.15s;">Swing</button>
                                        <button type="button" class="risk-preset-btn-${channel.id}" onclick="applyRiskPreset('${channel.id}', 'momentum')" style="padding: 4px 12px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.12); background: rgba(255,255,255,0.04); color: #8E8E93; font-size: 11px; cursor: pointer; transition: all 0.15s;">Momentum</button>
                                        <button type="button" class="risk-preset-btn-${channel.id}" onclick="applyRiskPreset('${channel.id}', 'trend')" style="padding: 4px 12px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.12); background: rgba(255,255,255,0.04); color: #8E8E93; font-size: 11px; cursor: pointer; transition: all 0.15s;">Trend</button>
                                    </div>
                                </div>
                                <div id="risk-validation-${channel.id}" style="display: none; margin-bottom: 12px; padding: 8px 12px; background: rgba(239,68,68,0.08); border-radius: 8px; border-left: 3px solid #EF4444;">
                                    <p id="risk-validation-msg-${channel.id}" style="color: #EF4444; margin: 0; font-size: 11px;"></p>
                                </div>
                                <div style="display: flex; gap: 4px; margin-bottom: 14px; border-bottom: 1px solid #3A3A3C; padding-bottom: 0;">
                                    <button type="button" class="risk-tab-btn-${channel.id}" data-risk-tab="targets" onclick="switchRiskTab('${channel.id}', 'targets')" style="padding: 6px 14px; background: none; border: none; border-bottom: 2px solid #00d4ff; color: #00d4ff; font-size: 12px; font-weight: 600; cursor: pointer;">Targets & SL</button>
                                    <button type="button" class="risk-tab-btn-${channel.id}" data-risk-tab="advanced" onclick="switchRiskTab('${channel.id}', 'advanced')" style="padding: 6px 14px; background: none; border: none; border-bottom: 2px solid transparent; color: #8E8E93; font-size: 12px; font-weight: 600; cursor: pointer;">Advanced</button>
                                </div>

                                <!-- TAB 1: Targets & SL -->
                                <div id="risk-tab-targets-${channel.id}" style="display: block;">
                                <h5 style="margin: 0 0 10px; color: #00d4ff; font-size: 12px;">📊 Profit Targets</h5>
                                <div style="display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 12px;">
                                    <div><label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">P1 Target %</label><input type="number" id="risk-profit-target-1-${channel.id}" value="${channel.profit_target_1_pct || ''}" placeholder="e.g. 10" step="0.01" min="0" max="500" style="width: 100%; padding: 8px 12px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;"></div>
                                    <div><label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">P2 Target %</label><input type="number" id="risk-profit-target-2-${channel.id}" value="${channel.profit_target_2_pct || ''}" placeholder="e.g. 20" step="0.01" min="0" max="500" style="width: 100%; padding: 8px 12px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;"></div>
                                    <div><label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">P3 Target %</label><input type="number" id="risk-profit-target-3-${channel.id}" value="${channel.profit_target_3_pct || ''}" placeholder="e.g. 30" step="0.01" min="0" max="500" style="width: 100%; padding: 8px 12px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;"></div>
                                    <div><label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">P4 Target %</label><input type="number" id="risk-profit-target-4-${channel.id}" value="${channel.profit_target_4_pct || ''}" placeholder="e.g. 40" step="0.01" min="0" max="500" style="width: 100%; padding: 8px 12px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;"></div>
                                </div>
                                <div style="margin-top: 12px; padding: 12px; background: rgba(99, 102, 241, 0.05); border: 1px solid rgba(99, 102, 241, 0.2); border-radius: 8px;">
                                    <label style="display: block; font-size: 12px; font-weight: 600; color: #818cf8; margin-bottom: 8px;">Custom Trim Quantities (optional)</label>
                                    <p style="font-size: 11px; color: #8E8E93; margin: 0 0 8px 0;">Specify exact contracts to trim at each target. Leave empty for auto-calculation.</p>
                                    <div style="display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 12px;">
                                        <div><label style="display: block; font-size: 10px; color: #8E8E93; margin-bottom: 4px;">P1 Qty</label><input type="number" id="risk-qty-1-${channel.id}" value="${channel.profit_target_qty_1 || ''}" placeholder="Auto" step="1" min="0" style="width: 100%; padding: 6px 10px; font-size: 12px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;"></div>
                                        <div><label style="display: block; font-size: 10px; color: #8E8E93; margin-bottom: 4px;">P2 Qty</label><input type="number" id="risk-qty-2-${channel.id}" value="${channel.profit_target_qty_2 || ''}" placeholder="Auto" step="1" min="0" style="width: 100%; padding: 6px 10px; font-size: 12px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;"></div>
                                        <div><label style="display: block; font-size: 10px; color: #8E8E93; margin-bottom: 4px;">P3 Qty</label><input type="number" id="risk-qty-3-${channel.id}" value="${channel.profit_target_qty_3 || ''}" placeholder="Auto" step="1" min="0" style="width: 100%; padding: 6px 10px; font-size: 12px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;"></div>
                                        <div><label style="display: block; font-size: 10px; color: #8E8E93; margin-bottom: 4px;">P4 Qty</label><input type="number" id="risk-qty-4-${channel.id}" value="${channel.profit_target_qty_4 || ''}" placeholder="Auto" step="1" min="0" style="width: 100%; padding: 6px 10px; font-size: 12px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;"></div>
                                    </div>
                                </div>
                                <h5 style="margin: 16px 0 10px; color: #EF4444; font-size: 12px;">🛑 Stop Loss & Trailing</h5>
                                <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px;">
                                    <div><label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Stop Loss %</label><input type="number" id="risk-stop-loss-${channel.id}" value="${channel.stop_loss_pct || ''}" placeholder="Leave empty for default" step="0.01" min="0" max="100" style="width: 100%; padding: 8px 12px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;"></div>
                                    <div><label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Trailing Stop % <span id="trailing-disabled-note-${channel.id}" style="color: #ff6b6b; font-size: 10px; display: ${channel.enable_early_trailing ? 'inline' : 'none'};">(disabled - Early Trailing active)</span></label><input type="number" id="risk-trailing-stop-${channel.id}" value="${channel.trailing_stop_pct || ''}" placeholder="${channel.enable_early_trailing ? 'Disabled' : 'Leave empty for default'}" step="0.01" min="0" max="100" ${channel.enable_early_trailing ? 'disabled' : ''} style="width: 100%; padding: 8px 12px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: ${channel.enable_early_trailing ? '#2A2A2C' : '#1C1C1E'}; color: ${channel.enable_early_trailing ? '#666' : 'white'}; opacity: ${channel.enable_early_trailing ? '0.6' : '1'};"></div>
                                    <div><label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Trailing Activation %</label><input type="number" id="risk-trailing-activation-${channel.id}" value="${channel.trailing_activation_pct || ''}" placeholder="${channel.enable_early_trailing ? 'Disabled' : 'Leave empty for default'}" step="0.01" min="0" max="500" ${channel.enable_early_trailing ? 'disabled' : ''} style="width: 100%; padding: 8px 12px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: ${channel.enable_early_trailing ? '#2A2A2C' : '#1C1C1E'}; color: ${channel.enable_early_trailing ? '#666' : 'white'}; opacity: ${channel.enable_early_trailing ? '0.6' : '1'};"></div>
                                </div>
                                <div style="margin-top: 12px; padding: 12px; background: rgba(0, 200, 150, 0.05); border: 1px solid rgba(0, 200, 150, 0.2); border-radius: 8px;">
                                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                                        <div style="display: flex; align-items: center; gap: 8px;">
                                            <span style="font-size: 16px;">🔒</span>
                                            <label style="font-size: 13px; font-weight: 600; color: #00c896;">Early Trailing Stop</label>
                                        </div>
                                        <label class="toggle-switch" title="Move to breakeven after X% gain, then lock profit in steps">
                                            <input type="checkbox" id="risk-early-trailing-${channel.id}" ${channel.enable_early_trailing ? 'checked' : ''} onchange="toggleEarlyTrailingExclusion('${channel.id}', this.checked)">
                                            <span class="toggle-slider"></span>
                                        </label>
                                    </div>
                                    <p style="font-size: 11px; color: #8E8E93; margin: 0 0 6px 0;">Move stop to breakeven after X% gain, then lock profit in step increments. Mutually exclusive with legacy Trailing Stop.</p>
                                    <div style="display: flex; align-items: center; gap: 16px; flex-wrap: wrap;">
                                        <div style="display: flex; align-items: center; gap: 8px;">
                                            <label style="font-size: 11px; color: #8E8E93; white-space: nowrap;">Breakeven at:</label>
                                            <input type="number" id="risk-early-activation-${channel.id}" value="${channel.early_trailing_activation_pct || 5}" placeholder="5" step="0.5" min="1" max="20" style="width: 60px; padding: 6px 10px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white; text-align: center;">
                                            <span style="font-size: 12px; color: #8E8E93;">% gain</span>
                                        </div>
                                        <div style="display: flex; align-items: center; gap: 8px;">
                                            <label style="font-size: 11px; color: #8E8E93; white-space: nowrap;">Lock profit every:</label>
                                            <input type="number" id="risk-early-step-${channel.id}" value="${channel.early_trailing_step_pct || 3}" placeholder="3" step="0.5" min="1" max="10" style="width: 60px; padding: 6px 10px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white; text-align: center;">
                                            <span style="font-size: 12px; color: #8E8E93;">% more</span>
                                        </div>
                                    </div>
                                </div>
                                <h5 style="margin: 16px 0 10px; color: #10B981; font-size: 12px;">🎯 Exit Strategy Mode</h5>
                                <div style="padding: 12px; background: rgba(16, 185, 129, 0.05); border: 1px solid rgba(16, 185, 129, 0.2); border-radius: 8px;">
                                    <p style="font-size: 11px; color: #8E8E93; margin: 0 0 10px 0;">Choose how positions are exited when both trader signals and risk management are active.</p>
                                    <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                                        <label class="exit-mode-opt-${channel.id}" style="flex: 1; min-width: 120px; padding: 10px; border-radius: 8px; border: 2px solid ${(channel.exit_strategy_mode || 'hybrid') === 'signal' ? '#10B981' : 'transparent'}; background: ${(channel.exit_strategy_mode || 'hybrid') === 'signal' ? 'rgba(16,185,129,0.08)' : 'rgba(255,255,255,0.03)'}; cursor: pointer; text-align: center;">
                                            <input type="radio" name="exit-strategy-mode-${channel.id}" value="signal" ${(channel.exit_strategy_mode || 'hybrid') === 'signal' ? 'checked' : ''} style="margin-bottom: 4px;" onchange="updateExitModeHighlight('${channel.id}')">
                                            <div style="font-size: 12px; font-weight: 600; color: white;">Signal</div>
                                            <div style="font-size: 10px; color: #8E8E93;">Follow trader exits</div>
                                        </label>
                                        <label class="exit-mode-opt-${channel.id}" style="flex: 1; min-width: 120px; padding: 10px; border-radius: 8px; border: 2px solid ${(channel.exit_strategy_mode || 'hybrid') === 'risk' ? '#10B981' : 'transparent'}; background: ${(channel.exit_strategy_mode || 'hybrid') === 'risk' ? 'rgba(16,185,129,0.08)' : 'rgba(255,255,255,0.03)'}; cursor: pointer; text-align: center;">
                                            <input type="radio" name="exit-strategy-mode-${channel.id}" value="risk" ${(channel.exit_strategy_mode || 'hybrid') === 'risk' ? 'checked' : ''} style="margin-bottom: 4px;" onchange="updateExitModeHighlight('${channel.id}')">
                                            <div style="font-size: 12px; font-weight: 600; color: white;">Risk</div>
                                            <div style="font-size: 10px; color: #8E8E93;">Auto PT/SL only</div>
                                        </label>
                                        <label class="exit-mode-opt-${channel.id}" style="flex: 1; min-width: 120px; padding: 10px; border-radius: 8px; border: 2px solid ${(channel.exit_strategy_mode || 'hybrid') === 'hybrid' ? '#10B981' : 'transparent'}; background: ${(channel.exit_strategy_mode || 'hybrid') === 'hybrid' ? 'rgba(16,185,129,0.08)' : 'rgba(255,255,255,0.03)'}; cursor: pointer; text-align: center;">
                                            <input type="radio" name="exit-strategy-mode-${channel.id}" value="hybrid" ${(channel.exit_strategy_mode || 'hybrid') === 'hybrid' ? 'checked' : ''} style="margin-bottom: 4px;" onchange="updateExitModeHighlight('${channel.id}')">
                                            <div style="font-size: 12px; font-weight: 600; color: white;">Hybrid</div>
                                            <div style="font-size: 10px; color: #8E8E93;">Both active</div>
                                        </label>
                                    </div>
                                <div style="margin-top: 12px; padding: 12px; background: rgba(255, 165, 0, 0.05); border: 1px solid rgba(255, 165, 0, 0.2); border-radius: 8px;">
                                    <label style="display: block; font-size: 12px; font-weight: 600; color: #ffb700; margin-bottom: 8px;">Trim Order Type</label>
                                    <div style="display: flex; gap: 16px; align-items: center;">
                                        <label style="display: flex; align-items: center; gap: 6px; cursor: pointer;">
                                            <input type="radio" name="trim-order-mode-${channel.id}" value="market" ${(channel.trim_order_mode || 'market') === 'market' ? 'checked' : ''} style="cursor: pointer;" onchange="document.getElementById('limit-offset-container-${channel.id}').style.display='none'">
                                            <span style="font-size: 12px; color: white;">Market</span>
                                        </label>
                                        <label style="display: flex; align-items: center; gap: 6px; cursor: pointer;">
                                            <input type="radio" name="trim-order-mode-${channel.id}" value="limit" ${channel.trim_order_mode === 'limit' ? 'checked' : ''} style="cursor: pointer;" onchange="document.getElementById('limit-offset-container-${channel.id}').style.display='flex'">
                                            <span style="font-size: 12px; color: white;">Limit</span>
                                        </label>
                                        <div style="display: ${channel.trim_order_mode === 'limit' ? 'flex' : 'none'}; align-items: center; gap: 8px; flex-wrap: wrap;" id="limit-offset-container-${channel.id}">
                                            <select id="risk-trim-offset-mode-${channel.id}" style="padding: 4px 6px; font-size: 11px; border: 1px solid #3A3A3C; border-radius: 4px; background: #1C1C1E; color: white;" onchange="toggleTrimOffsetMode('${channel.id}', this.value)">
                                                <option value="dollar" ${(channel.trim_limit_offset_mode || 'dollar') === 'dollar' ? 'selected' : ''}>$</option>
                                                <option value="percent" ${channel.trim_limit_offset_mode === 'percent' ? 'selected' : ''}>%</option>
                                            </select>
                                            <div id="trim-offset-dollar-${channel.id}" style="display: ${(channel.trim_limit_offset_mode || 'dollar') === 'dollar' ? 'flex' : 'none'}; align-items: center; gap: 4px;">
                                                <input type="number" id="risk-trim-offset-${channel.id}" value="${channel.trim_limit_offset || 0.01}" step="0.01" min="0" max="5" style="width: 60px; padding: 4px 8px; font-size: 12px; border: 1px solid #3A3A3C; border-radius: 4px; background: #1C1C1E; color: white;">
                                            </div>
                                            <div id="trim-offset-pct-${channel.id}" style="display: ${channel.trim_limit_offset_mode === 'percent' ? 'flex' : 'none'}; align-items: center; gap: 4px;">
                                                <input type="number" id="risk-trim-offset-pct-${channel.id}" value="${channel.trim_limit_offset_pct || 2.0}" step="0.5" min="0" max="20" style="width: 60px; padding: 4px 8px; font-size: 12px; border: 1px solid #3A3A3C; border-radius: 4px; background: #1C1C1E; color: white;">
                                            </div>
                                        </div>
                                    </div>
                                </div>
                                <div style="margin-top: 12px; padding: 12px; background: rgba(255, 82, 82, 0.05); border: 1px solid rgba(255, 82, 82, 0.2); border-radius: 8px;">
                                    <label style="display: block; font-size: 12px; font-weight: 600; color: #ff5252; margin-bottom: 8px;">Stop Loss Order Type</label>
                                    <div style="display: flex; gap: 16px; align-items: center;">
                                        <label style="display: flex; align-items: center; gap: 6px; cursor: pointer;">
                                            <input type="radio" name="sl-order-mode-${channel.id}" value="limit" ${(channel.sl_order_mode || 'limit') === 'limit' ? 'checked' : ''} style="cursor: pointer;" onchange="document.getElementById('sl-limit-offset-container-${channel.id}').style.display='flex'">
                                            <span style="font-size: 12px; color: white;">Limit</span>
                                        </label>
                                        <label style="display: flex; align-items: center; gap: 6px; cursor: pointer;">
                                            <input type="radio" name="sl-order-mode-${channel.id}" value="market" ${channel.sl_order_mode === 'market' ? 'checked' : ''} style="cursor: pointer;" onchange="document.getElementById('sl-limit-offset-container-${channel.id}').style.display='none'">
                                            <span style="font-size: 12px; color: white;">Market</span>
                                        </label>
                                    </div>
                                    <div style="display: ${(channel.sl_order_mode || 'limit') === 'limit' ? 'flex' : 'none'}; align-items: center; gap: 8px; margin-top: 8px;" id="sl-limit-offset-container-${channel.id}">
                                        <label style="font-size: 11px; color: #8E8E93;">Limit Offset %:</label>
                                        <input type="number" id="risk-sl-limit-offset-${channel.id}" value="${(channel.sl_limit_offset || 0.03) * 100}" step="0.5" min="0" max="20" style="width: 60px; padding: 4px 8px; font-size: 12px; border: 1px solid #3A3A3C; border-radius: 4px; background: #1C1C1E; color: white;">
                                        <span style="font-size: 10px; color: #8E8E93;">SL triggers at -10%, limit sells at -13% if offset=3%</span>
                                    </div>
                                </div>
                                <div style="margin-top: 12px; padding: 12px; background: rgba(124, 58, 237, 0.05); border: 1px solid rgba(124, 58, 237, 0.2); border-radius: 8px;">
                                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                                        <div style="display: flex; align-items: center; gap: 8px;">
                                            <span style="font-size: 16px;">🔄</span>
                                            <label style="font-size: 13px; font-weight: 600; color: #a78bfa;">Order Chase</label>
                                        </div>
                                        <select id="risk-chase-mode-${channel.id}" style="width: 130px; padding: 4px 8px; font-size: 12px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;">
                                            <option value="off" ${!channel.entry_chase_enabled && !channel.order_chase_enabled ? 'selected' : ''}>Off</option>
                                            <option value="entry" ${channel.entry_chase_enabled === 1 && channel.order_chase_enabled !== 1 ? 'selected' : ''}>Entry Only</option>
                                            <option value="exit" ${channel.order_chase_enabled === 1 && channel.entry_chase_enabled !== 1 ? 'selected' : ''}>Exit Only</option>
                                            <option value="both" ${channel.entry_chase_enabled === 1 && channel.order_chase_enabled === 1 ? 'selected' : ''}>Both</option>
                                        </select>
                                        <input type="checkbox" id="risk-order-chase-${channel.id}" style="display:none;" ${channel.order_chase_enabled === 1 || channel.entry_chase_enabled === 1 ? 'checked' : ''}>
                                    </div>
                                    <p style="font-size: 11px; color: #8E8E93; margin: 0;">Chase unfilled orders with mid-price replacement for better fills.</p>
                                </div>
                                <div style="margin-top: 12px; padding: 12px; background: rgba(0, 255, 136, 0.05); border: 1px solid rgba(0, 255, 136, 0.2); border-radius: 8px;">
                                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                                        <div style="display: flex; align-items: center; gap: 8px;">
                                            <span style="font-size: 16px;">🏃</span>
                                            <label style="font-size: 13px; font-weight: 600; color: #00ff88;">Leave Runner</label>
                                        </div>
                                        <label class="toggle-switch" title="Keep a portion of your position to ride further gains">
                                            <input type="checkbox" id="risk-leave-runner-enabled-${channel.id}" ${channel.leave_runner_enabled ? 'checked' : ''}>
                                            <span class="toggle-slider"></span>
                                        </label>
                                    </div>
                                    <p style="font-size: 11px; color: #8E8E93; margin: 0 0 8px 0;">Keep a percentage of your position after hitting profit targets.</p>
                                    <div style="display: flex; align-items: center; gap: 12px;">
                                        <label style="font-size: 11px; color: #8E8E93; white-space: nowrap;">Runner Size:</label>
                                        <input type="number" id="risk-leave-runner-pct-${channel.id}" value="${channel.leave_runner_pct || 25}" placeholder="25" step="1" min="1" max="100" style="width: 80px; padding: 6px 10px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white; text-align: center;">
                                        <span style="font-size: 12px; color: #8E8E93;">% of position</span>
                                    </div>
                                </div>
                                </div>
                                </div>

                                <!-- TAB 2: Advanced -->
                                <div id="risk-tab-advanced-${channel.id}" style="display: none;">
                                <div style="padding: 12px; background: rgba(255, 100, 100, 0.05); border: 1px solid rgba(255, 100, 100, 0.2); border-radius: 8px;">
                                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                                        <div style="display: flex; align-items: center; gap: 8px;">
                                            <span style="font-size: 16px;">🎯</span>
                                            <label style="font-size: 13px; font-weight: 600; color: #ff6b6b;">Dynamic Stop Loss Escalation</label>
                                        </div>
                                        <label class="toggle-switch" title="Automatically move stop loss after hitting profit targets">
                                            <input type="checkbox" id="risk-dynamic-sl-${channel.id}" ${channel.enable_dynamic_sl ? 'checked' : ''}>
                                            <span class="toggle-slider"></span>
                                        </label>
                                    </div>
                                    <p style="font-size: 11px; color: #8E8E93; margin: 0 0 6px 0;">Each time you hit a profit target, your stop loss moves UP to lock in more gains.</p>
                                    <div style="display: flex; align-items: center; gap: 12px;">
                                        <label style="font-size: 11px; color: #8E8E93; white-space: nowrap;">Profile:</label>
                                        <select id="risk-dynamic-sl-profile-${channel.id}" style="padding: 6px 10px; font-size: 12px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;">
                                            <option value="conservative" ${channel.dynamic_sl_profile === 'conservative' ? 'selected' : ''}>Conservative (PT1: BE, PT2: +3%, PT3: +10%, PT4: +20%)</option>
                                            <option value="standard" ${!channel.dynamic_sl_profile || channel.dynamic_sl_profile === 'standard' ? 'selected' : ''}>Standard (PT1: BE, PT2: +5%, PT3: +15%, PT4: +25%)</option>
                                            <option value="aggressive" ${channel.dynamic_sl_profile === 'aggressive' ? 'selected' : ''}>Aggressive (PT1: -2%, PT2: BE, PT3: +10%, PT4: +20%)</option>
                                        </select>
                                    </div>
                                    <div style="margin-top: 10px; padding: 10px; background: rgba(255, 100, 100, 0.03); border: 1px solid rgba(255, 100, 100, 0.12); border-radius: 6px;">
                                        <div style="display: flex; align-items: center; justify-content: space-between;">
                                            <div style="display: flex; align-items: center; gap: 8px;">
                                                <span style="font-size: 14px;">🔒</span>
                                                <label style="font-size: 12px; font-weight: 600; color: #ff8a80;">SL Escalation Only</label>
                                            </div>
                                            <label class="toggle-switch" title="Targets escalate stop loss only — no partial sells">
                                                <input type="checkbox" id="risk-escalation-only-${channel.id}" ${channel.escalation_only_mode ? 'checked' : ''}>
                                                <span class="toggle-slider"></span>
                                            </label>
                                        </div>
                                        <p style="font-size: 10px; color: #666; margin: 6px 0 0 0; font-style: italic;">Targets escalate stop loss only — no partial sells.</p>
                                    </div>
                                </div>
                                <div style="margin-top: 12px; padding: 12px; background: rgba(255, 200, 0, 0.05); border: 1px solid rgba(255, 200, 0, 0.2); border-radius: 8px;">
                                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                                        <div style="display: flex; align-items: center; gap: 8px;">
                                            <span style="font-size: 16px;">🛡️</span>
                                            <label style="font-size: 13px; font-weight: 600; color: #ffc800;">Max Profit Giveback Guard</label>
                                        </div>
                                        <label class="toggle-switch" title="Exit if profit drops too much from peak">
                                            <input type="checkbox" id="risk-giveback-guard-${channel.id}" ${channel.enable_giveback_guard ? 'checked' : ''}>
                                            <span class="toggle-slider"></span>
                                        </label>
                                    </div>
                                    <p style="font-size: 11px; color: #8E8E93; margin: 0 0 8px 0;">Exit if profit drops too much from its highest point. Activates after PT2 or trailing activation threshold.</p>
                                    <div style="display: flex; align-items: center; gap: 12px;">
                                        <label style="font-size: 11px; color: #8E8E93; white-space: nowrap;">Max Giveback:</label>
                                        <input type="number" id="risk-giveback-pct-${channel.id}" value="${channel.giveback_allowed_pct || 30}" placeholder="30" step="1" min="5" max="80" style="width: 80px; padding: 6px 10px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white; text-align: center;">
                                        <span style="font-size: 12px; color: #8E8E93;">% from peak profit</span>
                                    </div>
                                </div>
                                <div style="margin-top: 12px; padding: 12px; background: rgba(0, 188, 212, 0.05); border: 1px solid rgba(0, 188, 212, 0.2); border-radius: 8px;">
                                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                                        <div style="display: flex; align-items: center; gap: 8px;">
                                            <span style="font-size: 16px;">📊</span>
                                            <label style="font-size: 13px; font-weight: 600; color: #00bcd4;">EMA Risk Management</label>
                                        </div>
                                        <label class="toggle-switch" title="Monitor EMA crossovers for exit/escalation signals">
                                            <input type="checkbox" id="risk-ema-enabled-${channel.id}" ${channel.ema_risk_enabled ? 'checked' : ''} onchange="document.getElementById('ema-settings-grid-${channel.id}').style.display = this.checked ? 'block' : 'none';">
                                            <span class="toggle-slider"></span>
                                        </label>
                                    </div>
                                    <p style="font-size: 11px; color: #8E8E93; margin: 0 0 8px 0;">Builds live candles, computes EMA, and exits when price crosses unfavorably.</p>
                                    <div id="ema-settings-grid-${channel.id}" style="display: ${channel.ema_risk_enabled ? 'block' : 'none'};">
                                        <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; margin-bottom: 10px;">
                                            <div>
                                                <label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">EMA Period</label>
                                                <select id="risk-ema-period-${channel.id}" style="width: 100%; padding: 6px 10px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;">
                                                    <option value="3" ${(channel.ema_period || 5) == 3 ? 'selected' : ''}>3 (Fast)</option>
                                                    <option value="5" ${(channel.ema_period || 5) == 5 ? 'selected' : ''}>5 (Standard)</option>
                                                    <option value="8" ${(channel.ema_period || 5) == 8 ? 'selected' : ''}>8 (Moderate)</option>
                                                    <option value="13" ${(channel.ema_period || 5) == 13 ? 'selected' : ''}>13 (Slow)</option>
                                                    <option value="21" ${(channel.ema_period || 5) == 21 ? 'selected' : ''}>21 (Very Slow)</option>
                                                </select>
                                            </div>
                                            <div>
                                                <label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Candle Timeframe</label>
                                                <select id="risk-ema-timeframe-${channel.id}" style="width: 100%; padding: 6px 10px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;">
                                                    <option value="1" ${(channel.ema_timeframe_minutes || 5) == 1 ? 'selected' : ''}>1 min</option>
                                                    <option value="2" ${(channel.ema_timeframe_minutes || 5) == 2 ? 'selected' : ''}>2 min</option>
                                                    <option value="3" ${(channel.ema_timeframe_minutes || 5) == 3 ? 'selected' : ''}>3 min</option>
                                                    <option value="5" ${(channel.ema_timeframe_minutes || 5) == 5 ? 'selected' : ''}>5 min</option>
                                                </select>
                                            </div>
                                            <div>
                                                <label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Buffer %</label>
                                                <input type="number" id="risk-ema-buffer-${channel.id}" value="${channel.ema_buffer_pct != null ? channel.ema_buffer_pct : 0.1}" placeholder="0.1" step="0.05" min="0" max="2" style="width: 100%; padding: 6px 10px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white; text-align: center;">
                                            </div>
                                        </div>
                                        <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; margin-bottom: 10px;">
                                            <div style="display: flex; align-items: center; gap: 8px;">
                                                <label class="toggle-switch"><input type="checkbox" id="risk-ema-exit-${channel.id}" ${channel.ema_exit_enabled !== 0 ? 'checked' : ''}><span class="toggle-slider"></span></label>
                                                <label style="font-size: 11px; color: #8E8E93;">Exit on Cross</label>
                                            </div>
                                            <div style="display: flex; align-items: center; gap: 8px;">
                                                <label class="toggle-switch"><input type="checkbox" id="risk-ema-escalation-${channel.id}" ${channel.ema_escalation_enabled !== 0 ? 'checked' : ''}><span class="toggle-slider"></span></label>
                                                <label style="font-size: 11px; color: #8E8E93;">Stop Escalation</label>
                                            </div>
                                            <div style="display: flex; align-items: center; gap: 8px;">
                                                <label style="font-size: 11px; color: #8E8E93;">No-Trend:</label>
                                                <input type="number" id="risk-ema-no-trend-${channel.id}" value="${channel.ema_no_trend_candles != null ? channel.ema_no_trend_candles : 3}" placeholder="3" step="1" min="1" max="20" style="width: 50px; padding: 6px 8px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white; text-align: center;">
                                                <span style="font-size: 10px; color: #666;">candles</span>
                                            </div>
                                        </div>
                                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
                                            <div style="display: flex; align-items: center; gap: 8px;">
                                                <label class="toggle-switch"><input type="checkbox" id="risk-ema-underlying-${channel.id}" ${channel.ema_use_underlying !== 0 ? 'checked' : ''}><span class="toggle-slider"></span></label>
                                                <label style="font-size: 11px; color: #8E8E93;">Use Underlying Chart</label>
                                            </div>
                                            <div style="display: flex; align-items: center; gap: 8px;">
                                                <label class="toggle-switch"><input type="checkbox" id="risk-ema-extended-${channel.id}" ${channel.ema_extended_hours ? 'checked' : ''}><span class="toggle-slider"></span></label>
                                                <label style="font-size: 11px; color: #8E8E93;">Extended Hours</label>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                                <div style="margin-top: 12px; padding: 12px; background: rgba(138, 43, 226, 0.05); border: 1px solid rgba(138, 43, 226, 0.2); border-radius: 8px;">
                                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                                        <div style="display: flex; align-items: center; gap: 8px;">
                                            <span style="font-size: 16px;">📊</span>
                                            <label style="font-size: 13px; font-weight: 600; color: #a855f7;">Trade Summary</label>
                                        </div>
                                        <label class="toggle-switch" title="Post P/L summary to Discord when positions are closed">
                                            <input type="checkbox" id="trade-summary-enabled-${channel.id}" ${channel.trade_summary_enabled !== 0 ? 'checked' : ''}>
                                            <span class="toggle-slider"></span>
                                        </label>
                                    </div>
                                    <p style="font-size: 11px; color: #8E8E93; margin: 0;">Post a P/L summary message to Discord when STC signals close positions.</p>
                                </div>
                                </div>

                                <button onclick="saveRiskManagement('${channel.id}')" style="margin-top: 12px; padding: 8px 16px; background: var(--accent-gradient); border: none; border-radius: 6px; color: white; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.2s;" onmouseover="this.style.transform='scale(1.05)'" onmouseout="this.style.transform='scale(1)'">💾 Save Risk Settings</button>
                                </div>
                            </td>
                        </tr>
                        <tr id="ticker-filter-row-${channel.id}" style="display: none; background: rgba(255, 179, 0, 0.03);">
                            <td colspan="8" style="padding: 20px;">
                                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
                                    <h4 style="margin: 0; font-size: 14px; color: #ffb300; display: flex; align-items: center; gap: 8px;">
                                        🎯 Ticker Filter
                                        <span id="ticker-filter-badge-${channel.id}" style="font-size: 11px; padding: 2px 8px; background: ${channel.ticker_filter_mode && channel.ticker_filter_mode !== 'off' ? 'rgba(255, 179, 0, 0.15)' : 'rgba(142, 142, 147, 0.15)'}; border: 1px solid ${channel.ticker_filter_mode && channel.ticker_filter_mode !== 'off' ? 'rgba(255, 179, 0, 0.3)' : 'rgba(142, 142, 147, 0.3)'}; border-radius: 4px; color: ${channel.ticker_filter_mode && channel.ticker_filter_mode !== 'off' ? '#ffb300' : '#8E8E93'}; font-weight: 600;">${channel.ticker_filter_mode === 'allow' ? '✓ ALLOW LIST' : channel.ticker_filter_mode === 'block' ? '✗ BLOCK LIST' : 'OFF'}</span>
                                    </h4>
                                </div>
                                <p style="font-size: 12px; color: #8E8E93; margin: 0 0 16px 0;">Filter which tickers this channel can trade. Useful when a trader excels at specific symbols but underperforms on others.</p>
                                <div style="display: grid; grid-template-columns: 200px 1fr; gap: 16px; align-items: start;">
                                    <div>
                                        <label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Filter Mode</label>
                                        <select id="ticker-filter-mode-${channel.id}" style="width: 100%; padding: 8px 12px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;" onchange="toggleTickerFilterList('${channel.id}', this.value)">
                                            <option value="off" ${!channel.ticker_filter_mode || channel.ticker_filter_mode === 'off' ? 'selected' : ''}>Off - Trade all tickers</option>
                                            <option value="allow" ${channel.ticker_filter_mode === 'allow' ? 'selected' : ''}>Allow List - Only trade these</option>
                                            <option value="block" ${channel.ticker_filter_mode === 'block' ? 'selected' : ''}>Block List - Block these tickers</option>
                                        </select>
                                    </div>
                                    <div id="ticker-filter-list-container-${channel.id}" style="display: ${channel.ticker_filter_mode && channel.ticker_filter_mode !== 'off' ? 'block' : 'none'};">
                                        <label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Tickers (comma-separated)</label>
                                        <input type="text" id="ticker-filter-list-${channel.id}" value="${channel.ticker_filter_list || ''}" placeholder="SPY, QQQ, AAPL, TSLA" style="width: 100%; padding: 8px 12px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;">
                                        <p style="font-size: 10px; color: #666; margin: 4px 0 0 0;">For options, the underlying symbol is matched (e.g., SPY 450C matches "SPY"). Case-insensitive.</p>
                                    </div>
                                </div>
                                <div style="margin-top: 12px; padding: 10px; background: rgba(100, 100, 100, 0.1); border: 1px solid rgba(100, 100, 100, 0.2); border-radius: 6px;">
                                    <div style="font-size: 11px; color: #8E8E93;">
                                        <strong style="color: #ccc;">Examples:</strong><br>
                                        • <span style="color: #00ff88;">Allow List "SPY, QQQ"</span> → Only trades SPY and QQQ signals, ignores all others<br>
                                        • <span style="color: #ff6b6b;">Block List "COIN, GME, AMC"</span> → Trades everything except COIN, GME, AMC
                                    </div>
                                </div>
                                <button onclick="saveTickerFilter('${channel.id}')" style="margin-top: 12px; padding: 8px 16px; background: linear-gradient(135deg, #ffb300 0%, #ff8c00 100%); border: none; border-radius: 6px; color: white; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.2s;" onmouseover="this.style.transform='scale(1.05)'" onmouseout="this.style.transform='scale(1)'">💾 Save Ticker Filter</button>
                            </td>
                        </tr>
                        ${channelCategory === 'TRACK' ? `
                        <tr id="paper-trade-row-${channel.id}" style="display: none; background: rgba(0, 212, 255, 0.03);">
                            <td colspan="8" style="padding: 20px;">
                                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
                                    <h4 style="margin: 0; font-size: 14px; color: var(--primary-blue); display: flex; align-items: center; gap: 8px;">
                                        📄 Paper Trading & Account Info
                                        <span style="font-size: 11px; padding: 2px 8px; background: ${channel.paper_trade_enabled ? 'rgba(0, 255, 136, 0.15)' : 'rgba(142, 142, 147, 0.15)'}; border: 1px solid ${channel.paper_trade_enabled ? 'rgba(0, 255, 136, 0.3)' : 'rgba(142, 142, 147, 0.3)'}; border-radius: 4px; color: ${channel.paper_trade_enabled ? '#00ff88' : '#8E8E93'}; font-weight: 600;">Execution: ${channel.paper_trade_enabled ? '✓ ENABLED' : '✗ DISABLED'}</span>
                                    </h4>
                                    <label class="toggle-switch">
                                        <input type="checkbox" id="paper-trade-${channel.id}" ${channel.paper_trade_enabled ? 'checked' : ''} onchange="togglePaperTrade('${channel.id}')">
                                        <span class="toggle-slider"></span>
                                    </label>
                                </div>
                                
                                <div id="paper-account-dashboard-${channel.id}" style="margin-bottom: 16px; padding: 16px; background: rgba(0, 0, 0, 0.3); border: 1px solid rgba(0, 212, 255, 0.2); border-radius: 8px;">
                                    <div style="font-size: 12px; color: #8E8E93; text-align: center;">Loading paper account data...</div>
                                </div>
                                
                                <div id="paper-trade-config-${channel.id}" style="display: ${channel.paper_trade_enabled ? 'block' : 'none'};">
                                    <h5 style="margin: 0 0 12px 0; font-size: 13px; color: #00d4ff; font-weight: 600;">⚙️ Risk Management Settings</h5>
                                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
                                        <div>
                                            <label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Profit Target %</label>
                                            <input type="number" id="profit-target-${channel.id}" value="${channel.profit_target_pct || ''}" placeholder="Leave empty for global default" step="0.01" min="0" max="100" style="width: 100%; padding: 8px 12px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;">
                                        </div>
                                        <div>
                                            <label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Stop Loss %</label>
                                            <input type="number" id="stop-loss-${channel.id}" value="${channel.stop_loss_pct || ''}" placeholder="Leave empty for global default" step="0.01" min="0" max="100" style="width: 100%; padding: 8px 12px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;">
                                        </div>
                                        <div>
                                            <label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Trailing Stop %</label>
                                            <input type="number" id="trailing-stop-${channel.id}" value="${channel.trailing_stop_pct || ''}" placeholder="Leave empty for global default" step="0.01" min="0" max="100" style="width: 100%; padding: 8px 12px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;">
                                        </div>
                                        <div>
                                            <label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Trailing Activation %</label>
                                            <input type="number" id="trailing-activation-${channel.id}" value="${channel.trailing_activation_pct || ''}" placeholder="Leave empty for global default" step="0.01" min="0" max="100" style="width: 100%; padding: 8px 12px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;">
                                        </div>
                                    </div>
                                    <button onclick="updatePaperTradeConfig('${channel.id}')" style="margin-top: 12px; padding: 8px 16px; background: var(--accent-gradient); border: none; border-radius: 6px; color: white; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.2s;" onmouseover="this.style.transform='scale(1.05)'" onmouseout="this.style.transform='scale(1)'">💾 Save Configuration</button>
                                </div>
                            </td>
                        </tr>
                        ` : ''}
                        <tr id="allowed-users-row-${channel.id}" style="display: none;">
                            <td colspan="8" style="padding: 0; background: rgba(0, 0, 0, 0.2);">
                                <div class="channel-stats" style="display: none;">
                    <div class="stat-item">
                        <div class="stat-item-label">Total Signals</div>
                        <div class="stat-item-value">${channel.total_signals || 0}</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-item-label">Today</div>
                        <div class="stat-item-value" style="color: ${channel.signals_today > 0 ? '#00C853' : '#AEAEB2'};">${channel.signals_today || 0}</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-item-label">Last Signal</div>
                        <div class="stat-item-value" style="font-size: 11px;">
                            ${channel.last_signal_at ? new Date(channel.last_signal_at).toLocaleString('en-US', { 
                                month: 'short', 
                                day: 'numeric', 
                                hour: 'numeric', 
                                minute: '2-digit' 
                            }) : 'Never'}
                        </div>
                    </div>
                    ${channelCategory === 'TRACK' ? `
                    <div class="stat-item">
                        <div class="stat-item-label">Paper Trading</div>
                        <div class="stat-item-value" style="color: ${channel.paper_trade_enabled ? '#00C853' : '#AEAEB2'};">${channel.paper_trade_enabled ? '✓ Enabled' : '✗ Disabled'}</div>
                    </div>
                    ` : ''}
                </div>
                <div id="allowed-users-${channel.id}" class="allowed-users-section" style="display: none;">
                    <div style="border-top: 1px solid #2C2C2E; padding: 15px 0 0 0; margin-top: 15px;">
                        <h4 style="margin: 0 0 10px 0; font-size: 14px; color: var(--primary-blue);">👥 Allowed Users (Signal Filtering)</h4>
                        <div id="allowed-users-list-${channel.id}" style="margin-bottom: 10px;">
                            <div class="loading" style="font-size: 12px;">Loading users...</div>
                        </div>
                        <div style="display: flex; gap: 8px; margin-top: 10px;">
                            <input type="text" id="new-user-id-${channel.id}" placeholder="Discord User ID" style="flex: 1; padding: 6px 10px; font-size: 12px; border: 1px solid #3A3A3C; border-radius: 4px; background: #1C1C1E; color: white;">
                            <input type="text" id="new-username-${channel.id}" placeholder="Username" style="flex: 1; padding: 6px 10px; font-size: 12px; border: 1px solid #3A3A3C; border-radius: 4px; background: #1C1C1E; color: white;">
                            <button class="btn btn-primary" onclick="addAllowedUser('${channel.id}')" style="padding: 6px 12px; font-size: 12px;">➕ Add</button>
                        </div>
                        <div style="margin-top: 8px; font-size: 11px; color: #8E8E93;">
                            💡 Leave empty to allow ALL users | Add specific users to filter signals
                        </div>
                    </div>
                </div>
                            </td>
                        </tr>
                `).join('')}
                </tbody>
            </table>
        `;
        
        // Load allowed users for each channel
        channels.forEach(channel => {
            loadAllowedUsers(channel.id);
            initRiskRowListeners(channel.id);
        });
        
    } catch (error) {
        console.error('Failed to load channels:', error);
        container.innerHTML = '<div class="error">Failed to load channels</div>';
    }
}

async function addChannel() {
    const name = document.getElementById('channel-name').value;
    const channelId = document.getElementById('channel-id').value;
    
    // Collect selected brokers from checkboxes (new multi-broker system)
    const selectedBrokers = [];
    ALL_BROKERS.forEach(broker => {
        const checkbox = document.getElementById(`new-broker-${broker}`);
        if (checkbox && checkbox.checked) {
            selectedBrokers.push(broker);
        }
    });
    
    // Get channel type from dropdown (falls back to global channelCategory if not found)
    const channelTypeSelect = document.getElementById('channel-type-select');
    const category = channelTypeSelect ? channelTypeSelect.value : channelCategory;
    
    try {
        const response = await fetch('/api/channels', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                discord_channel_id: channelId,
                category: category,
                enabled_brokers: JSON.stringify(selectedBrokers)
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            const liveCount = selectedBrokers.filter(b => !b.includes('PAPER')).length;
            const paperCount = selectedBrokers.filter(b => b.includes('PAPER')).length;
            let brokerInfo = '';
            if (selectedBrokers.length > 0) {
                brokerInfo = ` (${liveCount > 0 ? `🔴 ${liveCount} LIVE` : ''} ${paperCount > 0 ? `🟢 ${paperCount} PAPER` : ''})`;
            }
            showMessage(`✅ ${category === 'EXECUTE' ? 'Execution' : 'Tracking'} channel added successfully!${brokerInfo}`);
            document.getElementById('add-channel-form').reset();
            
            // Switch to the tab of the channel type that was just added
            if (typeof switchChannelType === 'function') {
                switchChannelType(category);
            } else {
                loadChannels();
            }
        } else {
            showMessage('❌ ' + result.error, 'error');
        }
    } catch (error) {
        console.error('Failed to add channel:', error);
        showMessage('❌ Failed to add channel', 'error');
    }
}

async function toggleChannel(channelId, currentStatus) {
    try {
        await fetch(`/api/channels/${channelId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_active: currentStatus ? 0 : 1 })
        });
        
        showMessage('✅ Channel updated');
        loadChannels();
    } catch (error) {
        console.error('Failed to toggle channel:', error);
        showMessage('❌ Failed to update channel', 'error');
    }
}

async function deleteChannel(channelId, channelName) {
    if (!confirm(`Are you sure you want to delete channel "${channelName}"?`)) {
        return;
    }
    
    try {
        await fetch(`/api/channels/${channelId}`, {
            method: 'DELETE'
        });
        
        showMessage('✅ Channel deleted');
        loadChannels();
    } catch (error) {
        console.error('Failed to delete channel:', error);
        showMessage('❌ Failed to delete channel', 'error');
    }
}

async function resetChannelTracking(channelId, channelName) {
    if (!confirm(`⚠️ Reset tracking for "${channelName}"?\n\nThis will permanently delete:\n• All signal lots (open positions)\n• All lot closures (P&L history)\n• All signals\n\nThis cannot be undone!`)) {
        return;
    }
    
    try {
        const response = await fetch(`/api/channels/${channelId}/reset`, {
            method: 'POST'
        });
        
        const result = await response.json();
        
        if (response.ok) {
            showMessage(`✅ ${result.message}`);
            loadChannels();
        } else {
            showMessage('❌ ' + (result.error || 'Failed to reset tracking'), 'error');
        }
    } catch (error) {
        console.error('Failed to reset tracking:', error);
        showMessage('❌ Failed to reset tracking', 'error');
    }
}

async function loadSignalsForChannel(channelId) {
    const container = document.getElementById(`signals-${channelId}`);
    if (!container) return;
    
    try {
        const signals = await fetch(`/api/signals?channel_id=${channelId}&limit=10`).then(r => r.json());
        
        if (!signals || signals.length === 0) {
            container.innerHTML = '<div class="no-data" style="padding: 10px;">No signals received yet</div>';
            return;
        }
        
        container.innerHTML = `
            <h4 style="margin: 10px 0; color: var(--primary-blue);">Recent Signals (${signals.length})</h4>
            ${signals.map(signal => `
                <div class="signal-item" style="background: var(--bg-tertiary); padding: 10px; margin-bottom: 8px; border-radius: 4px; border-left: 3px solid ${signal.executed ? 'var(--primary-green)' : 'var(--accent-yellow)'};">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                        <strong>${signal.signal_type} ${signal.symbol}</strong>
                        <span style="color: var(--text-muted); font-size: 0.85em;">${new Date(signal.timestamp).toLocaleString()}</span>
                    </div>
                    <div style="color: var(--text-secondary); font-size: 0.9em;">
                        ${signal.strike && signal.option_type ? `
                            Strike: $${signal.strike} ${signal.option_type} | Exp: ${signal.expiry || 'N/A'} | 
                        ` : ''}
                        Qty: ${signal.quantity || 'Auto'} | Price: $${parseFloat(signal.price || 0).toFixed(2)}
                    </div>
                    <div style="margin-top: 5px;">
                        <span style="padding: 2px 8px; border-radius: 3px; font-size: 0.8em; background: ${signal.executed ? '#10b981' : '#f59e0b'}; color: white;">
                            ${signal.executed ? '✓ Executed' : '⏳ Pending'}
                        </span>
                        <span style="color: #94a3b8; font-size: 0.85em; margin-left: 10px;">Author: ${signal.author}</span>
                    </div>
                </div>
            `).join('')}
        `;
        
    } catch (error) {
        console.error('Failed to load signals:', error);
        container.innerHTML = '<div class="error" style="padding: 10px;">Failed to load signals</div>';
    }
}

function toggleSignals(channelId) {
    const container = document.getElementById(`signals-${channelId}`);
    if (!container) return;
    
    // Toggle visibility
    if (container.style.display === 'none' || container.style.display === '') {
        container.style.display = 'block';
        
        // Load signals only if not already loaded (container is empty or has placeholder)
        if (!container.dataset.loaded) {
            container.innerHTML = '<div class="loading">Loading signals...</div>';
            loadSignalsForChannel(channelId);
            container.dataset.loaded = 'true';
        }
    } else {
        container.style.display = 'none';
    }
}

function showMessage(message, type = 'success') {
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${type}`;
    msgDiv.textContent = message;
    msgDiv.style.position = 'fixed';
    msgDiv.style.top = '20px';
    msgDiv.style.right = '20px';
    msgDiv.style.zIndex = '1000';
    
    document.body.appendChild(msgDiv);
    
    setTimeout(() => {
        msgDiv.remove();
    }, 3000);
}

// Allowed Users Management
function toggleAllowedUsers(channelId) {
    const section = document.getElementById(`allowed-users-${channelId}`);
    if (!section) return;
    
    if (section.style.display === 'none') {
        section.style.display = 'block';
    } else {
        section.style.display = 'none';
    }
}

async function loadAllowedUsers(channelId) {
    const container = document.getElementById(`allowed-users-list-${channelId}`);
    if (!container) return;
    
    try {
        const users = await fetch(`/api/channels/${channelId}/allowed_users`).then(r => r.json());
        
        if (users.length === 0) {
            container.innerHTML = '<div style="padding: 8px; background: #2C2C2E; border-radius: 4px; font-size: 12px; color: #8E8E93;">⭕ No users configured - ALL users allowed</div>';
            return;
        }
        
        container.innerHTML = users.map(user => `
            <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px; background: #2C2C2E; border-radius: 4px; margin-bottom: 6px;">
                <div style="font-size: 12px;">
                    <strong style="color: white;">${user.discord_username}</strong>
                    <span style="color: #8E8E93; margin-left: 8px;">ID: ${user.discord_user_id}</span>
                </div>
                <button class="btn-icon" onclick="removeAllowedUser(${channelId}, '${user.discord_user_id}')" title="Remove User" style="padding: 4px 8px; font-size: 12px;">🗑️</button>
            </div>
        `).join('');
        
    } catch (error) {
        console.error('Failed to load allowed users:', error);
        container.innerHTML = '<div class="error" style="font-size: 12px;">Failed to load users</div>';
    }
}

async function addAllowedUser(channelId) {
    const userIdInput = document.getElementById(`new-user-id-${channelId}`);
    const usernameInput = document.getElementById(`new-username-${channelId}`);
    
    const userId = userIdInput.value.trim();
    const username = usernameInput.value.trim();
    
    if (!userId || !username) {
        showMessage('❌ Please enter both User ID and Username', 'error');
        return;
    }
    
    try {
        const response = await fetch(`/api/channels/${channelId}/allowed_users`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                discord_user_id: userId,
                discord_username: username
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            showMessage('✅ User added successfully!');
            userIdInput.value = '';
            usernameInput.value = '';
            loadAllowedUsers(channelId);
        } else {
            showMessage('❌ ' + result.error, 'error');
        }
    } catch (error) {
        console.error('Failed to add user:', error);
        showMessage('❌ Failed to add user', 'error');
    }
}

async function removeAllowedUser(channelId, userId) {
    if (!confirm('Remove this user from allowed list?')) {
        return;
    }
    
    try {
        const response = await fetch(`/api/channels/${channelId}/allowed_users/${userId}`, {
            method: 'DELETE'
        });
        
        const result = await response.json();
        
        if (result.success) {
            showMessage('✅ User removed');
            loadAllowedUsers(channelId);
        } else {
            showMessage('❌ ' + result.error, 'error');
        }
    } catch (error) {
        console.error('Failed to remove user:', error);
        showMessage('❌ Failed to remove user', 'error');
    }
}

function togglePaperTradeSection(channelId) {
    const section = document.getElementById(`paper-trade-row-${channelId}`);
    if (!section) return;
    
    if (section.style.display === 'none') {
        section.style.display = 'table-row';
        // Start refreshing dashboard when section is opened
        startPaperAccountRefresh(channelId);
    } else {
        section.style.display = 'none';
        // Stop refreshing when section is closed
        stopPaperAccountRefresh(channelId);
    }
}

async function togglePaperTrade(channelId) {
    const checkbox = document.getElementById(`paper-trade-${channelId}`);
    const configDiv = document.getElementById(`paper-trade-config-${channelId}`);
    const enabled = checkbox.checked ? 1 : 0;
    
    try {
        await fetch(`/api/channels/${channelId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ paper_trade_enabled: enabled })
        });
        
        showMessage(enabled ? '✅ Paper trading enabled' : '⏸️ Paper trading disabled');
        
        // Show/hide config section
        if (configDiv) {
            configDiv.style.display = enabled ? 'block' : 'none';
        }
        
        loadChannels(); // Refresh to update status badge
    } catch (error) {
        console.error('Failed to toggle paper trading:', error);
        showMessage('❌ Failed to update paper trading', 'error');
        checkbox.checked = !checkbox.checked; // Revert checkbox
    }
}

async function updatePaperTradeConfig(channelId) {
    const profitTarget = document.getElementById(`profit-target-${channelId}`).value;
    const stopLoss = document.getElementById(`stop-loss-${channelId}`).value;
    const trailingStop = document.getElementById(`trailing-stop-${channelId}`).value;
    const trailingActivation = document.getElementById(`trailing-activation-${channelId}`).value;
    
    try {
        await fetch(`/api/channels/${channelId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                profit_target_pct: profitTarget === '' ? null : parseFloat(profitTarget),
                stop_loss_pct: stopLoss === '' ? null : parseFloat(stopLoss),
                trailing_stop_pct: trailingStop === '' ? null : parseFloat(trailingStop),
                trailing_activation_pct: trailingActivation === '' ? null : parseFloat(trailingActivation)
            })
        });
        
        showMessage('✅ Paper trading configuration saved!');
    } catch (error) {
        console.error('Failed to update paper trade config:', error);
        showMessage('❌ Failed to save configuration', 'error');
    }
}

let paperAccountRefreshIntervals = {};

async function loadPaperAccountDashboard(channelId) {
    const dashboardDiv = document.getElementById(`paper-account-dashboard-${channelId}`);
    if (!dashboardDiv) return;
    
    try {
        const response = await fetch('/api/webull/paper_account');
        const data = await response.json();
        
        if (data.status === 'ok' && data.balance) {
            const balance = data.balance;
            const positions = data.positions || [];
            const orders = data.orders || [];
            
            // Safely convert to numbers with fallback
            const buyingPower = Number(balance.buying_power) || 0;
            const netLiq = Number(balance.net_liquidation) || 0;
            const unrealizedPnl = Number(balance.unrealized_pnl) || 0;
            const cashBalance = Number(balance.cash_balance) || 0;
            
            dashboardDiv.innerHTML = `
                <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px;">
                    <div style="background: rgba(0, 212, 255, 0.1); padding: 12px; border-radius: 6px; border: 1px solid rgba(0, 212, 255, 0.2);">
                        <div style="font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Buying Power</div>
                        <div style="font-size: 16px; font-weight: 700; color: #00d4ff;">$${buyingPower.toFixed(2)}</div>
                    </div>
                    <div style="background: rgba(0, 255, 136, 0.1); padding: 12px; border-radius: 6px; border: 1px solid rgba(0, 255, 136, 0.2);">
                        <div style="font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Net Liquidation</div>
                        <div style="font-size: 16px; font-weight: 700; color: #00ff88;">$${netLiq.toFixed(2)}</div>
                    </div>
                    <div style="background: ${unrealizedPnl >= 0 ? 'rgba(0, 255, 136, 0.1)' : 'rgba(255, 107, 107, 0.1)'}; padding: 12px; border-radius: 6px; border: 1px solid ${unrealizedPnl >= 0 ? 'rgba(0, 255, 136, 0.2)' : 'rgba(255, 107, 107, 0.2)'};">
                        <div style="font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Unrealized P/L</div>
                        <div style="font-size: 16px; font-weight: 700; color: ${unrealizedPnl >= 0 ? '#00ff88' : '#ff6b6b'};">${unrealizedPnl >= 0 ? '+' : ''}$${unrealizedPnl.toFixed(2)}</div>
                    </div>
                    <div style="background: rgba(255, 193, 7, 0.1); padding: 12px; border-radius: 6px; border: 1px solid rgba(255, 193, 7, 0.2);">
                        <div style="font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Cash Balance</div>
                        <div style="font-size: 16px; font-weight: 700; color: #ffc107;">$${cashBalance.toFixed(2)}</div>
                    </div>
                </div>
                
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
                    <div style="background: rgba(0, 0, 0, 0.2); padding: 12px; border-radius: 6px;">
                        <h5 style="margin: 0 0 10px 0; font-size: 12px; color: #00d4ff; font-weight: 600;">📊 Live Positions (${positions.length})</h5>
                        ${positions.length > 0 ? positions.map(pos => `
                            <div style="padding: 8px; background: rgba(255, 255, 255, 0.03); border-radius: 4px; margin-bottom: 6px; border-left: 3px solid ${pos.pnl >= 0 ? '#00ff88' : '#ff6b6b'};">
                                <div style="display: flex; justify-content: space-between; align-items: center;">
                                    <div>
                                        <span style="font-weight: 600; color: white; font-size: 13px;">${pos.symbol}</span>
                                        <span style="font-size: 11px; color: #8E8E93; margin-left: 6px;">${pos.quantity} ${pos.asset_type}</span>
                                    </div>
                                    <div style="text-align: right;">
                                        <div style="font-size: 13px; font-weight: 600; color: ${pos.pnl >= 0 ? '#00ff88' : '#ff6b6b'};">${pos.pnl >= 0 ? '+' : ''}$${pos.pnl.toFixed(2)}</div>
                                    </div>
                                </div>
                            </div>
                        `).join('') : '<div style="font-size: 12px; color: #8E8E93; text-align: center; padding: 20px;">No open positions</div>'}
                    </div>
                    
                    <div style="background: rgba(0, 0, 0, 0.2); padding: 12px; border-radius: 6px;">
                        <h5 style="margin: 0 0 10px 0; font-size: 12px; color: #00d4ff; font-weight: 600;">📝 Pending Orders (${orders.length})</h5>
                        ${orders.length > 0 ? orders.map(order => `
                            <div style="padding: 8px; background: rgba(255, 255, 255, 0.03); border-radius: 4px; margin-bottom: 6px;">
                                <div style="display: flex; justify-content: space-between; align-items: center;">
                                    <div>
                                        <span style="font-weight: 600; color: white; font-size: 13px;">${order.symbol}</span>
                                        <span style="font-size: 11px; color: ${order.action === 'BUY' ? '#00ff88' : '#ff6b6b'}; margin-left: 6px;">${order.action}</span>
                                    </div>
                                    <div style="text-align: right;">
                                        <div style="font-size: 11px; color: #8E8E93;">${order.filled}/${order.quantity}</div>
                                        <div style="font-size: 11px; color: #ffc107;">${order.status}</div>
                                    </div>
                                </div>
                            </div>
                        `).join('') : '<div style="font-size: 12px; color: #8E8E93; text-align: center; padding: 20px;">No pending orders</div>'}
                    </div>
                </div>
                <div style="margin-top: 10px; font-size: 11px; color: #8E8E93; text-align: center;">
                    ✅ Connected to Webull Paper Trading Account • Auto-refreshing every 5s
                </div>
            `;
        } else if (data.status === 'loading') {
            dashboardDiv.innerHTML = '<div style="font-size: 12px; color: #8E8E93; text-align: center; padding: 20px;">⏳ Loading paper account data...</div>';
        } else {
            dashboardDiv.innerHTML = `<div style="font-size: 12px; color: #ff6b6b; text-align: center; padding: 20px;">⚠️ Paper broker not available${data.error ? ': ' + data.error : ''}</div>`;
        }
    } catch (error) {
        console.error('Failed to load paper account dashboard:', error);
        dashboardDiv.innerHTML = '<div style="font-size: 12px; color: #ff6b6b; text-align: center; padding: 20px;">❌ Error loading paper account data</div>';
    }
}

function startPaperAccountRefresh(channelId) {
    // Stop any existing refresh first (prevents duplicates)
    stopPaperAccountRefresh(channelId);
    
    // Load immediately
    loadPaperAccountDashboard(channelId);
    
    // Then refresh every 5 seconds
    paperAccountRefreshIntervals[channelId] = setInterval(() => {
        const dashboardDiv = document.getElementById(`paper-account-dashboard-${channelId}`);
        // Only refresh if dashboard still exists in DOM
        if (dashboardDiv) {
            loadPaperAccountDashboard(channelId);
        } else {
            // Dashboard removed, stop interval
            stopPaperAccountRefresh(channelId);
        }
    }, 5000);
}

function stopPaperAccountRefresh(channelId) {
    if (paperAccountRefreshIntervals[channelId]) {
        clearInterval(paperAccountRefreshIntervals[channelId]);
        delete paperAccountRefreshIntervals[channelId];
    }
}

// Toggle Risk Management section visibility
function toggleBrokerSelection(channelId) {
    const row = document.getElementById(`broker-selection-row-${channelId}`);
    if (row) {
        if (row.style.display === 'none' || row.style.display === '') {
            row.style.display = 'table-row';
        } else {
            row.style.display = 'none';
        }
    }
}

async function saveBrokerSelection(channelId) {
    // Collect selected brokers from all 6 checkboxes
    const brokers = [];
    
    ALL_BROKERS.forEach(broker => {
        const checkbox = document.getElementById(`broker-${broker}-${channelId}`);
        if (checkbox && checkbox.checked) {
            brokers.push(broker);
        }
    });
    
    // Collect NDX→QQQ conversion settings
    const ndxToQqqCheckbox = document.getElementById(`ndx-to-qqq-${channelId}`);
    const ndxDeltaInput = document.getElementById(`ndx-delta-${channelId}`);
    const ndxToQqqEnabled = ndxToQqqCheckbox ? (ndxToQqqCheckbox.checked ? 1 : 0) : 0;
    const ndxToQqqDelta = ndxDeltaInput ? parseFloat(ndxDeltaInput.value) || 0.3 : 0.3;
    
    try {
        const response = await fetch(`/api/channels/${channelId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                enabled_brokers: brokers,
                ndx_to_qqq_enabled: ndxToQqqEnabled,
                ndx_to_qqq_delta: ndxToQqqDelta
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            const liveCount = brokers.filter(b => !b.includes('PAPER')).length;
            const paperCount = brokers.filter(b => b.includes('PAPER')).length;
            let message = `✅ Broker selection saved!`;
            if (brokers.length > 0) {
                message += ` ${liveCount > 0 ? `🔴 ${liveCount} LIVE` : ''} ${paperCount > 0 ? `🟢 ${paperCount} PAPER` : ''}`;
            } else {
                message += ' Using default broker.';
            }
            showMessage(message);
            loadChannels(); // Refresh to show updated badges
        } else {
            showMessage('❌ Failed to save broker selection', 'error');
        }
    } catch (error) {
        console.error('Failed to save broker selection:', error);
        showMessage('❌ Failed to save broker selection', 'error');
    }
}

function toggleRiskManagement(channelId) {
    const row = document.getElementById(`risk-management-row-${channelId}`);
    if (row) {
        if (row.style.display === 'none' || row.style.display === '') {
            row.style.display = 'table-row';
        } else {
            row.style.display = 'none';
        }
    }
}

function toggleTickerFilter(channelId) {
    const row = document.getElementById(`ticker-filter-row-${channelId}`);
    if (row) {
        if (row.style.display === 'none' || row.style.display === '') {
            row.style.display = 'table-row';
        } else {
            row.style.display = 'none';
        }
    }
}

function toggleTickerFilterList(channelId, mode) {
    const container = document.getElementById(`ticker-filter-list-container-${channelId}`);
    if (container) {
        container.style.display = mode === 'off' ? 'none' : 'block';
    }
}

async function saveTickerFilter(channelId) {
    try {
        const mode = document.getElementById(`ticker-filter-mode-${channelId}`).value;
        const list = document.getElementById(`ticker-filter-list-${channelId}`).value.trim();
        
        const response = await fetch(`/api/channels/${channelId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                ticker_filter_mode: mode,
                ticker_filter_list: list
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            const badge = document.getElementById(`ticker-filter-badge-${channelId}`);
            if (badge) {
                if (mode === 'allow') {
                    badge.textContent = '✓ ALLOW LIST';
                    badge.style.background = 'rgba(255, 179, 0, 0.15)';
                    badge.style.borderColor = 'rgba(255, 179, 0, 0.3)';
                    badge.style.color = '#ffb300';
                } else if (mode === 'block') {
                    badge.textContent = '✗ BLOCK LIST';
                    badge.style.background = 'rgba(255, 179, 0, 0.15)';
                    badge.style.borderColor = 'rgba(255, 179, 0, 0.3)';
                    badge.style.color = '#ffb300';
                } else {
                    badge.textContent = 'OFF';
                    badge.style.background = 'rgba(142, 142, 147, 0.15)';
                    badge.style.borderColor = 'rgba(142, 142, 147, 0.3)';
                    badge.style.color = '#8E8E93';
                }
            }
            showMessage('✅ Ticker filter saved successfully');
        } else {
            showMessage('❌ ' + (result.error || 'Failed to save ticker filter'), 'error');
        }
    } catch (error) {
        console.error('Error saving ticker filter:', error);
        showMessage('❌ Error: ' + error.message, 'error');
    }
}

// Save Risk Management settings
async function toggleChannelRisk(channelId, enabled) {
    try {
        const response = await fetch(`/api/channels/${channelId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ risk_management_enabled: enabled ? 1 : 0 })
        });
        
        const result = await response.json();
        
        if (result.success) {
            const badge = document.getElementById(`risk-status-badge-${channelId}`);
            const panel = document.getElementById(`risk-settings-panel-${channelId}`);
            
            if (enabled) {
                badge.textContent = '✓ ENABLED';
                badge.style.background = 'rgba(0, 255, 136, 0.15)';
                badge.style.borderColor = 'rgba(0, 255, 136, 0.3)';
                badge.style.color = '#00ff88';
                panel.style.display = 'block';
                showMessage('✅ Per-channel risk management ENABLED');
            } else {
                badge.textContent = '✗ DISABLED';
                badge.style.background = 'rgba(142, 142, 147, 0.15)';
                badge.style.borderColor = 'rgba(142, 142, 147, 0.3)';
                badge.style.color = '#8E8E93';
                panel.style.display = 'none';
                showMessage('⚠️ Per-channel risk management DISABLED');
            }
        } else {
            showMessage('❌ ' + (result.error || 'Failed to update'), 'error');
            document.getElementById(`risk-enabled-${channelId}`).checked = !enabled;
        }
    } catch (error) {
        console.error('Error toggling channel risk:', error);
        showMessage('❌ Error: ' + error.message, 'error');
        document.getElementById(`risk-enabled-${channelId}`).checked = !enabled;
    }
}

function toggleEarlyTrailingExclusion(channelId, enabled) {
    const trailingStopInput = document.getElementById(`risk-trailing-stop-${channelId}`);
    const trailingActivationInput = document.getElementById(`risk-trailing-activation-${channelId}`);
    const disabledNote = document.getElementById(`trailing-disabled-note-${channelId}`);
    
    if (enabled) {
        trailingStopInput.disabled = true;
        trailingStopInput.value = '';
        trailingStopInput.placeholder = 'Disabled';
        trailingStopInput.style.background = '#2A2A2C';
        trailingStopInput.style.color = '#666';
        trailingStopInput.style.opacity = '0.6';
        
        trailingActivationInput.disabled = true;
        trailingActivationInput.value = '';
        trailingActivationInput.placeholder = 'Disabled';
        trailingActivationInput.style.background = '#2A2A2C';
        trailingActivationInput.style.color = '#666';
        trailingActivationInput.style.opacity = '0.6';
        
        if (disabledNote) disabledNote.style.display = 'inline';
    } else {
        trailingStopInput.disabled = false;
        trailingStopInput.placeholder = 'Leave empty for default';
        trailingStopInput.style.background = '#1C1C1E';
        trailingStopInput.style.color = 'white';
        trailingStopInput.style.opacity = '1';
        
        trailingActivationInput.disabled = false;
        trailingActivationInput.placeholder = 'Leave empty for default';
        trailingActivationInput.style.background = '#1C1C1E';
        trailingActivationInput.style.color = 'white';
        trailingActivationInput.style.opacity = '1';
        
        if (disabledNote) disabledNote.style.display = 'none';
    }
}

function toggleTrimOffsetMode(channelId, mode) {
    const dollarDiv = document.getElementById(`trim-offset-dollar-${channelId}`);
    const pctDiv = document.getElementById(`trim-offset-pct-${channelId}`);
    if (dollarDiv) dollarDiv.style.display = mode === 'dollar' ? 'flex' : 'none';
    if (pctDiv) pctDiv.style.display = mode === 'percent' ? 'flex' : 'none';
}

async function saveRiskManagement(channelId) {
    try {
        const riskEnabled = document.getElementById(`risk-enabled-${channelId}`)?.checked ? 1 : 0;
        const profitTarget1 = document.getElementById(`risk-profit-target-1-${channelId}`).value;
        const profitTarget2 = document.getElementById(`risk-profit-target-2-${channelId}`).value;
        const profitTarget3 = document.getElementById(`risk-profit-target-3-${channelId}`).value;
        const profitTarget4 = document.getElementById(`risk-profit-target-4-${channelId}`).value;
        const qty1 = document.getElementById(`risk-qty-1-${channelId}`).value;
        const qty2 = document.getElementById(`risk-qty-2-${channelId}`).value;
        const qty3 = document.getElementById(`risk-qty-3-${channelId}`).value;
        const qty4 = document.getElementById(`risk-qty-4-${channelId}`).value;
        const stopLoss = document.getElementById(`risk-stop-loss-${channelId}`).value;
        const trailingStop = document.getElementById(`risk-trailing-stop-${channelId}`).value;
        const trailingActivation = document.getElementById(`risk-trailing-activation-${channelId}`).value;
        const leaveRunnerEnabled = document.getElementById(`risk-leave-runner-enabled-${channelId}`)?.checked ? 1 : 0;
        const leaveRunnerPct = document.getElementById(`risk-leave-runner-pct-${channelId}`).value;
        const trimOrderMode = document.querySelector(`input[name="trim-order-mode-${channelId}"]:checked`)?.value || 'market';
        const trimLimitOffset = document.getElementById(`risk-trim-offset-${channelId}`).value;
        const trimOffsetMode = document.getElementById(`risk-trim-offset-mode-${channelId}`)?.value || 'dollar';
        const trimOffsetPct = document.getElementById(`risk-trim-offset-pct-${channelId}`)?.value;
        const slOrderMode = document.querySelector(`input[name="sl-order-mode-${channelId}"]:checked`)?.value || 'limit';
        const slLimitOffset = document.getElementById(`risk-sl-limit-offset-${channelId}`).value;
        const tradeSummaryEnabled = document.getElementById(`trade-summary-enabled-${channelId}`)?.checked ? 1 : 0;
        const escalationOnlyMode = document.getElementById(`risk-escalation-only-${channelId}`)?.checked ? 1 : 0;
        const exitStrategyMode = document.querySelector(`input[name="exit-strategy-mode-${channelId}"]:checked`)?.value || 'hybrid';
        const chaseModeVal = document.getElementById(`risk-chase-mode-${channelId}`)?.value || 'off';
        const orderChaseEnabled = ['exit','both'].includes(chaseModeVal) ? 1 : 0;
        const entryChaseEnabled = ['entry','both'].includes(chaseModeVal) ? 1 : 0;

        // Enhanced risk settings
        const enableDynamicSl = document.getElementById(`risk-dynamic-sl-${channelId}`)?.checked ? 1 : 0;
        const dynamicSlProfile = document.getElementById(`risk-dynamic-sl-profile-${channelId}`)?.value || 'standard';
        const enableGivebackGuard = document.getElementById(`risk-giveback-guard-${channelId}`)?.checked ? 1 : 0;
        const givebackAllowedPct = document.getElementById(`risk-giveback-pct-${channelId}`).value;
        
        // Early Trailing Stop settings
        const enableEarlyTrailing = document.getElementById(`risk-early-trailing-${channelId}`)?.checked ? 1 : 0;
        const earlyTrailingActivationPct = document.getElementById(`risk-early-activation-${channelId}`).value;
        const earlyTrailingStepPct = document.getElementById(`risk-early-step-${channelId}`).value;

        // EMA Risk Management settings
        const emaRiskEnabled = document.getElementById(`risk-ema-enabled-${channelId}`)?.checked ? 1 : 0;
        const emaPeriod = document.getElementById(`risk-ema-period-${channelId}`)?.value || '5';
        const emaTimeframe = document.getElementById(`risk-ema-timeframe-${channelId}`)?.value || '5';
        const emaBuffer = document.getElementById(`risk-ema-buffer-${channelId}`)?.value;
        const emaExitEnabled = document.getElementById(`risk-ema-exit-${channelId}`)?.checked ? 1 : 0;
        const emaEscalationEnabled = document.getElementById(`risk-ema-escalation-${channelId}`)?.checked ? 1 : 0;
        const emaNoTrend = document.getElementById(`risk-ema-no-trend-${channelId}`)?.value || '3';
        const emaUseUnderlying = document.getElementById(`risk-ema-underlying-${channelId}`)?.checked ? 1 : 0;
        const emaExtendedHours = document.getElementById(`risk-ema-extended-${channelId}`)?.checked ? 1 : 0;

        // Mutual exclusion validation: Early Trailing and Legacy Trailing cannot both be active
        if (enableEarlyTrailing && trailingStop && parseFloat(trailingStop) > 0) {
            showMessage('⚠️ Early Trailing and Legacy Trailing Stop are mutually exclusive. Please disable one.', 'error');
            return;
        }
        
        const payload = {
                risk_management_enabled: riskEnabled,
                profit_target_1_pct: profitTarget1 ? parseFloat(profitTarget1) : null,
                profit_target_2_pct: profitTarget2 ? parseFloat(profitTarget2) : null,
                profit_target_3_pct: profitTarget3 ? parseFloat(profitTarget3) : null,
                profit_target_4_pct: profitTarget4 ? parseFloat(profitTarget4) : null,
                profit_target_qty_1: qty1 ? parseInt(qty1) : null,
                profit_target_qty_2: qty2 ? parseInt(qty2) : null,
                profit_target_qty_3: qty3 ? parseInt(qty3) : null,
                profit_target_qty_4: qty4 ? parseInt(qty4) : null,
                stop_loss_pct: stopLoss ? parseFloat(stopLoss) : null,
                trailing_stop_pct: trailingStop ? parseFloat(trailingStop) : null,
                trailing_activation_pct: trailingActivation ? parseFloat(trailingActivation) : null,
                leave_runner_enabled: leaveRunnerEnabled,
                leave_runner_pct: leaveRunnerPct ? parseFloat(leaveRunnerPct) : 25.0,
                trim_order_mode: trimOrderMode,
                trim_limit_offset: trimLimitOffset ? parseFloat(trimLimitOffset) : 0.01,
                trim_limit_offset_mode: trimOffsetMode,
                trim_limit_offset_pct: trimOffsetPct ? parseFloat(trimOffsetPct) : 2.0,
                sl_order_mode: slOrderMode,
                sl_limit_offset: slLimitOffset ? parseFloat(slLimitOffset) / 100 : 0.03,
                trade_summary_enabled: tradeSummaryEnabled,
                enable_dynamic_sl: enableDynamicSl,
                dynamic_sl_profile: dynamicSlProfile,
                enable_giveback_guard: enableGivebackGuard,
                giveback_allowed_pct: givebackAllowedPct ? parseFloat(givebackAllowedPct) : 30.0,
                enable_early_trailing: enableEarlyTrailing,
                early_trailing_activation_pct: earlyTrailingActivationPct ? parseFloat(earlyTrailingActivationPct) : 5.0,
                early_trailing_step_pct: earlyTrailingStepPct ? parseFloat(earlyTrailingStepPct) : 3.0,
                ema_risk_enabled: emaRiskEnabled,
                ema_period: parseInt(emaPeriod),
                ema_timeframe_minutes: parseInt(emaTimeframe),
                ema_buffer_pct: emaBuffer ? parseFloat(emaBuffer) : 0.1,
                ema_exit_enabled: emaExitEnabled,
                ema_escalation_enabled: emaEscalationEnabled,
                ema_no_trend_candles: parseInt(emaNoTrend),
                ema_use_underlying: emaUseUnderlying,
                ema_extended_hours: emaExtendedHours,
                escalation_only_mode: escalationOnlyMode,
                exit_strategy_mode: exitStrategyMode,
                order_chase_enabled: orderChaseEnabled,
                entry_chase_enabled: entryChaseEnabled,
                use_global_risk_settings: 0
        };
        const response = await fetch(`/api/channels/${channelId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        const result = await response.json();
        
        if (result.success) {
            showMessage('✅ Risk management settings saved!');
            loadChannels(); // Refresh to show updated values
        } else {
            showMessage('❌ ' + (result.error || 'Failed to save settings'), 'error');
        }
    } catch (error) {
        console.error('Failed to save risk management settings:', error);
        showMessage('❌ Failed to save settings', 'error');
    }
}

function switchRiskTab(channelId, tabName) {
    document.querySelectorAll(`.risk-tab-btn-${channelId}`).forEach(b => {
        b.style.borderBottomColor = 'transparent';
        b.style.color = '#8E8E93';
    });
    ['targets', 'advanced'].forEach(t => {
        const pane = document.getElementById(`risk-tab-${t}-${channelId}`);
        if (pane) pane.style.display = 'none';
    });
    const activeBtn = document.querySelector(`.risk-tab-btn-${channelId}[data-risk-tab="${tabName}"]`);
    if (activeBtn) {
        activeBtn.style.borderBottomColor = '#00d4ff';
        activeBtn.style.color = '#00d4ff';
    }
    const activePane = document.getElementById(`risk-tab-${tabName}-${channelId}`);
    if (activePane) activePane.style.display = 'block';
}

function updateRiskSummaryRail(channelId) {
    const pills = [];
    const pill = (text, color) => `<span style="display:inline-block;padding:2px 8px;border-radius:12px;font-size:10px;font-weight:600;background:${color}22;color:${color};border:1px solid ${color}44;">${text}</span>`;
    const sl = parseFloat(document.getElementById(`risk-stop-loss-${channelId}`)?.value) || 0;
    if (sl > 0) pills.push(pill('SL ' + sl + '%', '#EF4444'));
    const pts = [1,2,3,4].filter(i => parseFloat(document.getElementById(`risk-profit-target-${i}-${channelId}`)?.value) > 0);
    if (pts.length > 0) pills.push(pill('PT' + pts.join('/'), '#00d4ff'));
    const trail = parseFloat(document.getElementById(`risk-trailing-stop-${channelId}`)?.value) || 0;
    if (trail > 0) pills.push(pill('Trail ' + trail + '%', '#F59E0B'));
    if (document.getElementById(`risk-early-trailing-${channelId}`)?.checked) pills.push(pill('Early Trail', '#e879f9'));
    if (document.getElementById(`risk-dynamic-sl-${channelId}`)?.checked) pills.push(pill('Dyn SL', '#F59E0B'));
    if (document.getElementById(`risk-escalation-only-${channelId}`)?.checked) pills.push(pill('Esc Only', '#F59E0B'));
    if (document.getElementById(`risk-giveback-guard-${channelId}`)?.checked) pills.push(pill('Giveback', '#17a2b8'));
    if (document.getElementById(`risk-ema-enabled-${channelId}`)?.checked) pills.push(pill('EMA', '#38bdf8'));
    const chaseModeForPill = document.getElementById(`risk-chase-mode-${channelId}`)?.value || 'off';
    if (chaseModeForPill === 'entry') pills.push(pill('Chase Entry', '#7C3AED'));
    else if (chaseModeForPill === 'exit') pills.push(pill('Chase Exit', '#7C3AED'));
    else if (chaseModeForPill === 'both') pills.push(pill('Chase Both', '#7C3AED'));
    if (document.getElementById(`risk-leave-runner-enabled-${channelId}`)?.checked) pills.push(pill('Runner', '#7C3AED'));
    const pillsEl = document.getElementById(`risk-summary-pills-${channelId}`);
    if (pillsEl) pillsEl.innerHTML = pills.length > 0 ? pills.join(' ') : '<span style="color:#8E8E93;font-size:11px;">No risk features enabled</span>';
}

function validateRiskSettings(channelId) {
    const warnings = [];
    const pt1 = parseFloat(document.getElementById(`risk-profit-target-1-${channelId}`)?.value) || 0;
    const pt2 = parseFloat(document.getElementById(`risk-profit-target-2-${channelId}`)?.value) || 0;
    const pt3 = parseFloat(document.getElementById(`risk-profit-target-3-${channelId}`)?.value) || 0;
    const pt4 = parseFloat(document.getElementById(`risk-profit-target-4-${channelId}`)?.value) || 0;
    const sl = parseFloat(document.getElementById(`risk-stop-loss-${channelId}`)?.value) || 0;
    const trail = parseFloat(document.getElementById(`risk-trailing-stop-${channelId}`)?.value) || 0;
    const earlyOn = document.getElementById(`risk-early-trailing-${channelId}`)?.checked;
    const earlyAct = parseFloat(document.getElementById(`risk-early-activation-${channelId}`)?.value) || 0;
    const escOnly = document.getElementById(`risk-escalation-only-${channelId}`)?.checked;
    const dynSl = document.getElementById(`risk-dynamic-sl-${channelId}`)?.checked;
    const activePTs = [pt1, pt2, pt3, pt4].filter(v => v > 0);
    for (let i = 1; i < activePTs.length; i++) {
        if (activePTs[i] <= activePTs[i-1]) { warnings.push('Profit targets must be in ascending order.'); break; }
    }
    if (sl > 0 && activePTs.length > 0 && sl >= activePTs[0]) {
        warnings.push(`Stop loss (${sl}%) is >= your lowest PT (${activePTs[0]}%). The SL could trigger before any profit target.`);
    }
    if (earlyOn && trail > 0) {
        warnings.push('Both Early Trailing and Legacy Trailing are configured. Early Trailing takes priority.');
    }
    if (earlyOn && earlyAct <= 0) {
        warnings.push('Early Trailing is enabled but activation % is 0. It will not activate.');
    }
    if (escOnly && !dynSl && !earlyOn) {
        warnings.push('SL Escalation Only is enabled but neither Dynamic SL nor Early Trailing is active. Stop loss will not escalate.');
    }
    const validEl = document.getElementById(`risk-validation-${channelId}`);
    const msgEl = document.getElementById(`risk-validation-msg-${channelId}`);
    if (validEl && msgEl) {
        if (warnings.length > 0) {
            msgEl.innerHTML = warnings.map(w => '\u26a0\ufe0f ' + w).join('<br>');
            validEl.style.display = 'block';
        } else {
            validEl.style.display = 'none';
        }
    }
}

function updateExitModeHighlight(channelId) {
    document.querySelectorAll(`.exit-mode-opt-${channelId}`).forEach(opt => {
        const radio = opt.querySelector('input[type="radio"]');
        opt.style.border = radio?.checked ? '2px solid #10B981' : '2px solid transparent';
        opt.style.background = radio?.checked ? 'rgba(16,185,129,0.08)' : 'rgba(255,255,255,0.03)';
    });
    updateRiskSummaryRail(channelId);
}

function applyRiskPreset(channelId, preset) {
    const presets = {
        scalp: { pt1: 10, pt2: 20, pt3: 0, pt4: 0, sl: 15, trail: 0, trail_act: 0, early: true, early_act: 5, early_step: 3, dynamic: false, escalation: false, giveback: true, giveback_pct: 30, ema: false, ema_period: 5, ema_tf: 1, ema_buffer: 0.1, ema_exit: true, ema_esc: true, ema_ext: false, ema_under: true, ema_notrend: 3, runner: false, runner_pct: 25, exit_mode: 'risk', trim_order: 'market', sl_order: 'market', chase: false, sl_profile: 'standard', trim_offset_mode: 'dollar', trim_offset_dollar: 0.01, trim_offset_pct: 2.0, sl_offset: 3 },
        swing: { pt1: 15, pt2: 30, pt3: 50, pt4: 75, sl: 25, trail: 15, trail_act: 30, early: false, early_act: 5, early_step: 3, dynamic: true, escalation: false, giveback: true, giveback_pct: 35, ema: true, ema_period: 5, ema_tf: 5, ema_buffer: 0.1, ema_exit: true, ema_esc: true, ema_ext: false, ema_under: true, ema_notrend: 3, runner: true, runner_pct: 25, exit_mode: 'hybrid', trim_order: 'limit', sl_order: 'limit', chase: true, sl_profile: 'standard', trim_offset_mode: 'dollar', trim_offset_dollar: 0.01, trim_offset_pct: 2.0, sl_offset: 3 },
        momentum: { pt1: 20, pt2: 40, pt3: 60, pt4: 100, sl: 20, trail: 0, trail_act: 0, early: true, early_act: 8, early_step: 5, dynamic: true, escalation: true, giveback: true, giveback_pct: 25, ema: false, ema_period: 5, ema_tf: 5, ema_buffer: 0.1, ema_exit: true, ema_esc: true, ema_ext: false, ema_under: true, ema_notrend: 3, runner: true, runner_pct: 30, exit_mode: 'risk', trim_order: 'market', sl_order: 'market', chase: false, sl_profile: 'aggressive', trim_offset_mode: 'dollar', trim_offset_dollar: 0.01, trim_offset_pct: 2.0, sl_offset: 3 },
        trend: { pt1: 25, pt2: 50, pt3: 100, pt4: 150, sl: 30, trail: 20, trail_act: 40, early: false, early_act: 10, early_step: 5, dynamic: true, escalation: false, giveback: true, giveback_pct: 40, ema: true, ema_period: 5, ema_tf: 5, ema_buffer: 0.15, ema_exit: true, ema_esc: true, ema_ext: false, ema_under: true, ema_notrend: 5, runner: true, runner_pct: 30, exit_mode: 'hybrid', trim_order: 'limit', sl_order: 'limit', chase: true, sl_profile: 'standard', trim_offset_mode: 'dollar', trim_offset_dollar: 0.01, trim_offset_pct: 2.0, sl_offset: 3 }
    };
    const p = presets[preset];
    if (!p) return;

    const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
    const setChk = (id, val) => { const el = document.getElementById(id); if (el) el.checked = val; };

    setVal(`risk-profit-target-1-${channelId}`, p.pt1 || '');
    setVal(`risk-profit-target-2-${channelId}`, p.pt2 || '');
    setVal(`risk-profit-target-3-${channelId}`, p.pt3 || '');
    setVal(`risk-profit-target-4-${channelId}`, p.pt4 || '');
    setVal(`risk-qty-1-${channelId}`, '');
    setVal(`risk-qty-2-${channelId}`, '');
    setVal(`risk-qty-3-${channelId}`, '');
    setVal(`risk-qty-4-${channelId}`, '');
    setVal(`risk-stop-loss-${channelId}`, p.sl || '');
    setVal(`risk-trailing-stop-${channelId}`, p.trail || '');
    setVal(`risk-trailing-activation-${channelId}`, p.trail_act || '');

    setChk(`risk-early-trailing-${channelId}`, p.early);
    setVal(`risk-early-activation-${channelId}`, p.early_act);
    setVal(`risk-early-step-${channelId}`, p.early_step);
    toggleEarlyTrailingExclusion(channelId, p.early);

    setChk(`risk-dynamic-sl-${channelId}`, p.dynamic);
    const profileEl = document.getElementById(`risk-dynamic-sl-profile-${channelId}`);
    if (profileEl) profileEl.value = p.sl_profile;
    setChk(`risk-escalation-only-${channelId}`, p.escalation);
    setChk(`risk-giveback-guard-${channelId}`, p.giveback);
    setVal(`risk-giveback-pct-${channelId}`, p.giveback_pct);

    setChk(`risk-ema-enabled-${channelId}`, p.ema);
    const emaGrid = document.getElementById(`ema-settings-grid-${channelId}`);
    if (emaGrid) emaGrid.style.display = p.ema ? 'block' : 'none';
    setVal(`risk-ema-period-${channelId}`, p.ema_period);
    setVal(`risk-ema-timeframe-${channelId}`, p.ema_tf);
    setVal(`risk-ema-buffer-${channelId}`, p.ema_buffer);
    setChk(`risk-ema-exit-${channelId}`, p.ema_exit);
    setChk(`risk-ema-escalation-${channelId}`, p.ema_esc);
    setChk(`risk-ema-extended-${channelId}`, p.ema_ext);
    setChk(`risk-ema-underlying-${channelId}`, p.ema_under);
    setVal(`risk-ema-no-trend-${channelId}`, p.ema_notrend);

    setChk(`risk-leave-runner-enabled-${channelId}`, p.runner);
    setVal(`risk-leave-runner-pct-${channelId}`, p.runner_pct);
    setChk(`risk-order-chase-${channelId}`, p.chase);
    const chaseModePresetEl = document.getElementById(`risk-chase-mode-${channelId}`);
    if (chaseModePresetEl) chaseModePresetEl.value = p.chase ? 'exit' : 'off';

    const trimRadio = document.querySelector(`input[name="trim-order-mode-${channelId}"][value="${p.trim_order}"]`);
    if (trimRadio) trimRadio.checked = true;
    const limContainer = document.getElementById(`limit-offset-container-${channelId}`);
    if (limContainer) limContainer.style.display = p.trim_order === 'limit' ? 'flex' : 'none';
    const slRadio = document.querySelector(`input[name="sl-order-mode-${channelId}"][value="${p.sl_order}"]`);
    if (slRadio) slRadio.checked = true;
    const slContainer = document.getElementById(`sl-limit-offset-container-${channelId}`);
    if (slContainer) slContainer.style.display = p.sl_order === 'limit' ? 'flex' : 'none';

    setVal(`risk-trim-offset-mode-${channelId}`, p.trim_offset_mode);
    setVal(`risk-trim-offset-${channelId}`, p.trim_offset_dollar);
    setVal(`risk-trim-offset-pct-${channelId}`, p.trim_offset_pct);
    const dol = document.getElementById(`trim-offset-dollar-${channelId}`);
    const pctD = document.getElementById(`trim-offset-pct-${channelId}`);
    if (dol) dol.style.display = p.trim_offset_mode === 'dollar' ? 'flex' : 'none';
    if (pctD) pctD.style.display = p.trim_offset_mode === 'percent' ? 'flex' : 'none';
    setVal(`risk-sl-limit-offset-${channelId}`, p.sl_offset);

    const exitRadio = document.querySelector(`input[name="exit-strategy-mode-${channelId}"][value="${p.exit_mode}"]`);
    if (exitRadio) exitRadio.checked = true;
    updateExitModeHighlight(channelId);

    document.querySelectorAll(`.risk-preset-btn-${channelId}`).forEach(b => {
        b.style.borderColor = 'rgba(255,255,255,0.12)';
        b.style.background = 'rgba(255,255,255,0.04)';
        b.style.color = '#8E8E93';
    });
    const activeBtn = document.querySelector(`.risk-preset-btn-${channelId}[onclick="applyRiskPreset('${channelId}', '${preset}')"]`);
    if (activeBtn) {
        activeBtn.style.borderColor = '#00d4ff';
        activeBtn.style.background = 'rgba(0,212,255,0.12)';
        activeBtn.style.color = '#00d4ff';
    }

    updateRiskSummaryRail(channelId);
    validateRiskSettings(channelId);
}

function initRiskRowListeners(channelId) {
    const inputIds = [`risk-profit-target-1-${channelId}`, `risk-profit-target-2-${channelId}`, `risk-profit-target-3-${channelId}`, `risk-profit-target-4-${channelId}`, `risk-stop-loss-${channelId}`, `risk-trailing-stop-${channelId}`, `risk-early-activation-${channelId}`];
    inputIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('input', () => { updateRiskSummaryRail(channelId); validateRiskSettings(channelId); });
    });
    const changeIds = [`risk-early-trailing-${channelId}`, `risk-dynamic-sl-${channelId}`, `risk-giveback-guard-${channelId}`, `risk-chase-mode-${channelId}`, `risk-escalation-only-${channelId}`, `risk-leave-runner-enabled-${channelId}`, `risk-ema-enabled-${channelId}`];
    changeIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('change', () => { updateRiskSummaryRail(channelId); validateRiskSettings(channelId); });
    });
    updateRiskSummaryRail(channelId);
    validateRiskSettings(channelId);
}

// Show User Performance Modal
async function showUserPerformance(channelId, channelName) {
    try {
        // Fetch user performance data
        const response = await fetch(`/api/channels/${channelId}/users`);
        const data = await response.json();
        
        if (!response.ok || data.error) {
            showMessage('❌ Failed to load user performance: ' + (data.error || 'Unknown error'), 'error');
            return;
        }
        
        const users = data.users || [];
        
        // Create modal HTML
        let modalHtml = `
            <div id="user-performance-modal" style="position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.85); display: flex; align-items: center; justify-content: center; z-index: 10000;" onclick="closeUserPerformanceModal(event)">
                <div style="background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); border-radius: 16px; max-width: 90%; max-height: 90%; overflow-y: auto; border: 2px solid rgba(0, 212, 255, 0.3); box-shadow: 0 20px 60px rgba(0, 212, 255, 0.3);" onclick="event.stopPropagation()">
                    <div style="padding: 24px; border-bottom: 1px solid rgba(0, 212, 255, 0.2); display: flex; justify-content: space-between; align-items: center; background: rgba(0, 212, 255, 0.05);">
                        <h2 style="margin: 0; color: #00d4ff; font-size: 20px; font-weight: 700;">📈 User Performance - ${channelName}</h2>
                        <button onclick="closeUserPerformanceModal(event)" style="background: rgba(255, 107, 107, 0.2); border: 1px solid rgba(255, 107, 107, 0.5); color: #ff6b6b; width: 32px; height: 32px; border-radius: 8px; cursor: pointer; font-size: 18px; transition: all 0.2s;" onmouseover="this.style.background='rgba(255, 107, 107, 0.3)'" onmouseout="this.style.background='rgba(255, 107, 107, 0.2)'">✖</button>
                    </div>
                    <div style="padding: 24px;">
                        ${users.length === 0 ? `
                            <div style="text-align: center; padding: 40px; color: #8E8E93;">
                                <div style="font-size: 48px; margin-bottom: 16px;">📊</div>
                                <div style="font-size: 16px; color: #b4b8c5;">No user performance data available yet</div>
                                <div style="font-size: 13px; color: #6b7280; margin-top: 8px;">Users will appear here after they post signals that are executed and closed with P&L data</div>
                            </div>
                        ` : `
                            <table style="width: 100%; border-collapse: collapse;">
                                <thead>
                                    <tr style="background: rgba(0, 212, 255, 0.1); border-bottom: 2px solid rgba(0, 212, 255, 0.3);">
                                        <th style="padding: 12px; text-align: left; font-size: 12px; color: #00d4ff; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">User</th>
                                        <th style="padding: 12px; text-align: center; font-size: 12px; color: #00d4ff; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">Win Rate</th>
                                        <th style="padding: 12px; text-align: center; font-size: 12px; color: #00d4ff; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">Wins</th>
                                        <th style="padding: 12px; text-align: center; font-size: 12px; color: #00d4ff; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">Losses</th>
                                        <th style="padding: 12px; text-align: center; font-size: 12px; color: #00d4ff; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">Total Trades</th>
                                        <th style="padding: 12px; text-align: right; font-size: 12px; color: #00d4ff; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">Total P/L</th>
                                        <th style="padding: 12px; text-align: right; font-size: 12px; color: #00d4ff; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">Avg % PNL</th>
                                        <th style="padding: 12px; text-align: right; font-size: 12px; color: #00d4ff; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">Avg Return</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${users.map((user, index) => {
                                        const totalPnlColor = user.total_pnl >= 0 ? '#00ff88' : '#ff6b6b';
                                        const avgPnlColor = user.avg_pnl >= 0 ? '#00ff88' : '#ff6b6b';
                                        const winRateColor = user.win_rate >= 50 ? '#00ff88' : user.win_rate >= 30 ? '#ffb700' : '#ff6b6b';
                                        const rowBg = index % 2 === 0 ? 'rgba(0, 212, 255, 0.02)' : 'transparent';
                                        
                                        return `
                                            <tr style="background: ${rowBg}; border-bottom: 1px solid rgba(255,255,255,0.05);" onmouseover="this.style.background='rgba(0, 212, 255, 0.08)'" onmouseout="this.style.background='${rowBg}'">
                                                <td style="padding: 14px; color: #fff; font-weight: 600; font-size: 14px;">${user.name}</td>
                                                <td style="padding: 14px; text-align: center;">
                                                    <span style="background: ${winRateColor}22; border: 1px solid ${winRateColor}55; padding: 4px 10px; border-radius: 6px; color: ${winRateColor}; font-weight: 700; font-size: 13px;">
                                                        ${user.win_rate}%
                                                    </span>
                                                </td>
                                                <td style="padding: 14px; text-align: center; color: #00ff88; font-size: 14px; font-weight: 600;">${user.wins || 0}</td>
                                                <td style="padding: 14px; text-align: center; color: #ff6b6b; font-size: 14px; font-weight: 600;">${user.losses || 0}</td>
                                                <td style="padding: 14px; text-align: center; color: #b4b8c5; font-size: 14px; font-weight: 600;">${user.total_closed || 0}</td>
                                                <td style="padding: 14px; text-align: right; color: ${totalPnlColor}; font-weight: 700; font-size: 15px;">
                                                    ${user.total_pnl >= 0 ? '+' : ''}$${user.total_pnl.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}
                                                </td>
                                                <td style="padding: 14px; text-align: right; color: #b4b8c5; font-size: 14px; font-weight: 600;">
                                                    ${user.avg_pnl_percent >= 0 ? '+' : ''}${user.avg_pnl_percent.toFixed(1)}%
                                                </td>
                                                <td style="padding: 14px; text-align: right; color: ${avgPnlColor}; font-weight: 600; font-size: 14px;">
                                                    ${user.avg_pnl >= 0 ? '+' : ''}$${user.avg_pnl.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}
                                                </td>
                                            </tr>
                                        `;
                                    }).join('')}
                                </tbody>
                            </table>
                        `}
                    </div>
                </div>
            </div>
        `;
        
        // Insert modal into page
        const existingModal = document.getElementById('user-performance-modal');
        if (existingModal) {
            existingModal.remove();
        }
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        
    } catch (error) {
        console.error('Failed to load user performance:', error);
        showMessage('❌ Failed to load user performance', 'error');
    }
}

// Close User Performance Modal
function closeUserPerformanceModal(event) {
    const modal = document.getElementById('user-performance-modal');
    if (modal) {
        modal.remove();
    }
}
