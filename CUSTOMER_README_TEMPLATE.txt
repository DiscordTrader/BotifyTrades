=============================================================
Discord Trading Bot - Setup Instructions
=============================================================

Thank you for your purchase!

STEP 1: INSTALL (FIRST TIME ONLY)
----------------------------------
1. Extract all files to a folder (e.g., C:\TradingBot\)
2. Open config.ini with Notepad
3. Edit these important settings:
   
   [discord]
   channel_ids = YOUR_CHANNEL_IDS_HERE  (comma-separated)
   
   [webull]
   paper_trade = true   (Use 'true' for testing, 'false' for live trading)
   
4. Save and close config.ini

STEP 2: FIRST RUN - LICENSE ACTIVATION
---------------------------------------
1. Double-click DiscordTradingBot.exe
2. The setup wizard will appear
3. When prompted for license key, paste your license key:
   
   [YOUR LICENSE KEY WILL BE PROVIDED SEPARATELY]
   
4. Follow the wizard to enter:
   - Your Discord user token (instructions shown in wizard)
   - Your Webull credentials (email, password, 6-digit PIN)
   - Optional API keys (you can skip these for now)
   
5. Setup is complete! Your credentials are saved securely.

STEP 3: RUNNING THE BOT
------------------------
1. Double-click DiscordTradingBot.exe
2. The bot will:
   ✓ Validate your license
   ✓ Connect to Discord
   ✓ Login to Webull
   ✓ Start monitoring for trading signals
3. Keep the console window open while the bot runs
4. The bot will execute trades automatically

YOUR LICENSE INFORMATION:
-------------------------
• License Type: [7-day trial / 30-day / 365-day]
• Expires On: [EXPIRATION_DATE]
• Customer ID: [CUSTOMER_ID]

To renew your license after expiration, contact: [YOUR_EMAIL]

IMPORTANT SAFETY NOTES:
-----------------------
⚠️  ALWAYS test with paper_trade = true before enabling live trading
⚠️  Monitor the bot console for trading activity
⚠️  Review trades in your Webull account regularly
⚠️  Keep your license key secure - do not share it
⚠️  Your license key is for single-user use only

GETTING YOUR DISCORD CHANNEL IDs:
----------------------------------
1. Enable Developer Mode in Discord:
   Settings → Advanced → Developer Mode (toggle on)
2. Right-click any channel you want to monitor
3. Click "Copy ID"
4. Paste into config.ini (comma-separated for multiple channels)

Example: channel_ids = 123456789012345678, 987654321098765432

GETTING YOUR DISCORD USER TOKEN:
---------------------------------
1. Open Discord in your web browser (not the app)
2. Press F12 to open Developer Tools
3. Go to the Console tab
4. Paste this command and press Enter:
   (webpackChunkdiscord_app.push([[''],{},e=>{m=[];
   for(let c in e.c)m.push(e.c[c])}]),m).find(m=>
   m?.exports?.default?.getToken!==void 0).exports.default.getToken()
5. Copy the token (without quotes)
6. Paste when the setup wizard asks for it

TROUBLESHOOTING:
----------------
Problem: "License key required"
Solution: Enter your license key during first-time setup

Problem: "Invalid or expired license"
Solution: Contact support for license renewal

Problem: "Discord token error"
Solution: Delete .discord_trading_bot folder and re-run setup wizard

Problem: Bot not executing trades
Solution: 
  1. Check channel_ids in config.ini match your Discord channels
  2. Ensure paper_trade setting matches your intent
  3. Verify Webull credentials are correct

Problem: Windows Defender blocks the exe
Solution: Add exception for DiscordTradingBot.exe in Windows Security

FEATURES:
---------
✓ Automated BTO/STC signal execution
✓ Pre-trade swing analysis (validates signals before execution)
✓ Intelligent price slippage protection
✓ AI-powered trade analysis (!analyze, !ask commands)
✓ Real-time option flow scanning (!scanflow)
✓ Support for stocks and options (including LEAPS)
✓ Fundamental and technical analysis

INTERACTIVE COMMANDS (Optional):
---------------------------------
Send these commands in your monitored Discord channel:

!analyze TSLA         - Get AI analysis of TSLA stock
!ask Why is TSLA up?  - Ask AI trading questions
!scanflow SPY QQQ     - Scan for unusual option flow
!analyze_trade NVDA   - Get swing trading setup analysis

SUPPORT:
--------
Email: [YOUR_SUPPORT_EMAIL]
Discord: [YOUR_DISCORD_HANDLE]
Documentation: See LICENSE_SYSTEM.md for detailed license info

=============================================================
Version 1.0 - November 2025
=============================================================
