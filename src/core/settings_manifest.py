"""
Settings Manifest - Single Source of Truth
==========================================
Every application setting MUST be declared here.
This enables automated consistency checking across:
- Database schema (storage)
- GUI controls (user interface)
- Runtime enforcement (execution)

Industry pattern: Settings Registry with cross-layer validation
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Callable


class SettingType(Enum):
    BOOLEAN = "boolean"
    INTEGER = "integer"
    FLOAT = "float"
    STRING = "string"
    JSON = "json"
    PERCENTAGE = "percentage"


class SettingNamespace(Enum):
    TRADING = "trading"
    RISK = "risk"
    NOTIFICATIONS = "notifications"
    AI = "ai"
    MARKET_DATA = "market_data"
    DISCORD = "discord"
    BROKER = "broker"
    SYSTEM = "system"


@dataclass
class SettingDefinition:
    """Defines a single setting with full metadata for validation."""
    key: str
    namespace: SettingNamespace
    setting_type: SettingType
    default: Any
    description: str
    db_table: str = "settings"
    db_column: Optional[str] = None
    gui_route: Optional[str] = None
    gui_element_id: Optional[str] = None
    enforced_in: List[str] = field(default_factory=list)
    validator: Optional[Callable[[Any], bool]] = None
    
    @property
    def full_key(self) -> str:
        return f"{self.namespace.value}.{self.key}"
    
    @property
    def storage_key(self) -> str:
        return self.db_column or self.key


SETTINGS_MANIFEST: Dict[str, SettingDefinition] = {}


def register_setting(setting: SettingDefinition) -> SettingDefinition:
    """Register a setting in the manifest."""
    SETTINGS_MANIFEST[setting.full_key] = setting
    return setting


POSITION_SIZING_ENABLED = register_setting(SettingDefinition(
    key="position_sizing_enabled",
    namespace=SettingNamespace.TRADING,
    setting_type=SettingType.BOOLEAN,
    default=True,
    description="Enable automatic position sizing based on account value",
    gui_route="/settings",
    gui_element_id="position_sizing_enabled",
    enforced_in=["src/selfbot_webull.py:place_order", "src/execution/order_manager.py"],
))

MAX_POSITION_SIZE = register_setting(SettingDefinition(
    key="max_position_size",
    namespace=SettingNamespace.TRADING,
    setting_type=SettingType.FLOAT,
    default=1000.0,
    description="Maximum dollar amount per position",
    gui_route="/settings",
    gui_element_id="max_position_size",
    enforced_in=["src/selfbot_webull.py:place_order", "src/execution/order_manager.py"],
    validator=lambda x: x > 0,
))

POSITION_SIZE_PERCENT = register_setting(SettingDefinition(
    key="position_size_percent",
    namespace=SettingNamespace.TRADING,
    setting_type=SettingType.PERCENTAGE,
    default=5.0,
    description="Percentage of portfolio per position",
    gui_route="/settings",
    gui_element_id="position_size_percent",
    enforced_in=["src/selfbot_webull.py:place_order"],
    validator=lambda x: 0 < x <= 100,
))

SLIPPAGE_PROTECTION_ENABLED = register_setting(SettingDefinition(
    key="slippage_protection_enabled",
    namespace=SettingNamespace.TRADING,
    setting_type=SettingType.BOOLEAN,
    default=True,
    description="Enable price slippage protection on orders",
    gui_route="/settings",
    gui_element_id="slippage_protection_enabled",
    enforced_in=["src/selfbot_webull.py:place_order", "src/brokers/webull_broker.py"],
))

SLIPPAGE_PERCENT = register_setting(SettingDefinition(
    key="slippage_percent",
    namespace=SettingNamespace.TRADING,
    setting_type=SettingType.PERCENTAGE,
    default=2.0,
    description="Maximum allowed slippage percentage before rejecting order",
    gui_route="/settings",
    gui_element_id="slippage_percent",
    enforced_in=["src/selfbot_webull.py:place_order"],
    validator=lambda x: 0 < x <= 50,
))

AUTO_CLEAR_STALE_TRADES = register_setting(SettingDefinition(
    key="auto_clear_stale_trades",
    namespace=SettingNamespace.TRADING,
    setting_type=SettingType.BOOLEAN,
    default=False,
    description="Automatically clear stale/orphaned trades",
    gui_route="/settings",
    gui_element_id="auto_clear_stale_trades",
    enforced_in=["src/trade_tracker.py:cleanup_stale_trades"],
))

STALE_TRADE_HOURS = register_setting(SettingDefinition(
    key="stale_trade_hours",
    namespace=SettingNamespace.TRADING,
    setting_type=SettingType.INTEGER,
    default=24,
    description="Hours after which a trade is considered stale",
    gui_route="/settings",
    gui_element_id="stale_trade_hours",
    enforced_in=["src/trade_tracker.py:cleanup_stale_trades"],
    validator=lambda x: x > 0,
))

MAX_DAILY_TRADES = register_setting(SettingDefinition(
    key="max_daily_trades",
    namespace=SettingNamespace.TRADING,
    setting_type=SettingType.INTEGER,
    default=50,
    description="Maximum number of trades per day",
    gui_route="/settings",
    gui_element_id="max_daily_trades",
    enforced_in=["src/selfbot_webull.py:place_order"],
    validator=lambda x: x > 0,
))

MAX_DAILY_LOSS = register_setting(SettingDefinition(
    key="max_daily_loss",
    namespace=SettingNamespace.TRADING,
    setting_type=SettingType.FLOAT,
    default=500.0,
    description="Maximum daily loss before stopping trading",
    gui_route="/settings",
    gui_element_id="max_daily_loss",
    enforced_in=["src/selfbot_webull.py:place_order", "src/risk/position_monitor.py"],
    validator=lambda x: x > 0,
))

NOTIFICATIONS_ENABLED = register_setting(SettingDefinition(
    key="notifications_enabled",
    namespace=SettingNamespace.NOTIFICATIONS,
    setting_type=SettingType.BOOLEAN,
    default=True,
    description="Enable trade notifications",
    gui_route="/settings",
    gui_element_id="notifications_enabled",
    enforced_in=["gui_app/discord_notifier.py", "src/notifications/notifier.py"],
))

NOTIFICATION_ON_ENTRY = register_setting(SettingDefinition(
    key="notification_on_entry",
    namespace=SettingNamespace.NOTIFICATIONS,
    setting_type=SettingType.BOOLEAN,
    default=True,
    description="Send notification when entering a trade",
    gui_route="/settings",
    gui_element_id="notification_on_entry",
    enforced_in=["gui_app/discord_notifier.py"],
))

NOTIFICATION_ON_EXIT = register_setting(SettingDefinition(
    key="notification_on_exit",
    namespace=SettingNamespace.NOTIFICATIONS,
    setting_type=SettingType.BOOLEAN,
    default=True,
    description="Send notification when exiting a trade",
    gui_route="/settings",
    gui_element_id="notification_on_exit",
    enforced_in=["gui_app/discord_notifier.py"],
))

AI_ANALYSIS_ENABLED = register_setting(SettingDefinition(
    key="ai_analysis_enabled",
    namespace=SettingNamespace.AI,
    setting_type=SettingType.BOOLEAN,
    default=False,
    description="Enable AI-powered trade analysis",
    gui_route="/settings",
    gui_element_id="ai_analysis_enabled",
    enforced_in=["src/ai_analyzer.py", "src/selfbot_webull.py:analyze_trade"],
))

PRE_TRADE_ANALYSIS = register_setting(SettingDefinition(
    key="pre_trade_analysis",
    namespace=SettingNamespace.AI,
    setting_type=SettingType.BOOLEAN,
    default=True,
    description="Run AI analysis before executing trade",
    gui_route="/settings",
    gui_element_id="pre_trade_analysis",
    enforced_in=["src/selfbot_webull.py:place_order"],
))

POST_TRADE_ANALYSIS = register_setting(SettingDefinition(
    key="post_trade_analysis",
    namespace=SettingNamespace.AI,
    setting_type=SettingType.BOOLEAN,
    default=True,
    description="Run AI analysis after trade execution",
    gui_route="/settings",
    gui_element_id="post_trade_analysis",
    enforced_in=["src/selfbot_webull.py:on_order_filled"],
))

RISK_MANAGEMENT_ENABLED = register_setting(SettingDefinition(
    key="risk_management_enabled",
    namespace=SettingNamespace.RISK,
    setting_type=SettingType.BOOLEAN,
    default=False,
    description="Enable global risk management (stop loss, take profit)",
    gui_route="/settings",
    gui_element_id="risk_management_enabled",
    enforced_in=["src/risk/position_monitor.py:monitor_positions"],
))

GLOBAL_STOP_LOSS_PERCENT = register_setting(SettingDefinition(
    key="global_stop_loss_percent",
    namespace=SettingNamespace.RISK,
    setting_type=SettingType.PERCENTAGE,
    default=10.0,
    description="Global stop loss percentage",
    gui_route="/settings",
    gui_element_id="global_stop_loss_percent",
    enforced_in=["src/risk/position_monitor.py"],
    validator=lambda x: 0 < x <= 100,
))

GLOBAL_TAKE_PROFIT_PERCENT = register_setting(SettingDefinition(
    key="global_take_profit_percent",
    namespace=SettingNamespace.RISK,
    setting_type=SettingType.PERCENTAGE,
    default=20.0,
    description="Global take profit percentage",
    gui_route="/settings",
    gui_element_id="global_take_profit_percent",
    enforced_in=["src/risk/position_monitor.py"],
    validator=lambda x: 0 < x <= 500,
))

TRAILING_STOP_ENABLED = register_setting(SettingDefinition(
    key="trailing_stop_enabled",
    namespace=SettingNamespace.RISK,
    setting_type=SettingType.BOOLEAN,
    default=False,
    description="Enable trailing stop loss",
    gui_route="/settings",
    gui_element_id="trailing_stop_enabled",
    enforced_in=["src/risk/position_monitor.py"],
))

TRAILING_STOP_PERCENT = register_setting(SettingDefinition(
    key="trailing_stop_percent",
    namespace=SettingNamespace.RISK,
    setting_type=SettingType.PERCENTAGE,
    default=5.0,
    description="Trailing stop loss percentage from high",
    gui_route="/settings",
    gui_element_id="trailing_stop_percent",
    enforced_in=["src/risk/position_monitor.py"],
    validator=lambda x: 0 < x <= 50,
))

PAPER_TRADE_MODE = register_setting(SettingDefinition(
    key="paper_trade",
    namespace=SettingNamespace.BROKER,
    setting_type=SettingType.BOOLEAN,
    default=True,
    description="Enable paper trading mode (simulated trades)",
    gui_route="/settings",
    gui_element_id="paper_trade",
    enforced_in=["src/selfbot_webull.py:place_order", "src/brokers/webull_broker.py"],
))

DEFAULT_BROKER = register_setting(SettingDefinition(
    key="default_broker",
    namespace=SettingNamespace.BROKER,
    setting_type=SettingType.STRING,
    default="webull",
    description="Default broker for trade execution",
    gui_route="/settings",
    gui_element_id="default_broker",
    enforced_in=["src/selfbot_webull.py:get_broker"],
))

SIGNAL_AUTO_EXECUTE = register_setting(SettingDefinition(
    key="signal_auto_execute",
    namespace=SettingNamespace.DISCORD,
    setting_type=SettingType.BOOLEAN,
    default=False,
    description="Automatically execute parsed signals",
    gui_route="/settings",
    gui_element_id="signal_auto_execute",
    enforced_in=["src/selfbot_webull.py:on_message"],
))

MARKET_DATA_PROVIDER = register_setting(SettingDefinition(
    key="market_data_provider",
    namespace=SettingNamespace.MARKET_DATA,
    setting_type=SettingType.STRING,
    default="webull",
    description="Primary market data provider",
    gui_route="/settings",
    gui_element_id="market_data_provider",
    enforced_in=["src/market_data/provider.py"],
))

NEWS_ENABLED = register_setting(SettingDefinition(
    key="news_enabled",
    namespace=SettingNamespace.MARKET_DATA,
    setting_type=SettingType.BOOLEAN,
    default=False,
    description="Enable news feed integration",
    gui_route="/settings",
    gui_element_id="news_enabled",
    enforced_in=["src/market_data/news_service.py"],
))


CONVERSION_CHANNEL_ID = register_setting(SettingDefinition(
    key="conversion_channel_id",
    namespace=SettingNamespace.DISCORD,
    setting_type=SettingType.STRING,
    default="",
    description="Channel ID for signal conversion output",
    gui_route="/settings",
    gui_element_id="conversion_channel_id",
    enforced_in=["src/selfbot_webull.py:signal_conversion"],
))

TARGET_EXECUTION_CHANNEL_ID = register_setting(SettingDefinition(
    key="target_execution_channel_id",
    namespace=SettingNamespace.DISCORD,
    setting_type=SettingType.STRING,
    default="",
    description="Target channel for trade execution",
    gui_route="/settings",
    gui_element_id="target_execution_channel_id",
    enforced_in=["src/selfbot_webull.py:signal_conversion"],
))

USER_CONSENT_ACCEPTED = register_setting(SettingDefinition(
    key="user_consent_accepted",
    namespace=SettingNamespace.SYSTEM,
    setting_type=SettingType.BOOLEAN,
    default=False,
    description="User has accepted terms and conditions",
    gui_route="/setup",
    gui_element_id="user_consent_accepted",
    enforced_in=["gui_app/routes.py:check_consent"],
))

USER_CONSENT_VERSION = register_setting(SettingDefinition(
    key="user_consent_version",
    namespace=SettingNamespace.SYSTEM,
    setting_type=SettingType.STRING,
    default="",
    description="Version of terms user accepted",
    gui_route="/setup",
    gui_element_id="user_consent_version",
    enforced_in=["gui_app/routes.py:check_consent"],
))

USER_CONSENT_TIMESTAMP = register_setting(SettingDefinition(
    key="user_consent_timestamp",
    namespace=SettingNamespace.SYSTEM,
    setting_type=SettingType.STRING,
    default="",
    description="Timestamp when user accepted terms",
    gui_route="/setup",
    gui_element_id="user_consent_timestamp",
    enforced_in=["gui_app/routes.py:check_consent"],
))


def get_all_settings() -> Dict[str, SettingDefinition]:
    """Return all registered settings."""
    return SETTINGS_MANIFEST.copy()


def get_settings_by_namespace(namespace: SettingNamespace) -> Dict[str, SettingDefinition]:
    """Return settings filtered by namespace."""
    return {k: v for k, v in SETTINGS_MANIFEST.items() if v.namespace == namespace}


def get_enforced_settings(module_path: str) -> List[SettingDefinition]:
    """Return settings that should be enforced in a specific module."""
    return [s for s in SETTINGS_MANIFEST.values() if module_path in s.enforced_in]


def validate_setting_value(full_key: str, value: Any) -> bool:
    """Validate a setting value against its definition."""
    if full_key not in SETTINGS_MANIFEST:
        return False
    
    setting = SETTINGS_MANIFEST[full_key]
    
    if setting.setting_type == SettingType.BOOLEAN:
        if not isinstance(value, bool):
            return False
    elif setting.setting_type == SettingType.INTEGER:
        if not isinstance(value, int):
            return False
    elif setting.setting_type in (SettingType.FLOAT, SettingType.PERCENTAGE):
        if not isinstance(value, (int, float)):
            return False
    elif setting.setting_type == SettingType.STRING:
        if not isinstance(value, str):
            return False
    
    if setting.validator:
        return setting.validator(value)
    
    return True


def get_setting_default(full_key: str) -> Any:
    """Get the default value for a setting."""
    if full_key not in SETTINGS_MANIFEST:
        raise KeyError(f"Unknown setting: {full_key}")
    return SETTINGS_MANIFEST[full_key].default


def get_setting_info(full_key: str) -> Optional[SettingDefinition]:
    """Get full information about a setting."""
    return SETTINGS_MANIFEST.get(full_key)
