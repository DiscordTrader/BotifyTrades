/**
 * Agent Dashboard — SSE client, pipeline visualization, cost tracking, diff viewer
 */

const API_BASE = window.API_BASE || '';
let eventSource = null;
let currentTaskId = null;
let reconnectDelay = 1000;
let currentDetailData = null;
let tokenTotals = {};
let runningCost = 0;
const MAX_RECONNECT_DELAY = 30000;

const PIPELINE_ORDER = ['orchestrator', 'architect', 'approval', 'developer', 'tester', 'reviewer', 'devops'];
const PHASE_TO_PIPELINE = {
    orchestration: 'orchestrator',
    architecture: 'architect',
    awaiting_approval: 'approval',
    development: 'developer',
    testing: 'tester',
    review: 'reviewer',
    deployment: 'devops',
};

// ── SSE Connection ──
function connectSSE(taskId) {
    if (eventSource) {
        eventSource.close();
    }

    let url = API_BASE + '/api/stream';
    if (taskId) url += '?task_id=' + taskId;

    eventSource = new EventSource(url);
    reconnectDelay = 1000;

    eventSource.onopen = function() {
        console.log('[Agents] SSE connected');
    };

    eventSource.addEventListener('agent_state', function(e) {
        const data = JSON.parse(e.data);
        updateAgentCard(data);
        trackTokens(data);
    });

    eventSource.addEventListener('status', function(e) {
        const data = JSON.parse(e.data);
        addMessage(data);
        updatePipelineFromMessage(data);
    });

    eventSource.addEventListener('handoff', function(e) {
        const data = JSON.parse(e.data);
        addMessage(data);
        updatePipelineFromMessage(data);
        trackCostFromMessage(data);
    });

    eventSource.addEventListener('error', function(e) {
        if (e.data) {
            const data = JSON.parse(e.data);
            addMessage(data);
        }
    });

    eventSource.addEventListener('task', function(e) {
        const data = JSON.parse(e.data);
        addMessage(data);
    });

    eventSource.addEventListener('task_update', function(e) {
        refreshTasks();
    });

    eventSource.addEventListener('approval_required', function(e) {
        const data = JSON.parse(e.data);
        addMessage(data);
        showApprovalBar(data.task_id);
        setPipelineNode('approval', 'active');
    });

    eventSource.onerror = function() {
        console.log('[Agents] SSE disconnected, reconnecting in ' + reconnectDelay + 'ms');
        eventSource.close();
        setTimeout(function() {
            connectSSE(taskId);
            reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
        }, reconnectDelay);
    };
}

// ── Pipeline Flow Visualization ──
function setPipelineNode(name, state) {
    const node = document.querySelector('.pipeline-node[data-pipeline="' + name + '"]');
    if (!node) return;
    node.classList.remove('active', 'done');
    if (state === 'active') node.classList.add('active');
    if (state === 'done') node.classList.add('done');

    const idx = PIPELINE_ORDER.indexOf(name);
    if (idx > 0 && (state === 'active' || state === 'done')) {
        const prevName = PIPELINE_ORDER[idx - 1];
        const connector = document.querySelector('.pipeline-connector[data-after="' + prevName + '"]');
        if (connector) {
            connector.classList.add('active');
            if (state === 'active') connector.classList.add('flowing');
            else connector.classList.remove('flowing');
        }
        const prevNode = document.querySelector('.pipeline-node[data-pipeline="' + prevName + '"]');
        if (prevNode && !prevNode.classList.contains('active')) {
            prevNode.classList.add('done');
        }
    }
}

function resetPipeline() {
    document.querySelectorAll('.pipeline-node').forEach(function(n) {
        n.classList.remove('active', 'done');
    });
    document.querySelectorAll('.pipeline-connector').forEach(function(c) {
        c.classList.remove('active', 'flowing');
    });
}

function updatePipelineFromMessage(data) {
    const content = (data.content || '').toLowerCase();
    if (content.includes('orchestrator analyzing')) setPipelineNode('orchestrator', 'active');
    else if (content.includes('architect designing')) setPipelineNode('architect', 'active');
    else if (content.includes('awaiting your approval')) setPipelineNode('approval', 'active');
    else if (content.includes('developer writing')) setPipelineNode('developer', 'active');
    else if (content.includes('tester validating')) setPipelineNode('tester', 'active');
    else if (content.includes('reviewer checking')) setPipelineNode('reviewer', 'active');
    else if (content.includes('devops deploying')) setPipelineNode('devops', 'active');
    else if (content.includes('task complete')) {
        setPipelineNode('devops', 'done');
        updatePipelineStatus('Complete', '#10B981');
    }
    else if (content.includes('task failed') || content.includes('pipeline failed')) {
        updatePipelineStatus('Failed', '#EF4444');
    }
}

function updatePipelineStatus(text, color) {
    const badge = document.getElementById('pipeline-status');
    badge.textContent = text;
    badge.style.background = 'rgba(' + hexToRgb(color) + ', 0.15)';
    badge.style.color = color;
}

function hexToRgb(hex) {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return r + ', ' + g + ', ' + b;
}

// ── Agent Card Updates ──
function updateAgentCard(state) {
    const card = document.querySelector('.agent-card[data-agent="' + state.name + '"]');
    if (!card) return;

    const isActive = state.status !== 'idle' && state.status !== 'done';
    card.classList.toggle('active', isActive);

    const statusText = card.querySelector('.agent-status-text');
    if (statusText) statusText.textContent = state.status;

    const progressBar = card.querySelector('.agent-progress-bar');
    if (progressBar) progressBar.style.width = state.progress_pct + '%';

    const tokens = card.querySelector('.agent-tokens');
    if (tokens && state.token_usage) {
        const total = (state.token_usage.input || 0) + (state.token_usage.output || 0);
        tokens.textContent = formatTokens(total);
    }
}

function formatTokens(n) {
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M tok';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'k tok';
    return n + ' tok';
}

// ── Token & Cost Tracking ──
function trackTokens(state) {
    if (!state.token_usage) return;
    const total = (state.token_usage.input || 0) + (state.token_usage.output || 0);
    tokenTotals[state.name] = total;

    const el = document.querySelector('[data-token-agent="' + state.name + '"]');
    if (el) el.textContent = formatTokens(total);

    let grandTotal = 0;
    Object.keys(tokenTotals).forEach(function(k) { grandTotal += tokenTotals[k]; });
    document.getElementById('token-total').textContent = 'Total: ' + formatTokens(grandTotal);

    const costEl = document.querySelector('[data-agent-cost="' + state.name + '"]');
    if (costEl && state.cost_usd) {
        costEl.textContent = '$' + state.cost_usd.toFixed(4);
    }
}

function trackCostFromMessage(data) {
    if (data.metadata && data.metadata.cost_usd) {
        runningCost += data.metadata.cost_usd;
        const bar = document.getElementById('running-cost-bar');
        bar.style.display = '';
        document.getElementById('running-cost-value').textContent = '$' + runningCost.toFixed(4);
    }
}

// ── Message Stream ──
function addMessage(data) {
    const list = document.getElementById('message-list');
    const empty = list.querySelector('.empty-state');
    if (empty) empty.remove();

    const filter = document.getElementById('message-filter').value;
    const search = (document.getElementById('message-search').value || '').toLowerCase();
    const typeVisible = filter === 'all' || data.message_type === filter;
    const searchVisible = !search || (data.content || '').toLowerCase().includes(search)
        || (data.from_agent || '').toLowerCase().includes(search);

    const item = document.createElement('div');
    item.className = 'message-item type-' + data.message_type;
    if (!typeVisible || !searchVisible) item.style.display = 'none';
    item.setAttribute('data-type', data.message_type);
    item.setAttribute('data-content', (data.content || '').toLowerCase());
    item.onclick = function() { showMessageDetail(data); };

    const time = data.timestamp ? new Date(data.timestamp).toLocaleTimeString() : '';
    const from = data.from_agent || '?';
    const to = data.to_agent || '?';
    const content = (data.content || '').substring(0, 200);
    const typeBadge = '<span class="message-type-badge">' + escapeHtml(data.message_type || '') + '</span>';

    item.innerHTML =
        '<div class="message-header">' +
            '<span class="message-route">' +
                '<span class="from-agent">' + escapeHtml(from.toUpperCase()) + '</span>' +
                '<span class="arrow">&rarr;</span>' +
                '<span class="to-agent">' + escapeHtml(to.toUpperCase()) + '</span>' +
                typeBadge +
            '</span>' +
            '<span class="message-time">' + time + '</span>' +
        '</div>' +
        '<div class="message-content">' + escapeHtml(content) + '</div>';

    list.appendChild(item);

    if (document.getElementById('auto-scroll').checked) {
        list.scrollTop = list.scrollHeight;
    }
}

function filterMessages() {
    const filter = document.getElementById('message-filter').value;
    const search = (document.getElementById('message-search').value || '').toLowerCase();
    document.querySelectorAll('.message-item').forEach(function(item) {
        const type = item.getAttribute('data-type');
        const content = item.getAttribute('data-content') || '';
        const typeOk = filter === 'all' || type === filter;
        const searchOk = !search || content.includes(search);
        item.style.display = (typeOk && searchOk) ? '' : 'none';
    });
}

function searchMessages() {
    filterMessages();
}

// ── Message Detail with Tabs ──
function showMessageDetail(data) {
    currentDetailData = data;
    switchDetailTab('content');
    var feedbackBar = document.getElementById('feedback-bar');
    if (data.message_type === 'handoff' || data.message_type === 'status') {
        feedbackBar.style.display = '';
        feedbackBar.querySelectorAll('.btn-feedback').forEach(function(b) { b.classList.remove('active'); });
    } else {
        feedbackBar.style.display = 'none';
    }
}

function switchDetailTab(tab) {
    document.querySelectorAll('.detail-tab').forEach(function(t) {
        t.classList.toggle('active', t.getAttribute('data-tab') === tab);
    });

    const detail = document.getElementById('detail-content');

    if (!currentDetailData) {
        detail.innerHTML = '<div class="empty-state">Select a message to view details</div>';
        return;
    }

    const data = currentDetailData;

    if (tab === 'content') {
        let html = '<div class="detail-section">' +
            '<h4>Message</h4>' +
            '<p><strong>From:</strong> ' + escapeHtml(data.from_agent) + ' &rarr; ' + escapeHtml(data.to_agent) + '</p>' +
            '<p><strong>Type:</strong> ' + escapeHtml(data.message_type) + '</p>' +
            '<p><strong>Time:</strong> ' + (data.timestamp || 'N/A') + '</p>' +
            '</div>';

        html += '<div class="detail-section">' +
            '<h4>Content</h4>' +
            '<pre>' + escapeHtml(data.content || '(empty)') + '</pre>' +
            '</div>';

        detail.innerHTML = html;
    }
    else if (tab === 'diff') {
        detail.innerHTML = '';
        if (data.metadata && (data.metadata.diff || data.metadata.files)) {
            DiffViewer.renderFromMetadata(data.metadata, detail);
        } else if (data.content && data.content.includes('@@') && data.content.includes('+++')) {
            DiffViewer.render(data.content, detail);
        } else {
            detail.innerHTML = '<div class="empty-state">No diff data in this message</div>';
        }
    }
    else if (tab === 'metadata') {
        if (data.metadata && Object.keys(data.metadata).length > 0) {
            detail.innerHTML = '<div class="detail-section">' +
                '<h4>Metadata</h4>' +
                '<pre>' + escapeHtml(JSON.stringify(data.metadata, null, 2)) + '</pre>' +
                '</div>';
        } else {
            detail.innerHTML = '<div class="empty-state">No metadata</div>';
        }
    }
}

// ── Cost Estimation ──
function estimateCost() {
    const desc = document.getElementById('task-description').value.trim();
    const display = document.getElementById('cost-estimate-display');

    if (desc.length < 10) {
        display.classList.remove('visible');
        return;
    }

    fetch(API_BASE + '/api/config')
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success && data.config && data.config.cost_estimate) {
            var est = data.config.cost_estimate;
            document.getElementById('cost-range-text').textContent =
                '$' + est.min.toFixed(2) + ' - $' + est.max.toFixed(2);
            display.classList.add('visible');
        }
    })
    .catch(function() {});
}

// ── Task Submission ──
function submitTask() {
    var desc = document.getElementById('task-description').value.trim();
    if (!desc) return;

    var btn = document.getElementById('submit-task-btn');
    btn.disabled = true;

    resetPipeline();
    tokenTotals = {};
    runningCost = 0;
    document.getElementById('running-cost-bar').style.display = 'none';
    document.getElementById('running-cost-value').textContent = '$0.0000';
    document.querySelectorAll('[data-token-agent]').forEach(function(el) { el.textContent = '0'; });
    document.getElementById('token-total').textContent = 'Total: 0 tok';

    var body = {
        description: desc,
        priority: document.getElementById('task-priority').value,
        approval_mode: document.getElementById('task-approval').value,
    };

    fetch(API_BASE + '/api/tasks', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify(body),
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success) {
            currentTaskId = data.task_id;
            document.getElementById('task-description').value = '';
            document.getElementById('cost-estimate-display').classList.remove('visible');

            if (data.cost_estimate) {
                var badge = document.getElementById('cost-estimate-badge');
                badge.textContent = '~$' + data.cost_estimate.min.toFixed(2) + '-' + data.cost_estimate.max.toFixed(2);
                badge.style.display = '';
                setTimeout(function() { badge.style.display = 'none'; }, 8000);
            }

            updatePipelineStatus('Running', '#3B82F6');
            document.getElementById('running-cost-bar').style.display = '';

            document.getElementById('message-list').innerHTML = '';

            connectSSE(data.task_id);
            refreshTasks();
        } else {
            alert('Error: ' + (data.error || 'Unknown error'));
        }
    })
    .catch(function(err) {
        alert('Failed to submit task: ' + err);
    })
    .finally(function() {
        btn.disabled = false;
    });
}

// ── Task History ──
function refreshTasks() {
    fetch(API_BASE + '/api/tasks?limit=10')
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (!data.success) return;
        var list = document.getElementById('task-history-list');
        if (data.tasks.length === 0) {
            list.innerHTML = '<div class="empty-state">No tasks yet</div>';
            return;
        }
        list.innerHTML = data.tasks.map(function(t) {
            var desc = (t.description || '').substring(0, 50);
            var costStr = '';
            if (t.actual_cost && t.actual_cost.total) {
                costStr = '<span class="task-cost">$' + t.actual_cost.total.toFixed(4) + '</span>';
            }
            var phaseStr = '';
            if (t.current_phase && t.status === 'in_progress') {
                phaseStr = '<span class="task-phase">' + escapeHtml(t.current_phase) + '</span>';
            }
            var versionStr = '';
            if (t.version) {
                versionStr = '<span class="task-version-badge">v' + escapeHtml(t.version) + '</span>';
            }
            var rollbackStr = '';
            if (t.status === 'complete' && t.git_commit_sha) {
                rollbackStr = '<button class="btn-rollback" onclick="event.stopPropagation(); rollbackTask(\'' + t.id + '\')" title="Revert this commit">Rollback</button> ';
            }
            return '<div class="task-history-item" onclick="viewTask(\'' + t.id + '\')">' +
                '<span class="task-desc">' + escapeHtml(desc) + '</span>' +
                phaseStr + versionStr + costStr + rollbackStr +
                '<span class="task-status-badge ' + t.status + '">' + t.status.replace('_', ' ') + '</span>' +
                '</div>';
        }).join('');
    })
    .catch(function() {});
}

function viewTask(taskId) {
    currentTaskId = taskId;
    document.getElementById('message-list').innerHTML = '';
    resetPipeline();

    fetch(API_BASE + '/api/tasks/' + taskId)
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (!data.success) return;

        if (data.task.current_phase) {
            var pipeNode = PHASE_TO_PIPELINE[data.task.current_phase];
            if (pipeNode) {
                var idx = PIPELINE_ORDER.indexOf(pipeNode);
                for (var i = 0; i < idx; i++) {
                    setPipelineNode(PIPELINE_ORDER[i], 'done');
                }
                if (data.task.status === 'complete') {
                    setPipelineNode(pipeNode, 'done');
                } else {
                    setPipelineNode(pipeNode, 'active');
                }
            }
        }

        if (data.task.status === 'complete') {
            updatePipelineStatus('Complete', '#10B981');
        } else if (data.task.status === 'failed') {
            updatePipelineStatus('Failed', '#EF4444');
        } else if (data.task.status === 'in_progress') {
            updatePipelineStatus('Running', '#3B82F6');
        } else if (data.task.status === 'awaiting_approval') {
            updatePipelineStatus('Awaiting Approval', '#F59E0B');
        } else {
            updatePipelineStatus(data.task.status, '#8B949E');
        }

        if (data.task.actual_cost && data.task.actual_cost.total) {
            runningCost = data.task.actual_cost.total;
            document.getElementById('running-cost-bar').style.display = '';
            document.getElementById('running-cost-value').textContent = '$' + runningCost.toFixed(4);
        }

        data.messages.forEach(function(m) { addMessage(m); });
        if (data.task.status === 'awaiting_approval') {
            showApprovalBar(taskId);
        }
        connectSSE(taskId);
    });
}

// ── Approval ──
function showApprovalBar(taskId) {
    currentTaskId = taskId;
    document.getElementById('approval-bar').style.display = '';
}

function approveTask() {
    if (!currentTaskId) return;
    fetch(API_BASE + '/api/tasks/' + currentTaskId + '/approve', {
        method: 'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
    })
    .then(function(r) { return r.json(); })
    .then(function() {
        document.getElementById('approval-bar').style.display = 'none';
        setPipelineNode('approval', 'done');
        refreshTasks();
    });
}

function rejectTask() {
    if (!currentTaskId) return;
    var reason = prompt('Rejection reason (optional):') || '';
    fetch(API_BASE + '/api/tasks/' + currentTaskId + '/reject', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify({ reason: reason }),
    })
    .then(function(r) { return r.json(); })
    .then(function() {
        document.getElementById('approval-bar').style.display = 'none';
        updatePipelineStatus('Rejected', '#EF4444');
        refreshTasks();
    });
}

// ── Rollback ──
function rollbackTask(taskId) {
    if (!confirm('Revert the commit from this task? This creates a new revert commit.')) return;
    fetch(API_BASE + '/api/tasks/' + taskId + '/rollback', {
        method: 'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success) {
            alert('Rollback successful! Revert commit: ' + (data.revert_commit || '').substring(0, 8));
            refreshTasks();
        } else {
            alert('Rollback failed: ' + (data.error || 'Unknown error'));
        }
    })
    .catch(function(err) {
        alert('Rollback error: ' + err);
    });
}

// ── Feedback ──
function submitFeedback(rating) {
    if (!currentTaskId || !currentDetailData) return;
    fetch(API_BASE + '/api/tasks/' + currentTaskId + '/feedback', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify({
            rating: rating,
            message_id: currentDetailData.id || null,
        }),
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success) {
            var bar = document.getElementById('feedback-bar');
            bar.querySelectorAll('.btn-feedback').forEach(function(b) { b.classList.remove('active'); });
            bar.querySelector('.btn-feedback.' + rating).classList.add('active');
        }
    })
    .catch(function() {});
}

// ── Utilities ──
function escapeHtml(text) {
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ── Auth Settings ──
function toggleSettings() {
    var body = document.getElementById('settings-body');
    var btn = document.getElementById('settings-toggle-btn');
    if (body.style.display === 'none') {
        body.style.display = '';
        btn.innerHTML = '&#9650;';
    } else {
        body.style.display = 'none';
        btn.innerHTML = '&#9660;';
    }
}

function loadAuthStatus() {
    fetch(API_BASE + '/api/auth/status')
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (!data.success) return;
        var badge = document.getElementById('auth-status-badge');
        badge.textContent = data.display || data.method;
        badge.style.background = data.configured
            ? 'rgba(16, 185, 129, 0.15)' : 'rgba(245, 158, 11, 0.15)';
        badge.style.color = data.configured ? '#10B981' : '#F59E0B';

        var radios = document.querySelectorAll('input[name="auth-method"]');
        radios.forEach(function(r) {
            r.checked = r.value === data.method;
        });

        document.getElementById('oauth-section').style.display = data.method === 'oauth' ? '' : 'none';
        document.getElementById('apikey-section').style.display = data.method === 'api_key' ? '' : 'none';

        if (data.method === 'oauth') {
            var connectBtn = document.getElementById('oauth-connect-btn');
            var disconnectBtn = document.getElementById('oauth-disconnect-btn');
            if (data.configured) {
                connectBtn.style.display = 'none';
                disconnectBtn.style.display = '';
            } else {
                connectBtn.style.display = '';
                disconnectBtn.style.display = 'none';
            }
        }

        if (!data.configured) {
            document.getElementById('settings-body').style.display = '';
            document.getElementById('settings-toggle-btn').innerHTML = '&#9650;';
        }
    })
    .catch(function() {});
}

function switchAuthMethod(method) {
    fetch(API_BASE + '/api/auth/method', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify({ method: method }),
    })
    .then(function(r) { return r.json(); })
    .then(function() { loadAuthStatus(); })
    .catch(function() {});
}

function saveApiKey() {
    var key = document.getElementById('api-key-input').value.trim();
    if (!key) { alert('Enter an API key'); return; }

    fetch(API_BASE + '/api/auth/api-key', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify({ api_key: key }),
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success) {
            document.getElementById('api-key-input').value = '';
            loadAuthStatus();
        } else {
            alert('Error: ' + (data.error || 'Failed'));
        }
    })
    .catch(function(err) { alert('Error: ' + err); });
}

function saveOAuthCredentials() {
    var clientId = document.getElementById('oauth-client-id').value.trim();
    if (!clientId) { alert('Enter a client ID'); return; }

    fetch(API_BASE + '/api/auth/oauth/credentials', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify({
            client_id: clientId,
            client_secret: document.getElementById('oauth-client-secret').value.trim(),
        }),
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success) {
            alert('OAuth credentials saved. Click "Connect with Anthropic" to authenticate.');
        } else {
            alert('Error: ' + (data.error || 'Failed'));
        }
    })
    .catch(function(err) { alert('Error: ' + err); });
}

function startOAuth() {
    fetch(API_BASE + '/api/auth/oauth/start', {
        method: 'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success && data.auth_url) {
            window.location.href = data.auth_url;
        } else {
            alert('OAuth error: ' + (data.error || 'Could not start OAuth flow'));
        }
    })
    .catch(function(err) { alert('Error: ' + err); });
}

function disconnectOAuth() {
    if (!confirm('Disconnect your Anthropic account?')) return;
    fetch(API_BASE + '/api/auth/oauth/disconnect', {
        method: 'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
    })
    .then(function(r) { return r.json(); })
    .then(function() { loadAuthStatus(); })
    .catch(function() {});
}

// ── Init ──
document.addEventListener('DOMContentLoaded', function() {
    loadAuthStatus();
    connectSSE();
    refreshTasks();

    setInterval(function() {
        fetch(API_BASE + '/api/states')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) return;
            Object.keys(data.agents).forEach(function(name) {
                updateAgentCard(data.agents[name]);
                trackTokens(data.agents[name]);
            });
        })
        .catch(function() {});
    }, 5000);

    setInterval(refreshTasks, 10000);

    if (window.location.search.includes('auth=connected')) {
        var badge = document.getElementById('auth-status-badge');
        badge.textContent = 'Connected!';
        badge.style.background = 'rgba(16, 185, 129, 0.15)';
        badge.style.color = '#10B981';
    }
});
