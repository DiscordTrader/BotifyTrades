"""
Setup Wizard Launcher
Standalone launcher for the PySide6 setup wizard
Can be run independently or called from the main application
"""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


def check_pyside6_installed() -> bool:
    """Check if PySide6 is installed"""
    try:
        import PySide6
        print(f"[Wizard] PySide6 found: {PySide6.__version__}")
        return True
    except ImportError as e:
        print(f"[Wizard] PySide6 not found: {e}")
        return False


def check_pyqt5_installed() -> bool:
    """Check if PyQt5 is installed (fallback)"""
    try:
        import PyQt5
        print("[Wizard] PyQt5 found")
        return True
    except ImportError as e:
        print(f"[Wizard] PyQt5 not found: {e}")
        return False


def show_console_setup():
    """Fallback console-based setup when no GUI is available"""
    print("=" * 60)
    print("BotifyTrades Setup Wizard (Console Mode)")
    print("=" * 60)
    print("\nPySide6 or PyQt5 is not installed.")
    print("Please install one of them to use the graphical setup wizard:")
    print("  pip install PySide6")
    print("  or")
    print("  pip install PyQt5")
    print("\nAlternatively, configure the bot manually via:")
    import os as _os
    _port = _os.environ.get('GUI_PORT', '5000')
    print(f"  - The web control panel at http://localhost:{_port}")
    print("  - Edit config.ini directly")
    print("=" * 60)


def _setup_qt_environment():
    """Set up Qt environment for frozen EXE"""
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS if hasattr(sys, '_MEIPASS') else os.path.dirname(sys.executable)
        
        qt_plugin_path = os.path.join(base_path, 'PySide6', 'plugins')
        if os.path.exists(qt_plugin_path):
            os.environ['QT_PLUGIN_PATH'] = qt_plugin_path
            print(f"[Wizard] Set QT_PLUGIN_PATH: {qt_plugin_path}")
        
        if 'QT_QPA_PLATFORM_PLUGIN_PATH' not in os.environ:
            platforms_path = os.path.join(qt_plugin_path, 'platforms')
            if os.path.exists(platforms_path):
                os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = platforms_path
                print(f"[Wizard] Set QT_QPA_PLATFORM_PLUGIN_PATH: {platforms_path}")


def launch_wizard(skip_first_run_check: bool = False) -> bool:
    """
    Launch the setup wizard
    
    Args:
        skip_first_run_check: If True, always show wizard regardless of first-run status
        
    Returns:
        True if wizard completed successfully, False otherwise
    """
    import tempfile
    import time
    
    log_path = os.path.join(tempfile.gettempdir(), 'botifytrades_wizard_launcher.log')
    
    def log(msg):
        try:
            with open(log_path, 'a') as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        except:
            pass
        print(msg, flush=True)
    
    log("=" * 50)
    log("[Launcher] Starting wizard launcher...")
    log(f"[Launcher] Python: {sys.version}")
    log(f"[Launcher] Frozen: {getattr(sys, 'frozen', False)}")
    log(f"[Launcher] Log file: {log_path}")
    
    _setup_qt_environment()
    
    log("[Launcher] Checking for Qt frameworks...")
    if not check_pyside6_installed() and not check_pyqt5_installed():
        log("[Launcher] No Qt framework available!")
        show_console_setup()
        return False
    
    log("[Launcher] Importing config_db...")
    from .config_db import WizardDatabaseAdapter, check_first_run
    
    if not skip_first_run_check and not check_first_run():
        log("[Launcher] Setup already completed. Use --force-wizard to run again.")
        return True
    
    try:
        log("[Launcher] Importing Qt modules...")
        if check_pyside6_installed():
            from PySide6.QtWidgets import QApplication
            from PySide6.QtCore import Qt
            log("[Launcher] Using PySide6")
        else:
            from PyQt5.QtWidgets import QApplication
            from PyQt5.QtCore import Qt
            log("[Launcher] Using PyQt5")
        
        log("[Launcher] Importing SetupWizard class...")
        from .wizard import SetupWizard
        log("[Launcher] SetupWizard imported successfully")
        
        log("[Launcher] Checking for existing QApplication...")
        app = QApplication.instance()
        created_app = False
        if not app:
            log("[Launcher] Creating new QApplication...")
            app = QApplication(sys.argv if sys.argv else ['BotifyTrades'])
            created_app = True
            log("[Launcher] Created new QApplication")
        else:
            log("[Launcher] Using existing QApplication")
        
        app.setApplicationName("BotifyTrades Setup")
        app.setApplicationDisplayName("BotifyTrades Setup Wizard")
        
        log("[Launcher] Loading stylesheet...")
        stylesheet_loaded = False
        
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS if hasattr(sys, '_MEIPASS') else os.path.dirname(sys.executable)
            styles_path = os.path.join(base_path, 'ui', 'styles.qss')
        else:
            styles_path = os.path.join(Path(__file__).parent.parent, 'styles.qss')
        
        if os.path.exists(styles_path):
            try:
                with open(styles_path, 'r', encoding='utf-8') as f:
                    stylesheet = f.read()
                app.setStyleSheet(stylesheet)
                stylesheet_loaded = True
                log(f"[Launcher] Loaded stylesheet from: {styles_path}")
            except Exception as e:
                log(f"[Launcher] Failed to load stylesheet: {e}")
        else:
            log(f"[Launcher] Stylesheet not found at: {styles_path}")
        
        if not stylesheet_loaded:
            log("[Launcher] Using default inline styles")
        
        log("[Launcher] Creating database adapter...")
        db_adapter = WizardDatabaseAdapter()
        log("[Launcher] Database adapter created")
        
        log("[Launcher] Creating wizard window...")
        wizard = SetupWizard(db_adapter=db_adapter)
        log("[Launcher] Wizard window created")
        
        result = {'completed': False}
        
        def on_completed(data):
            result['completed'] = True
            log("[Launcher] Setup completed successfully!")
        
        def on_cancelled():
            log("[Launcher] Setup cancelled by user.")
        
        wizard.wizard_completed.connect(on_completed)
        wizard.wizard_cancelled.connect(on_cancelled)
        
        log("[Launcher] Calling wizard.show()...")
        wizard.show()
        log("[Launcher] Calling wizard.raise_()...")
        wizard.raise_()
        log("[Launcher] Calling wizard.activateWindow()...")
        wizard.activateWindow()
        log("[Launcher] Wizard window should now be visible!")
        
        log("[Launcher] Starting Qt event loop...")
        if created_app:
            log("[Launcher] Calling app.exec()...")
            app.exec()
        else:
            log("[Launcher] Calling wizard.exec() or app.exec()...")
            wizard.exec() if hasattr(wizard, 'exec') else app.exec()
        
        log(f"[Launcher] Event loop finished. Completed: {result['completed']}")
        return result['completed']
        
    except Exception as e:
        log(f"[Launcher] EXCEPTION: {type(e).__name__}: {e}")
        import traceback
        log(traceback.format_exc())
        return False


def main():
    """Main entry point for standalone wizard execution"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="BotifyTrades Setup Wizard",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        '--force', '-f',
        action='store_true',
        help='Force wizard to run even if setup was already completed'
    )
    parser.add_argument(
        '--check',
        action='store_true',
        help='Only check if first-run wizard is needed, do not launch'
    )
    
    args = parser.parse_args()
    
    if args.check:
        from .config_db import check_first_run
        is_first_run = check_first_run()
        if is_first_run:
            print("First run detected - wizard needed")
            sys.exit(0)
        else:
            print("Setup already completed")
            sys.exit(1)
    
    success = launch_wizard(skip_first_run_check=args.force)
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
