"""
Update Configuration
====================
Configuration settings for the auto-update system.
"""

import os
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class UpdateConfig:
    """Configuration for the auto-update system."""
    
    github_owner: str = "DiscordTrader"
    github_repo: str = "BotifyTrades-Releases"
    
    update_check_url: Optional[str] = None
    
    check_on_startup: bool = True
    check_interval_hours: int = 6
    
    skip_versions: List[str] = field(default_factory=list)
    remind_later_hours: int = 24
    
    backup_retention_count: int = 5
    require_backup_before_update: bool = True
    
    verify_checksums: bool = True
    verify_signatures: bool = False
    
    show_changelog: bool = True
    allow_skip_version: bool = True
    force_update_on_critical: bool = True
    
    download_timeout_seconds: int = 300
    
    @classmethod
    def from_env(cls) -> 'UpdateConfig':
        """Create config from environment variables."""
        return cls(
            github_owner=os.environ.get('UPDATE_GITHUB_OWNER', 'DiscordTrader'),
            github_repo=os.environ.get('UPDATE_GITHUB_REPO', 'BotifyTrades-Releases'),
            update_check_url=os.environ.get('UPDATE_CHECK_URL'),
            check_on_startup=os.environ.get('UPDATE_CHECK_ON_STARTUP', 'true').lower() == 'true',
            check_interval_hours=int(os.environ.get('UPDATE_CHECK_INTERVAL_HOURS', '6')),
        )
    
    def get_github_releases_url(self) -> str:
        """Get the GitHub releases API URL."""
        return f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/releases/latest"
    
    def get_github_releases_all_url(self) -> str:
        """Get URL for all releases."""
        return f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/releases"
    
    def get_update_manifest_url(self) -> str:
        """Get the update manifest URL (custom server or GitHub)."""
        if self.update_check_url:
            return self.update_check_url
        return self.get_github_releases_url()


DEFAULT_CONFIG = UpdateConfig()
