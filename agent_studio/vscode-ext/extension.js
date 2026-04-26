const vscode = require('vscode');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');

let serverProcess = null;
let panel = null;
let outputChannel = null;

function activate(context) {
    outputChannel = vscode.window.createOutputChannel('Agent Studio');

    context.subscriptions.push(
        vscode.commands.registerCommand('agentStudio.open', () => openDashboard(context)),
        vscode.commands.registerCommand('agentStudio.startServer', () => startServer(context)),
        vscode.commands.registerCommand('agentStudio.stopServer', stopServer)
    );
}

function deactivate() {
    stopServer();
    if (panel) {
        panel.dispose();
        panel = null;
    }
}

function getConfig() {
    const config = vscode.workspace.getConfiguration('agentStudio');
    return {
        port: config.get('port', 5100),
        pythonPath: config.get('pythonPath', 'python'),
    };
}

function getWorkspaceRoot() {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders || folders.length === 0) {
        vscode.window.showErrorMessage('Agent Studio: No workspace folder open.');
        return null;
    }
    return folders[0].uri.fsPath;
}

function startServer(context) {
    if (serverProcess) {
        outputChannel.appendLine('[Agent Studio] Server already running.');
        return Promise.resolve();
    }

    const root = getWorkspaceRoot();
    if (!root) return Promise.reject(new Error('No workspace'));

    const { port, pythonPath } = getConfig();
    const runScript = path.join(root, 'agent_studio', 'run.py');

    if (!fs.existsSync(runScript)) {
        vscode.window.showErrorMessage('Agent Studio: run.py not found at ' + runScript);
        return Promise.reject(new Error('run.py not found'));
    }

    outputChannel.appendLine(`[Agent Studio] Starting server on port ${port}...`);
    outputChannel.show(true);

    return new Promise((resolve, reject) => {
        serverProcess = spawn(pythonPath, [runScript, '--port', String(port), '--host', '127.0.0.1'], {
            cwd: root,
            env: { ...process.env },
        });

        let started = false;

        serverProcess.stdout.on('data', (data) => {
            const text = data.toString();
            outputChannel.appendLine(text.trimEnd());
            if (!started && text.includes('Running on')) {
                started = true;
                resolve();
            }
        });

        serverProcess.stderr.on('data', (data) => {
            outputChannel.appendLine('[stderr] ' + data.toString().trimEnd());
            if (!started && data.toString().includes('Running on')) {
                started = true;
                resolve();
            }
        });

        serverProcess.on('error', (err) => {
            outputChannel.appendLine('[Agent Studio] Failed to start: ' + err.message);
            serverProcess = null;
            if (!started) reject(err);
        });

        serverProcess.on('close', (code) => {
            outputChannel.appendLine(`[Agent Studio] Server exited (code ${code})`);
            serverProcess = null;
            if (!started) reject(new Error('Server exited before ready'));
        });

        setTimeout(() => {
            if (!started) {
                started = true;
                resolve();
            }
        }, 5000);
    });
}

function stopServer() {
    if (serverProcess) {
        outputChannel.appendLine('[Agent Studio] Stopping server...');
        serverProcess.kill();
        serverProcess = null;
    }
}

async function openDashboard(context) {
    if (panel) {
        panel.reveal(vscode.ViewColumn.One);
        return;
    }

    const root = getWorkspaceRoot();
    if (!root) return;

    const { port } = getConfig();

    const statusBar = vscode.window.setStatusBarMessage('Agent Studio: Starting server...');

    try {
        await startServer(context);
    } catch (e) {
        outputChannel.appendLine('[Agent Studio] Server start warning: ' + e.message);
    }

    statusBar.dispose();

    const staticDir = path.join(root, 'agent_studio', 'static');

    panel = vscode.window.createWebviewPanel(
        'agentStudio',
        'Agent Studio',
        vscode.ViewColumn.One,
        {
            enableScripts: true,
            retainContextWhenHidden: true,
            localResourceRoots: [vscode.Uri.file(staticDir)],
        }
    );

    const cssUri = panel.webview.asWebviewUri(
        vscode.Uri.file(path.join(staticDir, 'css', 'dashboard.css'))
    );
    const diffJsUri = panel.webview.asWebviewUri(
        vscode.Uri.file(path.join(staticDir, 'js', 'diff-viewer.js'))
    );
    const dashJsUri = panel.webview.asWebviewUri(
        vscode.Uri.file(path.join(staticDir, 'js', 'dashboard.js'))
    );

    const nonce = getNonce();
    const apiBase = `http://127.0.0.1:${port}`;

    panel.webview.html = getWebviewHtml({ cssUri, diffJsUri, dashJsUri, nonce, apiBase, cspSource: panel.webview.cspSource });

    panel.onDidDispose(() => {
        panel = null;
    });
}

function getNonce() {
    let text = '';
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    for (let i = 0; i < 32; i++) {
        text += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return text;
}

function getWebviewHtml({ cssUri, diffJsUri, dashJsUri, nonce, apiBase, cspSource }) {
    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="
        default-src 'none';
        style-src ${cspSource} 'unsafe-inline';
        script-src 'nonce-${nonce}';
        connect-src ${apiBase};
        font-src ${cspSource};
        img-src ${cspSource} data:;
    ">
    <title>Agent Studio</title>
    <style>
        :root {
            --bg-primary: #0E1117;
            --bg-card: #161B22;
            --bg-card-hover: #1C2129;
            --border-color: #30363D;
            --text-primary: #E6EDF3;
            --text-secondary: #8B949E;
            --text-muted: #6E7681;
            --accent-mint: #0FF0B3;
            --accent-violet: #A78BFA;
            --accent-gradient: linear-gradient(135deg, #0FF0B3 0%, #00D4AA 100%);
            --shadow-glow: 0 0 20px rgba(15, 240, 179, 0.15);
            --radius-md: 12px;
            --radius-sm: 8px;
            --font-primary: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
            --font-mono: 'SF Mono', 'Cascadia Code', 'Fira Code', monospace;
            --success: #10B981;
            --error: #EF4444;
        }
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: var(--font-primary);
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
        }
        .studio-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px 24px;
            border-bottom: 1px solid var(--border-color);
            background: var(--bg-card);
        }
        .studio-logo {
            font-size: 15px;
            font-weight: 700;
            color: var(--accent-mint);
            letter-spacing: 0.02em;
        }
        .studio-logo span { color: var(--text-muted); font-weight: 400; }
        .studio-subtitle {
            font-size: 11px;
            color: var(--text-muted);
        }
    </style>
    <link rel="stylesheet" href="${cssUri}">
</head>
<body>
    <header class="studio-header">
        <div>
            <div class="studio-logo">Agent Studio <span>for BotifyTrades</span></div>
            <div class="studio-subtitle">AI-Powered Software Development Pipeline</div>
        </div>
    </header>

    <div class="agent-dashboard">
        <!-- Auth Settings (collapsible) -->
        <div class="agent-panel settings-panel" id="settings-panel">
            <div class="panel-header" style="cursor:pointer" onclick="toggleSettings()">
                <h3>Settings</h3>
                <div style="display:flex; align-items:center; gap:8px">
                    <span class="panel-badge" id="auth-status-badge">Loading...</span>
                    <button class="panel-action" id="settings-toggle-btn">&#9660;</button>
                </div>
            </div>
            <div class="settings-body" id="settings-body" style="display:none">
                <div class="auth-method-selector">
                    <label class="auth-method-option">
                        <input type="radio" name="auth-method" value="api_key" onchange="switchAuthMethod('api_key')">
                        <div class="auth-method-card">
                            <strong>API Key</strong>
                            <span class="auth-method-desc">Get from console.anthropic.com &mdash; recommended</span>
                        </div>
                    </label>
                    <label class="auth-method-option" style="opacity:0.5; pointer-events:none">
                        <input type="radio" name="auth-method" value="oauth" disabled>
                        <div class="auth-method-card">
                            <strong>Anthropic OAuth</strong>
                            <span class="auth-method-desc">Coming soon</span>
                        </div>
                    </label>
                </div>
                <div class="auth-section" id="apikey-section" style="display:none">
                    <div class="auth-field-group">
                        <label>Anthropic API Key</label>
                        <div style="display:flex; gap:8px">
                            <input type="password" id="api-key-input" placeholder="sk-ant-..." style="flex:1">
                            <button class="btn-primary" onclick="saveApiKey()" style="font-size:12px; padding:6px 14px">Save</button>
                        </div>
                        <span class="auth-hint">Or set ANTHROPIC_API_KEY in your .env file</span>
                    </div>
                </div>
                <div class="auth-section" id="oauth-section" style="display:none"></div>
            </div>
        </div>

        <!-- Task Input + History Row -->
        <div class="agent-top-row">
            <div class="agent-panel task-input-panel">
                <div class="panel-header">
                    <h3>New Task</h3>
                    <span class="panel-badge" id="cost-estimate-badge" style="display:none">~$0.00</span>
                </div>
                <div class="task-input-body">
                    <textarea id="task-description" placeholder="Describe what you want built, fixed, or changed..." maxlength="500" oninput="estimateCost()"></textarea>
                    <div class="cost-estimate-display" id="cost-estimate-display">
                        <span class="cost-label">Estimated cost:</span>
                        <span class="cost-range" id="cost-range-text">$0.01 - $0.05</span>
                    </div>
                    <div class="task-input-footer">
                        <div class="task-options">
                            <select id="task-priority">
                                <option value="normal">Normal</option>
                                <option value="high">High</option>
                                <option value="low">Low</option>
                            </select>
                            <select id="task-approval">
                                <option value="review">Review Mode</option>
                                <option value="auto">Auto Mode</option>
                                <option value="strict">Strict Mode</option>
                            </select>
                        </div>
                        <button id="submit-task-btn" class="btn-primary" onclick="submitTask()">
                            <span class="btn-icon">&#9654;</span> Submit Task
                        </button>
                    </div>
                </div>
            </div>
            <div class="agent-panel task-history-panel">
                <div class="panel-header">
                    <h3>Task History</h3>
                    <button class="panel-action" onclick="refreshTasks()">Refresh</button>
                </div>
                <div class="task-history-list" id="task-history-list">
                    <div class="empty-state">No tasks yet</div>
                </div>
            </div>
        </div>

        <!-- Pipeline Flow -->
        <div class="agent-panel pipeline-panel">
            <div class="panel-header">
                <h3>Pipeline</h3>
                <span class="panel-badge" id="pipeline-status">Idle</span>
            </div>
            <div class="pipeline-flow" id="pipeline-flow">
                <div class="pipeline-node" data-pipeline="orchestrator" style="--agent-color: #0FF0B3"><div class="pipeline-dot"></div><span class="pipeline-node-label">Orchestrator</span></div>
                <div class="pipeline-connector" data-after="orchestrator"></div>
                <div class="pipeline-node" data-pipeline="architect" style="--agent-color: #7C3AED"><div class="pipeline-dot"></div><span class="pipeline-node-label">Architect</span></div>
                <div class="pipeline-connector" data-after="architect"></div>
                <div class="pipeline-node" data-pipeline="approval" style="--agent-color: #F59E0B"><div class="pipeline-dot"></div><span class="pipeline-node-label">Approval</span></div>
                <div class="pipeline-connector" data-after="approval"></div>
                <div class="pipeline-node" data-pipeline="developer" style="--agent-color: #3B82F6"><div class="pipeline-dot"></div><span class="pipeline-node-label">Developer</span></div>
                <div class="pipeline-connector" data-after="developer"></div>
                <div class="pipeline-node" data-pipeline="tester" style="--agent-color: #F59E0B"><div class="pipeline-dot"></div><span class="pipeline-node-label">Tester</span></div>
                <div class="pipeline-connector" data-after="tester"></div>
                <div class="pipeline-node" data-pipeline="reviewer" style="--agent-color: #EF4444"><div class="pipeline-dot"></div><span class="pipeline-node-label">Reviewer</span></div>
                <div class="pipeline-connector" data-after="reviewer"></div>
                <div class="pipeline-node" data-pipeline="devops" style="--agent-color: #10B981"><div class="pipeline-dot"></div><span class="pipeline-node-label">DevOps</span></div>
            </div>
            <div class="running-cost-bar" id="running-cost-bar" style="display:none">
                <span>Running cost</span>
                <span class="cost-value" id="running-cost-value">$0.0000</span>
            </div>
        </div>

        <!-- Agent Status Cards -->
        <div class="agent-panel agent-status-panel">
            <div class="panel-header"><h3>Agent Status</h3></div>
            <div class="agent-cards" id="agent-cards">
                <div class="agent-card" data-agent="orchestrator" style="--agent-color: #0FF0B3"><div class="agent-card-header"><span class="agent-indicator"></span><span class="agent-name">Orchestrator</span></div><div class="agent-progress"><div class="agent-progress-bar"></div></div><div class="agent-meta"><span class="agent-status-text">idle</span><span class="agent-tokens">0 tok</span></div><div class="agent-cost" data-agent-cost="orchestrator"></div></div>
                <div class="agent-card" data-agent="architect" style="--agent-color: #7C3AED"><div class="agent-card-header"><span class="agent-indicator"></span><span class="agent-name">Architect</span></div><div class="agent-progress"><div class="agent-progress-bar"></div></div><div class="agent-meta"><span class="agent-status-text">idle</span><span class="agent-tokens">0 tok</span></div><div class="agent-cost" data-agent-cost="architect"></div></div>
                <div class="agent-card" data-agent="developer" style="--agent-color: #3B82F6"><div class="agent-card-header"><span class="agent-indicator"></span><span class="agent-name">Developer</span></div><div class="agent-progress"><div class="agent-progress-bar"></div></div><div class="agent-meta"><span class="agent-status-text">idle</span><span class="agent-tokens">0 tok</span></div><div class="agent-cost" data-agent-cost="developer"></div></div>
                <div class="agent-card" data-agent="tester" style="--agent-color: #F59E0B"><div class="agent-card-header"><span class="agent-indicator"></span><span class="agent-name">Tester</span></div><div class="agent-progress"><div class="agent-progress-bar"></div></div><div class="agent-meta"><span class="agent-status-text">idle</span><span class="agent-tokens">0 tok</span></div><div class="agent-cost" data-agent-cost="tester"></div></div>
                <div class="agent-card" data-agent="reviewer" style="--agent-color: #EF4444"><div class="agent-card-header"><span class="agent-indicator"></span><span class="agent-name">Reviewer</span></div><div class="agent-progress"><div class="agent-progress-bar"></div></div><div class="agent-meta"><span class="agent-status-text">idle</span><span class="agent-tokens">0 tok</span></div><div class="agent-cost" data-agent-cost="reviewer"></div></div>
                <div class="agent-card" data-agent="devops" style="--agent-color: #10B981"><div class="agent-card-header"><span class="agent-indicator"></span><span class="agent-name">DevOps</span></div><div class="agent-progress"><div class="agent-progress-bar"></div></div><div class="agent-meta"><span class="agent-status-text">idle</span><span class="agent-tokens">0 tok</span></div><div class="agent-cost" data-agent-cost="devops"></div></div>
            </div>
            <div class="token-summary" id="token-summary">
                <div class="token-summary-item"><span class="token-dot" style="background:#0FF0B3"></span> Orchestrator: <span data-token-agent="orchestrator">0</span></div>
                <div class="token-summary-item"><span class="token-dot" style="background:#7C3AED"></span> Arch: <span data-token-agent="architect">0</span></div>
                <div class="token-summary-item"><span class="token-dot" style="background:#3B82F6"></span> Dev: <span data-token-agent="developer">0</span></div>
                <div class="token-summary-item"><span class="token-dot" style="background:#F59E0B"></span> Test: <span data-token-agent="tester">0</span></div>
                <div class="token-summary-item"><span class="token-dot" style="background:#EF4444"></span> Rev: <span data-token-agent="reviewer">0</span></div>
                <div class="token-summary-item"><span class="token-dot" style="background:#10B981"></span> Ops: <span data-token-agent="devops">0</span></div>
                <span class="token-summary-total" id="token-total">Total: 0 tok</span>
            </div>
        </div>

        <!-- Message Stream + Detail Panel -->
        <div class="agent-bottom-row">
            <div class="agent-panel message-stream-panel">
                <div class="panel-header">
                    <h3>Message Stream</h3>
                    <div class="stream-controls">
                        <div class="message-search"><input type="text" id="message-search" placeholder="Search..." oninput="searchMessages()"></div>
                        <label class="auto-scroll-toggle"><input type="checkbox" id="auto-scroll" checked> Auto-scroll</label>
                        <select id="message-filter" onchange="filterMessages()">
                            <option value="all">All</option>
                            <option value="handoff">Handoffs</option>
                            <option value="error">Errors</option>
                            <option value="status">Status</option>
                            <option value="approval_required">Approvals</option>
                            <option value="retry">Retries</option>
                        </select>
                    </div>
                </div>
                <div class="message-list" id="message-list"><div class="empty-state">Waiting for task...</div></div>
                <div class="approval-bar" id="approval-bar" style="display:none">
                    <span class="approval-text">Architect plan ready &mdash; review before proceeding</span>
                    <button class="btn-approve" onclick="approveTask()">Approve</button>
                    <button class="btn-reject" onclick="rejectTask()">Reject</button>
                </div>
            </div>
            <div class="agent-panel detail-panel">
                <div class="panel-header"><h3>Details</h3></div>
                <div class="detail-tabs" id="detail-tabs">
                    <button class="detail-tab active" data-tab="content" onclick="switchDetailTab('content')">Content</button>
                    <button class="detail-tab" data-tab="diff" onclick="switchDetailTab('diff')">Diff</button>
                    <button class="detail-tab" data-tab="metadata" onclick="switchDetailTab('metadata')">Metadata</button>
                </div>
                <div class="detail-content" id="detail-content"><div class="empty-state">Select a message to view details</div></div>
                <div class="feedback-bar" id="feedback-bar" style="display:none">
                    <span class="feedback-label">Rate this output:</span>
                    <button class="btn-feedback up" onclick="submitFeedback('up')" title="Good output">&#128077;</button>
                    <button class="btn-feedback down" onclick="submitFeedback('down')" title="Bad output">&#128078;</button>
                </div>
            </div>
        </div>
    </div>

    <script nonce="${nonce}">window.API_BASE = '${apiBase}';</script>
    <script nonce="${nonce}" src="${diffJsUri}"></script>
    <script nonce="${nonce}" src="${dashJsUri}"></script>
</body>
</html>`;
}

module.exports = { activate, deactivate };
