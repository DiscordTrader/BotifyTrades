// Main JavaScript for Discord Trading Bot Control Panel

// Update bot status indicator
async function updateBotStatus() {
    try {
        const indicator = document.getElementById('bot-status');
        const userSpan = document.getElementById('bot-user');
        
        // Check if elements exist (they won't exist on pages like /options)
        if (!indicator || !userSpan) {
            return; // Silently skip update if elements don't exist
        }
        
        const status = await fetch('/api/status').then(r => r.json());
        
        if (status.connected) {
            indicator.style.background = '#10b981';
            userSpan.textContent = status.bot_user;
        } else {
            indicator.style.background = '#ef4444';
            userSpan.textContent = 'Disconnected';
        }
    } catch (error) {
        console.error('Failed to update bot status:', error);
    }
}

// Update license status indicator
async function updateLicenseStatus() {
    try {
        const badge = document.getElementById('license-badge');
        const text = document.getElementById('license-text');
        
        // Check if elements exist
        if (!badge || !text) {
            return;
        }
        
        const response = await fetch('/api/license/status');
        const data = await response.json();
        
        // Remove existing status classes
        badge.classList.remove('warning', 'expired', 'inactive');
        
        if (data.is_valid) {
            const days = data.days_remaining || 0;
            
            if (days <= 7) {
                badge.classList.add('expired');
                text.textContent = `${days}d left`;
            } else if (days <= 30) {
                badge.classList.add('warning');
                text.textContent = `${days}d left`;
            } else {
                text.textContent = `${days}d`;
            }
        } else if (data.is_expired) {
            badge.classList.add('expired');
            text.textContent = 'Expired';
        } else {
            badge.classList.add('inactive');
            text.textContent = 'No License';
        }
    } catch (error) {
        console.error('Failed to update license status:', error);
        const badge = document.getElementById('license-badge');
        const text = document.getElementById('license-text');
        if (badge && text) {
            badge.classList.add('inactive');
            text.textContent = '--';
        }
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    // Highlight active nav link (immediate)
    const currentPath = window.location.pathname;
    document.querySelectorAll('.nav-link').forEach(link => {
        if (link.getAttribute('href') === currentPath) {
            link.classList.add('active');
        }
    });
    
    // Update license status immediately
    updateLicenseStatus();
    
    // Delay bot status polling to allow bot initialization (15 second startup window)
    updateBotStatus();
    setTimeout(() => {
        setInterval(updateBotStatus, 10000); // Start polling after 15 seconds
        setInterval(updateLicenseStatus, 60000); // Update license status every minute
    }, 15000);
});

// Utility functions
function showMessage(message, type = 'success') {
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${type}`;
    msgDiv.textContent = message;
    
    document.body.appendChild(msgDiv);
    
    setTimeout(() => {
        msgDiv.remove();
    }, 3000);
}

function confirmAction(message) {
    return confirm(message);
}
