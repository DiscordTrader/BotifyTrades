console.log('[BrokerStore] Script loading...');

const BrokerStore = (function() {
    console.log('[BrokerStore] Module initializing...');
    const STORAGE_KEY = 'botify_selected_broker';
    const REFRESH_INTERVAL = 30000;
    
    let state = {
        selectedBroker: null,
        selectedRegion: 'USA',
        brokers: [],
        byRegion: { USA: [], Canada: [], UK_EU: [] },
        lastRefresh: null,
        isLoading: false,
        listeners: []
    };
    
    let refreshTimer = null;
    
    function init() {
        console.log('[BrokerStore] init() called');
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved) {
            try {
                const parsed = JSON.parse(saved);
                state.selectedBroker = parsed.broker || null;
                state.selectedRegion = parsed.region || 'USA';
            } catch (e) {}
        }
        
        loadBrokerStates();
        startAutoRefresh();
        
        window.addEventListener('storage', function(e) {
            if (e.key === STORAGE_KEY) {
                const parsed = JSON.parse(e.newValue || '{}');
                state.selectedBroker = parsed.broker || null;
                state.selectedRegion = parsed.region || 'USA';
                notifyListeners('selection_changed');
            }
        });
    }
    
    async function loadBrokerStates() {
        state.isLoading = true;
        notifyListeners('loading');
        console.log('[BrokerStore] Loading broker states...');
        
        try {
            const response = await fetch('/api/v2/broker-states');
            const data = await response.json();
            
            console.log('[BrokerStore] API response:', data);
            
            // Handle auth error
            if (data.error) {
                console.error('[BrokerStore] API error:', data.error);
                notifyListeners('error', data.error);
                return;
            }
            
            if (data.success) {
                state.brokers = data.states || [];
                // Filter out India region
                const byRegion = data.by_region || { USA: [], Canada: [], UK_EU: [] };
                state.byRegion = { USA: byRegion.USA || [], Canada: byRegion.Canada || [], UK_EU: byRegion.UK_EU || [] };
                state.lastRefresh = new Date();
                
                console.log('[BrokerStore] Loaded', state.brokers.length, 'brokers:', state.byRegion);
                
                // Auto-refresh if no broker states found (first load)
                if (state.brokers.length === 0) {
                    console.log('[BrokerStore] No states found, triggering refresh-all...');
                    await refreshAll();
                    return;
                }
                
                notifyListeners('data_loaded');
            } else {
                console.warn('[BrokerStore] API returned success=false');
            }
        } catch (error) {
            console.error('[BrokerStore] Failed to load states:', error);
            notifyListeners('error', error);
        } finally {
            state.isLoading = false;
        }
    }
    
    async function refreshBroker(brokerName) {
        try {
            const response = await fetch(`/api/v2/broker-states/${brokerName}/refresh`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            const data = await response.json();
            
            if (data.success) {
                const idx = state.brokers.findIndex(b => b.broker_name === brokerName);
                if (idx >= 0) {
                    state.brokers[idx] = { ...state.brokers[idx], ...data.state };
                }
                notifyListeners('broker_refreshed', brokerName);
            }
            return data;
        } catch (error) {
            console.error(`[BrokerStore] Failed to refresh ${brokerName}:`, error);
            return { success: false, error: error.message };
        }
    }
    
    async function refreshAll() {
        try {
            const response = await fetch('/api/v2/broker-states/refresh-all', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            const data = await response.json();
            
            if (data.success) {
                await loadBrokerStates();
                notifyListeners('all_refreshed');
            }
            return data;
        } catch (error) {
            console.error('[BrokerStore] Failed to refresh all:', error);
            return { success: false, error: error.message };
        }
    }
    
    function selectBroker(brokerName, region) {
        state.selectedBroker = brokerName;
        if (region) state.selectedRegion = region;
        
        localStorage.setItem(STORAGE_KEY, JSON.stringify({
            broker: brokerName,
            region: state.selectedRegion
        }));
        
        notifyListeners('selection_changed');
    }
    
    function selectRegion(region) {
        state.selectedRegion = region;
        
        const regionBrokers = state.byRegion[region] || [];
        const connected = regionBrokers.find(b => b.is_connected);
        if (connected) {
            state.selectedBroker = connected.broker_name;
        } else if (regionBrokers.length > 0) {
            state.selectedBroker = regionBrokers[0].broker_name;
        }
        
        localStorage.setItem(STORAGE_KEY, JSON.stringify({
            broker: state.selectedBroker,
            region: region
        }));
        
        notifyListeners('region_changed');
    }
    
    function getSelectedBroker() {
        return state.brokers.find(b => b.broker_name === state.selectedBroker) || null;
    }
    
    function getConnectedBrokers() {
        return state.brokers.filter(b => b.is_connected);
    }
    
    function getBrokersByRegion(region) {
        return state.byRegion[region] || [];
    }
    
    function subscribe(callback) {
        state.listeners.push(callback);
        return function unsubscribe() {
            state.listeners = state.listeners.filter(cb => cb !== callback);
        };
    }
    
    function notifyListeners(event, data) {
        state.listeners.forEach(cb => {
            try {
                cb(event, state, data);
            } catch (e) {
                console.error('[BrokerStore] Listener error:', e);
            }
        });
    }
    
    function startAutoRefresh() {
        if (refreshTimer) clearInterval(refreshTimer);
        refreshTimer = setInterval(loadBrokerStates, REFRESH_INTERVAL);
    }
    
    function stopAutoRefresh() {
        if (refreshTimer) {
            clearInterval(refreshTimer);
            refreshTimer = null;
        }
    }
    
    function formatCurrency(amount, currency) {
        const symbols = { USD: '$', CAD: 'C$', INR: '₹' };
        const symbol = symbols[currency] || '$';
        return `${symbol}${parseFloat(amount || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }
    
    function renderBrokerSelector(containerId, options = {}) {
        const container = document.getElementById(containerId);
        if (!container) return;
        
        const showRegionTabs = options.showRegionTabs !== false;
        const onSelect = options.onSelect || function() {};
        
        let html = '';
        
        if (showRegionTabs) {
            html += `
                <div class="broker-region-tabs" style="display: flex; gap: 8px; margin-bottom: 12px;">
                    ${['USA', 'Canada', 'UK_EU'].map(region => `
                        <button class="region-tab ${state.selectedRegion === region ? 'active' : ''}" 
                                data-region="${region}"
                                style="padding: 6px 16px; border-radius: 6px; border: 1px solid var(--border); 
                                       background: ${state.selectedRegion === region ? 'var(--primary)' : 'var(--bg-card)'};
                                       color: ${state.selectedRegion === region ? 'white' : 'var(--text-primary)'};
                                       cursor: pointer; font-size: 0.875rem;">
                            ${region === 'USA' ? '🇺🇸 USA' : region === 'Canada' ? '🇨🇦 Canada' : '🇬🇧 UK / EU'}
                        </button>
                    `).join('')}
                </div>
            `;
        }
        
        const regionBrokers = state.byRegion[state.selectedRegion] || [];
        
        html += `
            <div class="broker-cards" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px;">
                ${regionBrokers.length === 0 ? `
                    <div style="grid-column: 1/-1; text-align: center; padding: 24px; color: var(--text-muted);">
                        No brokers configured for ${state.selectedRegion}
                    </div>
                ` : regionBrokers.map(broker => `
                    <div class="broker-card ${state.selectedBroker === broker.broker_name ? 'selected' : ''} ${broker.is_connected ? 'connected' : 'disconnected'}"
                         data-broker="${broker.broker_name}"
                         style="padding: 16px; border-radius: 8px; border: 2px solid ${state.selectedBroker === broker.broker_name ? 'var(--primary)' : 'var(--border)'};
                                background: var(--bg-card); cursor: pointer; transition: all 0.2s;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                            <span style="font-weight: 600; text-transform: capitalize;">${broker.broker_name.replace('_', ' ')}</span>
                            <span style="width: 10px; height: 10px; border-radius: 50%; background: ${broker.is_connected ? '#10b981' : '#6b7280'};"></span>
                        </div>
                        <div style="font-size: 1.25rem; font-weight: 700; color: ${broker.is_connected ? 'var(--text-primary)' : 'var(--text-muted)'};">
                            ${broker.is_connected ? formatCurrency(broker.balance, broker.currency) : 'Disconnected'}
                        </div>
                        ${!broker.is_connected && broker.reason ? `
                            <div style="font-size: 0.7rem; color: #ef4444; margin-top: 4px; line-height: 1.3;">
                                ${broker.reason}
                            </div>
                        ` : ''}
                        ${broker.is_connected && broker.buying_power ? `
                            <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 4px;">
                                Buying Power: ${formatCurrency(broker.buying_power, broker.currency)}
                            </div>
                        ` : ''}
                        ${broker.is_paper ? `
                            <div style="display: inline-block; padding: 2px 6px; background: var(--warning); color: black; 
                                        border-radius: 4px; font-size: 0.625rem; margin-top: 8px;">PAPER</div>
                        ` : ''}
                    </div>
                `).join('')}
            </div>
        `;
        
        container.innerHTML = html;
        
        container.querySelectorAll('.region-tab').forEach(tab => {
            tab.addEventListener('click', function() {
                selectRegion(this.dataset.region);
                renderBrokerSelector(containerId, options);
            });
        });
        
        container.querySelectorAll('.broker-card').forEach(card => {
            card.addEventListener('click', function() {
                const brokerName = this.dataset.broker;
                selectBroker(brokerName, state.selectedRegion);
                renderBrokerSelector(containerId, options);
                onSelect(brokerName, getSelectedBroker());
            });
        });
    }
    
    function getAllStates() {
        const result = {};
        state.brokers.forEach(broker => {
            result[broker.broker_name] = broker;
        });
        return result;
    }
    
    function getSelected() {
        return state.selectedBroker;
    }
    
    function setSelected(brokerName) {
        selectBroker(brokerName, state.selectedRegion);
    }
    
    function onUpdate(callback) {
        return subscribe(callback);
    }
    
    return {
        init,
        loadBrokerStates,
        refreshBroker,
        refreshAll,
        selectBroker,
        selectRegion,
        getState: () => ({ ...state }),
        getSelected,
        setSelected,
        getSelectedBroker,
        getConnectedBrokers,
        getBrokersByRegion,
        getAllStates,
        subscribe,
        onUpdate,
        startAutoRefresh,
        stopAutoRefresh,
        formatCurrency,
        renderBrokerSelector
    };
})();
