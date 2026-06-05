"""
BotifyTrades Setup Wizard UI Module
Professional PySide6-based setup wizard for first-run configuration
"""

__version__ = "1.0.0"

from .wizard import (
    SetupWizard,
    launch_wizard,
    launch_wizard_standalone,
    WizardDatabaseAdapter,
    check_first_run,
    get_wizard_adapter
)

__all__ = [
    'SetupWizard',
    'launch_wizard',
    'launch_wizard_standalone',
    'WizardDatabaseAdapter',
    'check_first_run',
    'get_wizard_adapter'
]
