# BotifyTrades Development Fork - Setup Guide

## Overview

This guide helps you create an isolated development copy of BotifyTrades for major UI changes without affecting the production project.

---

## Step 1: Create the Fork in Replit UI

### Option A: Download & Upload (Recommended for Private Projects)

1. **In Current Project (Production):**
   - Click the three dots menu (⋮) next to project name
   - Select "Download as ZIP"
   - Save the ZIP file to your computer

2. **Create New Replit:**
   - Go to https://replit.com
   - Click "Create Repl"
   - Choose "Python" template
   - Name it: `BotifyTrades-v5-Dev` (or similar)
   - Click "Create Repl"

3. **Upload Files:**
   - In new project, delete default files
   - Drag and drop the ZIP contents (or use "Upload folder")
   - Verify all files transferred

### Option B: Git Clone (If Using GitHub)

```bash
# In new Replit Shell:
git clone https://github.com/YOUR_USERNAME/botifytrades.git .
```

---

## Step 2: Configure Secrets (REQUIRED)

Secrets do NOT transfer with fork. Add these manually in the new project:

### Navigate to: Tools → Secrets

| Secret Name | Description | Required |
|-------------|-------------|----------|
| `LICENSE_KEY` | Your BotifyTrades license | ✅ Yes |
| `FINNHUB_API_KEY` | Market data API | ✅ Yes |
| `RELEASE_TOKEN` | Release management | Optional |
| `SESSION_SECRET` | Flask session | Auto-generated |
| `FLASK_SECRET_KEY` | Flask security | Auto-generated |

### Copy from Production (if available):
```
LICENSE_KEY=BTF-XXXX-XXXX-XXXX
FINNHUB_API_KEY=your_finnhub_key
```

---

## Step 3: Configure Environment Variables

### Add to Secrets tab:

```
BUILD_TYPE=ADMIN
DATABASE_PATH=bot_data.db
DEV_MODE=true
```

### Development Indicator (helps distinguish from production):
```
DEV_PROJECT=true
PROJECT_VERSION=v5-dev
```

---

## Step 4: Database Setup

### Option A: Fresh Database (Recommended for Development)
- The existing `bot_data.db` will be copied
- Delete it and let the app create a fresh one
- Add test channels manually

### Option B: Copy Production Data
- Keep the copied `bot_data.db`
- Contains your channel configurations
- Be careful not to execute real trades

---

## Step 5: Integrations Re-Authorization

These integrations need to be re-authorized in the new project:

### OpenAI (AI Chat Assistant)
- Usually auto-populates from your Replit account
- Check: Tools → Integrations → OpenAI
- If not connected, re-add the integration

### GitHub
- Re-authorize if you need Git push/pull
- Check: Version Control tab

### Gmail (Email Notifications)
- Re-authorize if using email features
- Requires new OAuth consent

---

## Step 6: Workflow Configuration

The workflow should auto-configure. If not:

### Create Workflow:
- Name: `Dev Trading Bot`
- Command: `python src/selfbot_webull.py`
- Output: Console

### Add Development Indicator:
Add to the workflow command or environment:
```
DEV_MODE=true python src/selfbot_webull.py
```

---

## Step 7: Verify Setup

### Run Checklist:
```
□ 1. Workflow starts without errors
□ 2. Web GUI loads at the Webview URL
□ 3. Login page appears
□ 4. Database tables created
□ 5. No license errors (LICENSE_KEY set)
□ 6. AI Chat works (OpenAI connected)
```

### Test Commands:
```bash
# Check Python environment
python --version

# Verify database
ls -la *.db

# Check secrets loaded
python -c "import os; print('LICENSE_KEY' in os.environ)"
```

---

## Step 8: Add Development Indicators

### Visual Banner (Recommended)
Add to `gui_app/templates/base.html` at top of body:

```html
{% if config.get('DEV_PROJECT') %}
<div style="background: linear-gradient(90deg, #ff6b6b, #ffa500); 
            color: white; 
            text-align: center; 
            padding: 8px; 
            font-weight: bold;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            z-index: 9999;">
    🚧 DEVELOPMENT BUILD - v5 UI Redesign 🚧
</div>
<div style="height: 36px;"></div>  <!-- Spacer -->
{% endif %}
```

### Environment Check in routes.py:
```python
# Add to context_processor
DEV_PROJECT = os.environ.get('DEV_PROJECT', 'false').lower() == 'true'

@app.context_processor
def inject_dev_flags():
    return {
        'dev_mode': DEV_PROJECT,
        'project_version': os.environ.get('PROJECT_VERSION', 'production')
    }
```

---

## Project Comparison

| Aspect | Production | Development (Fork) |
|--------|------------|-------------------|
| Project Name | BotifyTrades | BotifyTrades-v5-Dev |
| DEV_MODE | false | true |
| Paper Trading | Optional | ALWAYS ON |
| Live Trading | Enabled | DISABLED |
| Database | Production data | Test data |
| URL | Different | Different |

---

## Safe Development Practices

### DO:
- ✅ Use paper trading mode for all tests
- ✅ Add DEV banner to distinguish from production
- ✅ Test thoroughly before syncing back
- ✅ Keep notes of all changes made

### DON'T:
- ❌ Connect real broker credentials with live trading
- ❌ Execute signals without paper_trade=true
- ❌ Modify production database
- ❌ Share development URL publicly

---

## Syncing Changes Back to Production

When development is complete:

### Method 1: File-by-File Copy
1. Identify changed files
2. Copy each file to production project
3. Test in production
4. Commit changes

### Method 2: Git Diff/Patch
```bash
# In Development project:
git diff > changes.patch

# In Production project:
git apply changes.patch
```

### Method 3: Full Replacement
1. Create checkpoint in Production
2. Download Development as ZIP
3. Replace Production files
4. Test thoroughly

---

## Rollback Plan

If something goes wrong in production after sync:

1. **Replit Checkpoints:**
   - Go to Version History
   - Select checkpoint before changes
   - Restore

2. **Manual Rollback:**
   - Keep backup of production files before sync
   - Restore from backup

---

## Support Files to Create

### docs/DEV_CHANGELOG.md
Track all changes made in development:
```markdown
# Development Changelog

## v5 UI Redesign

### Changed
- [ ] Moved channel settings from Channels page to Execution page
- [ ] Added settings modal with tabs
- [ ] New route: /api/channels/<id>/settings

### New Files
- gui_app/templates/partials/channel_settings_modal.html
- gui_app/static/js/channel-modal.js

### Modified Files
- gui_app/templates/execution.html
- gui_app/templates/channels.html
- gui_app/routes.py
```

---

## Quick Reference

### Production Project URL
```
https://YOUR-PRODUCTION-URL.replit.app
```

### Development Project URL
```
https://YOUR-DEV-URL.replit.app
```

### Key Differences
| Setting | Production | Development |
|---------|------------|-------------|
| DEV_PROJECT | not set | true |
| BUILD_TYPE | ADMIN | ADMIN |
| paper_trade | varies | ALWAYS true |
