"""
Version Checker Service
=======================
Checks for available updates from GitHub releases or custom update server.
"""

import os
import json
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Callable
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

from .version import get_current_version, compare_versions, APP_VERSION
from .config import UpdateConfig, DEFAULT_CONFIG


class UpdateInfo:
    """Information about an available update."""
    
    def __init__(
        self,
        version: str,
        download_url: str,
        changelog: str = "",
        release_date: str = "",
        is_critical: bool = False,
        checksum: str = "",
        size_bytes: int = 0,
        min_version: str = ""
    ):
        self.version = version
        self.download_url = download_url
        self.changelog = changelog
        self.release_date = release_date
        self.is_critical = is_critical
        self.checksum = checksum
        self.size_bytes = size_bytes
        self.min_version = min_version
    
    def to_dict(self) -> Dict:
        return {
            'version': self.version,
            'download_url': self.download_url,
            'changelog': self.changelog,
            'release_date': self.release_date,
            'is_critical': self.is_critical,
            'checksum': self.checksum,
            'size_bytes': self.size_bytes,
            'min_version': self.min_version
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'UpdateInfo':
        return cls(
            version=data.get('version', ''),
            download_url=data.get('download_url', ''),
            changelog=data.get('changelog', ''),
            release_date=data.get('release_date', ''),
            is_critical=data.get('is_critical', False),
            checksum=data.get('checksum', ''),
            size_bytes=data.get('size_bytes', 0),
            min_version=data.get('min_version', '')
        )


class VersionChecker:
    """Service to check for available updates."""
    
    def __init__(self, config: UpdateConfig = None):
        self.config = config or DEFAULT_CONFIG
        self._last_check: Optional[datetime] = None
        self._cached_update: Optional[UpdateInfo] = None
        self._check_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._callbacks: List[Callable[[UpdateInfo], None]] = []
        self._state_file = Path('upgrade/.update_state.json')
    
    def add_update_callback(self, callback: Callable[[UpdateInfo], None]):
        """Add a callback to be called when an update is found."""
        self._callbacks.append(callback)
    
    def _notify_callbacks(self, update_info: UpdateInfo):
        """Notify all registered callbacks of an update."""
        for callback in self._callbacks:
            try:
                callback(update_info)
            except Exception as e:
                print(f"[UPDATE] Callback error: {e}")
    
    def _load_state(self) -> Dict:
        """Load persisted state (skipped versions, remind later, etc)."""
        try:
            if self._state_file.exists():
                with open(self._state_file, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}
    
    def _save_state(self, state: Dict):
        """Save state to disk."""
        try:
            self._state_file.parent.mkdir(exist_ok=True)
            with open(self._state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            print(f"[UPDATE] Failed to save state: {e}")
    
    def skip_version(self, version: str):
        """Mark a version as skipped (don't notify again)."""
        state = self._load_state()
        skipped = state.get('skipped_versions', [])
        if version not in skipped:
            skipped.append(version)
        state['skipped_versions'] = skipped
        self._save_state(state)
    
    def is_version_skipped(self, version: str) -> bool:
        """Check if a version has been skipped."""
        state = self._load_state()
        return version in state.get('skipped_versions', [])
    
    def remind_later(self, hours: int = None):
        """Postpone update notification for specified hours."""
        hours = hours or self.config.remind_later_hours
        state = self._load_state()
        state['remind_after'] = (datetime.now() + timedelta(hours=hours)).isoformat()
        self._save_state(state)
    
    def should_remind(self) -> bool:
        """Check if we should show the update reminder."""
        state = self._load_state()
        remind_after = state.get('remind_after')
        if not remind_after:
            return True
        try:
            remind_time = datetime.fromisoformat(remind_after)
            return datetime.now() >= remind_time
        except:
            return True
    
    def check_for_updates(self, force: bool = False) -> Optional[UpdateInfo]:
        """
        Check for available updates.
        
        Args:
            force: If True, bypass cache and always check
            
        Returns:
            UpdateInfo if an update is available, None otherwise
        """
        if not requests:
            print("[UPDATE] requests library not available")
            return None
        
        if not force and self._cached_update and self._last_check:
            cache_valid = datetime.now() - self._last_check < timedelta(minutes=30)
            if cache_valid:
                return self._cached_update
        
        current_version = get_current_version()
        print(f"[UPDATE] Current version: {current_version}")
        print(f"[UPDATE] Checking GitHub: {self.config.get_github_releases_url()}")
        
        try:
            update_info = self._check_github_releases()
            
            if update_info:
                print(f"[UPDATE] Latest version on GitHub: {update_info.version}")
                comparison = compare_versions(update_info.version, current_version)
                print(f"[UPDATE] Version comparison result: {comparison} (>0 means update available)")
                
                if comparison > 0:
                    if not update_info.is_critical and self.is_version_skipped(update_info.version):
                        print(f"[UPDATE] Version {update_info.version} is skipped by user")
                        return None
                    
                    print(f"[UPDATE] Update available: {current_version} -> {update_info.version}")
                    self._cached_update = update_info
                    self._last_check = datetime.now()
                    return update_info
                else:
                    print(f"[UPDATE] Already on latest version")
            else:
                print("[UPDATE] No update info returned from GitHub check")
            
            self._cached_update = None
            self._last_check = datetime.now()
            return None
            
        except Exception as e:
            print(f"[UPDATE] Error checking for updates: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _check_github_releases(self) -> Optional[UpdateInfo]:
        """Check GitHub releases for updates."""
        url = self.config.get_github_releases_url()
        print(f"[UPDATE] Fetching releases from: {url}")
        
        try:
            headers = {'Accept': 'application/vnd.github.v3+json'}
            
            github_token = os.environ.get('GITHUB_TOKEN')
            if github_token:
                headers['Authorization'] = f'token {github_token}'
                print("[UPDATE] Using GitHub token for authentication")
            
            response = requests.get(url, headers=headers, timeout=10)
            print(f"[UPDATE] GitHub API response status: {response.status_code}")
            
            if response.status_code == 404:
                print("[UPDATE] No releases found on GitHub (404)")
                return None
            
            if response.status_code != 200:
                print(f"[UPDATE] GitHub API error: {response.status_code} - {response.text[:200]}")
                return None
            
            release = response.json()
            
            version = release.get('tag_name', '').lstrip('v')
            if not version:
                return None
            
            download_url = ""
            size_bytes = 0
            
            # Determine platform-specific asset name
            import sys
            if sys.platform == 'win32':
                platform_keyword = 'windows'
            elif sys.platform == 'darwin':
                platform_keyword = 'macos'
            else:
                platform_keyword = 'linux'
            
            print(f"[UPDATE] Looking for {platform_keyword} asset...")
            
            for asset in release.get('assets', []):
                name = asset.get('name', '').lower()
                if ('botify' in name or 'trading' in name) and platform_keyword in name:
                    if name.endswith('.exe') or name.endswith('.zip') or name.endswith('.tar.gz'):
                        download_url = asset.get('browser_download_url', '')
                        size_bytes = asset.get('size', 0)
                        print(f"[UPDATE] Found matching asset: {name}")
                        break
            
            if not download_url and release.get('zipball_url'):
                download_url = release.get('zipball_url')
            
            body = release.get('body', '')
            is_critical = '[CRITICAL]' in body.upper() or '[SECURITY]' in body.upper()
            
            return UpdateInfo(
                version=version,
                download_url=download_url,
                changelog=body,
                release_date=release.get('published_at', ''),
                is_critical=is_critical,
                size_bytes=size_bytes
            )
            
        except requests.exceptions.Timeout:
            print("[UPDATE] GitHub request timed out")
            return None
        except Exception as e:
            print(f"[UPDATE] Error parsing GitHub response: {e}")
            return None
    
    def _check_custom_server(self) -> Optional[UpdateInfo]:
        """Check custom update server for updates."""
        url = self.config.update_check_url
        if not url:
            return None
        
        try:
            response = requests.get(url, timeout=10)
            if response.status_code != 200:
                return None
            
            data = response.json()
            return UpdateInfo.from_dict(data)
            
        except Exception as e:
            print(f"[UPDATE] Error checking custom server: {e}")
            return None
    
    def start_background_checks(self):
        """Start periodic background update checks."""
        if self._check_thread and self._check_thread.is_alive():
            return
        
        self._stop_event.clear()
        self._check_thread = threading.Thread(target=self._background_check_loop, daemon=True)
        self._check_thread.start()
    
    def stop_background_checks(self):
        """Stop background update checks."""
        self._stop_event.set()
        if self._check_thread:
            self._check_thread.join(timeout=2)
    
    def _background_check_loop(self):
        """Background thread for periodic update checks."""
        interval_seconds = self.config.check_interval_hours * 3600
        
        while not self._stop_event.is_set():
            if self.should_remind():
                update = self.check_for_updates()
                if update:
                    self._notify_callbacks(update)
            
            self._stop_event.wait(interval_seconds)
    
    def get_status(self) -> Dict:
        """Get current update checker status."""
        return {
            'current_version': get_current_version(),
            'app_version': APP_VERSION,
            'last_check': self._last_check.isoformat() if self._last_check else None,
            'cached_update': self._cached_update.to_dict() if self._cached_update else None,
            'background_running': self._check_thread is not None and self._check_thread.is_alive(),
            'should_remind': self.should_remind()
        }


_checker_instance: Optional[VersionChecker] = None


def get_version_checker(config: UpdateConfig = None) -> VersionChecker:
    """Get or create the global version checker instance."""
    global _checker_instance
    if _checker_instance is None:
        _checker_instance = VersionChecker(config)
    return _checker_instance


def check_for_updates(force: bool = False) -> Optional[UpdateInfo]:
    """Convenience function to check for updates."""
    return get_version_checker().check_for_updates(force)
