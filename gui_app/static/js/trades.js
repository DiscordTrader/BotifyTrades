// Live Trades Monitoring JavaScript

let currentFilter = 'all';
let refreshInterval = null;

function initTradesMonitor() {
    loadTrades();
    loadOpenOrders();
    loadSummary();
    
    // Auto-refresh every 30 seconds
    refreshInterval = setInterval(() => {
        loadTrades();
        loadOpenOrders();
        loadSummary();
    }, 30000);
    
    // Setup filter buttons
    setupFilters();
}

function setupFilters() {
    const filterButtons = document.querySelectorAll('.filter-btn');
    filterButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            filterButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentFilter = btn.dataset.filter;
            loadTrades();
        });
    });
}

async function loadTrades() {
    const container = document.getElementById('trades-container');
    
    try {
        let url = '/api/trades?limit=100';
        if (currentFilter !== 'all') {
            url += `&status=${currentFilter.toUpperCase()}`;
        }
        
        const trades = await fetch(url).then(r => r.json());
        
        if (trades.length === 0) {
            container.innerHTML = '<div class="no-data">No trades found</div>';
            return;
        }
        
        container.innerHTML = trades.map(trade => renderTradeCard(trade)).join('');
        
    } catch (error) {
        console.error('Failed to load trades:', error);
        container.innerHTML = '<div class="error">Failed to load trades</div>';
    }
}

function renderTradeCard(trade) {
    const isOpen = trade.status === 'OPEN';
    const isClosed = trade.status === 'CLOSED';
    const isProfitable = trade.pnl && trade.pnl > 0;
    
    const statusClass = isOpen ? 'open' : 'closed';
    const pnlClass = isProfitable ? 'profit' : 'loss';
    
    const pnl = trade.pnl || 0;
    const pnlPercent = trade.pnl_percent || 0;
    
    const executedTime = trade.executed_at ? new Date(trade.executed_at).toLocaleString() : 'N/A';
    const closedTime = trade.closed_at ? new Date(trade.closed_at).toLocaleString() : null;
    
    return `
        <div class="trade-card ${statusClass}">
            <div class="trade-header">
                <span class="status-icon">${isOpen ? '🟢' : '🔵'}</span>
                <div class="trade-title">
                    ${trade.symbol} ${trade.asset_type === 'option' ? '(Option)' : '(Stock)'}
                </div>
                <span class="trade-status">${trade.status}</span>
            </div>
            
            <div class="trade-details">
                <div class="detail-row">
                    <span><strong>Action:</strong> ${trade.action}</span>
                    <span><strong>Quantity:</strong> ${trade.quantity}</span>
                    <span><strong>Price:</strong> $${parseFloat(trade.price || 0).toFixed(2)}</span>
                </div>
                
                <div class="detail-row">
                    <span><strong>Broker:</strong> ${trade.broker.toUpperCase()}</span>
                    <span><strong>Channel:</strong> ${trade.discord_channel_id}</span>
                </div>
                
                ${isOpen ? `
                    <div class="detail-row">
                        <span><strong>Current P&L:</strong> <span class="${pnlClass}">$${pnl.toFixed(2)} (${pnlPercent.toFixed(2)}%)</span></span>
                    </div>
                ` : ''}
                
                ${isClosed && trade.pnl != null ? `
                    <div class="detail-row">
                        <span><strong>Final P&L:</strong> <span class="${pnlClass}">$${pnl.toFixed(2)} (${pnlPercent.toFixed(2)}%)</span></span>
                    </div>
                ` : ''}
                
                <div class="trade-time">
                    📅 Executed: ${executedTime}
                    ${closedTime ? ` | Closed: ${closedTime}` : ''}
                </div>
            </div>
        </div>
    `;
}

async function loadOpenOrders() {
    const container = document.getElementById('open-orders-container');
    
    try {
        const orders = await fetch('/api/webull/orders').then(r => r.json());
        
        if (!orders || orders.length === 0) {
            container.innerHTML = '<div class="no-data">No open orders</div>';
            return;
        }
        
        container.innerHTML = orders.map(order => renderOrderCard(order)).join('');
        
    } catch (error) {
        console.error('Failed to load open orders:', error);
        container.innerHTML = '<div class="error">Failed to load open orders</div>';
    }
}

function renderOrderCard(order) {
    return `
        <div class="trade-card open-order">
            <div class="trade-header">
                <span class="status-icon">⏳</span>
                <div class="trade-title">
                    ${order.symbol} - ${order.action}
                </div>
                <span class="trade-status">${order.status}</span>
            </div>
            
            <div class="trade-details">
                <div class="detail-row">
                    <span><strong>Order ID:</strong> ${order.order_id}</span>
                    <span><strong>Type:</strong> ${order.order_type}</span>
                </div>
                
                <div class="detail-row">
                    <span><strong>Quantity:</strong> ${order.quantity}</span>
                    <span><strong>Filled:</strong> ${order.filled_quantity}</span>
                    <span><strong>Limit Price:</strong> $${parseFloat(order.limit_price || 0).toFixed(2)}</span>
                </div>
                
                <div class="trade-time">
                    📅 Created: ${order.created_time}
                </div>
            </div>
        </div>
    `;
}

async function loadSummary() {
    try {
        const data = await fetch('/api/trades/summary').then(r => r.json());
        
        // Update summary stats
        document.getElementById('open-count').textContent = data.open_count || 0;
        document.getElementById('closed-count').textContent = data.closed_count || 0;
        
        const totalPnl = data.total_pnl || 0;
        const pnlElement = document.getElementById('total-pnl');
        pnlElement.textContent = `$${totalPnl.toFixed(2)}`;
        pnlElement.className = totalPnl >= 0 ? 'profit' : 'loss';
        
    } catch (error) {
        console.error('Failed to load summary:', error);
    }
}

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    if (refreshInterval) {
        clearInterval(refreshInterval);
    }
});
