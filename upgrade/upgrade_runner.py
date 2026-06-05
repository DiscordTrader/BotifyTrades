"""
Upgrade Runner
==============
Orchestrates the complete upgrade process: backup, download, verify, migrate, apply.
"""

import os
import sys
import json
import hashlib
import tempfile
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Tuple, Callable
from enum import Enum

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    requests = None
    REQUESTS_AVAILABLE = False

from .version import get_current_version, set_current_version, compare_versions
from .version_checker import UpdateInfo
from .backup_manager import get_backup_manager
from .readiness import ReadinessChecker
from .config import DEFAULT_CONFIG


def _find_database_path() -> Path:
    """Find the database file in common locations."""
    db_name = 'bot_data.db'
    
    env_path = os.environ.get('DATABASE_PATH')
    if env_path and Path(env_path).exists():
        return Path(env_path)
    
    possible_paths = [
        Path(db_name),
        Path(sys.executable).parent / db_name if getattr(sys, 'frozen', False) else None,
        Path.cwd() / db_name,
        Path(__file__).parent.parent / db_name,
    ]
    
    for path in possible_paths:
        if path and path.exists():
            return path
    
    return Path(db_name)


class UpgradeStatus(Enum):
    """Status of the upgrade process."""
    PENDING = "pending"
    CHECKING = "checking_readiness"
    BACKING_UP = "backing_up"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    APPLYING = "applying"
    MIGRATING = "migrating"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class UpgradeResult:
    """Result of an upgrade attempt."""
    
    def __init__(
        self,
        success: bool,
        status: UpgradeStatus,
        message: str,
        from_version: str = "",
        to_version: str = "",
        backup_path: str = "",
        error: str = ""
    ):
        self.success = success
        self.status = status
        self.message = message
        self.from_version = from_version
        self.to_version = to_version
        self.backup_path = backup_path
        self.error = error
        self.timestamp = datetime.now().isoformat()
    
    def to_dict(self) -> Dict:
        return {
            'success': self.success,
            'status': self.status.value,
            'message': self.message,
            'from_version': self.from_version,
            'to_version': self.to_version,
            'backup_path': self.backup_path,
            'error': self.error,
            'timestamp': self.timestamp
        }


class UpgradeRunner:
    """Orchestrates the upgrade process."""
    
    def __init__(self, config=None):
        self.config = config or DEFAULT_CONFIG
        self.backup_manager = get_backup_manager()
        self.readiness_checker = ReadinessChecker()
        self._status = UpgradeStatus.PENDING
        self._progress = 0
        self._progress_callback: Optional[Callable[[int, str], None]] = None
        self._history_file = Path('upgrade/upgrade_history.json')
    
    def set_progress_callback(self, callback: Callable[[int, str], None]):
        """Set a callback for progress updates."""
        self._progress_callback = callback
    
    def _update_progress(self, percent: int, message: str):
        """Update progress and notify callback."""
        self._progress = percent
        if self._progress_callback:
            self._progress_callback(percent, message)
        print(f"[UPGRADE] {percent}% - {message}")
    
    def run_upgrade(self, update_info: UpdateInfo) -> UpgradeResult:
        """
        Run the complete upgrade process.
        
        Args:
            update_info: Information about the update to apply
            
        Returns:
            UpgradeResult with success status and details
        """
        from_version = get_current_version()
        to_version = update_info.version
        backup_path = ""
        patch_id = f"upgrade_{from_version}_to_{to_version}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        if not REQUESTS_AVAILABLE:
            result = UpgradeResult(
                success=False,
                status=UpgradeStatus.FAILED,
                message="Cannot perform upgrade: requests library not available",
                from_version=from_version,
                to_version=to_version,
                error="Missing dependency: requests"
            )
            self._record_patch_history(patch_id, to_version, 'upgrade', 'failed', result.error)
            return result
        
        try:
            self._record_patch_history(patch_id, to_version, 'upgrade', 'in_progress', '')
            
            self._status = UpgradeStatus.CHECKING
            self._update_progress(5, "Checking upgrade readiness...")
            
            ready, checks = self.readiness_checker.run_all_checks()
            if not ready:
                failed = [c.name for c in checks if not c.passed and c.critical]
                result = UpgradeResult(
                    success=False,
                    status=UpgradeStatus.FAILED,
                    message=f"Readiness check failed: {', '.join(failed)}",
                    from_version=from_version,
                    to_version=to_version,
                    error="System not ready for upgrade"
                )
                self._record_patch_history(patch_id, to_version, 'upgrade', 'failed', result.error)
                return result
            
            self._status = UpgradeStatus.BACKING_UP
            self._update_progress(15, "Creating database backup...")
            
            success, backup_path, error = self.backup_manager.create_backup(tag='pre-upgrade')
            if not success:
                result = UpgradeResult(
                    success=False,
                    status=UpgradeStatus.FAILED,
                    message=f"Backup failed: {error}",
                    from_version=from_version,
                    to_version=to_version,
                    error=error
                )
                self._record_patch_history(patch_id, to_version, 'upgrade', 'failed', error)
                return result
            
            self._status = UpgradeStatus.DOWNLOADING
            self._update_progress(30, "Downloading update...")
            
            download_path, error = self._download_update(update_info)
            if not download_path:
                self._update_progress(35, "Download failed, rolling back...")
                self._rollback(backup_path, from_version)
                result = UpgradeResult(
                    success=False,
                    status=UpgradeStatus.ROLLED_BACK,
                    message=f"Download failed: {error}",
                    from_version=from_version,
                    to_version=to_version,
                    backup_path=backup_path,
                    error=error
                )
                self._record_patch_history(patch_id, to_version, 'upgrade', 'rolled_back', f"Download failed: {error}")
                return result
            
            self._status = UpgradeStatus.VERIFYING
            self._update_progress(50, "Verifying download...")
            
            if update_info.checksum:
                valid, error = self._verify_checksum(download_path, update_info.checksum)
                if not valid:
                    self._update_progress(55, "Checksum failed, rolling back...")
                    self._rollback(backup_path, from_version)
                    result = UpgradeResult(
                        success=False,
                        status=UpgradeStatus.ROLLED_BACK,
                        message=f"Checksum verification failed: {error}",
                        from_version=from_version,
                        to_version=to_version,
                        backup_path=backup_path,
                        error=error
                    )
                    self._record_patch_history(patch_id, to_version, 'upgrade', 'rolled_back', f"Checksum failed: {error}")
                    return result
            
            self._status = UpgradeStatus.APPLYING
            self._update_progress(60, "Extracting update package...")
            
            new_exe_path, error = self._extract_update(download_path, to_version)
            if not new_exe_path:
                self._update_progress(62, "Extraction failed, rolling back...")
                self._rollback(backup_path, from_version)
                result = UpgradeResult(
                    success=False,
                    status=UpgradeStatus.ROLLED_BACK,
                    message=f"Extraction failed: {error}",
                    from_version=from_version,
                    to_version=to_version,
                    backup_path=backup_path,
                    error=error
                )
                self._record_patch_history(patch_id, to_version, 'upgrade', 'rolled_back', f"Extraction failed: {error}")
                return result
            
            self._status = UpgradeStatus.MIGRATING
            self._update_progress(70, "Running database migrations...")
            
            success, error = self._run_migrations(to_version)
            if not success:
                self._update_progress(75, "Migration failed, rolling back...")
                self._rollback(backup_path, from_version)
                result = UpgradeResult(
                    success=False,
                    status=UpgradeStatus.ROLLED_BACK,
                    message=f"Migration failed, rolled back: {error}",
                    from_version=from_version,
                    to_version=to_version,
                    backup_path=backup_path,
                    error=error
                )
                self._record_patch_history(patch_id, to_version, 'upgrade', 'rolled_back', f"Migration failed: {error}")
                return result
            
            self._status = UpgradeStatus.VALIDATING
            self._update_progress(90, "Validating upgrade...")
            
            success, error = self._validate_upgrade()
            if not success:
                self._update_progress(92, "Validation failed, rolling back...")
                self._rollback(backup_path, from_version)
                result = UpgradeResult(
                    success=False,
                    status=UpgradeStatus.ROLLED_BACK,
                    message=f"Validation failed, rolled back: {error}",
                    from_version=from_version,
                    to_version=to_version,
                    backup_path=backup_path,
                    error=error
                )
                self._record_patch_history(patch_id, to_version, 'upgrade', 'rolled_back', f"Validation failed: {error}")
                return result
            
            self._update_progress(95, "Applying EXE update...")
            
            requires_restart = False
            if new_exe_path:
                success, error, requires_restart = self._apply_exe_update(new_exe_path, to_version)
                if not success:
                    print(f"[UPGRADE] Warning: EXE update failed: {error}")
            
            set_current_version(to_version)
            
            self._status = UpgradeStatus.COMPLETED
            
            if requires_restart:
                self._update_progress(100, "Upgrade ready! Application will restart...")
                message = f"Successfully upgraded from {from_version} to {to_version}. Application will restart automatically."
            else:
                self._update_progress(100, "Upgrade completed successfully!")
                message = f"Successfully upgraded from {from_version} to {to_version}"
            
            # Print prominent upgrade summary to console
            print("\n" + "="*60)
            print("  UPGRADE COMPLETE")
            print("="*60)
            print(f"  From Version: {from_version}")
            print(f"  To Version:   {to_version}")
            print(f"  Backup:       {backup_path}")
            if requires_restart:
                print("  Status:       Application will restart automatically")
            else:
                print("  Status:       Success - No restart required")
            print("="*60 + "\n")
            
            result = UpgradeResult(
                success=True,
                status=UpgradeStatus.COMPLETED,
                message=message,
                from_version=from_version,
                to_version=to_version,
                backup_path=backup_path
            )
            
            self._record_patch_history(patch_id, to_version, 'upgrade', 'completed', '')
            self._record_upgrade(result)
            
            return result
            
        except Exception as e:
            self._status = UpgradeStatus.FAILED
            error_msg = str(e)
            
            if backup_path:
                self._update_progress(0, "Unexpected error, rolling back...")
                self._rollback(backup_path, from_version)
            
            # Print prominent upgrade failure to console
            print("\n" + "="*60)
            print("  UPGRADE FAILED")
            print("="*60)
            print(f"  From Version: {from_version}")
            print(f"  To Version:   {to_version}")
            print(f"  Error:        {error_msg}")
            if backup_path:
                print(f"  Backup:       {backup_path}")
                print("  Status:       Rolled back to previous version")
            print("="*60 + "\n")
            
            self._record_patch_history(patch_id, to_version, 'upgrade', 'failed', error_msg)
            
            return UpgradeResult(
                success=False,
                status=UpgradeStatus.FAILED,
                message=f"Upgrade failed: {error_msg}",
                from_version=from_version,
                to_version=to_version,
                backup_path=backup_path,
                error=error_msg
            )
    
    def _download_update(self, update_info: UpdateInfo) -> Tuple[Optional[str], str]:
        """Download the update package."""
        if not requests:
            return None, "requests library not available"
        
        if not update_info.download_url:
            return None, "No download URL provided"
        
        try:
            response = requests.get(
                update_info.download_url,
                stream=True,
                timeout=self.config.download_timeout_seconds
            )
            
            if response.status_code != 200:
                return None, f"Download failed with status {response.status_code}"
            
            download_dir = Path('upgrade/downloads')
            download_dir.mkdir(parents=True, exist_ok=True)
            
            filename = f"update_{update_info.version}.zip"
            download_path = download_dir / filename
            
            with open(download_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            return str(download_path), ""
            
        except requests.exceptions.Timeout:
            return None, "Download timed out"
        except Exception as e:
            return None, str(e)
    
    def _verify_checksum(self, file_path: str, expected_checksum: str) -> Tuple[bool, str]:
        """Verify file checksum."""
        try:
            sha256 = hashlib.sha256()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    sha256.update(chunk)
            
            actual = sha256.hexdigest()
            if actual.lower() == expected_checksum.lower():
                return True, ""
            else:
                return False, f"Checksum mismatch: expected {expected_checksum}, got {actual}"
        except Exception as e:
            return False, str(e)
    
    def _run_migrations(self, target_version: str) -> Tuple[bool, str]:
        """Run database migrations for the upgrade."""
        try:
            sys.path.insert(0, str(Path.cwd()))
            from scripts.migrations import MigrationManager
            
            manager = MigrationManager()
            result = manager.upgrade()
            
            if result.get('status') in ['current', 'upgraded']:
                return True, ""
            else:
                return False, f"Migration returned: {result}"
                
        except Exception as e:
            return False, str(e)
    
    def _validate_upgrade(self) -> Tuple[bool, str]:
        """Validate the upgrade was successful."""
        try:
            sys.path.insert(0, str(Path.cwd()))
            from scripts.migrations import MigrationManager
            
            manager = MigrationManager()
            missing = manager.get_missing_tables()
            
            if missing:
                return False, f"Missing tables after upgrade: {missing}"
            
            return True, ""
            
        except Exception as e:
            return False, str(e)
    
    def _extract_update(self, zip_path: str, target_version: str) -> Tuple[Optional[str], str]:
        """
        Extract the update ZIP and find the new EXE.
        
        Returns:
            Tuple of (path to new EXE or None, error message)
        """
        try:
            extract_dir = Path('upgrade/extracted') / target_version
            extract_dir.mkdir(parents=True, exist_ok=True)
            
            print(f"[UPGRADE] Extracting {zip_path} to {extract_dir}")
            
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(extract_dir)
            
            exe_files = list(extract_dir.rglob('*.exe'))
            print(f"[UPGRADE] Found EXE files: {[str(f) for f in exe_files]}")
            
            target_exe = None
            for exe in exe_files:
                if 'BotifyTrades' in exe.name or 'selfbot' in exe.name.lower():
                    target_exe = exe
                    break
            
            if not target_exe and exe_files:
                target_exe = exe_files[0]
            
            if target_exe:
                print(f"[UPGRADE] Selected EXE for update: {target_exe}")
                return str(target_exe), ""
            else:
                return None, "No EXE found in update package"
                
        except zipfile.BadZipFile:
            return None, "Invalid ZIP file"
        except Exception as e:
            return None, f"Extraction failed: {str(e)}"
    
    def _apply_exe_update(self, new_exe_path: str, target_version: str) -> Tuple[bool, str, bool]:
        """
        Apply EXE update using a batch script (Windows) or shell script (Linux).
        
        The script will:
        1. Wait for current process to exit
        2. Replace old EXE with new EXE
        3. Start the new EXE
        4. Clean up
        
        Returns:
            Tuple of (success, error_message, requires_restart)
        """
        if not getattr(sys, 'frozen', False):
            print("[UPGRADE] Not running as frozen EXE, skipping EXE replacement")
            return True, "", False
        
        current_exe = Path(sys.executable)
        new_exe = Path(new_exe_path)
        
        if not new_exe.exists():
            return False, f"New EXE not found: {new_exe_path}", False
        
        print(f"[UPGRADE] Current EXE: {current_exe}")
        print(f"[UPGRADE] New EXE: {new_exe}")
        print(f"[UPGRADE] New EXE size: {new_exe.stat().st_size / 1024 / 1024:.2f} MB")
        
        try:
            if sys.platform == 'win32':
                return self._create_windows_updater(current_exe, new_exe, target_version)
            else:
                return self._create_unix_updater(current_exe, new_exe, target_version)
        except Exception as e:
            return False, f"Failed to create updater: {str(e)}", False
    
    def _create_windows_updater(self, current_exe: Path, new_exe: Path, version: str) -> Tuple[bool, str, bool]:
        """Create a Windows batch script to replace the EXE after app exits."""
        batch_path = current_exe.parent / f'_update_{version}.bat'
        
        batch_content = f'''@echo off
echo ============================================
echo BotifyTrades Updater - Updating to {version}
echo ============================================
echo.
echo Waiting for application to close...
:waitloop
tasklist /FI "PID eq %1" 2>NUL | find /I "%1" >NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak >NUL
    goto waitloop
)
echo Application closed. Applying update...
echo.

:: Backup old EXE
if exist "{current_exe}" (
    echo Backing up old version...
    move /Y "{current_exe}" "{current_exe}.old" >NUL 2>&1
)

:: Copy new EXE
echo Installing new version...
copy /Y "{new_exe}" "{current_exe}" >NUL 2>&1
if errorlevel 1 (
    echo ERROR: Failed to copy new EXE
    echo Restoring backup...
    move /Y "{current_exe}.old" "{current_exe}" >NUL 2>&1
    pause
    exit /b 1
)

:: Start new version
echo Starting updated application...
start "" "{current_exe}"

:: Cleanup
echo Cleaning up...
del /Q "{current_exe}.old" >NUL 2>&1
timeout /t 3 /nobreak >NUL
del /Q "%~f0" >NUL 2>&1
'''
        
        try:
            with open(batch_path, 'w') as f:
                f.write(batch_content)
            
            print(f"[UPGRADE] Created Windows updater: {batch_path}")
            
            import subprocess
            import threading
            pid = os.getpid()
            CREATE_NEW_CONSOLE = 0x00000010
            DETACHED_PROCESS = 0x00000008
            subprocess.Popen(
                ['cmd', '/c', str(batch_path), str(pid)],
                creationflags=CREATE_NEW_CONSOLE | DETACHED_PROCESS,
                close_fds=True
            )
            
            print(f"[UPGRADE] Updater launched. Application will exit in 3 seconds...")
            print(f"[UPGRADE] The updater will replace the EXE and restart automatically.")
            
            # Schedule app exit so the batch script can replace the EXE
            def delayed_exit():
                import time
                time.sleep(3)
                print("[UPGRADE] Exiting for EXE replacement...")
                os._exit(0)
            
            exit_thread = threading.Thread(target=delayed_exit, daemon=True)
            exit_thread.start()
            
            return True, "", True
            
        except Exception as e:
            return False, f"Failed to create updater batch: {str(e)}", False
    
    def _create_unix_updater(self, current_exe: Path, new_exe: Path, version: str) -> Tuple[bool, str, bool]:
        """Create a Unix shell script to replace the executable after app exits."""
        script_path = current_exe.parent / f'_update_{version}.sh'
        
        script_content = f'''#!/bin/bash
echo "BotifyTrades Updater - Updating to {version}"
echo "Waiting for application to close..."

while kill -0 $1 2>/dev/null; do
    sleep 1
done

echo "Application closed. Applying update..."

# Backup old executable
if [ -f "{current_exe}" ]; then
    mv "{current_exe}" "{current_exe}.old"
fi

# Copy new executable
cp "{new_exe}" "{current_exe}"
chmod +x "{current_exe}"

# Start new version
"{current_exe}" &

# Cleanup
rm -f "{current_exe}.old"
sleep 2
rm -f "$0"
'''
        
        try:
            with open(script_path, 'w') as f:
                f.write(script_content)
            os.chmod(script_path, 0o755)
            
            print(f"[UPGRADE] Created Unix updater: {script_path}")
            
            import subprocess
            import threading
            pid = os.getpid()
            subprocess.Popen(
                ['/bin/bash', str(script_path), str(pid)],
                start_new_session=True,
                close_fds=True
            )
            
            print(f"[UPGRADE] Updater launched. Application will exit in 3 seconds...")
            print(f"[UPGRADE] The updater will replace the binary and restart automatically.")
            
            # Schedule app exit so the script can replace the binary
            def delayed_exit():
                import time
                time.sleep(3)
                print("[UPGRADE] Exiting for binary replacement...")
                os._exit(0)
            
            exit_thread = threading.Thread(target=delayed_exit, daemon=True)
            exit_thread.start()
            
            return True, "", True
            
        except Exception as e:
            return False, f"Failed to create updater script: {str(e)}", False
    
    def _rollback(self, backup_path: str, original_version: str = "") -> bool:
        """Rollback to the backup and restore version."""
        if not backup_path:
            return False
        
        success, error = self.backup_manager.restore_backup(backup_path)
        
        if success and original_version:
            set_current_version(original_version)
        
        return success
    
    def _record_patch_history(self, patch_id: str, version: str, patch_type: str, status: str, error_msg: str):
        """Record upgrade attempt in the database patch_history table."""
        try:
            import sqlite3
            from pathlib import Path
            
            db_path = _find_database_path()
            if not db_path.exists():
                print(f"[UPGRADE] Database not found for patch history")
                return
            
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS patch_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version TEXT NOT NULL,
                    patch_id TEXT UNIQUE NOT NULL,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    applied_at TEXT NOT NULL
                )
            ''')
            
            applied_at = datetime.now().isoformat()
            
            cursor.execute('''
                INSERT OR REPLACE INTO patch_history (version, patch_id, type, status, error_message, applied_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (version, patch_id, patch_type, status, error_msg, applied_at))
            
            conn.commit()
            conn.close()
            
            print(f"[UPGRADE] Recorded patch history: {patch_id} -> {status}")
            
        except Exception as e:
            print(f"[UPGRADE] Failed to record patch history: {e}")
    
    def _record_upgrade(self, result: UpgradeResult):
        """Record the upgrade in history."""
        try:
            history = []
            if self._history_file.exists():
                with open(self._history_file, 'r') as f:
                    history = json.load(f)
            
            history.append(result.to_dict())
            
            history = history[-50:]
            
            self._history_file.parent.mkdir(exist_ok=True)
            with open(self._history_file, 'w') as f:
                json.dump(history, f, indent=2)
                
        except Exception as e:
            print(f"[UPGRADE] Failed to record history: {e}")
    
    def get_upgrade_history(self) -> list:
        """Get the upgrade history from JSON file."""
        try:
            if self._history_file.exists():
                with open(self._history_file, 'r') as f:
                    return json.load(f)
        except:
            pass
        return []
    
    def get_patch_history(self) -> list:
        """Get patch history from the database."""
        try:
            import sqlite3
            from pathlib import Path
            
            db_path = _find_database_path()
            if not db_path.exists():
                return []
            
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT version, patch_id, type, status, error_message, applied_at
                FROM patch_history
                ORDER BY applied_at DESC
                LIMIT 50
            ''')
            
            rows = cursor.fetchall()
            conn.close()
            
            return [dict(row) for row in rows]
            
        except Exception as e:
            print(f"[UPGRADE] Failed to get patch history: {e}")
            return []
    
    def get_status(self) -> Dict:
        """Get current upgrade status."""
        return {
            'status': self._status.value,
            'progress': self._progress
        }


_runner_instance: Optional[UpgradeRunner] = None


def get_upgrade_runner() -> UpgradeRunner:
    """Get or create the global upgrade runner instance."""
    global _runner_instance
    if _runner_instance is None:
        _runner_instance = UpgradeRunner()
    return _runner_instance


def run_upgrade(update_info: UpdateInfo) -> UpgradeResult:
    """Convenience function to run an upgrade."""
    return get_upgrade_runner().run_upgrade(update_info)
