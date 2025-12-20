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
    print("  - The web control panel at http://localhost:5000")
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
    print("[Wizard] Starting wizard launcher...")
    print(f"[Wizard] Python: {sys.version}")
    print(f"[Wizard] Frozen: {getattr(sys, 'frozen', False)}")
    
    _setup_qt_environment()
    
    if not check_pyside6_installed() and not check_pyqt5_installed():
        show_console_setup()
        return False
    
    from .config_db import WizardDatabaseAdapter, check_first_run
    
    if not skip_first_run_check and not check_first_run():
        print("[Wizard] Setup already completed. Use --force-wizard to run again.")
        return True
    
    try:
        print("[Wizard] Importing Qt modules...")
        if check_pyside6_installed():
            from PySide6.QtWidgets import QApplication
            from PySide6.QtCore import Qt
            print("[Wizard] Using PySide6")
        else:
            from PyQt5.QtWidgets import QApplication
            from PyQt5.QtCore import Qt
            print("[Wizard] Using PyQt5")
        
        print("[Wizard] Importing SetupWizard...")
        from .wizard import SetupWizard
        
        print("[Wizard] Creating QApplication...")
        app = QApplication.instance()
        created_app = False
        if not app:
            app = QApplication(sys.argv if sys.argv else ['BotifyTrades'])
            created_app = True
            print("[Wizard] Created new QApplication")
        else:
            print("[Wizard] Using existing QApplication")
        
        app.setApplicationName("BotifyTrades Setup")
        app.setApplicationDisplayName("BotifyTrades Setup Wizard")
        
        print("[Wizard] Creating database adapter...")
        db_adapter = WizardDatabaseAdapter()
        
        print("[Wizard] Creating wizard window...")
        wizard = SetupWizard(db_adapter=db_adapter)
        
        result = {'completed': False}
        
        def on_completed(data):
            result['completed'] = True
            print("[Wizard] Setup completed successfully!")
        
        def on_cancelled():
            print("[Wizard] Setup cancelled by user.")
        
        wizard.wizard_completed.connect(on_completed)
        wizard.wizard_cancelled.connect(on_cancelled)
        
        print("[Wizard] Showing wizard window...")
        wizard.show()
        wizard.raise_()
        wizard.activateWindow()
        
        print("[Wizard] Starting event loop...")
        if created_app:
            app.exec()
        else:
            wizard.exec() if hasattr(wizard, 'exec') else app.exec()
        
        print(f"[Wizard] Event loop finished. Completed: {result['completed']}")
        return result['completed']
        
    except Exception as e:
        print(f"[Wizard] Error launching wizard: {e}")
        import traceback
        traceback.print_exc()
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
