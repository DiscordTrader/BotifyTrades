"""
BotifyTrades GUI Components
- Splash Screen with progress bar
- System Tray icon for background operation
- Single Instance Detection (no PySide6 dependency)
"""


def __getattr__(name):
    if name in ('SplashScreen', 'StartupProgress', 'show_splash_screen'):
        from .splash_screen import SplashScreen, StartupProgress, show_splash_screen
        return locals()[name]
    if name in ('TrayIconManager', 'get_tray_manager', 'setup_system_tray'):
        from .system_tray import TrayIconManager, get_tray_manager, setup_system_tray
        return locals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    'SplashScreen',
    'StartupProgress',
    'show_splash_screen',
    'TrayIconManager',
    'get_tray_manager',
    'setup_system_tray'
]
