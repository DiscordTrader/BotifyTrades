// Channel Management JavaScript

let channelCategory = 'EXECUTE';

// All available broker options
const ALL_BROKERS = ['WEBULL', 'WEBULL_OFFICIAL', 'ALPACA', 'ALPACA_PAPER', 'IBKR', 'IBKR_PAPER', 'SCHWAB', 'SCHWAB_PAPER', 'TASTYTRADE_LIVE', 'TASTYTRADE_PAPER', 'ROBINHOOD', 'TRADING212', 'TRADING212_PAPER'];

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
    
    const addForm = document.getElementById('add-channel-form');
    if (addForm) {
        addForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            await addChannel();
        });
    }
}

async function loadChannels() {
    const container = document.getElementById('channels-list');
    
    try {
        const channels = await fetch(`/api/channels?category=${channelCategory}`).then(r => r.json());
        
        if (channels.length === 0) {
            container.innerHTML = '<div class="no-data">No channels added yet. Add one from the Channels page.</div>';
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
                                    <button onclick="resetChannelTracking('${channel.id}', '${channel.name}')" title="Reset" style="background: rgba(0, 212, 255, 0.1); border: 1px solid rgba(0, 212, 255, 0.3); color: #00d4ff; width: 28px; height: 28px; border-radius: 6px; cursor: pointer; font-size: 14px; transition: all 0.2s; display: flex; align-items: center; justify-content: center;" onmouseover="this.style.background='rgba(0, 212, 255, 0.25)'; this.style.transform='scale(1.1)'" onmouseout="this.style.background='rgba(0, 212, 255, 0.1)'; this.style.transform='scale(1)'">🔄</button>
                                    <button onclick="toggleChannel('${channel.id}', ${channel.is_active})" title="${channel.is_active ? 'Disable' : 'Enable'}" style="background: rgba(0, 212, 255, 0.1); border: 1px solid rgba(0, 212, 255, 0.3); color: #00d4ff; width: 28px; height: 28px; border-radius: 6px; cursor: pointer; font-size: 14px; transition: all 0.2s; display: flex; align-items: center; justify-content: center;" onmouseover="this.style.background='rgba(0, 212, 255, 0.25)'; this.style.transform='scale(1.1)'" onmouseout="this.style.background='rgba(0, 212, 255, 0.1)'; this.style.transform='scale(1)'">${channel.is_active ? '⏸️' : '▶️'}</button>
                                    <button onclick="deleteChannel('${channel.id}', '${channel.name}')" title="Delete" style="background: rgba(255, 107, 107, 0.1); border: 1px solid rgba(255, 107, 107, 0.3); color: #ff6b6b; width: 28px; height: 28px; border-radius: 6px; cursor: pointer; font-size: 14px; transition: all 0.2s; display: flex; align-items: center; justify-content: center;" onmouseover="this.style.background='rgba(255, 107, 107, 0.25)'; this.style.transform='scale(1.1)'" onmouseout="this.style.background='rgba(255, 107, 107, 0.1)'; this.style.transform='scale(1)'">🗑️</button>
                                </div>
                            </td>
                        </tr>
                        <tr id="broker-selection-row-${channel.id}" style="display: none; background: rgba(0, 212, 255, 0.03);">
                            <td colspan="8" style="padding: 20px;">
                                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
                                <h4 style="margin: 0; font-size: 14px; color: var(--primary-blue); display: flex; align-items: center; gap: 8px;">🔌 Multi-Broker ${channelCategory === 'EXECUTE' ? 'Execution' : 'Tracking'}</h4>
                                <button type="button" onclick="showRiskHelp('multi-broker')" style="width:22px;height:22px;border-radius:50%;border:1.5px solid #52525B;background:rgba(99,102,241,0.08);color:#818CF8;font-size:12px;font-weight:700;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:all 0.15s;padding:0;line-height:1;font-family:system-ui,sans-serif;" onmouseover="this.style.background='rgba(99,102,241,0.2)';this.style.borderColor='#818CF8';this.style.color='#A5B4FC'" onmouseout="this.style.background='rgba(99,102,241,0.08)';this.style.borderColor='#52525B';this.style.color='#818CF8'" title="Click for help">?</button>
                                </div>
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
                                    <label style="display: flex; align-items: center; gap: 8px; padding: 12px; background: rgba(0, 168, 255, 0.15); border: 1px solid rgba(0, 168, 255, 0.4); border-radius: 8px; cursor: pointer; transition: all 0.2s;" onmouseover="this.style.borderColor='#00a8ff'" onmouseout="this.style.borderColor='rgba(0, 168, 255, 0.4)'">
                                        <input type="checkbox" id="broker-WEBULL_OFFICIAL-${channel.id}" value="WEBULL_OFFICIAL" style="width: 18px; height: 18px; cursor: pointer;" ${getBrokerChecked(channel.enabled_brokers, 'WEBULL_OFFICIAL')}>
                                        <div>
                                            <div style="font-weight: 600; color: #00a8ff; font-size: 13px;">🌐 Webull Official API</div>
                                            <div style="font-size: 11px; color: #8E8E93;">v2 REST API (stocks + options)</div>
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
                                        <button type="button" class="risk-preset-btn-${channel.id}" onclick="applyRiskPreset('${channel.id}', 'default')" style="padding: 6px 14px; border-radius: 8px; border: 1px solid #52525B; background: #27272A; color: #E4E4E7; font-size: 12px; font-weight: 500; cursor: pointer; transition: all 0.15s;" onmouseover="this.style.background='#3F3F46';this.style.borderColor='#71717A'" onmouseout="this.style.background='#27272A';this.style.borderColor='#52525B'">Default</button>
                                        <button type="button" class="risk-preset-btn-${channel.id}" onclick="applyRiskPreset('${channel.id}', 'swing')" style="padding: 6px 14px; border-radius: 8px; border: 1px solid #52525B; background: #27272A; color: #E4E4E7; font-size: 12px; font-weight: 500; cursor: pointer; transition: all 0.15s;" onmouseover="this.style.background='#3F3F46';this.style.borderColor='#71717A'" onmouseout="this.style.background='#27272A';this.style.borderColor='#52525B'">Swing</button>
                                        <button type="button" class="risk-preset-btn-${channel.id}" onclick="applyRiskPreset('${channel.id}', 'momentum')" style="padding: 6px 14px; border-radius: 8px; border: 1px solid #52525B; background: #27272A; color: #E4E4E7; font-size: 12px; font-weight: 500; cursor: pointer; transition: all 0.15s;" onmouseover="this.style.background='#3F3F46';this.style.borderColor='#71717A'" onmouseout="this.style.background='#27272A';this.style.borderColor='#52525B'">Momentum</button>
                                        <button type="button" class="risk-preset-btn-${channel.id}" onclick="applyRiskPreset('${channel.id}', 'trend')" style="padding: 6px 14px; border-radius: 8px; border: 1px solid #52525B; background: #27272A; color: #E4E4E7; font-size: 12px; font-weight: 500; cursor: pointer; transition: all 0.15s;" onmouseover="this.style.background='#3F3F46';this.style.borderColor='#71717A'" onmouseout="this.style.background='#27272A';this.style.borderColor='#52525B'">Trend</button>
                                    </div>
                                </div>
                                <div id="risk-validation-${channel.id}" style="display: none; margin-bottom: 12px; padding: 8px 12px; background: rgba(239,68,68,0.08); border-radius: 8px; border-left: 3px solid #EF4444;">
                                    <p id="risk-validation-msg-${channel.id}" style="color: #EF4444; margin: 0; font-size: 11px;"></p>
                                </div>
                                <div style="display: flex; gap: 0; margin-bottom: 14px; border-bottom: 2px solid #27272A; padding-bottom: 0;">
                                    <button type="button" class="risk-tab-btn-${channel.id}" data-risk-tab="targets" onclick="switchRiskTab('${channel.id}', 'targets')" style="padding: 10px 20px; background: none; border: none; border-bottom: 3px solid #22D3EE; color: #F4F4F5; font-size: 13px; font-weight: 600; cursor: pointer; margin-bottom: -2px; transition: all 0.15s;">Targets & SL</button>
                                    <button type="button" class="risk-tab-btn-${channel.id}" data-risk-tab="advanced" onclick="switchRiskTab('${channel.id}', 'advanced')" style="padding: 10px 20px; background: none; border: none; border-bottom: 3px solid transparent; color: #A1A1AA; font-size: 13px; font-weight: 600; cursor: pointer; margin-bottom: -2px; transition: all 0.15s;">Advanced</button>
                                </div>

                                <!-- TAB 1: Targets & SL -->
                                <div id="risk-tab-targets-${channel.id}" style="display: block;">
                                <div style="display:flex;align-items:center;justify-content:space-between;margin:0 0 10px;">
                                    <h5 style="margin:0;color:#00d4ff;font-size:12px;">📊 Profit Targets</h5>
                                    <button type="button" onclick="showRiskHelp('profit-targets')" style="width:22px;height:22px;border-radius:50%;border:1.5px solid #52525B;background:rgba(99,102,241,0.08);color:#818CF8;font-size:12px;font-weight:700;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:all 0.15s;padding:0;line-height:1;font-family:system-ui,sans-serif;" onmouseover="this.style.background='rgba(99,102,241,0.2)';this.style.borderColor='#818CF8';this.style.color='#A5B4FC'" onmouseout="this.style.background='rgba(99,102,241,0.08)';this.style.borderColor='#52525B';this.style.color='#818CF8'" title="Click for help">?</button>
                                </div>
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
                                <div style="margin-top: 12px; padding: 12px; background: rgba(234, 179, 8, 0.05); border: 1px solid rgba(234, 179, 8, 0.2); border-radius: 8px;">
                                    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
                                        <label style="display: block; font-size: 12px; font-weight: 600; color: #eab308;">Custom Trim Percentages (optional)</label>
                                        <button type="button" onclick="showRiskHelp('custom-trim')" style="width:22px;height:22px;border-radius:50%;border:1.5px solid #52525B;background:rgba(99,102,241,0.08);color:#818CF8;font-size:12px;font-weight:700;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:all 0.15s;padding:0;line-height:1;font-family:system-ui,sans-serif;" onmouseover="this.style.background='rgba(99,102,241,0.2)';this.style.borderColor='#818CF8';this.style.color='#A5B4FC'" onmouseout="this.style.background='rgba(99,102,241,0.08)';this.style.borderColor='#52525B';this.style.color='#818CF8'" title="Click for help">?</button>
                                    </div>
                                    <p style="font-size: 11px; color: #8E8E93; margin: 0 0 8px 0;">Specify % of position to trim at each target. Set 0 for escalation-only (mark tier, no sell). Leave empty for auto-split.</p>
                                    <div style="display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 12px;">
                                        <div><label style="display: block; font-size: 10px; color: #8E8E93; margin-bottom: 4px;">P1 Trim %</label><input type="number" id="risk-trim-pct-1-${channel.id}" value="${channel.profit_target_trim_pct_1 != null ? channel.profit_target_trim_pct_1 : ''}" placeholder="Auto" step="1" min="0" max="100" style="width: 100%; padding: 6px 10px; font-size: 12px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;"></div>
                                        <div><label style="display: block; font-size: 10px; color: #8E8E93; margin-bottom: 4px;">P2 Trim %</label><input type="number" id="risk-trim-pct-2-${channel.id}" value="${channel.profit_target_trim_pct_2 != null ? channel.profit_target_trim_pct_2 : ''}" placeholder="Auto" step="1" min="0" max="100" style="width: 100%; padding: 6px 10px; font-size: 12px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;"></div>
                                        <div><label style="display: block; font-size: 10px; color: #8E8E93; margin-bottom: 4px;">P3 Trim %</label><input type="number" id="risk-trim-pct-3-${channel.id}" value="${channel.profit_target_trim_pct_3 != null ? channel.profit_target_trim_pct_3 : ''}" placeholder="Auto" step="1" min="0" max="100" style="width: 100%; padding: 6px 10px; font-size: 12px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;"></div>
                                        <div><label style="display: block; font-size: 10px; color: #8E8E93; margin-bottom: 4px;">P4 Trim %</label><input type="number" id="risk-trim-pct-4-${channel.id}" value="${channel.profit_target_trim_pct_4 != null ? channel.profit_target_trim_pct_4 : ''}" placeholder="Auto" step="1" min="0" max="100" style="width: 100%; padding: 6px 10px; font-size: 12px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;"></div>
                                    </div>
                                </div>
                                <div style="display:flex;align-items:center;justify-content:space-between;margin:16px 0 10px;">
                                    <h5 style="margin:0;color:#EF4444;font-size:12px;">🛑 Stop Loss & Trailing</h5>
                                    <button type="button" onclick="showRiskHelp('stop-loss-trailing')" style="width:22px;height:22px;border-radius:50%;border:1.5px solid #52525B;background:rgba(99,102,241,0.08);color:#818CF8;font-size:12px;font-weight:700;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:all 0.15s;padding:0;line-height:1;font-family:system-ui,sans-serif;" onmouseover="this.style.background='rgba(99,102,241,0.2)';this.style.borderColor='#818CF8';this.style.color='#A5B4FC'" onmouseout="this.style.background='rgba(99,102,241,0.08)';this.style.borderColor='#52525B';this.style.color='#818CF8'" title="Click for help">?</button>
                                </div>
                                <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px;">
                                    <div><label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Stop Loss %</label><input type="number" id="risk-stop-loss-${channel.id}" value="${channel.stop_loss_pct || ''}" placeholder="Leave empty for default" step="0.01" min="0" max="100" style="width: 100%; padding: 8px 12px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;"></div>
                                    <div><label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Trailing Stop % <span id="trailing-disabled-note-${channel.id}" style="color: #ff6b6b; font-size: 10px; display: ${channel.enable_early_trailing ? 'inline' : 'none'};">(disabled - Early Trailing active)</span></label><input type="number" id="risk-trailing-stop-${channel.id}" value="${channel.trailing_stop_pct || ''}" placeholder="${channel.enable_early_trailing ? 'Disabled' : 'Leave empty for default'}" step="0.01" min="0" max="100" ${channel.enable_early_trailing ? 'disabled' : ''} style="width: 100%; padding: 8px 12px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: ${channel.enable_early_trailing ? '#2A2A2C' : '#1C1C1E'}; color: ${channel.enable_early_trailing ? '#666' : 'white'}; opacity: ${channel.enable_early_trailing ? '0.6' : '1'};"></div>
                                    <div><label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Trailing Activation %</label><input type="number" id="risk-trailing-activation-${channel.id}" value="${channel.trailing_activation_pct || ''}" placeholder="${channel.enable_early_trailing ? 'Disabled' : 'Leave empty for default'}" step="0.01" min="0" max="500" ${channel.enable_early_trailing ? 'disabled' : ''} style="width: 100%; padding: 8px 12px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: ${channel.enable_early_trailing ? '#2A2A2C' : '#1C1C1E'}; color: ${channel.enable_early_trailing ? '#666' : 'white'}; opacity: ${channel.enable_early_trailing ? '0.6' : '1'};"></div>
                                </div>
                                <div style="display:flex;align-items:center;justify-content:space-between;margin:16px 0 10px;">
                                    <h5 style="margin:0;color:#10B981;font-size:12px;">🎯 Exit Strategy Mode</h5>
                                    <button type="button" onclick="showRiskHelp('exit-strategy')" style="width:22px;height:22px;border-radius:50%;border:1.5px solid #52525B;background:rgba(99,102,241,0.08);color:#818CF8;font-size:12px;font-weight:700;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:all 0.15s;padding:0;line-height:1;font-family:system-ui,sans-serif;" onmouseover="this.style.background='rgba(99,102,241,0.2)';this.style.borderColor='#818CF8';this.style.color='#A5B4FC'" onmouseout="this.style.background='rgba(99,102,241,0.08)';this.style.borderColor='#52525B';this.style.color='#818CF8'" title="Click for help">?</button>
                                </div>
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
                                <div style="margin-top: 12px; padding: 12px; background: rgba(124, 58, 237, 0.05); border: 1px solid rgba(124, 58, 237, 0.2); border-radius: 8px;">
                                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                                        <div style="display: flex; align-items: center; gap: 8px;">
                                            <span style="font-size: 16px;">🔄</span>
                                            <label style="font-size: 13px; font-weight: 600; color: #a78bfa;">Order Chase</label>
                                        </div>
                                        <div style="display:flex;align-items:center;gap:8px;">
                                            <button type="button" onclick="showRiskHelp('order-chase')" style="width:22px;height:22px;border-radius:50%;border:1.5px solid #52525B;background:rgba(99,102,241,0.08);color:#818CF8;font-size:12px;font-weight:700;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:all 0.15s;padding:0;line-height:1;font-family:system-ui,sans-serif;" onmouseover="this.style.background='rgba(99,102,241,0.2)';this.style.borderColor='#818CF8';this.style.color='#A5B4FC'" onmouseout="this.style.background='rgba(99,102,241,0.08)';this.style.borderColor='#52525B';this.style.color='#818CF8'" title="Click for help">?</button>
                                            <select id="risk-chase-mode-${channel.id}" style="width: 130px; padding: 4px 8px; font-size: 12px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;">
                                                <option value="off" ${!channel.entry_chase_enabled && !channel.order_chase_enabled ? 'selected' : ''}>Off</option>
                                                <option value="entry" ${channel.entry_chase_enabled === 1 && channel.order_chase_enabled !== 1 ? 'selected' : ''}>Entry Only</option>
                                                <option value="exit" ${channel.order_chase_enabled === 1 && channel.entry_chase_enabled !== 1 ? 'selected' : ''}>Exit Only</option>
                                                <option value="both" ${channel.entry_chase_enabled === 1 && channel.order_chase_enabled === 1 ? 'selected' : ''}>Both</option>
                                            </select>
                                            <input type="checkbox" id="risk-order-chase-${channel.id}" style="display:none;" ${channel.order_chase_enabled === 1 || channel.entry_chase_enabled === 1 ? 'checked' : ''}>
                                        </div>
                                    </div>
                                    <p style="font-size: 11px; color: #8E8E93; margin: 0;">Chase unfilled orders with mid-price replacement for better fills.</p>
                                </div>
                                <div style="margin-top: 12px; padding: 12px; background: rgba(0, 255, 136, 0.05); border: 1px solid rgba(0, 255, 136, 0.2); border-radius: 8px;">
                                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                                        <div style="display: flex; align-items: center; gap: 8px;">
                                            <span style="font-size: 16px;">🏃</span>
                                            <label style="font-size: 13px; font-weight: 600; color: #00ff88;">Leave Runner</label>
                                        </div>
                                        <div style="display:flex;align-items:center;gap:8px;">
                                            <button type="button" onclick="showRiskHelp('leave-runner')" style="width:22px;height:22px;border-radius:50%;border:1.5px solid #52525B;background:rgba(99,102,241,0.08);color:#818CF8;font-size:12px;font-weight:700;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:all 0.15s;padding:0;line-height:1;font-family:system-ui,sans-serif;" onmouseover="this.style.background='rgba(99,102,241,0.2)';this.style.borderColor='#818CF8';this.style.color='#A5B4FC'" onmouseout="this.style.background='rgba(99,102,241,0.08)';this.style.borderColor='#52525B';this.style.color='#818CF8'" title="Click for help">?</button>
                                            <label class="toggle-switch" title="Keep a portion of your position to ride further gains">
                                                <input type="checkbox" id="risk-leave-runner-enabled-${channel.id}" ${channel.leave_runner_enabled ? 'checked' : ''}>
                                                <span class="toggle-slider"></span>
                                            </label>
                                        </div>
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
                                <div style="padding: 12px; background: rgba(0, 188, 212, 0.05); border: 1px solid rgba(0, 188, 212, 0.2); border-radius: 8px;">
                                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                                        <div style="display: flex; align-items: center; gap: 8px;">
                                            <span style="font-size: 16px;">📋</span>
                                            <label style="font-size: 13px; font-weight: 600; color: #00BCD4;">Broker Bracket Orders</label>
                                        </div>
                                        <button type="button" onclick="showRiskHelp('broker-bracket-mode')" style="width:22px;height:22px;border-radius:50%;border:1.5px solid #52525B;background:rgba(0,188,212,0.08);color:#00BCD4;font-size:12px;font-weight:700;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:all 0.15s;padding:0;line-height:1;font-family:system-ui,sans-serif;" onmouseover="this.style.background='rgba(0,188,212,0.2)';this.style.borderColor='#00BCD4';this.style.color='#4DD0E1'" onmouseout="this.style.background='rgba(0,188,212,0.08)';this.style.borderColor='#52525B';this.style.color='#00BCD4'" title="Click for help">?</button>
                                    </div>
                                    <div style="display: flex; gap: 12px; align-items: center; flex-wrap: wrap;">
                                        <label style="display: flex; align-items: center; gap: 5px; cursor: pointer;">
                                            <input type="radio" name="broker-bracket-mode-${channel.id}" value="both" ${(channel.broker_bracket_mode || 'none') === 'both' ? 'checked' : ''} style="cursor: pointer;" onchange="handleBracketModeChange('${channel.id}', this.value)">
                                            <span style="font-size: 12px; color: white;">Both</span>
                                        </label>
                                        <label style="display: flex; align-items: center; gap: 5px; cursor: pointer;">
                                            <input type="radio" name="broker-bracket-mode-${channel.id}" value="sl_only" ${channel.broker_bracket_mode === 'sl_only' ? 'checked' : ''} style="cursor: pointer;" onchange="handleBracketModeChange('${channel.id}', this.value)">
                                            <span style="font-size: 12px; color: white;">SL Only</span>
                                        </label>
                                        <label style="display: flex; align-items: center; gap: 5px; cursor: pointer;">
                                            <input type="radio" name="broker-bracket-mode-${channel.id}" value="pt_only" ${channel.broker_bracket_mode === 'pt_only' ? 'checked' : ''} style="cursor: pointer;" onchange="handleBracketModeChange('${channel.id}', this.value)">
                                            <span style="font-size: 12px; color: white;">PT Only</span>
                                        </label>
                                        <label style="display: flex; align-items: center; gap: 5px; cursor: pointer;">
                                            <input type="radio" name="broker-bracket-mode-${channel.id}" value="none" ${(channel.broker_bracket_mode || 'none') === 'none' ? 'checked' : ''} style="cursor: pointer;" onchange="handleBracketModeChange('${channel.id}', this.value)">
                                            <span style="font-size: 12px; color: white;">Disabled</span>
                                        </label>
                                    </div>
                                    <p style="font-size: 11px; color: #8E8E93; margin: 6px 0 0 0;">Which bracket orders to place on the broker. Risk engine always monitors regardless.</p>
                                </div>
                                <div style="margin-top: 12px; padding: 10px 12px; background: rgba(99,102,241,0.06); border: 1px solid rgba(99,102,241,0.15); border-radius: 8px; font-size: 11px; color: #A5B4FC;">
                                    Order type settings (Trim & SL) are in <strong>Channels → Order Types</strong> tab.
                                </div>
                                <div style="margin-top: 12px; padding: 12px; background: rgba(0, 200, 150, 0.05); border: 1px solid rgba(0, 200, 150, 0.2); border-radius: 8px;">
                                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                                        <div style="display: flex; align-items: center; gap: 8px;">
                                            <span style="font-size: 16px;">🔒</span>
                                            <label style="font-size: 13px; font-weight: 600; color: #00c896;">Early Trailing Stop</label>
                                        </div>
                                        <div style="display:flex;align-items:center;gap:8px;">
                                            <button type="button" onclick="showRiskHelp('early-trailing')" style="width:22px;height:22px;border-radius:50%;border:1.5px solid #52525B;background:rgba(99,102,241,0.08);color:#818CF8;font-size:12px;font-weight:700;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:all 0.15s;padding:0;line-height:1;font-family:system-ui,sans-serif;" onmouseover="this.style.background='rgba(99,102,241,0.2)';this.style.borderColor='#818CF8';this.style.color='#A5B4FC'" onmouseout="this.style.background='rgba(99,102,241,0.08)';this.style.borderColor='#52525B';this.style.color='#818CF8'" title="Click for help">?</button>
                                            <label class="toggle-switch" title="Move to breakeven after X% gain, then lock profit in steps">
                                                <input type="checkbox" id="risk-early-trailing-${channel.id}" ${channel.enable_early_trailing ? 'checked' : ''} onchange="toggleEarlyTrailingExclusion('${channel.id}', this.checked)">
                                                <span class="toggle-slider"></span>
                                            </label>
                                        </div>
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
                                <div style="margin-top: 12px; padding: 12px; background: rgba(255, 100, 100, 0.05); border: 1px solid rgba(255, 100, 100, 0.2); border-radius: 8px;">
                                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                                        <div style="display: flex; align-items: center; gap: 8px;">
                                            <span style="font-size: 16px;">🎯</span>
                                            <label style="font-size: 13px; font-weight: 600; color: #ff6b6b;">Dynamic Stop Loss Escalation</label>
                                        </div>
                                        <div style="display:flex;align-items:center;gap:8px;">
                                            <button type="button" onclick="showRiskHelp('dynamic-sl')" style="width:22px;height:22px;border-radius:50%;border:1.5px solid #52525B;background:rgba(99,102,241,0.08);color:#818CF8;font-size:12px;font-weight:700;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:all 0.15s;padding:0;line-height:1;font-family:system-ui,sans-serif;" onmouseover="this.style.background='rgba(99,102,241,0.2)';this.style.borderColor='#818CF8';this.style.color='#A5B4FC'" onmouseout="this.style.background='rgba(99,102,241,0.08)';this.style.borderColor='#52525B';this.style.color='#818CF8'" title="Click for help">?</button>
                                            <label class="toggle-switch" title="Automatically move stop loss after hitting profit targets">
                                                <input type="checkbox" id="risk-dynamic-sl-${channel.id}" ${channel.enable_dynamic_sl ? 'checked' : ''}>
                                                <span class="toggle-slider"></span>
                                            </label>
                                        </div>
                                    </div>
                                    <p style="font-size: 11px; color: #8E8E93; margin: 0 0 6px 0;">Each time you hit a profit target, your stop loss moves UP to lock in more gains.</p>
                                    <div style="display: flex; align-items: center; gap: 12px;">
                                        <label style="font-size: 11px; color: #8E8E93; white-space: nowrap;">Profile:</label>
                                        <select id="risk-dynamic-sl-profile-${channel.id}" style="padding: 6px 10px; font-size: 12px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white;">
                                            <option value="conservative" ${channel.dynamic_sl_profile === 'conservative' ? 'selected' : ''}>Conservative (PT1: BE, PT2: +3%, PT3: +8%, PT4: +15%)</option>
                                            <option value="standard" ${!channel.dynamic_sl_profile || channel.dynamic_sl_profile === 'standard' ? 'selected' : ''}>Standard (PT1: BE, PT2: +5%, PT3: +10%, PT4: +17%)</option>
                                            <option value="aggressive" ${channel.dynamic_sl_profile === 'aggressive' ? 'selected' : ''}>Aggressive (PT1: -2%, PT2: BE, PT3: +8%, PT4: +15%)</option>
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
                                        <div style="display:flex;align-items:center;gap:8px;">
                                            <button type="button" onclick="showRiskHelp('giveback-guard')" style="width:22px;height:22px;border-radius:50%;border:1.5px solid #52525B;background:rgba(99,102,241,0.08);color:#818CF8;font-size:12px;font-weight:700;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:all 0.15s;padding:0;line-height:1;font-family:system-ui,sans-serif;" onmouseover="this.style.background='rgba(99,102,241,0.2)';this.style.borderColor='#818CF8';this.style.color='#A5B4FC'" onmouseout="this.style.background='rgba(99,102,241,0.08)';this.style.borderColor='#52525B';this.style.color='#818CF8'" title="Click for help">?</button>
                                            <label class="toggle-switch" title="Exit if profit drops too much from peak">
                                                <input type="checkbox" id="risk-giveback-guard-${channel.id}" ${channel.enable_giveback_guard ? 'checked' : ''}>
                                                <span class="toggle-slider"></span>
                                            </label>
                                        </div>
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
                                        <div style="display:flex;align-items:center;gap:8px;">
                                            <button type="button" onclick="showRiskHelp('ema-risk')" style="width:22px;height:22px;border-radius:50%;border:1.5px solid #52525B;background:rgba(99,102,241,0.08);color:#818CF8;font-size:12px;font-weight:700;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:all 0.15s;padding:0;line-height:1;font-family:system-ui,sans-serif;" onmouseover="this.style.background='rgba(99,102,241,0.2)';this.style.borderColor='#818CF8';this.style.color='#A5B4FC'" onmouseout="this.style.background='rgba(99,102,241,0.08)';this.style.borderColor='#52525B';this.style.color='#818CF8'" title="Click for help">?</button>
                                            <label class="toggle-switch" title="Monitor EMA crossovers for exit/escalation signals">
                                                <input type="checkbox" id="risk-ema-enabled-${channel.id}" ${channel.ema_risk_enabled ? 'checked' : ''} onchange="document.getElementById('ema-settings-grid-${channel.id}').style.display = this.checked ? 'block' : 'none';">
                                                <span class="toggle-slider"></span>
                                            </label>
                                        </div>
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
                                <div style="margin-top: 12px; padding: 12px; background: rgba(52,211,153,0.05); border: 1px solid rgba(52,211,153,0.2); border-radius: 8px;">
                                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                                        <div style="display: flex; align-items: center; gap: 8px;">
                                            <span style="font-size: 16px;">🎯</span>
                                            <label style="font-size: 13px; font-weight: 600; color: #34d399;">PT Near-Lock</label>
                                        </div>
                                        <div style="display:flex;align-items:center;gap:8px;">
                                            <button type="button" onclick="showRiskHelp('pt-near-lock')" style="width:22px;height:22px;border-radius:50%;border:1.5px solid #52525B;background:rgba(99,102,241,0.08);color:#818CF8;font-size:12px;font-weight:700;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:all 0.15s;padding:0;line-height:1;font-family:system-ui,sans-serif;" onmouseover="this.style.background='rgba(99,102,241,0.2)';this.style.borderColor='#818CF8';this.style.color='#A5B4FC'" onmouseout="this.style.background='rgba(99,102,241,0.08)';this.style.borderColor='#52525B';this.style.color='#818CF8'" title="Click for help">?</button>
                                            <label class="toggle-switch" title="Protect profit when price approaches but hasn't hit a target">
                                                <input type="checkbox" id="risk-pt-near-lock-${channel.id}" ${channel.enable_pt_near_lock ? 'checked' : ''} onchange="document.getElementById('pt-near-lock-settings-${channel.id}').style.display=this.checked?'block':'none'">
                                                <span class="toggle-slider"></span>
                                            </label>
                                        </div>
                                    </div>
                                    <p style="font-size: 11px; color: #8E8E93; margin: 0 0 8px 0;">Activates a tight trailing stop when price approaches but hasn't hit a profit target — captures gains on near-misses (e.g. +8% when PT1=10%).</p>
                                    <div id="pt-near-lock-settings-${channel.id}" style="display: ${channel.enable_pt_near_lock ? 'block' : 'none'};">
                                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 10px;">
                                            <div>
                                                <label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Lock Threshold % of PT</label>
                                                <input type="number" id="risk-pt-near-threshold-${channel.id}" value="${channel.pt_near_lock_threshold_pct != null ? channel.pt_near_lock_threshold_pct : 80}" placeholder="80" step="1" min="1" max="99" style="width: 100%; padding: 6px 10px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white; text-align: center;">
                                                <p style="font-size: 10px; color: #666; margin: 3px 0 0 0;">Activate at 80% = locks when +8% toward PT1=10%</p>
                                            </div>
                                            <div>
                                                <label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Trail From High %</label>
                                                <input type="number" id="risk-pt-near-trail-${channel.id}" value="${channel.pt_near_lock_trail_pct != null ? channel.pt_near_lock_trail_pct : 3}" placeholder="3" step="0.5" min="0.5" max="20" style="width: 100%; padding: 6px 10px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white; text-align: center;">
                                                <p style="font-size: 10px; color: #666; margin: 3px 0 0 0;">Tight trail distance from the highest price</p>
                                            </div>
                                        </div>
                                        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
                                            <label class="toggle-switch"><input type="checkbox" id="risk-pt-near-soft-${channel.id}" ${channel.pt_near_lock_soft_exit ? 'checked' : ''} onchange="document.getElementById('pt-near-soft-settings-${channel.id}').style.display=this.checked?'grid':'none'"><span class="toggle-slider"></span></label>
                                            <label style="font-size: 11px; color: #8E8E93;">Auto Partial Trim at Soft Threshold (one-time)</label>
                                        </div>
                                        <div id="pt-near-soft-settings-${channel.id}" style="display: ${channel.pt_near_lock_soft_exit ? 'grid' : 'none'}; grid-template-columns: 1fr 1fr; gap: 12px;">
                                            <div>
                                                <label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Soft Threshold % of PT</label>
                                                <input type="number" id="risk-pt-near-soft-threshold-${channel.id}" value="${channel.pt_near_lock_soft_threshold_pct != null ? channel.pt_near_lock_soft_threshold_pct : 90}" placeholder="90" step="1" min="1" max="100" style="width: 100%; padding: 6px 10px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white; text-align: center;">
                                            </div>
                                            <div>
                                                <label style="display: block; font-size: 11px; color: #8E8E93; margin-bottom: 4px;">Trim Size % of Position</label>
                                                <input type="number" id="risk-pt-near-soft-trim-${channel.id}" value="${channel.pt_near_lock_soft_trim_pct != null ? channel.pt_near_lock_soft_trim_pct : 25}" placeholder="25" step="5" min="5" max="75" style="width: 100%; padding: 6px 10px; font-size: 13px; border: 1px solid #3A3A3C; border-radius: 6px; background: #1C1C1E; color: white; text-align: center;">
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
                                    <button type="button" onclick="showRiskHelp('ticker-filter')" style="width:22px;height:22px;border-radius:50%;border:1.5px solid #52525B;background:rgba(99,102,241,0.08);color:#818CF8;font-size:12px;font-weight:700;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:all 0.15s;padding:0;line-height:1;font-family:system-ui,sans-serif;" onmouseover="this.style.background='rgba(99,102,241,0.2)';this.style.borderColor='#818CF8';this.style.color='#A5B4FC'" onmouseout="this.style.background='rgba(99,102,241,0.08)';this.style.borderColor='#52525B';this.style.color='#818CF8'" title="Click for help">?</button>
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
                                    <div style="display:flex;align-items:center;gap:8px;">
                                    <button type="button" onclick="showRiskHelp('paper-trading')" style="width:22px;height:22px;border-radius:50%;border:1.5px solid #52525B;background:rgba(99,102,241,0.08);color:#818CF8;font-size:12px;font-weight:700;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:all 0.15s;padding:0;line-height:1;font-family:system-ui,sans-serif;" onmouseover="this.style.background='rgba(99,102,241,0.2)';this.style.borderColor='#818CF8';this.style.color='#A5B4FC'" onmouseout="this.style.background='rgba(99,102,241,0.08)';this.style.borderColor='#52525B';this.style.color='#818CF8'" title="Click for help">?</button>
                                    <label class="toggle-switch">
                                        <input type="checkbox" id="paper-trade-${channel.id}" ${channel.paper_trade_enabled ? 'checked' : ''} onchange="togglePaperTrade('${channel.id}')">
                                        <span class="toggle-slider"></span>
                                    </label>
                                    </div>
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
                        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
                        <h4 style="margin: 0; font-size: 14px; color: var(--primary-blue);">👥 Allowed Users (Signal Filtering)</h4>
                        <button type="button" onclick="showRiskHelp('allowed-users')" style="width:22px;height:22px;border-radius:50%;border:1.5px solid #52525B;background:rgba(99,102,241,0.08);color:#818CF8;font-size:12px;font-weight:700;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:all 0.15s;padding:0;line-height:1;font-family:system-ui,sans-serif;" onmouseover="this.style.background='rgba(99,102,241,0.2)';this.style.borderColor='#818CF8';this.style.color='#A5B4FC'" onmouseout="this.style.background='rgba(99,102,241,0.08)';this.style.borderColor='#52525B';this.style.color='#818CF8'" title="Click for help">?</button>
                        </div>
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

function handleBracketModeChange(channelId, mode) {
    const ptEnabled = (mode === 'both' || mode === 'pt_only');
    const trimMarketLabel = document.getElementById(`trim-market-label-${channelId}`);
    const trimMarketRadio = document.querySelector(`input[name="trim-order-mode-${channelId}"][value="market"]`);
    const trimLimitRadio = document.querySelector(`input[name="trim-order-mode-${channelId}"][value="limit"]`);
    const autoNote = document.getElementById(`bracket-trim-auto-note-${channelId}`);
    const limitContainer = document.getElementById(`limit-offset-container-${channelId}`);

    if (ptEnabled) {
        if (trimMarketRadio) { trimMarketRadio.disabled = true; trimMarketRadio.checked = false; }
        if (trimLimitRadio) trimLimitRadio.checked = true;
        if (trimMarketLabel) { trimMarketLabel.style.opacity = '0.4'; trimMarketLabel.style.pointerEvents = 'none'; }
        if (autoNote) autoNote.style.display = 'block';
        if (limitContainer) limitContainer.style.display = 'flex';
    } else {
        if (trimMarketRadio) trimMarketRadio.disabled = false;
        if (trimMarketLabel) { trimMarketLabel.style.opacity = '1'; trimMarketLabel.style.pointerEvents = 'auto'; }
        if (autoNote) autoNote.style.display = 'none';
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

function handleBracketModeChange(channelId, mode) {
    const ptEnabled = (mode === 'both' || mode === 'pt_only');
    const trimMarketLabel = document.getElementById(`trim-market-label-${channelId}`);
    const trimMarketRadio = document.querySelector(`input[name="trim-order-mode-${channelId}"][value="market"]`);
    const trimLimitRadio = document.querySelector(`input[name="trim-order-mode-${channelId}"][value="limit"]`);
    const autoNote = document.getElementById(`bracket-trim-auto-note-${channelId}`);
    const limitContainer = document.getElementById(`limit-offset-container-${channelId}`);

    if (ptEnabled) {
        if (trimMarketRadio) { trimMarketRadio.disabled = true; trimMarketRadio.checked = false; }
        if (trimLimitRadio) trimLimitRadio.checked = true;
        if (trimMarketLabel) { trimMarketLabel.style.opacity = '0.4'; trimMarketLabel.style.pointerEvents = 'none'; }
        if (autoNote) autoNote.style.display = 'block';
        if (limitContainer) limitContainer.style.display = 'flex';
    } else {
        if (trimMarketRadio) trimMarketRadio.disabled = false;
        if (trimMarketLabel) { trimMarketLabel.style.opacity = '1'; trimMarketLabel.style.pointerEvents = 'auto'; }
        if (autoNote) autoNote.style.display = 'none';
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
        const trimPct1 = document.getElementById(`risk-trim-pct-1-${channelId}`).value;
        const trimPct2 = document.getElementById(`risk-trim-pct-2-${channelId}`).value;
        const trimPct3 = document.getElementById(`risk-trim-pct-3-${channelId}`).value;
        const trimPct4 = document.getElementById(`risk-trim-pct-4-${channelId}`).value;
        const stopLoss = document.getElementById(`risk-stop-loss-${channelId}`).value;
        const trailingStop = document.getElementById(`risk-trailing-stop-${channelId}`).value;
        const trailingActivation = document.getElementById(`risk-trailing-activation-${channelId}`).value;
        const leaveRunnerEnabled = document.getElementById(`risk-leave-runner-enabled-${channelId}`)?.checked ? 1 : 0;
        const leaveRunnerPct = document.getElementById(`risk-leave-runner-pct-${channelId}`).value;
        const brokerBracketMode = document.querySelector(`input[name="broker-bracket-mode-${channelId}"]:checked`)?.value || 'both';
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

        // PT Near-Lock settings
        const enablePtNearLock = document.getElementById(`risk-pt-near-lock-${channelId}`)?.checked ? 1 : 0;
        const ptNearLockThreshold = document.getElementById(`risk-pt-near-threshold-${channelId}`)?.value;
        const ptNearLockTrail = document.getElementById(`risk-pt-near-trail-${channelId}`)?.value;
        const ptNearLockSoftExit = document.getElementById(`risk-pt-near-soft-${channelId}`)?.checked ? 1 : 0;
        const ptNearLockSoftThreshold = document.getElementById(`risk-pt-near-soft-threshold-${channelId}`)?.value;
        const ptNearLockSoftTrim = document.getElementById(`risk-pt-near-soft-trim-${channelId}`)?.value;

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
                profit_target_trim_pct_1: trimPct1 !== '' && trimPct1 !== null && trimPct1 !== undefined ? parseFloat(trimPct1) : null,
                profit_target_trim_pct_2: trimPct2 !== '' && trimPct2 !== null && trimPct2 !== undefined ? parseFloat(trimPct2) : null,
                profit_target_trim_pct_3: trimPct3 !== '' && trimPct3 !== null && trimPct3 !== undefined ? parseFloat(trimPct3) : null,
                profit_target_trim_pct_4: trimPct4 !== '' && trimPct4 !== null && trimPct4 !== undefined ? parseFloat(trimPct4) : null,
                stop_loss_pct: stopLoss ? parseFloat(stopLoss) : null,
                trailing_stop_pct: trailingStop ? parseFloat(trailingStop) : null,
                trailing_activation_pct: trailingActivation ? parseFloat(trailingActivation) : null,
                leave_runner_enabled: leaveRunnerEnabled,
                leave_runner_pct: leaveRunnerPct ? parseFloat(leaveRunnerPct) : 25.0,
                trade_summary_enabled: tradeSummaryEnabled,
                enable_dynamic_sl: enableDynamicSl,
                dynamic_sl_profile: dynamicSlProfile,
                enable_giveback_guard: enableGivebackGuard,
                giveback_allowed_pct: givebackAllowedPct ? parseFloat(givebackAllowedPct) : 30.0,
                enable_early_trailing: enableEarlyTrailing,
                early_trailing_activation_pct: earlyTrailingActivationPct ? parseFloat(earlyTrailingActivationPct) : 5.0,
                early_trailing_step_pct: earlyTrailingStepPct ? parseFloat(earlyTrailingStepPct) : 3.0,
                enable_pt_near_lock: enablePtNearLock,
                pt_near_lock_threshold_pct: ptNearLockThreshold ? parseFloat(ptNearLockThreshold) : 80.0,
                pt_near_lock_trail_pct: ptNearLockTrail ? parseFloat(ptNearLockTrail) : 3.0,
                pt_near_lock_soft_exit: ptNearLockSoftExit,
                pt_near_lock_soft_threshold_pct: ptNearLockSoftThreshold ? parseFloat(ptNearLockSoftThreshold) : 90.0,
                pt_near_lock_soft_trim_pct: ptNearLockSoftTrim ? parseFloat(ptNearLockSoftTrim) : 25.0,
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
                broker_bracket_mode: brokerBracketMode,
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
        b.style.color = '#A1A1AA';
    });
    ['targets', 'advanced'].forEach(t => {
        const pane = document.getElementById(`risk-tab-${t}-${channelId}`);
        if (pane) pane.style.display = 'none';
    });
    const activeBtn = document.querySelector(`.risk-tab-btn-${channelId}[data-risk-tab="${tabName}"]`);
    if (activeBtn) {
        activeBtn.style.borderBottomColor = '#22D3EE';
        activeBtn.style.color = '#F4F4F5';
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
        default: { pt1: 10, pt2: 0, pt3: 0, pt4: 0, sl: 10, trail: 3, trail_act: 11, early: false, early_act: 5, early_step: 3, dynamic: false, escalation: false, giveback: false, giveback_pct: 30, ema: false, ema_period: 5, ema_tf: 1, ema_buffer: 0.1, ema_exit: true, ema_esc: true, ema_ext: false, ema_under: true, ema_notrend: 3, runner: true, runner_pct: 20, exit_mode: 'risk', trim_order: 'market', sl_order: 'market', chase: true, sl_profile: 'standard', trim_offset_mode: 'dollar', trim_offset_dollar: 0.01, trim_offset_pct: 2.0, sl_offset: 3 },
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
    setVal(`risk-trim-pct-1-${channelId}`, '');
    setVal(`risk-trim-pct-2-${channelId}`, '');
    setVal(`risk-trim-pct-3-${channelId}`, '');
    setVal(`risk-trim-pct-4-${channelId}`, '');
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

    const orderTypePayload = {
        trim_order_mode: p.trim_order,
        trim_limit_offset_mode: p.trim_offset_mode,
        trim_limit_offset: p.trim_offset_dollar,
        trim_limit_offset_pct: p.trim_offset_pct,
        sl_order_mode: p.sl_order,
        sl_limit_offset: p.sl_offset / 100
    };
    fetch(`/api/channels/${channelId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(orderTypePayload)
    }).then(r => r.json()).then(result => {
        if (result.success) {
            updateLocalChannel(channelId, orderTypePayload);
        }
    }).catch(err => console.error('Failed to save preset order types:', err));

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

const RISK_HELP_CONTENT = {
    'profit-targets': {
        title: 'Profit Targets & Trim Settings',
        sections: [
            {
                heading: 'What It Does',
                body: 'Automatically sells portions of your position as the price moves in your favor. You can set up to 4 profit targets (P1\u2013P4). When price reaches each target, the system trims (sells) part of your position to lock in gains.'
            },
            {
                heading: 'How Targets Work',
                body: 'Each target is a <strong>percentage gain from your entry price</strong>. Targets are triggered sequentially: P1 must hit before P2 can trigger, P2 before P3, and so on.',
                diagram: `<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:14px 0;">
                    <div style="padding:10px 16px;border-radius:10px;background:#1E1E24;border:1px solid #3A3A3C;font-size:14px;color:#A1A1AA;font-weight:500;">Entry</div>
                    <span style="color:#52525B;font-size:16px;">→</span>
                    <div style="padding:10px 16px;border-radius:10px;background:rgba(0,212,255,0.1);border:1px solid #00d4ff;font-size:14px;color:#22D3EE;font-weight:600;">P1: +10%<br><span style="font-size:12px;color:#A1A1AA;font-weight:400;">Sell portion</span></div>
                    <span style="color:#52525B;font-size:16px;">→</span>
                    <div style="padding:10px 16px;border-radius:10px;background:rgba(0,212,255,0.15);border:1px solid #00d4ff;font-size:14px;color:#22D3EE;font-weight:600;">P2: +20%<br><span style="font-size:12px;color:#A1A1AA;font-weight:400;">Sell portion</span></div>
                    <span style="color:#52525B;font-size:16px;">→</span>
                    <div style="padding:10px 16px;border-radius:10px;background:rgba(0,212,255,0.2);border:1px solid #00d4ff;font-size:14px;color:#22D3EE;font-weight:600;">P3: +30%<br><span style="font-size:12px;color:#A1A1AA;font-weight:400;">Sell portion</span></div>
                    <span style="color:#52525B;font-size:16px;">→</span>
                    <div style="padding:10px 16px;border-radius:10px;background:rgba(0,212,255,0.25);border:1px solid #00d4ff;font-size:14px;color:#22D3EE;font-weight:600;">P4: +40%<br><span style="font-size:12px;color:#A1A1AA;font-weight:400;">Sell rest</span></div>
                </div>`
            },
            {
                heading: 'How Quantities Are Split',
                body: '<strong>Priority:</strong> Custom Qty > Custom Trim % > Auto-Split<br><br>' +
                    '<strong>Auto-Split:</strong> Position is divided equally among configured targets.<br>' +
                    '<strong>Custom Qty:</strong> Sell exactly N contracts/shares at that target.<br>' +
                    '<strong>Custom Trim %:</strong> Sell a percentage of the sellable position at that target.',
                diagram: `<div style="margin:12px 0;padding:14px;background:#1E1E24;border-radius:12px;border:1px solid #2D2D30;">
                    <div style="font-size:13px;font-weight:600;color:#818CF8;margin-bottom:10px;">Example: Options \u2014 10 contracts, P1=10%, P2=25%, P3=50%</div>
                    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;font-size:13px;color:#D4D4D8;">
                        <div style="padding:10px;background:rgba(99,102,241,0.08);border:1px solid rgba(99,102,241,0.2);border-radius:8px;text-align:center;"><strong style="color:#818CF8;">Auto-Split</strong><br>P1: sell 3<br>P2: sell 3<br>P3: sell 4</div>
                        <div style="padding:10px;background:rgba(234,179,8,0.08);border:1px solid rgba(234,179,8,0.2);border-radius:8px;text-align:center;"><strong style="color:#FACC15;">Trim 40/30/30%</strong><br>P1: sell 4<br>P2: sell 3<br>P3: sell 3</div>
                        <div style="padding:10px;background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.2);border-radius:8px;text-align:center;"><strong style="color:#34D399;">Custom 5/3/2</strong><br>P1: sell 5<br>P2: sell 3<br>P3: sell 2</div>
                    </div>
                    <div style="font-size:13px;font-weight:600;color:#818CF8;margin:16px 0 10px;">Example: Stocks \u2014 100 shares, P1=5%, P2=10%</div>
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:13px;color:#D4D4D8;">
                        <div style="padding:10px;background:rgba(99,102,241,0.08);border:1px solid rgba(99,102,241,0.2);border-radius:8px;text-align:center;"><strong style="color:#818CF8;">Auto-Split</strong><br>P1: sell 50 shares<br>P2: sell 50 shares</div>
                        <div style="padding:10px;background:rgba(234,179,8,0.08);border:1px solid rgba(234,179,8,0.2);border-radius:8px;text-align:center;"><strong style="color:#FACC15;">Trim 60/40%</strong><br>P1: sell 60 shares<br>P2: sell 40 shares</div>
                    </div>
                </div>`
            }
        ]
    },
    'custom-trim': {
        title: 'Custom Trim Percentages',
        sections: [
            {
                heading: 'How Trim % Works',
                body: 'Each trim % specifies how much of the <strong>remaining position</strong> to sell when that target hits. Trim applies to what is left after previous trims, not the original size.'
            },
            {
                heading: 'Trim Values',
                body: '<strong>Empty (Auto):</strong> Position is auto-split equally across remaining targets.<br><br>' +
                    '<strong>1-100%:</strong> Sell that percentage of remaining position. Minimum 1 contract/share is always sold even if % rounds to zero.<br><br>' +
                    '<strong>0% (Escalation Only):</strong> Mark the tier as hit but do NOT sell. Use this for Dynamic SL escalation markers — the tier hit advances your Dynamic SL level without trimming the position.'
            },
            {
                heading: 'Example: Trim + Escalation',
                body: 'Config: P1=8% (trim 60%), P2=10% (trim 0%), P3=15% (trim 0%), P4=20% (trim 100%)',
                diagram: `<div style="margin:12px 0;padding:14px;background:#1E1E24;border-radius:12px;border:1px solid #2D2D30;">
                    <div style="font-size:13px;color:#D4D4D8;line-height:1.8;">
                        <div><span style="color:#22D3EE;font-weight:600;">P1 +8%:</span> Sell 60% of position — lock profits</div>
                        <div><span style="color:#FACC15;font-weight:600;">P2 +10%:</span> Trim 0% = escalation only — Dynamic SL moves to breakeven</div>
                        <div><span style="color:#FACC15;font-weight:600;">P3 +15%:</span> Trim 0% = escalation only — Dynamic SL moves to +10%</div>
                        <div><span style="color:#34D399;font-weight:600;">P4 +20%:</span> Sell 100% — close remaining position</div>
                        <div style="margin-top:8px;padding-top:8px;border-top:1px solid #2D2D30;color:#A1A1AA;font-size:12px;">If price reverses after P3 but before P4, Dynamic SL at +10% protects your gains automatically.</div>
                    </div>
                </div>`
            },
            {
                heading: 'Priority',
                body: 'If both Custom Qty and Trim % are set for the same target, <strong>Custom Qty wins</strong>. Trim % is only used when Custom Qty is empty.'
            }
        ]
    },
    'stop-loss-trailing': {
        title: 'Stop Loss & Trailing Stop',
        sections: [
            {
                heading: 'Stop Loss',
                body: 'Automatically sells your entire position if the price drops by the specified percentage from your entry price. This protects against large losses.',
                diagram: `<div style="margin:12px 0;padding:14px;background:#1E1E24;border-radius:12px;border:1px solid #2D2D30;">
                    <div style="font-size:13px;font-weight:600;color:#F87171;margin-bottom:8px;">Options Example: Entry $2.50, Stop Loss = 25%</div>
                    <div style="display:flex;align-items:center;gap:10px;font-size:13px;margin-bottom:12px;">
                        <div style="padding:6px 12px;border-radius:8px;background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.3);color:#F87171;font-weight:500;">SL triggers at $1.875 (-25%)</div>
                        <span style="color:#A1A1AA;">→ Position closed</span>
                    </div>
                    <div style="font-size:13px;font-weight:600;color:#F87171;margin-bottom:8px;">Stocks Example: Entry $150.00, Stop Loss = 10%</div>
                    <div style="display:flex;align-items:center;gap:10px;font-size:13px;">
                        <div style="padding:6px 12px;border-radius:8px;background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.3);color:#F87171;font-weight:500;">SL triggers at $135.00 (-10%)</div>
                        <span style="color:#A1A1AA;">→ Position closed</span>
                    </div>
                </div>`
            },
            {
                heading: 'Trailing Stop',
                body: 'A dynamic stop that moves UP as your position gains value, but never moves down. It only activates after the price rises by the <strong>Trailing Activation %</strong>. Once active, the stop follows the price at a distance equal to the <strong>Trailing Stop %</strong>.',
                diagram: `<div style="margin:12px 0;padding:14px;background:#1E1E24;border-radius:12px;border:1px solid #2D2D30;">
                    <div style="font-size:13px;font-weight:600;color:#FBBF24;margin-bottom:10px;">Example: Entry $3.00, Trailing Stop = 15%, Activation = 30%</div>
                    <div style="display:flex;flex-direction:column;gap:8px;font-size:13px;">
                        <div style="display:flex;align-items:center;gap:10px;">
                            <span style="color:#A1A1AA;min-width:120px;font-weight:500;">Price hits $3.90</span>
                            <div style="padding:5px 10px;border-radius:6px;background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.25);color:#34D399;font-weight:500;">+30% → Trailing activates</div>
                            <span style="color:#D4D4D8;">Floor: $3.315</span>
                        </div>
                        <div style="display:flex;align-items:center;gap:10px;">
                            <span style="color:#A1A1AA;min-width:120px;font-weight:500;">Price → $4.50</span>
                            <div style="padding:5px 10px;border-radius:6px;background:rgba(0,212,255,0.1);border:1px solid rgba(0,212,255,0.25);color:#22D3EE;font-weight:500;">Floor moves up</div>
                            <span style="color:#D4D4D8;">Floor: $3.825</span>
                        </div>
                        <div style="display:flex;align-items:center;gap:10px;">
                            <span style="color:#A1A1AA;min-width:120px;font-weight:500;">Price → $3.80</span>
                            <div style="padding:5px 10px;border-radius:6px;background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.25);color:#F87171;font-weight:500;">Below floor $3.825</div>
                            <span style="color:#D4D4D8;">EXIT \u2014 Locked in +26.7%</span>
                        </div>
                    </div>
                </div>`
            }
        ]
    },
    'early-trailing': {
        title: 'Early Trailing Stop',
        sections: [
            {
                heading: 'What It Does',
                body: 'A smarter trailing mechanism that moves your stop to <strong>breakeven</strong> after a small gain, then locks in additional profit in fixed step increments. This replaces the legacy Trailing Stop (they cannot be used together).'
            },
            {
                heading: 'How It Works',
                body: '<strong>Step 1:</strong> When price gains the <em>Breakeven At</em> percentage, the stop moves to your entry price (breakeven).<br>' +
                    '<strong>Step 2:</strong> For each additional <em>Lock Profit Every</em> percentage gained, the stop moves up by that same amount.',
                diagram: `<div style="margin:12px 0;padding:14px;background:#1E1E24;border-radius:12px;border:1px solid #2D2D30;">
                    <div style="font-size:13px;font-weight:600;color:#34D399;margin-bottom:10px;">Options: Entry $4.00, Breakeven at 5%, Lock every 3%</div>
                    <div style="display:flex;flex-direction:column;gap:8px;font-size:13px;">
                        <div style="display:flex;align-items:center;gap:10px;">
                            <span style="color:#A1A1AA;min-width:120px;font-weight:500;">Price +5% ($4.20)</span>
                            <div style="padding:5px 10px;border-radius:6px;background:rgba(0,200,150,0.12);border:1px solid rgba(0,200,150,0.25);color:#34D399;font-weight:500;">Stop → $4.00 (breakeven)</div>
                        </div>
                        <div style="display:flex;align-items:center;gap:10px;">
                            <span style="color:#A1A1AA;min-width:120px;font-weight:500;">Price +8% ($4.32)</span>
                            <div style="padding:5px 10px;border-radius:6px;background:rgba(0,200,150,0.15);border:1px solid rgba(0,200,150,0.25);color:#34D399;font-weight:500;">Stop → $4.12 (+3% locked)</div>
                        </div>
                        <div style="display:flex;align-items:center;gap:10px;">
                            <span style="color:#A1A1AA;min-width:120px;font-weight:500;">Price +11% ($4.44)</span>
                            <div style="padding:5px 10px;border-radius:6px;background:rgba(0,200,150,0.18);border:1px solid rgba(0,200,150,0.25);color:#34D399;font-weight:500;">Stop → $4.24 (+6% locked)</div>
                        </div>
                        <div style="display:flex;align-items:center;gap:10px;">
                            <span style="color:#A1A1AA;min-width:120px;font-weight:500;">Price drops → $4.20</span>
                            <div style="padding:5px 10px;border-radius:6px;background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.25);color:#F87171;font-weight:500;">Below $4.24 → EXIT +5%</div>
                        </div>
                    </div>
                    <div style="font-size:13px;font-weight:600;color:#34D399;margin:16px 0 10px;">Stocks: Entry $50.00, Breakeven at 5%, Lock every 3%</div>
                    <div style="display:flex;flex-direction:column;gap:8px;font-size:13px;">
                        <div style="display:flex;align-items:center;gap:10px;">
                            <span style="color:#A1A1AA;min-width:120px;font-weight:500;">Price +5% ($52.50)</span>
                            <div style="padding:5px 10px;border-radius:6px;background:rgba(0,200,150,0.12);border:1px solid rgba(0,200,150,0.25);color:#34D399;font-weight:500;">Stop → $50.00 (breakeven)</div>
                        </div>
                        <div style="display:flex;align-items:center;gap:10px;">
                            <span style="color:#A1A1AA;min-width:120px;font-weight:500;">Price +8% ($54.00)</span>
                            <div style="padding:5px 10px;border-radius:6px;background:rgba(0,200,150,0.15);border:1px solid rgba(0,200,150,0.25);color:#34D399;font-weight:500;">Stop → $51.50 (+3% locked)</div>
                        </div>
                    </div>
                </div>`
            }
        ]
    },
    'exit-strategy': {
        title: 'Exit Strategy Mode',
        sections: [
            {
                heading: 'What It Does',
                body: 'Controls how your positions are closed. Choose whether to follow the original trader\'s exit signals, use automated risk management, or combine both.'
            },
            {
                heading: 'The Three Modes',
                body: '',
                diagram: `<div style="margin:12px 0;display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;">
                    <div style="padding:14px;background:rgba(16,185,129,0.06);border:1px solid rgba(16,185,129,0.25);border-radius:12px;">
                        <div style="font-size:14px;font-weight:700;color:#34D399;margin-bottom:8px;">Signal Mode</div>
                        <div style="font-size:13px;color:#D4D4D8;line-height:1.6;">
                            Exits <strong>only</strong> when the original trader sends a sell signal.<br><br>
                            Automated profit targets and stop losses are <strong>disabled</strong>. Exception: EMA Risk still evaluates if enabled separately.<br><br>
                            <span style="color:#A1A1AA;">Best for: Trusting the trader\u2019s judgment completely.</span>
                        </div>
                    </div>
                    <div style="padding:14px;background:rgba(0,212,255,0.06);border:1px solid rgba(0,212,255,0.25);border-radius:12px;">
                        <div style="font-size:14px;font-weight:700;color:#22D3EE;margin-bottom:8px;">Risk Mode</div>
                        <div style="font-size:13px;color:#D4D4D8;line-height:1.6;">
                            Exits <strong>only</strong> via automated targets and stop losses.<br><br>
                            Trader sell signals are <strong>ignored</strong>.<br><br>
                            <span style="color:#A1A1AA;">Best for: Full automated risk control, ignoring signal exits.</span>
                        </div>
                    </div>
                    <div style="padding:14px;background:rgba(234,179,8,0.06);border:1px solid rgba(234,179,8,0.25);border-radius:12px;">
                        <div style="font-size:14px;font-weight:700;color:#FACC15;margin-bottom:8px;">Hybrid Mode</div>
                        <div style="font-size:13px;color:#D4D4D8;line-height:1.6;">
                            <strong>Both</strong> trader signals and automated exits are active.<br><br>
                            Whichever triggers first wins.<br><br>
                            <span style="color:#A1A1AA;">Best for: Maximum protection with trader guidance.</span>
                        </div>
                    </div>
                </div>`
            }
        ]
    },
    'trim-order-type': {
        title: 'Trim Order Type',
        sections: [
            {
                heading: 'What It Does',
                body: 'Controls how profit-target trim orders are placed when selling portions of your position at each target.'
            },
            {
                heading: 'Market vs Limit',
                body: '',
                diagram: `<div style="margin:12px 0;display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                    <div style="padding:14px;background:rgba(255,183,0,0.06);border:1px solid rgba(255,183,0,0.2);border-radius:12px;">
                        <div style="font-size:14px;font-weight:700;color:#FBBF24;margin-bottom:8px;">Market Order</div>
                        <div style="font-size:13px;color:#D4D4D8;line-height:1.6;">
                            Sells immediately at the best available price.<br><br>
                            <span style="color:#34D399;font-weight:500;">Pros:</span> Fastest execution, guaranteed fill.<br>
                            <span style="color:#F87171;font-weight:500;">Cons:</span> May get a slightly worse price in fast markets.<br><br>
                            <span style="color:#A1A1AA;">Best for: Fast-moving options, 0DTE trades.</span>
                        </div>
                    </div>
                    <div style="padding:14px;background:rgba(0,212,255,0.06);border:1px solid rgba(0,212,255,0.2);border-radius:12px;">
                        <div style="font-size:14px;font-weight:700;color:#22D3EE;margin-bottom:8px;">Limit Order</div>
                        <div style="font-size:13px;color:#D4D4D8;line-height:1.6;">
                            Places a limit order slightly below current price for better fills.<br><br>
                            <strong>Offset</strong> controls how far below:<br>
                            <span style="color:#A1A1AA;">Dollar mode:</span> e.g. $0.01 below bid<br>
                            <span style="color:#A1A1AA;">Percent mode:</span> e.g. 2% below bid<br><br>
                            <span style="color:#A1A1AA;">Best for: Swing trades, higher-priced options.</span>
                        </div>
                    </div>
                </div>
                <div style="margin-top:10px;padding:10px 14px;background:#1E1E24;border-radius:8px;font-size:13px;color:#D4D4D8;">
                    <strong style="color:#FBBF24;">Example:</strong> Option at $5.20, Limit with $0.01 offset = Limit sell at $5.19
                </div>`
            }
        ]
    },
    'sl-order-type': {
        title: 'Stop Loss Order Type',
        sections: [
            {
                heading: 'What It Does',
                body: 'Controls how stop loss exit orders are placed when your position hits the stop loss threshold.'
            },
            {
                heading: 'Market vs Limit',
                body: '',
                diagram: `<div style="margin:12px 0;display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                    <div style="padding:14px;background:rgba(255,82,82,0.06);border:1px solid rgba(255,82,82,0.2);border-radius:12px;">
                        <div style="font-size:14px;font-weight:700;color:#F87171;margin-bottom:8px;">Limit (Default)</div>
                        <div style="font-size:13px;color:#D4D4D8;line-height:1.6;">
                            Places a limit sell order with an offset below the trigger price.<br><br>
                            The <strong>Limit Offset %</strong> controls how far below: if SL triggers at -10% and offset is 3%, the limit price is set at -13%.<br><br>
                            <span style="color:#34D399;font-weight:500;">Pros:</span> More control over fill price.<br>
                            <span style="color:#F87171;font-weight:500;">Cons:</span> May not fill in a fast crash.
                        </div>
                    </div>
                    <div style="padding:14px;background:rgba(255,183,0,0.06);border:1px solid rgba(255,183,0,0.2);border-radius:12px;">
                        <div style="font-size:14px;font-weight:700;color:#FBBF24;margin-bottom:8px;">Market</div>
                        <div style="font-size:13px;color:#D4D4D8;line-height:1.6;">
                            Sells immediately at market price when SL triggers.<br><br>
                            <span style="color:#34D399;font-weight:500;">Pros:</span> Guaranteed exit, no risk of unfilled order.<br>
                            <span style="color:#F87171;font-weight:500;">Cons:</span> May get worse price due to slippage.<br><br>
                            <span style="color:#A1A1AA;">Best for: Volatile or low-liquidity positions.</span>
                        </div>
                    </div>
                </div>
                <div style="margin-top:10px;padding:10px 14px;background:#1E1E24;border-radius:8px;font-size:13px;color:#D4D4D8;">
                    <strong style="color:#F87171;">Example:</strong> Option entry $2.00, SL 25%, Offset 3% → SL triggers at $1.50 (-25%), limit sell at $1.44 (-28%).<br>Stock entry $100, SL 10%, Offset 3% → triggers at $90, limit at $87.
                </div>`
            }
        ]
    },
    'order-chase': {
        title: 'Order Chase',
        sections: [
            {
                heading: 'What It Does',
                body: 'Automatically replaces unfilled limit orders with updated prices to improve fill rates. Works for entry orders (buying) and exit orders (selling).'
            },
            {
                heading: 'Chase Modes',
                body: '',
                diagram: `<div style="margin:12px 0;display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                    <div style="padding:14px;background:rgba(167,139,250,0.06);border:1px solid rgba(167,139,250,0.2);border-radius:12px;">
                        <div style="font-size:14px;font-weight:700;color:#A78BFA;margin-bottom:8px;">Entry Chase</div>
                        <div style="font-size:13px;color:#D4D4D8;line-height:1.6;">
                            Chases unfilled <strong>buy</strong> orders by adjusting toward the ask price.<br><br>
                            Uses progressively aggressive pricing to get filled quickly.
                        </div>
                    </div>
                    <div style="padding:14px;background:rgba(0,212,255,0.06);border:1px solid rgba(0,212,255,0.2);border-radius:12px;">
                        <div style="font-size:14px;font-weight:700;color:#22D3EE;margin-bottom:8px;">Exit Chase</div>
                        <div style="font-size:13px;color:#D4D4D8;line-height:1.6;">
                            Chases unfilled <strong>sell</strong> orders through 3 stages:<br><br>
                            <span style="color:#34D399;font-weight:500;">Round 1:</span> Mid/Last/Bid price<br>
                            <span style="color:#FACC15;font-weight:500;">Round 2:</span> Bid/Last price<br>
                            <span style="color:#F87171;font-weight:500;">Round 3+:</span> Market order
                        </div>
                    </div>
                </div>
                <div style="margin-top:10px;padding:10px 14px;background:#1E1E24;border-radius:8px;font-size:13px;color:#D4D4D8;">
                    <strong style="color:#A78BFA;">Example:</strong> You sell 5 SPY $450C at $3.20 limit. If unfilled after a few seconds, the chaser replaces at $3.15 (bid), then $3.10, then converts to market order to guarantee exit.
                </div>`
            }
        ]
    },
    'leave-runner': {
        title: 'Leave Runner',
        sections: [
            {
                heading: 'What It Does',
                body: 'Keeps a small portion of your position after all profit targets are hit, allowing you to ride further gains. The runner is protected by your stop loss or trailing stop.'
            },
            {
                heading: 'How It Works',
                body: 'The <strong>Runner Size %</strong> determines what percentage of your original position is reserved. This portion is excluded from profit target trim calculations. A minimum of 1 contract/share is always kept.',
                diagram: `<div style="margin:12px 0;padding:14px;background:#1E1E24;border-radius:12px;border:1px solid #2D2D30;">
                    <div style="font-size:13px;font-weight:600;color:#4ADE80;margin-bottom:10px;">Options: 10 contracts, Runner = 20%, P1=10%, P2=25%, P3=50%</div>
                    <div style="display:flex;align-items:center;gap:10px;font-size:13px;flex-wrap:wrap;margin-bottom:12px;">
                        <div style="padding:6px 12px;border-radius:8px;background:rgba(99,102,241,0.1);border:1px solid rgba(99,102,241,0.25);color:#818CF8;font-weight:500;">Sellable: 8 contracts</div>
                        <span style="color:#52525B;font-size:16px;">|</span>
                        <div style="padding:6px 12px;border-radius:8px;background:rgba(0,255,136,0.08);border:1px solid rgba(74,222,128,0.3);color:#4ADE80;font-weight:500;">Runner: 2 contracts (reserved)</div>
                    </div>
                    <div style="display:flex;flex-direction:column;gap:6px;font-size:13px;color:#D4D4D8;">
                        <div>P1 hits +10%: Sell 3 of 8 sellable</div>
                        <div>P2 hits +25%: Sell 3 of remaining 5</div>
                        <div>P3 hits +50%: Sell remaining 2</div>
                        <div style="color:#4ADE80;font-weight:600;margin-top:4px;">Runner (2 contracts) rides with trailing stop protection</div>
                    </div>
                    <div style="font-size:13px;font-weight:600;color:#4ADE80;margin:16px 0 8px;">Stocks: 100 shares, Runner = 25%</div>
                    <div style="display:flex;flex-direction:column;gap:6px;font-size:13px;color:#D4D4D8;">
                        <div>Sellable: 75 shares across targets</div>
                        <div style="color:#4ADE80;font-weight:600;">Runner: 25 shares reserved for extended gains</div>
                    </div>
                </div>`
            }
        ]
    },
    'dynamic-sl': {
        title: 'Dynamic Stop Loss Escalation',
        sections: [
            {
                heading: 'What It Does',
                body: 'Automatically moves your stop loss higher each time a profit target is hit. As you lock in more gains, your downside protection tightens. The <strong>Escalation Only</strong> sub-option makes targets only move the stop loss without selling any contracts.'
            },
            {
                heading: 'Escalation Profiles',
                body: 'Each profile defines how much the stop loss moves after each target:',
                diagram: `<div style="margin:12px 0;padding:14px;background:#1E1E24;border-radius:12px;border:1px solid #2D2D30;">
                    <table style="width:100%;font-size:13px;border-collapse:collapse;color:#D4D4D8;">
                        <thead>
                            <tr style="border-bottom:1px solid #3A3A3C;">
                                <th style="text-align:left;padding:8px 10px;color:#A1A1AA;font-weight:600;">Profile</th>
                                <th style="text-align:center;padding:8px 10px;color:#22D3EE;font-weight:600;">After P1</th>
                                <th style="text-align:center;padding:8px 10px;color:#22D3EE;font-weight:600;">After P2</th>
                                <th style="text-align:center;padding:8px 10px;color:#22D3EE;font-weight:600;">After P3</th>
                                <th style="text-align:center;padding:8px 10px;color:#22D3EE;font-weight:600;">After P4</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr style="border-bottom:1px solid #27272A;">
                                <td style="padding:8px 10px;color:#34D399;font-weight:600;">Conservative</td>
                                <td style="text-align:center;padding:8px 10px;">Breakeven</td>
                                <td style="text-align:center;padding:8px 10px;">+3%</td>
                                <td style="text-align:center;padding:8px 10px;">+8%</td>
                                <td style="text-align:center;padding:8px 10px;">+15%</td>
                            </tr>
                            <tr style="border-bottom:1px solid #27272A;">
                                <td style="padding:8px 10px;color:#FACC15;font-weight:600;">Standard</td>
                                <td style="text-align:center;padding:8px 10px;">Breakeven</td>
                                <td style="text-align:center;padding:8px 10px;">+5%</td>
                                <td style="text-align:center;padding:8px 10px;">+10%</td>
                                <td style="text-align:center;padding:8px 10px;">+17%</td>
                            </tr>
                            <tr>
                                <td style="padding:8px 10px;color:#F87171;font-weight:600;">Aggressive</td>
                                <td style="text-align:center;padding:8px 10px;">-2%</td>
                                <td style="text-align:center;padding:8px 10px;">Breakeven</td>
                                <td style="text-align:center;padding:8px 10px;">+8%</td>
                                <td style="text-align:center;padding:8px 10px;">+15%</td>
                            </tr>
                        </tbody>
                    </table>
                    <div style="margin-top:14px;font-size:13px;font-weight:600;color:#FB7185;">Example: Options entry $3.00, Standard profile</div>
                    <div style="font-size:13px;margin-top:6px;color:#D4D4D8;line-height:1.7;">
                        P1 hits at +15%: SL moves to $3.00 (breakeven)<br>
                        P2 hits at +30%: SL moves to $3.15 (+5%)<br>
                        P3 hits at +50%: SL moves to $3.30 (+10%)
                    </div>
                </div>`
            },
            {
                heading: 'Escalation Only Mode',
                body: 'When enabled, hitting a profit target <strong>only moves the stop loss</strong> \u2014 it does <strong>not</strong> sell any contracts. This lets you ride the full position while progressively tightening your safety net.'
            }
        ]
    },
    'giveback-guard': {
        title: 'Max Profit Giveback Guard',
        sections: [
            {
                heading: 'What It Does',
                body: 'Monitors your position\'s peak profit and exits if too much of that profit is given back. This prevents a winning trade from turning into a loss or a much smaller win.'
            },
            {
                heading: 'How It Works',
                body: 'The system tracks the highest unrealized profit your position reaches. If the current profit drops below a percentage of that peak, it triggers an exit. It activates after P2 is hit, or after the trailing activation threshold is reached.',
                diagram: `<div style="margin:12px 0;padding:14px;background:#1E1E24;border-radius:12px;border:1px solid #2D2D30;">
                    <div style="font-size:13px;font-weight:600;color:#FBBF24;margin-bottom:10px;">Options: Entry $2.00, Giveback = 30%, peak reached +60%</div>
                    <div style="display:flex;flex-direction:column;gap:8px;font-size:13px;">
                        <div style="display:flex;align-items:center;gap:10px;">
                            <span style="color:#A1A1AA;min-width:140px;font-weight:500;">Peak profit: +60%</span>
                            <span style="color:#34D399;font-weight:500;">Price at $3.20</span>
                        </div>
                        <div style="display:flex;align-items:center;gap:10px;">
                            <span style="color:#A1A1AA;min-width:140px;font-weight:500;">Giveback threshold</span>
                            <span style="color:#FBBF24;font-weight:500;">60% \u00d7 (1 - 0.30) = +42%</span>
                        </div>
                        <div style="display:flex;align-items:center;gap:10px;">
                            <span style="color:#A1A1AA;min-width:140px;font-weight:500;">Price drops to +40%</span>
                            <div style="padding:5px 10px;border-radius:6px;background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.25);color:#F87171;font-weight:500;">Below 42% threshold → EXIT</div>
                        </div>
                    </div>
                    <div style="margin-top:10px;font-size:13px;color:#A1A1AA;font-style:italic;">Result: Exited with +40% instead of watching it fall further. Still a great trade!</div>
                    <div style="font-size:13px;font-weight:600;color:#FBBF24;margin:16px 0 8px;">Stocks: Entry $100, Giveback = 30%, peak +20%</div>
                    <div style="font-size:13px;color:#D4D4D8;">Threshold: 20% \u00d7 0.70 = +14%. If profit drops below +14%, position is closed.</div>
                </div>`
            }
        ]
    },
    'ema-risk': {
        title: 'EMA Risk Management',
        sections: [
            {
                heading: 'What It Does',
                body: 'Uses Exponential Moving Average (EMA) analysis on live price candles to detect momentum shifts. When price crosses below the EMA unfavorably, it can trigger an exit or escalate your stop loss.'
            },
            {
                heading: 'Key Settings',
                body: '',
                diagram: `<div style="margin:12px 0;display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                    <div style="padding:12px;background:rgba(0,188,212,0.06);border:1px solid rgba(0,188,212,0.2);border-radius:10px;">
                        <div style="font-size:13px;font-weight:600;color:#22D3EE;margin-bottom:6px;">EMA Period</div>
                        <div style="font-size:13px;color:#D4D4D8;line-height:1.5;">Number of candles used. Lower = more sensitive (3=fast, 21=slow).</div>
                    </div>
                    <div style="padding:12px;background:rgba(0,188,212,0.06);border:1px solid rgba(0,188,212,0.2);border-radius:10px;">
                        <div style="font-size:13px;font-weight:600;color:#22D3EE;margin-bottom:6px;">Candle Timeframe</div>
                        <div style="font-size:13px;color:#D4D4D8;line-height:1.5;">Duration of each candle (1\u20135 min). Shorter = faster reaction.</div>
                    </div>
                    <div style="padding:12px;background:rgba(0,188,212,0.06);border:1px solid rgba(0,188,212,0.2);border-radius:10px;">
                        <div style="font-size:13px;font-weight:600;color:#22D3EE;margin-bottom:6px;">Buffer %</div>
                        <div style="font-size:13px;color:#D4D4D8;line-height:1.5;">Price must cross EMA by this % to trigger. Prevents false signals from noise.</div>
                    </div>
                    <div style="padding:12px;background:rgba(0,188,212,0.06);border:1px solid rgba(0,188,212,0.2);border-radius:10px;">
                        <div style="font-size:13px;font-weight:600;color:#22D3EE;margin-bottom:6px;">No-Trend Candles</div>
                        <div style="font-size:13px;color:#D4D4D8;line-height:1.5;">Consecutive candles below EMA needed before action (default 3).</div>
                    </div>
                </div>
                <div style="margin-top:10px;padding:12px;background:#1E1E24;border-radius:10px;">
                    <div style="font-size:14px;font-weight:600;color:#22D3EE;margin-bottom:8px;">How EMA Exit Works</div>
                    <div style="display:flex;flex-direction:column;gap:6px;font-size:13px;color:#D4D4D8;">
                        <div>1. System builds live candles from the underlying asset price</div>
                        <div>2. EMA is calculated using the selected period</div>
                        <div>3. Waits for at least 2 candles after entry (warmup period)</div>
                        <div>4. If price closes below EMA (minus buffer) for N consecutive candles:</div>
                        <div style="padding-left:20px;color:#F87171;font-weight:500;"><strong>Exit on Cross</strong> = Sell the position</div>
                        <div style="padding-left:20px;color:#FACC15;font-weight:500;"><strong>Stop Escalation</strong> = Move stop loss to EMA-based level (stocks only; options use Exit on Cross)</div>
                    </div>
                </div>
                <div style="margin-top:10px;padding:10px 14px;background:#1E1E24;border:1px solid rgba(0,188,212,0.15);border-radius:8px;font-size:13px;color:#D4D4D8;">
                    <strong style="color:#22D3EE;">Tip for Options:</strong> Enable \u201cUse Underlying\u201d to compute EMA on the stock price (e.g., SPY) rather than the option price, which tends to be more reliable. EMA on option prices can be noisy due to bid-ask spreads.
                </div>`
            }
        ]
    },
    'pt-near-lock': {
        title: '🎯 PT Near-Lock',
        sections: [
            {
                heading: 'What It Does',
                body: 'PT Near-Lock protects your unrealized profit when price gets close to a Profit Target (PT) but hasn\'t actually hit it yet. Instead of watching a +8% gain evaporate back to breakeven because PT1 was at +10%, the bot locks in a tight trailing stop from the highest price reached — so you capture most of the move even on a near-miss.'
            },
            {
                heading: 'The Problem It Solves',
                body: `<div style="padding:12px;background:rgba(52,211,153,0.06);border:1px solid rgba(52,211,153,0.2);border-radius:10px;font-size:13px;color:#D4D4D8;line-height:1.7;">
                    <strong style="color:#34d399;">Example:</strong> PT1 = +10%, SL = -10%, Dynamic SL enabled.<br>
                    Price climbs to <strong>+8.5%</strong> — then reverses hard.<br>
                    Without PT Near-Lock: stop is still at entry/breakeven → you exit at <strong>0%</strong> or worse.<br>
                    With PT Near-Lock (threshold 80% of PT1 = +8%): a tight trailing stop activates at +8%,<br>
                    following price up to +8.5%, then exits on the dip → you capture roughly <strong>+5–7%</strong>.
                </div>`
            },
            {
                heading: 'Key Settings',
                body: '',
                diagram: `<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:4px;">
                    <div style="padding:12px;background:rgba(52,211,153,0.06);border:1px solid rgba(52,211,153,0.2);border-radius:10px;">
                        <div style="font-size:13px;font-weight:600;color:#34d399;margin-bottom:6px;">Lock Threshold % of PT</div>
                        <div style="font-size:13px;color:#D4D4D8;line-height:1.5;">Activate when price reaches this % of the distance to the next PT. <em>Default 80%</em> — if PT1 is +10%, activates at +8%.</div>
                    </div>
                    <div style="padding:12px;background:rgba(52,211,153,0.06);border:1px solid rgba(52,211,153,0.2);border-radius:10px;">
                        <div style="font-size:13px;font-weight:600;color:#34d399;margin-bottom:6px;">Trail From High %</div>
                        <div style="font-size:13px;color:#D4D4D8;line-height:1.5;">How far below the highest price the trailing stop sits. <em>Default 3%</em> — price peaks at +9%, stop is at +6%.</div>
                    </div>
                    <div style="padding:12px;background:rgba(52,211,153,0.06);border:1px solid rgba(52,211,153,0.2);border-radius:10px;">
                        <div style="font-size:13px;font-weight:600;color:#34d399;margin-bottom:6px;">Soft Exit (Partial Trim)</div>
                        <div style="font-size:13px;color:#D4D4D8;line-height:1.5;">Optional one-time partial sell when the lock threshold is first crossed — trim a slice to lock in gains before the full trailing stop takes over.</div>
                    </div>
                    <div style="padding:12px;background:rgba(52,211,153,0.06);border:1px solid rgba(52,211,153,0.2);border-radius:10px;">
                        <div style="font-size:13px;font-weight:600;color:#34d399;margin-bottom:6px;">Soft Threshold % / Trim %</div>
                        <div style="font-size:13px;color:#D4D4D8;line-height:1.5;">Controls when the soft partial trim fires (as % of PT) and how much to sell (e.g. 25% of position). Only fires once per PT level.</div>
                    </div>
                </div>
                <div style="margin-top:12px;padding:12px;background:#1E1E24;border-radius:10px;">
                    <div style="font-size:14px;font-weight:600;color:#34d399;margin-bottom:8px;">How It Flows</div>
                    <div style="display:flex;flex-direction:column;gap:6px;font-size:13px;color:#D4D4D8;">
                        <div>1. Price climbs toward the next unmet PT (e.g. PT1 = +10%)</div>
                        <div>2. When price crosses <strong>Lock Threshold</strong> (e.g. +8%) → near-lock activates</div>
                        <div>3. <em>If Soft Exit enabled</em>: one-time partial trim fires at the Soft Threshold</div>
                        <div>4. A tight trailing stop is set at <strong>highest price − Trail %</strong>, ratchets upward as price rises</div>
                        <div>5. Price reverses past the trailing stop → position exits, profit captured</div>
                        <div style="margin-top:4px;padding:8px 10px;background:rgba(52,211,153,0.06);border:1px solid rgba(52,211,153,0.15);border-radius:6px;color:#86EFAC;">
                            ✓ Applies independently to each unmet PT level. Once a PT is actually hit, the normal PT trim/OCO logic takes over.
                        </div>
                    </div>
                </div>`
            },
            {
                heading: 'Tips',
                body: `<ul style="margin:0;padding-left:20px;display:flex;flex-direction:column;gap:6px;font-size:13px;color:#D4D4D8;">
                    <li><strong style="color:#34d399;">80% threshold + 3% trail</strong> is a balanced default — aggressive enough to capture near-misses, loose enough to avoid premature exits on normal dips.</li>
                    <li>Lower the trail % (e.g. <strong>1.5%</strong>) if your signals are fast-moving options where reversals are sharp.</li>
                    <li>Enable <strong>Soft Exit</strong> if you'd rather take partial profits immediately rather than wait for the trailing stop to hit.</li>
                    <li>PT Near-Lock only activates for <strong>unmet</strong> targets. If you already hit PT1, the lock doesn't re-trigger for PT1 — it moves on to PT2.</li>
                    <li>Works alongside Dynamic SL — they govern different phases of the trade and don't conflict.</li>
                </ul>`
            }
        ]
    },
    'multi-broker': {
        title: 'Multi-Broker Execution',
        sections: [
            {
                heading: 'What It Does',
                body: 'Controls which brokerage accounts receive trades from this channel. When multiple brokers are enabled, signals are executed simultaneously across ALL selected accounts.'
            },
            {
                heading: 'How It Works',
                body: `<div style="display:grid;gap:6px;">
                <div style="padding:8px 12px;background:rgba(0,212,255,0.06);border:1px solid rgba(0,212,255,0.15);border-radius:6px;font-size:13px;">
                    <strong style="color:#22D3EE;">Select Brokers</strong> <span style="color:#A1A1AA;">\u2192</span> Check the boxes next to each broker you want active for this channel
                </div>
                <div style="padding:8px 12px;background:rgba(0,212,255,0.06);border:1px solid rgba(0,212,255,0.15);border-radius:6px;font-size:13px;">
                    <strong style="color:#22D3EE;">Simultaneous Execution</strong> <span style="color:#A1A1AA;">\u2192</span> A single signal triggers orders on every enabled broker at the same time
                </div>
                <div style="padding:8px 12px;background:rgba(0,212,255,0.06);border:1px solid rgba(0,212,255,0.15);border-radius:6px;font-size:13px;">
                    <strong style="color:#22D3EE;">Independent Sizing</strong> <span style="color:#A1A1AA;">\u2192</span> Each broker uses its own position-sizing and account settings
                </div>
                </div>`
            },
            {
                heading: 'Supported Brokers',
                body: `<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">
                <div style="padding:6px 10px;background:rgba(0,255,136,0.06);border:1px solid rgba(0,255,136,0.12);border-radius:5px;font-size:13px;color:#D4D4D8;"><strong style="color:#4ADE80;">Webull</strong> \u2014 Options & Stocks</div>
                <div style="padding:6px 10px;background:rgba(0,255,136,0.06);border:1px solid rgba(0,255,136,0.12);border-radius:5px;font-size:13px;color:#D4D4D8;"><strong style="color:#4ADE80;">Schwab</strong> \u2014 Options & Stocks</div>
                <div style="padding:6px 10px;background:rgba(0,255,136,0.06);border:1px solid rgba(0,255,136,0.12);border-radius:5px;font-size:13px;color:#D4D4D8;"><strong style="color:#4ADE80;">Alpaca</strong> \u2014 Options & Stocks</div>
                <div style="padding:6px 10px;background:rgba(0,255,136,0.06);border:1px solid rgba(0,255,136,0.12);border-radius:5px;font-size:13px;color:#D4D4D8;"><strong style="color:#4ADE80;">IBKR</strong> \u2014 Options & Stocks</div>
                <div style="padding:6px 10px;background:rgba(0,255,136,0.06);border:1px solid rgba(0,255,136,0.12);border-radius:5px;font-size:13px;color:#D4D4D8;"><strong style="color:#4ADE80;">TastyTrade</strong> \u2014 Options & Stocks</div>
                <div style="padding:6px 10px;background:rgba(0,255,136,0.06);border:1px solid rgba(0,255,136,0.12);border-radius:5px;font-size:13px;color:#D4D4D8;"><strong style="color:#4ADE80;">Trading212</strong> \u2014 Stocks Only</div>
                <div style="padding:6px 10px;background:rgba(0,255,136,0.06);border:1px solid rgba(0,255,136,0.12);border-radius:5px;font-size:13px;color:#D4D4D8;"><strong style="color:#4ADE80;">Robinhood</strong> \u2014 Options & Stocks</div>
                </div>`
            },
            {
                heading: 'Tips',
                body: `<div style="margin-top:4px;padding:10px 14px;background:#1E1E24;border:1px solid rgba(0,188,212,0.15);border-radius:8px;font-size:13px;color:#D4D4D8;">
                \u2022 You must configure broker credentials on the <strong style="color:#22D3EE;">Broker Settings</strong> page before enabling a broker here.<br>
                \u2022 Each broker maintains its own positions independently \u2014 closing on one does not affect the others.<br>
                \u2022 Risk management settings apply to each broker\u2019s positions individually.
                </div>`
            }
        ]
    },
    'ticker-filter': {
        title: 'Ticker Filter',
        sections: [
            {
                heading: 'What It Does',
                body: 'Filters which tickers (symbols) are allowed or blocked for this channel. Useful when a signal provider is strong on certain tickers but weak on others.'
            },
            {
                heading: 'Filter Modes',
                body: `<div style="display:grid;gap:6px;">
                <div style="padding:8px 12px;background:rgba(0,255,136,0.06);border:1px solid rgba(0,255,136,0.15);border-radius:6px;font-size:13px;">
                    <strong style="color:#4ADE80;">Allow List</strong> <span style="color:#A1A1AA;">\u2014</span> <span style="color:#D4D4D8;">Only trade signals matching these tickers. Everything else is ignored.</span>
                </div>
                <div style="padding:8px 12px;background:rgba(255,107,107,0.06);border:1px solid rgba(255,107,107,0.15);border-radius:6px;font-size:13px;">
                    <strong style="color:#F87171;">Block List</strong> <span style="color:#A1A1AA;">\u2014</span> <span style="color:#D4D4D8;">Trade everything EXCEPT these tickers. Listed symbols are skipped.</span>
                </div>
                <div style="padding:8px 12px;background:rgba(142,142,147,0.06);border:1px solid rgba(142,142,147,0.15);border-radius:6px;font-size:13px;">
                    <strong style="color:#A1A1AA;">Off</strong> <span style="color:#A1A1AA;">\u2014</span> <span style="color:#D4D4D8;">No filtering. All tickers from this channel are traded.</span>
                </div>
                </div>`
            },
            {
                heading: 'How Matching Works',
                body: `<div style="display:grid;gap:6px;">
                <div style="padding:8px 12px;background:rgba(0,212,255,0.06);border:1px solid rgba(0,212,255,0.15);border-radius:6px;font-size:13px;color:#D4D4D8;">
                    <strong style="color:#22D3EE;">Options:</strong> The underlying symbol is matched. A signal for <code style="background:#2A2A30;padding:1px 5px;border-radius:3px;color:#F4F4F5;">SPY 450C 12/15</code> matches the ticker <code style="background:#2A2A30;padding:1px 5px;border-radius:3px;color:#F4F4F5;">SPY</code>.
                </div>
                <div style="padding:8px 12px;background:rgba(0,212,255,0.06);border:1px solid rgba(0,212,255,0.15);border-radius:6px;font-size:13px;color:#D4D4D8;">
                    <strong style="color:#22D3EE;">Case-Insensitive:</strong> <code style="background:#2A2A30;padding:1px 5px;border-radius:3px;color:#F4F4F5;">spy</code>, <code style="background:#2A2A30;padding:1px 5px;border-radius:3px;color:#F4F4F5;">SPY</code>, and <code style="background:#2A2A30;padding:1px 5px;border-radius:3px;color:#F4F4F5;">Spy</code> all match the same ticker.
                </div>
                <div style="padding:8px 12px;background:rgba(0,212,255,0.06);border:1px solid rgba(0,212,255,0.15);border-radius:6px;font-size:13px;color:#D4D4D8;">
                    <strong style="color:#22D3EE;">Format:</strong> Enter tickers comma-separated: <code style="background:#2A2A30;padding:1px 5px;border-radius:3px;color:#F4F4F5;">SPY, QQQ, AAPL, TSLA</code>
                </div>
                </div>`
            },
            {
                heading: 'Examples',
                body: `<div style="padding:10px 14px;background:#1E1E24;border:1px solid rgba(0,188,212,0.15);border-radius:8px;font-size:13px;color:#D4D4D8;">
                \u2022 <strong style="color:#4ADE80;">Allow List "SPY, QQQ"</strong> \u2192 Only trades SPY and QQQ signals, ignores AAPL, TSLA, etc.<br>
                \u2022 <strong style="color:#F87171;">Block List "COIN, GME, AMC"</strong> \u2192 Trades everything except meme stocks<br>
                \u2022 <strong style="color:#A1A1AA;">Off</strong> \u2192 Every signal from this channel is traded regardless of ticker
                </div>`
            }
        ]
    },
    'paper-trading': {
        title: 'Paper Trading',
        sections: [
            {
                heading: 'What It Does',
                body: 'Paper trading simulates trade execution without risking real money. When enabled, the system tracks entries, exits, profit targets, and stop losses exactly as it would with a live broker, but uses a virtual account balance instead.'
            },
            {
                heading: 'How It Works',
                body: `<div style="display:grid;gap:6px;">
                <div style="padding:8px 12px;background:rgba(0,212,255,0.06);border:1px solid rgba(0,212,255,0.15);border-radius:6px;font-size:13px;color:#D4D4D8;">
                    <strong style="color:#22D3EE;">Virtual Account</strong> \u2014 Starts with a simulated balance. Trades deduct and add to this balance just like a real account.
                </div>
                <div style="padding:8px 12px;background:rgba(0,212,255,0.06);border:1px solid rgba(0,212,255,0.15);border-radius:6px;font-size:13px;color:#D4D4D8;">
                    <strong style="color:#22D3EE;">Full Risk Engine</strong> \u2014 All risk management rules (profit targets, stop losses, trailing stops) apply exactly the same as live trading.
                </div>
                <div style="padding:8px 12px;background:rgba(0,212,255,0.06);border:1px solid rgba(0,212,255,0.15);border-radius:6px;font-size:13px;color:#D4D4D8;">
                    <strong style="color:#22D3EE;">Performance Tracking</strong> \u2014 Track win rate, P&L, and trade history to evaluate a signal provider before going live.
                </div>
                </div>`
            },
            {
                heading: 'Configuration',
                body: `<div style="display:grid;gap:6px;">
                <div style="padding:8px 12px;background:rgba(255,179,0,0.06);border:1px solid rgba(255,179,0,0.15);border-radius:6px;font-size:13px;color:#D4D4D8;">
                    <strong style="color:#FBBF24;">Profit Target %</strong> \u2014 Override the global profit target for this channel\u2019s paper trades
                </div>
                <div style="padding:8px 12px;background:rgba(255,179,0,0.06);border:1px solid rgba(255,179,0,0.15);border-radius:6px;font-size:13px;color:#D4D4D8;">
                    <strong style="color:#FBBF24;">Stop Loss %</strong> \u2014 Override the global stop loss for this channel\u2019s paper trades
                </div>
                <div style="padding:8px 12px;background:rgba(255,179,0,0.06);border:1px solid rgba(255,179,0,0.15);border-radius:6px;font-size:13px;color:#D4D4D8;">
                    <strong style="color:#FBBF24;">Trailing Stop %</strong> \u2014 Set a trailing stop that follows price upward
                </div>
                <div style="padding:8px 12px;background:rgba(255,179,0,0.06);border:1px solid rgba(255,179,0,0.15);border-radius:6px;font-size:13px;color:#D4D4D8;">
                    <strong style="color:#FBBF24;">Trailing Activation %</strong> \u2014 Profit level at which the trailing stop begins tracking
                </div>
                </div>`
            },
            {
                heading: 'When to Use',
                body: `<div style="padding:10px 14px;background:#1E1E24;border:1px solid rgba(0,188,212,0.15);border-radius:8px;font-size:13px;color:#D4D4D8;">
                \u2022 <strong style="color:#4ADE80;">Testing a new channel</strong> \u2014 Evaluate signal quality before risking real capital<br>
                \u2022 <strong style="color:#4ADE80;">Tuning risk settings</strong> \u2014 Experiment with different profit targets and stop losses<br>
                \u2022 <strong style="color:#4ADE80;">Comparing providers</strong> \u2014 Run multiple channels on paper to find the best performers<br>
                \u2022 Leave fields empty to use the global default settings
                </div>`
            }
        ]
    },
    'allowed-users': {
        title: 'Allowed Users (Signal Filtering)',
        sections: [
            {
                heading: 'What It Does',
                body: 'Controls which Discord users\u2019 messages are treated as trading signals in this channel. By default, ALL messages in the channel are parsed for signals. Adding specific users restricts signal processing to only those users.'
            },
            {
                heading: 'How It Works',
                body: `<div style="display:grid;gap:6px;">
                <div style="padding:8px 12px;background:rgba(0,212,255,0.06);border:1px solid rgba(0,212,255,0.15);border-radius:6px;font-size:13px;color:#D4D4D8;">
                    <strong style="color:#22D3EE;">No Users Added</strong> \u2014 Every message in the channel is parsed for trade signals (default behavior)
                </div>
                <div style="padding:8px 12px;background:rgba(0,212,255,0.06);border:1px solid rgba(0,212,255,0.15);border-radius:6px;font-size:13px;color:#D4D4D8;">
                    <strong style="color:#22D3EE;">Users Added</strong> \u2014 Only messages from the listed Discord User IDs are treated as signals. All other messages are ignored.
                </div>
                </div>`
            },
            {
                heading: 'Finding a Discord User ID',
                body: `<div style="display:grid;gap:6px;">
                <div style="padding:8px 12px;background:rgba(255,179,0,0.06);border:1px solid rgba(255,179,0,0.15);border-radius:6px;font-size:13px;color:#D4D4D8;">
                    <strong style="color:#FBBF24;">Step 1:</strong> Enable Developer Mode in Discord (Settings \u2192 Advanced \u2192 Developer Mode)
                </div>
                <div style="padding:8px 12px;background:rgba(255,179,0,0.06);border:1px solid rgba(255,179,0,0.15);border-radius:6px;font-size:13px;color:#D4D4D8;">
                    <strong style="color:#FBBF24;">Step 2:</strong> Right-click the user\u2019s name in Discord
                </div>
                <div style="padding:8px 12px;background:rgba(255,179,0,0.06);border:1px solid rgba(255,179,0,0.15);border-radius:6px;font-size:13px;color:#D4D4D8;">
                    <strong style="color:#FBBF24;">Step 3:</strong> Click \u201cCopy User ID\u201d \u2014 paste it into the Discord User ID field
                </div>
                </div>`
            },
            {
                heading: 'Tips',
                body: `<div style="padding:10px 14px;background:#1E1E24;border:1px solid rgba(0,188,212,0.15);border-radius:8px;font-size:13px;color:#D4D4D8;">
                \u2022 <strong style="color:#4ADE80;">Best Practice:</strong> Always add the signal provider\u2019s User ID to avoid executing trades from random chat messages<br>
                \u2022 The Username field is optional \u2014 it\u2019s just a label to help you identify who each ID belongs to<br>
                \u2022 You can add multiple users if a channel has more than one signal provider<br>
                \u2022 Bot accounts (webhooks) have their own User IDs and can be added here too
                </div>`
            }
        ]
    },
    'broker-bracket-mode': {
        title: '\ud83d\udee1\ufe0f Broker Bracket Orders',
        sections: [
            {
                heading: 'What It Does',
                body: 'Places native stop-loss (SL) and profit-target (PT) orders directly on your broker when a position opens. These orders live on the broker\u2019s server \u2014 if the bot crashes or disconnects, your protection stays active. The risk engine always monitors your positions regardless of this setting.'
            },
            {
                heading: 'Modes',
                body: `<div style="display:grid;gap:6px;">
                <div style="padding:8px 12px;background:rgba(0,255,136,0.06);border:1px solid rgba(0,255,136,0.15);border-radius:6px;font-size:13px;color:#D4D4D8;">
                    <strong style="color:#4ADE80;">Both (SL + PT)</strong> \u2014 Places linked OCO (One-Cancels-Other) bracket: when SL fills, PT auto-cancels; when PT fills, SL auto-cancels. <em>Recommended for maximum protection.</em>
                </div>
                <div style="padding:8px 12px;background:rgba(255,179,0,0.06);border:1px solid rgba(255,179,0,0.15);border-radius:6px;font-size:13px;color:#D4D4D8;">
                    <strong style="color:#FBBF24;">SL Only</strong> \u2014 Only stop-loss placed with broker. Profit targets managed by software risk engine. Use when broker rejects simultaneous SL + PT.
                </div>
                <div style="padding:8px 12px;background:rgba(99,102,241,0.06);border:1px solid rgba(99,102,241,0.15);border-radius:6px;font-size:13px;color:#D4D4D8;">
                    <strong style="color:#818CF8;">PT Only</strong> \u2014 Only profit target placed with broker. Stop loss managed by software risk engine only.
                </div>
                <div style="padding:8px 12px;background:rgba(239,68,68,0.06);border:1px solid rgba(239,68,68,0.15);border-radius:6px;font-size:13px;color:#D4D4D8;">
                    <strong style="color:#F87171;">Disabled</strong> \u2014 No broker orders. All exits managed by software risk engine. <em>\u26a0\ufe0f If bot crashes, no protection.</em>
                </div>
                </div>`
            },
            {
                heading: 'How It Works Per Broker',
                body: `<div style="display:grid;gap:8px;">
                <div style="padding:10px 14px;background:#1E1E24;border:1px solid rgba(0,188,212,0.15);border-radius:8px;font-size:13px;color:#D4D4D8;">
                    <strong style="color:#22D3EE;">Webull Official</strong><br>
                    \u2022 <strong>Stocks:</strong> OCO bracket (GTC) \u2014 SL uses STOP_LOSS, PT uses LIMIT. Survives overnight + bot crash. SL escalation cancels & replaces entire OCO.<br>
                    \u2022 <strong>Options:</strong> OCO bracket (DAY only) \u2014 SL uses STOP_LOSS_LIMIT. Expires at 4pm ET, auto re-placed each morning.<br>
                    \u2022 <strong>Trailing stop:</strong> Native server-side for stocks (survives crash). Not available for options.
                </div>
                <div style="padding:10px 14px;background:#1E1E24;border:1px solid rgba(99,102,241,0.15);border-radius:8px;font-size:13px;color:#D4D4D8;">
                    <strong style="color:#818CF8;">Schwab</strong><br>
                    \u2022 <strong>Stocks:</strong> OCO bracket (GTC) \u2014 same as Webull. SL + PT linked, auto-cancel on fill.<br>
                    \u2022 <strong>Options:</strong> OCO bracket (DAY) \u2014 SL uses STOP_LIMIT. Trim Order Type locked to Limit when PT is active.
                </div>
                <div style="padding:10px 14px;background:#1E1E24;border:1px solid rgba(239,68,68,0.15);border-radius:8px;font-size:13px;color:#D4D4D8;">
                    <strong style="color:#F87171;">IBKR (Interactive Brokers)</strong><br>
                    \u2022 <strong>Stocks & Options:</strong> Independent SL (STOP) + PT (LIMIT) via ib.placeOrder. GTC for stocks, DAY for options.<br>
                    \u2022 No OCO \u2014 software detects fill and cancels the other leg (~3-5s).<br>
                    \u2022 SL escalation: in-place modify via ib.placeOrder (zero-gap, no cancel needed).
                </div>
                <div style="padding:10px 14px;background:#1E1E24;border:1px solid rgba(0,255,136,0.15);border-radius:8px;font-size:13px;color:#D4D4D8;">
                    <strong style="color:#4ADE80;">Alpaca</strong><br>
                    \u2022 <strong>Stocks:</strong> OCO bracket (GTC) \u2014 native Alpaca OCO API.<br>
                    \u2022 <strong>Options:</strong> Not supported (Alpaca options API has no stop orders).
                </div>
                </div>`
            },
            {
                heading: 'Example: Both Mode (OCO)',
                body: `<div style="padding:10px 14px;background:#1E1E24;border:1px solid rgba(0,188,212,0.15);border-radius:8px;font-size:13px;color:#D4D4D8;">
                Entry: <strong style="color:#22D3EE;">BTO 10 AAPL @ $180</strong> | SL: <strong style="color:#F87171;">25%</strong> | PT1: <strong style="color:#4ADE80;">15%</strong><br><br>
                After fill, bot places OCO bracket:<br>
                \u2022 Leg 1 (PT): SELL LIMIT 10 AAPL @ <strong style="color:#4ADE80;">$207.00</strong> (+15%)<br>
                \u2022 Leg 2 (SL): SELL STOP 10 AAPL @ <strong style="color:#F87171;">$135.00</strong> (-25%)<br>
                \u2022 Linked via OCO \u2014 one fills, other auto-cancels<br><br>
                <strong style="color:#FBBF24;">If AAPL hits $207:</strong> PT fills \u2192 SL auto-cancelled \u2192 risk engine places PT2 bracket<br>
                <strong style="color:#F87171;">If AAPL drops to $135:</strong> SL fills \u2192 PT auto-cancelled \u2192 position closed
                </div>`
            },
            {
                heading: 'Important Notes',
                body: `<div style="display:grid;gap:6px;">
                <div style="padding:8px 12px;background:rgba(255,179,0,0.06);border:1px solid rgba(255,179,0,0.15);border-radius:6px;font-size:13px;color:#D4D4D8;">
                    \u26a0\ufe0f <strong style="color:#FBBF24;">Options DAY TIF:</strong> Option sell orders expire at 4pm ET. The risk engine automatically re-places them each morning.
                </div>
                <div style="padding:8px 12px;background:rgba(255,179,0,0.06);border:1px solid rgba(255,179,0,0.15);border-radius:6px;font-size:13px;color:#D4D4D8;">
                    \u26a0\ufe0f <strong style="color:#FBBF24;">Trim Order Type lock:</strong> When PT is active (Both or PT Only), Trim Order Type is automatically locked to Limit.
                </div>
                <div style="padding:8px 12px;background:rgba(255,179,0,0.06);border:1px solid rgba(255,179,0,0.15);border-radius:6px;font-size:13px;color:#D4D4D8;">
                    \u26a0\ufe0f <strong style="color:#FBBF24;">Dynamic SL still works:</strong> When risk engine escalates the SL, the broker bracket is automatically updated (cancel + re-place with new SL price).
                </div>
                </div>`
            }
        ]
    }
};

function showRiskHelp(topic) {
    const content = RISK_HELP_CONTENT[topic];
    if (!content) return;

    const existing = document.getElementById('risk-help-modal');
    if (existing) existing.remove();

    const styleTag = document.createElement('style');
    styleTag.id = 'risk-help-modal-styles';
    const existingStyle = document.getElementById('risk-help-modal-styles');
    if (existingStyle) existingStyle.remove();
    styleTag.textContent = `
        #risk-help-modal { position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.75);z-index:10000;display:flex;align-items:center;justify-content:center;padding:16px;backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);animation:riskHelpFadeIn 0.2s ease-out; }
        @keyframes riskHelpFadeIn { from{opacity:0} to{opacity:1} }
        @keyframes riskHelpSlideUp { from{opacity:0;transform:translateY(12px)} to{opacity:1;transform:translateY(0)} }
        .risk-help-panel { background:#18181B;border:1px solid #2D2D30;border-radius:20px;max-width:720px;width:100%;max-height:85vh;display:flex;flex-direction:column;box-shadow:0 25px 80px rgba(0,0,0,0.6),0 0 0 1px rgba(255,255,255,0.05) inset;animation:riskHelpSlideUp 0.25s ease-out; }
        .risk-help-header { padding:20px 24px 16px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #2D2D30;flex-shrink:0; }
        .risk-help-header h2 { font-size:18px;font-weight:700;color:#F4F4F5;margin:0;letter-spacing:-0.3px; }
        .risk-help-close { width:32px;height:32px;border-radius:10px;border:1px solid #3A3A3C;background:rgba(255,255,255,0.04);color:#A1A1AA;font-size:18px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all 0.15s; }
        .risk-help-close:hover { background:rgba(255,255,255,0.1);color:#F4F4F5;border-color:#52525B; }
        .risk-help-body { padding:24px;overflow-y:auto;flex:1;scrollbar-width:thin;scrollbar-color:#3A3A3C transparent; }
        .risk-help-body::-webkit-scrollbar { width:6px; }
        .risk-help-body::-webkit-scrollbar-track { background:transparent; }
        .risk-help-body::-webkit-scrollbar-thumb { background:#3A3A3C;border-radius:3px; }
        .risk-help-section { margin-bottom:24px; }
        .risk-help-section:last-child { margin-bottom:0; }
        .risk-help-section-heading { font-size:15px;font-weight:700;color:#E4E4E7;margin-bottom:10px;display:flex;align-items:center;gap:8px; }
        .risk-help-section-heading::before { content:'';width:3px;height:16px;border-radius:2px;background:linear-gradient(180deg,#818CF8,#6366F1);flex-shrink:0; }
        .risk-help-section-body { font-size:14px;color:#D4D4D8;line-height:1.7; }
        .risk-help-section-body strong { color:#F4F4F5;font-weight:600; }
        .risk-help-section-body em { color:#A78BFA;font-style:normal;font-weight:500; }
        .risk-help-diagram { margin-top:12px; }
        .risk-help-footer { padding:16px 24px;border-top:1px solid #2D2D30;flex-shrink:0; }
        .risk-help-footer-text { font-size:12px;color:#71717A;text-align:center; }
    `;
    document.head.appendChild(styleTag);

    let sectionsHtml = '';
    for (const section of content.sections) {
        sectionsHtml += `<div class="risk-help-section">`;
        if (section.heading) {
            sectionsHtml += `<div class="risk-help-section-heading">${section.heading}</div>`;
        }
        if (section.body) {
            sectionsHtml += `<div class="risk-help-section-body">${section.body}</div>`;
        }
        if (section.diagram) {
            sectionsHtml += `<div class="risk-help-diagram">${section.diagram}</div>`;
        }
        sectionsHtml += `</div>`;
    }

    const modal = document.createElement('div');
    modal.id = 'risk-help-modal';
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
    modal.innerHTML = `
        <div class="risk-help-panel">
            <div class="risk-help-header">
                <h2>${content.title}</h2>
                <button class="risk-help-close" onclick="document.getElementById('risk-help-modal').remove()" aria-label="Close">&times;</button>
            </div>
            <div class="risk-help-body">${sectionsHtml}</div>
            <div class="risk-help-footer">
                <div class="risk-help-footer-text">Click outside or press the X to close</div>
            </div>
        </div>`;
    document.body.appendChild(modal);

    modal.querySelector('.risk-help-panel').addEventListener('keydown', (e) => {
        if (e.key === 'Escape') modal.remove();
    });
}
