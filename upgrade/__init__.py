"""
BotifyTrades Auto-Update System
===============================
Provides automatic update checking, downloading, and safe application of updates
while preserving user data (database, credentials, settings).
"""

from .version import (
    APP_VERSION,
    get_current_version,
    set_current_version,
    compare_versions,
    parse_version,
    get_version_info
)

from .config import UpdateConfig, DEFAULT_CONFIG

from .version_checker import (
    VersionChecker,
    UpdateInfo,
    get_version_checker,
    check_for_updates
)

from .backup_manager import (
    BackupManager,
    get_backup_manager,
    create_backup,
    restore_backup,
    list_backups
)

from .readiness import (
    ReadinessChecker,
    ReadinessCheck,
    check_upgrade_readiness
)

from .upgrade_runner import (
    UpgradeRunner,
    UpgradeResult,
    UpgradeStatus,
    get_upgrade_runner,
    run_upgrade
)

__all__ = [
    'APP_VERSION',
    'get_current_version', 
    'set_current_version',
    'compare_versions',
    'parse_version',
    'get_version_info',
    'UpdateConfig',
    'DEFAULT_CONFIG',
    'VersionChecker',
    'UpdateInfo',
    'get_version_checker',
    'check_for_updates',
    'BackupManager',
    'get_backup_manager',
    'create_backup',
    'restore_backup',
    'list_backups',
    'ReadinessChecker',
    'ReadinessCheck',
    'check_upgrade_readiness',
    'UpgradeRunner',
    'UpgradeResult',
    'UpgradeStatus',
    'get_upgrade_runner',
    'run_upgrade'
]
