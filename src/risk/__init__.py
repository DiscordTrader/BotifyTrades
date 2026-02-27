"""
Risk Management Module
======================
Centralized position monitoring and risk management for the trading bot.

Components:
- RiskManager: Async position monitoring coordinator
- TieredTargets: Per-channel T1/T2/T3 profit target evaluation  
- GlobalRisk: Global stop loss and profit target fallback
- TrailingStop: Trailing stop activation and trigger logic
- PositionCache: Position state persistence and management

Usage:
    from src.risk import RiskManager, RiskDBAdapter
    
    risk_manager = RiskManager(
        position_fetcher=webull_broker.get_positions,
        alpaca_broker=alpaca_broker,
        db_adapter=RiskDBAdapter(),
        order_queue=order_queue,
        settings_provider=get_risk_management_settings
    )
    await risk_manager.start_monitoring()
"""

from .risk_types import (
    PositionSnapshot,
    RiskSettings,
    ChannelRiskSettings,
    ExitDecision,
    PositionCacheEntry
)

from .position_cache import PositionCache
from .tiered_targets import evaluate_tiered_targets
from .global_risk import evaluate_global_risk
from .trailing_stop import evaluate_trailing_stop
from .early_trailing import (
    evaluate_early_trailing,
    get_early_trailing_status,
    validate_early_trailing_settings,
    EarlyTrailingState,
    EarlyTrailingResult
)
from .position_monitor import RiskManager, RiskDBAdapter
from .risk_engine import (
    RiskAction,
    ActionType,
    TradeState,
    evaluate_exit_actions,
    apply_actions_to_cache,
    DYNAMIC_SL_PROFILES
)
from .ema_engine import (
    CandleAggregator,
    EMAEngine,
    EMAExitEvaluator,
    CandlePreWarmService,
    get_candle_service,
    EMAState,
    EMADecision,
    EMAEvalResult,
    Candle
)

__all__ = [
    'RiskManager',
    'RiskDBAdapter',
    'PositionSnapshot',
    'RiskSettings', 
    'ChannelRiskSettings',
    'ExitDecision',
    'PositionCacheEntry',
    'PositionCache',
    'evaluate_tiered_targets',
    'evaluate_global_risk',
    'evaluate_trailing_stop',
    'evaluate_early_trailing',
    'get_early_trailing_status',
    'validate_early_trailing_settings',
    'EarlyTrailingState',
    'EarlyTrailingResult',
    'RiskAction',
    'ActionType',
    'TradeState',
    'evaluate_exit_actions',
    'apply_actions_to_cache',
    'DYNAMIC_SL_PROFILES',
    'CandleAggregator',
    'EMAEngine',
    'EMAExitEvaluator',
    'CandlePreWarmService',
    'get_candle_service',
    'EMAState',
    'EMADecision',
    'EMAEvalResult',
    'Candle',
]
