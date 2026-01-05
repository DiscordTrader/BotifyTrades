"""
BotifyTrades GUI Components
- Splash Screen with progress bar
- System Tray icon for background operation
"""

from .splash_screen import SplashScreen, StartupProgress, show_splash_screen
from .system_tray import TrayIconManager, get_tray_manager, setup_system_tray

__all__ = [
    'SplashScreen',
    'StartupProgress', 
    'show_splash_screen',
    'TrayIconManager',
    'get_tray_manager',
    'setup_system_tray'
]
