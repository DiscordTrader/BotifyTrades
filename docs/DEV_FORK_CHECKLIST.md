# Development Fork - Quick Setup Checklist

## Before Forking
- [ ] Production project is working correctly
- [ ] Note your current Replit project URL
- [ ] Have LICENSE_KEY ready to copy

---

## Create New Project
- [ ] Download current project as ZIP (⋮ menu → Download as ZIP)
- [ ] Create new Replit (Python template)
- [ ] Name: `BotifyTrades-v5-Dev`
- [ ] Upload ZIP contents to new project
- [ ] Verify files transferred correctly

---

## Configure Secrets (Tools → Secrets)

### Required:
- [ ] `LICENSE_KEY` = your license key
- [ ] `FINNHUB_API_KEY` = your API key

### Add New:
- [ ] `DEV_PROJECT` = true
- [ ] `BUILD_TYPE` = ADMIN
- [ ] `DATABASE_PATH` = bot_data.db

---

## Integrations
- [ ] OpenAI - Check if auto-connected
- [ ] GitHub - Re-authorize if needed

---

## First Run
- [ ] Click "Run" or start workflow
- [ ] Wait for webview to load
- [ ] Login works
- [ ] No license errors
- [ ] Channels page loads

---

## Add Dev Banner (Optional but Recommended)

Add to `gui_app/templates/base.html` after `<body>`:
```html
{% if config.get('DEV_PROJECT') %}
<div style="background:#ff6b6b;color:white;text-align:center;padding:8px;font-weight:bold;">
  🚧 DEV BUILD 🚧
</div>
{% endif %}
```

---

## Safety Settings
- [ ] Set paper_trade = true for all test channels
- [ ] DO NOT connect live broker credentials
- [ ] Keep production project open in separate tab

---

## Ready for Development!

Now you can safely make major changes:
- Move channel settings to Execution page
- Create new routes
- Restructure UI
- Test thoroughly

Production remains unaffected.
