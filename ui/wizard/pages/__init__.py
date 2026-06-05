"""
Wizard Pages Package
Contains all individual wizard step pages
"""

from .welcome import WelcomePage
from .app_mode import AppModePage
from .discord import DiscordPage
from .broker_selection import BrokerSelectionPage
from .broker_credentials import BrokerCredentialsPage
from .channels import ChannelConfigPage
from .risk_management import RiskManagementPage
from .notifications import NotificationsPage
from .privacy import PrivacyPage
from .review import ReviewPage

__all__ = [
    'WelcomePage',
    'AppModePage',
    'DiscordPage',
    'BrokerSelectionPage',
    'BrokerCredentialsPage',
    'ChannelConfigPage',
    'RiskManagementPage',
    'NotificationsPage',
    'PrivacyPage',
    'ReviewPage'
]
