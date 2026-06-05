"""
India Trading Bot - Main Entry Point
No console window, splash screen for license, background operation with system tray
"""
import os
import sys
import threading
from typing import Optional

# Set build type (changed by CI to USER or ADMIN)
BUILD_TYPE = 'DEV'


def main():
    """Main entry point with splash screen and license validation"""
    
    # Initialize Qt application FIRST (required for splash screen)
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # Keep running in tray
    app.setApplicationName("IndiaTradingBot")
    
    # Import components after Qt is initialized
    from src.gui.splash_screen import SplashScreen, StartupProgress
    from src.gui.system_tray import setup_system_tray, get_tray_manager
    from src.services.lifecycle_manager import get_lifecycle_manager
    
    # Create progress reporter for startup steps
    progress = StartupProgress()
    
    # Create and show splash screen
    splash = SplashScreen(progress_reporter=progress)
    splash.show()
    
    # Variables for startup state
    startup_state = {'license_valid': False, 'license_data': {}}
    
    def on_license_validated(license_data: dict):
        """Called when license is validated successfully"""
        startup_state['license_valid'] = True
        startup_state['license_data'] = license_data
        print(f"[MAIN] License validated: {license_data.get('days_remaining')} days remaining")
    
    def on_startup_ready():
        """Called when splash is done and we can start the bot"""
        if not startup_state['license_valid']:
            print("[MAIN] License not validated - cannot start")
            return
        
        # Start the actual bot components
        QTimer.singleShot(100, lambda: start_bot_components(app, splash, progress))
    
    # Connect splash signals
    splash.license_validated.connect(on_license_validated)
    splash.startup_ready.connect(on_startup_ready)
    
    # Start event loop
    sys.exit(app.exec())


def start_bot_components(app, splash, progress):
    """Start all bot components after license validation"""
    from src.gui.system_tray import setup_system_tray, get_tray_manager
    from src.services.lifecycle_manager import get_lifecycle_manager
    from src.license import start_network_monitor, start_license_heartbeat
    from PySide6.QtCore import QTimer
    
    try:
        # Step 1: Initialize license monitoring
        progress.update(1, "Starting license monitor...")
        license_key = os.getenv('LICENSE_KEY', '')
        if license_key:
            start_network_monitor(license_key)
            start_license_heartbeat(license_key, interval_minutes=30)
        
        # Step 2: Setup system tray
        progress.update(2, "Setting up system tray...")
        tray = setup_system_tray()
        tray.set_status("starting", "Initializing...")
        
        # Step 3: Initialize database
        progress.update(3, "Initializing database...")
        try:
            from gui_app.database import init_db
            init_db()
        except ImportError:
            pass
        
        # Step 4: Start Flask web panel
        progress.update(4, "Starting control panel...")
        flask_thread = start_flask_server()
        
        # Step 5: Initialize broker connections
        progress.update(5, "Connecting to brokers...")
        # Add your broker initialization here (Upstox, DhanHQ, Zerodha)
        
        # Step 6: Start Discord/Telegram bot
        progress.update(6, "Starting signal monitors...")
        discord_thread, discord_shutdown = start_discord_bot()
        telegram_thread, telegram_shutdown = start_telegram_bot()
        
        # Step 7: Register with lifecycle manager
        progress.update(7, "Registering services...")
        lifecycle = get_lifecycle_manager()
        lifecycle.register_threads(
            discord_thread=discord_thread,
            telegram_thread=telegram_thread,
            discord_shutdown=discord_shutdown,
            telegram_shutdown=telegram_shutdown,
            gui_port=5000
        )
        lifecycle.register_qt_app(app)
        
        # Step 8: Final setup
        progress.update(8, "Finalizing...")
        
        # Update tray status
        tray.set_status("running", "Monitoring signals")
        tray.show_notification(
            "India Trading Bot",
            "Bot is now running and monitoring for signals"
        )
        
        # Step 9: Complete startup
        progress.update(9, "Ready!")
        progress.complete()
        
        # Hide splash screen after brief delay
        QTimer.singleShot(500, splash.close)
        
        print("[MAIN] Bot started successfully")
        
    except Exception as e:
        print(f"[MAIN] Startup error: {e}")
        import traceback
        traceback.print_exc()
        progress.fail(str(e))


def start_flask_server() -> threading.Thread:
    """Start Flask web control panel in background thread"""
    def run_flask():
        try:
            from gui_app.app import create_app
            flask_app = create_app()
            flask_app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)
        except ImportError:
            print("[FLASK] gui_app.app not found - web panel disabled")
        except Exception as e:
            print(f"[FLASK] Error: {e}")
    
    thread = threading.Thread(target=run_flask, daemon=True, name="FlaskServer")
    thread.start()
    return thread


def start_discord_bot():
    """Start Discord bot - placeholder for your implementation"""
    shutdown_event = threading.Event()
    
    def run_discord():
        print("[DISCORD] Discord bot placeholder started")
        # Replace with your Discord bot implementation:
        # import discord
        # from discord.ext import commands
        # ...
        while not shutdown_event.is_set():
            shutdown_event.wait(1)
        print("[DISCORD] Discord bot stopped")
    
    thread = threading.Thread(target=run_discord, daemon=True, name="DiscordBot")
    thread.start()
    return thread, shutdown_event


def start_telegram_bot():
    """Start Telegram bot - placeholder for your implementation"""
    shutdown_event = threading.Event()
    
    def run_telegram():
        print("[TELEGRAM] Telegram bot placeholder started")
        # Replace with your Telegram bot implementation:
        # from telethon import TelegramClient
        # ...
        while not shutdown_event.is_set():
            shutdown_event.wait(1)
        print("[TELEGRAM] Telegram bot stopped")
    
    thread = threading.Thread(target=run_telegram, daemon=True, name="TelegramBot")
    thread.start()
    return thread, shutdown_event


if __name__ == '__main__':
    main()
