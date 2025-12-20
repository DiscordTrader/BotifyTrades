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
        return True
    except ImportError:
        return False


def check_pyqt5_installed() -> bool:
    """Check if PyQt5 is installed (fallback)"""
    try:
        import PyQt5
        return True
    except ImportError:
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


def launch_wizard(skip_first_run_check: bool = False) -> bool:
    """
    Launch the setup wizard
    
    Args:
        skip_first_run_check: If True, always show wizard regardless of first-run status
        
    Returns:
        True if wizard completed successfully, False otherwise
    """
    if not check_pyside6_installed() and not check_pyqt5_installed():
        show_console_setup()
        return False
    
    from .config_db import WizardDatabaseAdapter, check_first_run
    
    if not skip_first_run_check and not check_first_run():
        print("[Wizard] Setup already completed. Use --force-wizard to run again.")
        return True
    
    try:
        if check_pyside6_installed():
            from PySide6.QtWidgets import QApplication
            from PySide6.QtCore import Qt
        else:
            from PyQt5.QtWidgets import QApplication
            from PyQt5.QtCore import Qt
        
        from .wizard import SetupWizard
        
        app = QApplication.instance()
        if not app:
            app = QApplication(sys.argv)
        
        app.setApplicationName("BotifyTrades Setup")
        app.setApplicationDisplayName("BotifyTrades Setup Wizard")
        
        db_adapter = WizardDatabaseAdapter()
        
        wizard = SetupWizard(db_adapter=db_adapter)
        
        result = {'completed': False}
        
        def on_completed(data):
            result['completed'] = True
            print("[Wizard] Setup completed successfully!")
        
        def on_cancelled():
            print("[Wizard] Setup cancelled by user.")
        
        wizard.wizard_completed.connect(on_completed)
        wizard.wizard_cancelled.connect(on_cancelled)
        
        wizard.show()
        
        app.exec()
        
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
