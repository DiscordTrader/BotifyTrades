"""
Signal Format Registry - Industry-standard modular signal parsing system.

This registry allows multiple trader signal formats to be registered with priorities.
Each format handler is self-contained and can be added without modifying core code.

Usage:
    from services.signal_format_registry import SignalFormatRegistry
    
    registry = SignalFormatRegistry()
    result = registry.parse(text)
    if result:
        print(f"Matched format: {result['_format_name']}")
"""

import re
from typing import Optional, Dict, List, Callable, Any
from datetime import datetime
from dataclasses import dataclass


@dataclass
class SignalFormat:
    """Represents a registered signal format handler."""
    name: str
    description: str
    priority: int  # Lower = higher priority (tried first)
    pattern: re.Pattern
    parser: Callable[[re.Match, str], Optional[Dict[str, Any]]]
    examples: List[str]
    enabled: bool = True


class SignalFormatRegistry:
    """
    Modular signal format registry with priority-based matching.
    
    Formats are tried in priority order (lowest number first).
    First successful match wins.
    """
    
    def __init__(self):
        self._formats: Dict[str, SignalFormat] = {}
        self._sorted_formats: List[SignalFormat] = []
        self._register_builtin_formats()
    
    def register(self, 
                 name: str,
                 description: str,
                 priority: int,
                 pattern: str,
                 parser: Callable[[re.Match, str], Optional[Dict[str, Any]]],
                 examples: List[str],
                 flags: int = re.IGNORECASE) -> None:
        """
        Register a new signal format handler.
        
        Args:
            name: Unique identifier for this format
            description: Human-readable description
            priority: Lower = higher priority (0-100 recommended)
            pattern: Regex pattern string
            parser: Function that takes (match, original_text) and returns parsed dict or None
            examples: Example signals this format handles
            flags: Regex flags (default: IGNORECASE)
        """
        compiled = re.compile(pattern, flags)
        fmt = SignalFormat(
            name=name,
            description=description,
            priority=priority,
            pattern=compiled,
            parser=parser,
            examples=examples
        )
        self._formats[name] = fmt
        self._rebuild_sorted_list()
    
    def unregister(self, name: str) -> bool:
        """Remove a format from the registry."""
        if name in self._formats:
            del self._formats[name]
            self._rebuild_sorted_list()
            return True
        return False
    
    def set_enabled(self, name: str, enabled: bool) -> bool:
        """Enable or disable a format without removing it."""
        if name in self._formats:
            self._formats[name].enabled = enabled
            return True
        return False
    
    def _rebuild_sorted_list(self) -> None:
        """Rebuild sorted format list by priority."""
        self._sorted_formats = sorted(
            self._formats.values(),
            key=lambda f: f.priority
        )
    
    def _strip_discord_mentions(self, text: str) -> str:
        """Strip Discord mentions from text to allow pattern matching."""
        text = re.sub(r'<@&\d+>\s*', '', text)
        text = re.sub(r'<@!?\d+>\s*', '', text)
        text = re.sub(r'<#\d+>\s*', '', text)
        text = re.sub(r'@(?:everyone|here)\s*', '', text)
        return text.strip()
    
    def parse(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Parse text using registered formats in priority order.
        
        Returns:
            Parsed signal dict with '_format_name' indicating which format matched,
            or None if no format matched.
        """
        # Strip Discord mentions to allow patterns to match
        clean_text = self._strip_discord_mentions(text.strip())
        
        for fmt in self._sorted_formats:
            if not fmt.enabled:
                continue
            
            match = fmt.pattern.search(clean_text)
            if match:
                try:
                    result = fmt.parser(match, clean_text)
                    if result:
                        result['_format_name'] = fmt.name
                        print(f"[FORMAT REGISTRY] ✓ Matched '{fmt.name}': {result.get('action')} {result.get('symbol')} {result.get('strike')}{result.get('opt_type', '')}")
                        return result
                except Exception as e:
                    print(f"[FORMAT REGISTRY] Error in {fmt.name} parser: {e}")
                    continue
        
        return None
    
    def list_formats(self) -> List[Dict[str, Any]]:
        """List all registered formats."""
        return [
            {
                'name': f.name,
                'description': f.description,
                'priority': f.priority,
                'enabled': f.enabled,
                'examples': f.examples
            }
            for f in self._sorted_formats
        ]
    
    def _register_builtin_formats(self) -> None:
        """Register all built-in trader formats."""
        
        # =====================================================================
        # JAKE / OPTIONEERING FORMAT
        # =====================================================================
        
        # Jake +/- notation for options: +5 IWM @ lim0.08, -2 IWM @ lim0.16
        self.register(
            name="jake_plusminus_simple",
            description="Jake's +/- qty notation for options (symbol only)",
            priority=10,
            pattern=r'^([+-])(\d+)\s+\$?([A-Za-z]+)\s*@\s*lim([0-9.]+)',
            parser=self._parse_jake_plusminus_simple,
            examples=["+5 IWM @ lim0.08", "-2 IWM @ lim0.16", "+1 GRAB @ lim0.65"]
        )
        
        # Jake full format: +1 $GRAB $7c 17APR2026 @ lim0.65
        self.register(
            name="jake_full_option",
            description="Jake's full option format with expiry",
            priority=15,
            pattern=r'^([+-])(\d+)\s+\$?([A-Za-z]+)\s+\$?(\d+(?:\.\d+)?)([CPcp])\s+(\d{1,2})([A-Za-z]{3})(\d{2,4})\s*@\s*lim([0-9.]+)',
            parser=self._parse_jake_full_option,
            examples=["+1 $GRAB $7c 17APR2026 @ lim0.65", "+2 $BBAI $8c 16JAN2026 @lim0.37"]
        )
        
        # Jake alternate expiry: +1 $ONON $55c 20FEB2026 @lim0.75
        self.register(
            name="jake_option_exp",
            description="Jake's option with DDMMMYYYY expiry",
            priority=16,
            pattern=r'^([+-])?(\d+)\s+\$?([A-Za-z]+)\s+\$?(\d+(?:\.\d+)?)([CPcp])\s+(\d{1,2})([A-Za-z]{3})(\d{2,4})\s*@?\s*(?:lim)?([0-9.]+)',
            parser=self._parse_jake_option_exp,
            examples=["+1 $ONON $55c 20FEB2026 @lim0.75", "$BBAI $8c 16JAN2026 @lim0.59"]
        )
        
        # Jake Order Executed format: Bought 1 Single MSTR 12/12/2025 185 CALL @1.68
        self.register(
            name="jake_order_executed",
            description="Jake's order execution notification",
            priority=20,
            pattern=r'(Bought|Sold)\s+(\d+)\s+Single\s+([A-Za-z]+)\s+(\d{1,2})/(\d{1,2})/(\d{2,4})\s+(\d+(?:\.\d+)?)\s+(CALL|PUT)\s*@\s*([0-9.]+)',
            parser=self._parse_jake_order_executed,
            examples=["Bought 1 Single MSTR 12/12/2025 185 CALL @1.68", "Sold -1 Single MSTR 1/2/2026 150 PUT @1.38"]
        )
        
        # Jake price update: $ZS +44% @lim2.40
        self.register(
            name="jake_price_update",
            description="Jake's price/gain update (not actionable, tracking only)",
            priority=90,
            pattern=r'\$([A-Za-z]+)\s+[+-]?\d+%\s*@\s*lim([0-9.]+)',
            parser=self._parse_jake_price_update,
            examples=["$ZS +44% @lim2.40", "$NBIS +86% @lim7.63"]
        )
        
        # =====================================================================
        # SLEM FORMAT
        # =====================================================================
        
        # Slem format: $TSLA 445p 4.18 1/9 exp
        self.register(
            name="slem_option",
            description="Slem's option format with exp suffix",
            priority=25,
            pattern=r'\$([A-Za-z]+)\s+(\d+(?:\.\d+)?)([CPcp])\s+([0-9.]+)\s+(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\s*(?:exp)?',
            parser=self._parse_slem_option,
            examples=["$TSLA 445p 4.18 1/9 exp", "$LITE 400c 2.25 1/9 exp", "$NVDA 187.5c 1.05 1/9 exp"]
        )
        
        # Slem lotto format: $MDB 422.5c 2.20 1/9 @Lottos
        self.register(
            name="slem_lotto",
            description="Slem's lotto format with @ tag",
            priority=26,
            pattern=r'\$([A-Za-z]+)\s+(\d+(?:\.\d+)?)([CPcp])\s+([0-9.]+)\s+(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\s*@',
            parser=self._parse_slem_option,
            examples=["$MDB 422.5c 2.20 1/9 @Lottos", "$IREN 60c 1.45 1/30 @Leaps"]
        )
        
        # Slem gain update: $MDB 270% gain (not actionable)
        self.register(
            name="slem_gain_update",
            description="Slem's gain update (tracking only)",
            priority=91,
            pattern=r'\$([A-Za-z]+)\s+(\d+)%\s+gain',
            parser=self._parse_slem_gain_update,
            examples=["$MDB 270% gain", "$LITE 600% gain"]
        )
        
        # =====================================================================
        # STACK$ FORMAT (already exists, registering for completeness)
        # =====================================================================
        
        # STACK$ with expiry: BTO 1 NVDA 185p 01/16 @ 4.50
        self.register(
            name="stack_option",
            description="STACK$ format with combined strike+type",
            priority=30,
            pattern=r'(BTO|STC)\s+(\d+)\s+\$?([A-Za-z]+)\s+(\d+(?:\.\d+)?)([CPcp])\s+(\d{1,2})/(\d{1,2})\s*@\s*([0-9.]+)',
            parser=self._parse_stack_option,
            examples=["BTO 1 NVDA 185p 01/16 @ 4.50", "STC 1 RKLB 75p 01/16 @ 7.50"]
        )
        
        # STACK$ 0DTE: BTO 1 SPX 6925c @ 1.90
        self.register(
            name="stack_0dte",
            description="STACK$ 0DTE format (no expiry)",
            priority=31,
            pattern=r'(BTO|STC)\s+(\d+)\s+\$?([A-Za-z]+)\s+(\d+(?:\.\d+)?)([CPcp])\s*@\s*([0-9.]+)',
            parser=self._parse_stack_0dte,
            examples=["BTO 1 SPX 6925c @ 1.90"]
        )
        
        # STACK$ ticker-less: STC 1 6935c @ 1.50
        self.register(
            name="stack_tickerless",
            description="STACK$ ticker-less exit (infers SPX/NDX)",
            priority=32,
            pattern=r'(BTO|STC)\s+(\d+)\s+(\d{4,5})([CPcp])\s*@\s*([0-9.]+)',
            parser=self._parse_stack_tickerless,
            examples=["STC 1 6935c @ 1.50"]
        )
        
        # =====================================================================
        # FOXTRADES NATURAL LANGUAGE FORMAT (Stock signals)
        # =====================================================================
        
        # Foxtrades entry: Taking a position in $SYMBOL average $PRICE
        self.register(
            name="foxtrades_entry",
            description="Foxtrades natural language entry (stocks)",
            priority=35,
            pattern=r'[Tt]aking\s+a\s+(?:small\s+)?position\s+in\s+\$?([A-Za-z]+).*?average\s+\$?([0-9.]+)',
            parser=self._parse_foxtrades_entry,
            examples=["Taking a position in $NAMM average $2.38", "Taking a small position in LAZR average 0.49"]
        )
        
        # Foxtrades add: Adding more to SYMBOL + Average is now PRICE
        self.register(
            name="foxtrades_add",
            description="Foxtrades adding to position",
            priority=36,
            pattern=r'[Aa]dding\s+(?:more\s+)?(?:to\s+)?\$?([A-Za-z]+).*?[Aa]verage\s+(?:is\s+now\s+)?\$?([0-9.]+)',
            parser=self._parse_foxtrades_add,
            examples=["Adding more to IBRX. Average is now 6.65", "Adding to $GPUS average 0.32"],
            flags=re.IGNORECASE | re.DOTALL
        )
        
        # Foxtrades buy: Buying SYMBOL average PRICE
        self.register(
            name="foxtrades_buy",
            description="Foxtrades buying entry",
            priority=37,
            pattern=r'[Bb]uying\s+\$?([A-Za-z]+).*?average\s+\$?([0-9.]+)',
            parser=self._parse_foxtrades_entry,
            examples=["Buying SIDU average 2.30", "Buying $BEAT average 3.2"]
        )
        
        # Foxtrades back in: Back in on SYMBOL average PRICE
        self.register(
            name="foxtrades_backin",
            description="Foxtrades re-entry",
            priority=38,
            pattern=r'[Bb]ack\s+in\s+on\s+\$?([A-Za-z]+).*?average\s+\$?([0-9.]+)',
            parser=self._parse_foxtrades_entry,
            examples=["Back in on ROLR average 18.59"]
        )
        
        # Foxtrades exit: All out of $SYMBOL
        self.register(
            name="foxtrades_exit",
            description="Foxtrades full exit",
            priority=39,
            pattern=r'[Aa]ll\s+out\s+of\s+\$?([A-Za-z]+)',
            parser=self._parse_foxtrades_exit,
            examples=["All out of $ROLR now with profits", "All out of DBRG with 15.78% profit"]
        )
        
        # Foxtrades out: Out of $SYMBOL
        self.register(
            name="foxtrades_out",
            description="Foxtrades exit (out of)",
            priority=40,
            pattern=r'[Oo]ut\s+of\s+\$?([A-Za-z]+)',
            parser=self._parse_foxtrades_exit,
            examples=["Out of LAZR at a loss", "Out of $VMAR with small profit"]
        )
        
        # Foxtrades stopped out: Stopped out of SYMBOL
        self.register(
            name="foxtrades_stoppedout",
            description="Foxtrades stopped out exit",
            priority=41,
            pattern=r'[Ss]topped\s+out\s+of\s+\$?([A-Za-z]+)',
            parser=self._parse_foxtrades_exit,
            examples=["Stopped out of IRBT long with a loss"]
        )
        
        # Foxtrades trim: Taking profits on SYMBOL
        self.register(
            name="foxtrades_trim",
            description="Foxtrades taking profits (trim)",
            priority=42,
            pattern=r'[Tt]aking\s+(?:some\s+)?profits\s+on\s+\$?([A-Za-z]+)',
            parser=self._parse_foxtrades_trim,
            examples=["Taking some profits on SIDU", "Taking profits on IRBT"]
        )
        
        # Foxtrades securing: Securing profits on SYMBOL
        self.register(
            name="foxtrades_secure",
            description="Foxtrades securing profits",
            priority=43,
            pattern=r'[Ss]ecuring\s+(?:some\s+)?profits\s+on\s+\$?([A-Za-z]+)',
            parser=self._parse_foxtrades_trim,
            examples=["Securing some profits on BEAT"]
        )
        
        # BRONZE SWINGS NATURAL LANGUAGE FORMAT (Stock swing signals)
        # Priority 45-55 - after Foxtrades, before learned patterns
        
        # Entry patterns
        self.register(
            name="bronze_starter_position",
            description="Bronze Swings starter position entry",
            priority=45,
            pattern=r'(?:taken\s+a\s+)?starter\s+position\s+on\s+\$?([A-Z]{1,5})\s*(?:@?\s*\$?([\d.]+))?',
            parser=self._parse_bronze_entry,
            examples=["Taken a starter position on DUOL $177.69", "Starter position on SRFM"]
        )
        self.register(
            name="bronze_position_on",
            description="Bronze Swings position entry",
            priority=46,
            pattern=r'taken\s+a\s+(?:swing\s+)?position\s+on\s+\$?([A-Z]{1,5})\s*(?:@?\s*\$?([\d.]+))?',
            parser=self._parse_bronze_entry,
            examples=["Taken a position on VTEX @3.94", "Taken a swing position on OLO"]
        )
        self.register(
            name="bronze_entered",
            description="Bronze Swings entered position",
            priority=47,
            pattern=r'entered\s+\$?([A-Z]{1,5})\s*(?:@?\s*\$?([\d.]+))?\s*(?:average\s+price)?',
            parser=self._parse_bronze_entry,
            examples=["Entered LFST @$6.02 average price"]
        )
        self.register(
            name="bronze_long_swing",
            description="Bronze Swings long swing entry",
            priority=48,
            pattern=r'\$?([A-Z]{1,5})\s+(?:long\s+swing|for\s+a\s+long\s+swing)',
            parser=self._parse_bronze_entry,
            examples=["CYBN long swing probably to Q1 2026"]
        )
        
        # Add patterns
        self.register(
            name="bronze_added_to",
            description="Bronze Swings adding to position",
            priority=49,
            pattern=r'added\s+to\s+\$?([A-Z]{1,5})\s*(?:@?\s*\$?([\d.]+))?(?:\s*average\s+price)?',
            parser=self._parse_bronze_add,
            examples=["Added to SRFM average price $1.97", "Added to DUOL $177.46"]
        )
        self.register(
            name="bronze_symbol_added",
            description="Bronze Swings symbol added",
            priority=50,
            pattern=r'\$?([A-Z]{1,5})\s+added\s+(?:average\s+price\s*)?\$?([\d.]+)?',
            parser=self._parse_bronze_add,
            examples=["BGC added average price $9.28"]
        )
        
        # Exit patterns
        self.register(
            name="bronze_closed_position",
            description="Bronze Swings closed position",
            priority=51,
            pattern=r'closed\s+(?:his\s+)?position\s+(?:now\s+)?(?:on|in)\s+\$?([A-Z]{1,5})',
            parser=self._parse_bronze_exit,
            examples=["Closed position now on SRFM", "Closed position in CYBN"]
        )
        self.register(
            name="bronze_position_closed",
            description="Bronze Swings position closed",
            priority=52,
            pattern=r'\$?([A-Z]{1,5})\s+position\s+closed',
            parser=self._parse_bronze_exit,
            examples=["CYBN position closed", "VTEX position closed"]
        )
        self.register(
            name="bronze_closed_symbol",
            description="Bronze Swings closed symbol",
            priority=53,
            pattern=r'closed\s+\$?([A-Z]{1,5})\s*(?:position)?\s*(?:@?\s*\$?([\d.]+))?',
            parser=self._parse_bronze_exit,
            examples=["Closed LCID position at $2.32", "Closed SLDE $14.83"]
        )
        
        # Trim patterns
        self.register(
            name="bronze_taken_profits",
            description="Bronze Swings taking profits",
            priority=54,
            pattern=r'\$?([A-Z]{1,5})\s+taken\s+profits?\s*(?:@?\s*(\d+)%)?',
            parser=self._parse_bronze_trim,
            examples=["SRFM taken profits @55%", "SRFM taken profits"]
        )
        self.register(
            name="bronze_secured_profits",
            description="Bronze Swings secured profits",
            priority=55,
            pattern=r'secured\s+profits?\s*(?:on\s+)?\$?([A-Z]{1,5})',
            parser=self._parse_bronze_trim,
            examples=["secured profits on BITF", "Secured profits RXRX"]
        )
        
        # =====================================================================
        # PHOENIX NATURAL LANGUAGE FORMAT (Stock signals)
        # Priority 56-68 - after Bronze Swings, before learned patterns
        # =====================================================================
        
        # Phoenix entry: <@&role> SYMBOL over PRICE + SL PRICE
        self.register(
            name="phoenix_entry_over",
            description="Phoenix entry with 'over' price trigger and stop loss",
            priority=56,
            pattern=r'<@&\d+>\s+\$?([A-Z]{1,5})\s+(?:over|ocer|ober|ovre|ovwe|ovr)\s+\$?([\d.]+)\s*\n?\s*SL\s+\$?([\d.]+)',
            parser=self._parse_phoenix_entry,
            examples=["<@&role> PAVM over 21.50 SL 20", "<@&role> AMZE ocer 0.67 SL 0.62"],
            flags=re.IGNORECASE | re.DOTALL
        )
        
        # Phoenix entry: <@&role> SYMBOL over PRICE + SL X% (percentage stop loss)
        self.register(
            name="phoenix_entry_over_pct_sl",
            description="Phoenix entry with 'over' price trigger and percentage stop loss",
            priority=57,
            pattern=r'<@&\d+>\s+\$?([A-Z]{1,5})\s+(?:over|ocer|ober|ovre|ovwe|ovr)\s+\$?([\d.]+)\s*\n?\s*SL\s+(\d+)%',
            parser=self._parse_phoenix_entry_over_pct_sl,
            examples=["<@&role> PHEG over 7.50 SL 10%", "<@&role> MOVE ober 30 SL 10%"],
            flags=re.IGNORECASE | re.DOTALL
        )
        
        # Phoenix entry: <@&role> SYMBOL PRICE + SL X%
        self.register(
            name="phoenix_entry_price",
            description="Phoenix entry with direct price and percentage stop loss",
            priority=58,
            pattern=r'<@&\d+>\s+\$?([A-Z]{1,5})\s+\$?([\d.]+)\s*\n?\s*SL\s+(\d+)%',
            parser=self._parse_phoenix_entry_pct_sl,
            examples=["<@&role> GITS 2.50 SL 9%"],
            flags=re.IGNORECASE | re.DOTALL
        )
        
        # Phoenix entry: in SYMBOL at PRICE
        self.register(
            name="phoenix_entry_in_at",
            description="Phoenix entry - in SYMBOL at PRICE",
            priority=59,
            pattern=r'\bin\s+\$?([A-Z]{1,5})\s+at\s+\$?([\d.]+)',
            parser=self._parse_phoenix_entry_in_at,
            examples=["in XHLD at 2.13", "in GITS at 5.60"],
            flags=re.IGNORECASE
        )
        
        # Phoenix trim: selling X% here SYMBOL
        self.register(
            name="phoenix_trim_here",
            description="Phoenix partial exit - selling X% here",
            priority=60,
            pattern=r'selling\s+(\d+)%\s+here\s+\$?([A-Z]{1,5})',
            parser=self._parse_phoenix_trim,
            examples=["selling 80% here PAVM", "selling 80% here IBRX"]
        )
        
        # Phoenix trim: selling X% more SYMBOL
        self.register(
            name="phoenix_trim_more",
            description="Phoenix partial exit - selling X% more",
            priority=61,
            pattern=r'selling\s+(\d+)%\s+more\s+\$?([A-Z]{1,5})',
            parser=self._parse_phoenix_trim,
            examples=["selling 10% more GITS", "selling 10% more CRVS"]
        )
        
        # Phoenix trim: selling X% SYMBOL (simple format without here/more)
        self.register(
            name="phoenix_trim_simple",
            description="Phoenix partial exit - selling X% SYMBOL (simple format)",
            priority=62,
            pattern=r'selling\s+(\d+)%\s+\$?([A-Z]{1,5})(?:\s|$)',
            parser=self._parse_phoenix_trim,
            examples=["selling 80% XHLD", "selling 10% GITS"]
        )
        
        # Phoenix trim: leaving X% here SYMBOL
        self.register(
            name="phoenix_leaving",
            description="Phoenix partial exit - leaving X% (meaning selling rest)",
            priority=63,
            pattern=r'leaving\s+(\d+)%\s+(?:here\s+)?\$?([A-Z]{1,5})',
            parser=self._parse_phoenix_leaving,
            examples=["leaving 10% here GITS", "leaving 20% PAVM"]
        )
        
        # Phoenix trim: let the rest run (runner signal)
        self.register(
            name="phoenix_let_rest_run",
            description="Phoenix leave runner signal",
            priority=64,
            pattern=r'let\s+(?:the\s+)?rest\s+run',
            parser=self._parse_phoenix_let_rest_run,
            examples=["let the rest run", "let rest run"]
        )
        
        # Phoenix exit: hit SL
        self.register(
            name="phoenix_hit_sl",
            description="Phoenix stop loss hit (full exit)",
            priority=65,
            pattern=r'hit\s+SL',
            parser=self._parse_phoenix_hit_sl,
            examples=["hit SL"]
        )
        
        # Phoenix exit: out of SYMBOL (with optional reason)
        self.register(
            name="phoenix_out_of",
            description="Phoenix exit - out of SYMBOL",
            priority=66,
            pattern=r'out\s+of\s+\$?([A-Z]{1,5})',
            parser=self._parse_phoenix_exit,
            examples=["out of PHGE", "out of PHGE with a loss"]
        )
        
        # Phoenix exit: got a loss with SYMBOL
        self.register(
            name="phoenix_loss",
            description="Phoenix loss exit",
            priority=67,
            pattern=r'got\s+a\s+loss\s+with\s+\$?([A-Z]{1,5})',
            parser=self._parse_phoenix_exit,
            examples=["got a loss with ADTX"]
        )
        
        # Load learned patterns from database
        self._learned_pattern_metadata: Dict[str, Dict] = {}  # Store metadata by pattern name
        self._load_learned_patterns()
    
    def _load_learned_patterns(self) -> None:
        """Load learned patterns from database with full metadata."""
        try:
            old_learned = [name for name in self._formats if name.startswith('learned_')]
            for name in old_learned:
                self.unregister(name)
            self._learned_pattern_metadata.clear()

            from gui_app.database import get_active_learned_patterns
            patterns = get_active_learned_patterns()
            loaded = 0
            for p in patterns:
                if p.get('pattern') and p.get('name'):
                    pattern_name = f"learned_{p['name']}"
                    self._learned_pattern_metadata[pattern_name] = {
                        'action': p.get('action', 'BTO'),
                        'asset_type': p.get('asset_type', 'stock'),
                        'confidence': p.get('confidence', 0.85),
                        'approved_by': p.get('approved_by'),
                        'approved_at': p.get('approved_at'),
                        'admin_approved': p.get('approved_by') is not None
                    }
                    self.register(
                        name=pattern_name,
                        description=p.get('description', 'Learned pattern'),
                        priority=50 + p.get('id', 0),
                        pattern=p['pattern'],
                        parser=lambda m, t, pn=pattern_name: self._parse_learned_pattern_with_metadata(m, t, pn),
                        examples=[p.get('example_text', '')]
                    )
                    loaded += 1
            print(f"[FORMAT REGISTRY] ✓ Loaded {loaded} learned patterns (cleared {len(old_learned)} old)")
        except Exception as e:
            print(f"[FORMAT REGISTRY] Warning: Could not load learned patterns: {e}")
    
    # =========================================================================
    # PARSER IMPLEMENTATIONS
    # =========================================================================
    
    def _parse_jake_plusminus_simple(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Jake's +/- simple format: +5 IWM @ lim0.08"""
        sign, qty, symbol, price = match.groups()
        action = "BTO" if sign == "+" else "STC"
        return {
            "asset": "option",
            "action": action,
            "qty": int(qty),
            "qty_specified": True,
            "symbol": symbol.upper(),
            "strike": None,  # Not specified in this format
            "opt_type": None,
            "expiry": None,
            "price": float(price),
            "is_market_order": False,
            "_jake_simple": True,
            "_needs_position_match": True  # Will match to existing position
        }
    
    def _parse_jake_full_option(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Jake's full format: +1 $GRAB $7c 17APR2026 @ lim0.65"""
        sign, qty, symbol, strike, opt_type, day, month_name, year, price = match.groups()
        action = "BTO" if sign == "+" else "STC"
        month = self._month_name_to_num(month_name)
        expiry = f"{month}/{day}"
        return {
            "asset": "option",
            "action": action,
            "qty": int(qty),
            "qty_specified": True,
            "symbol": symbol.upper(),
            "strike": float(strike),
            "opt_type": opt_type.upper(),
            "expiry": expiry,
            "price": float(price),
            "is_market_order": False,
            "_jake_full": True
        }
    
    def _parse_jake_option_exp(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Jake's option format: $BBAI $8c 16JAN2026 @lim0.59"""
        sign, qty, symbol, strike, opt_type, day, month_name, year, price = match.groups()
        action = "BTO" if sign == "+" or sign is None else "STC"
        month = self._month_name_to_num(month_name)
        expiry = f"{month}/{day}"
        return {
            "asset": "option",
            "action": action,
            "qty": int(qty) if qty else 1,
            "qty_specified": bool(qty),
            "symbol": symbol.upper(),
            "strike": float(strike),
            "opt_type": opt_type.upper(),
            "expiry": expiry,
            "price": float(price),
            "is_market_order": False,
            "_jake_exp": True
        }
    
    def _parse_jake_order_executed(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Jake's order executed: Bought 1 Single MSTR 12/12/2025 185 CALL @1.68"""
        bought_sold, qty, symbol, month, day, year, strike, opt_type, price = match.groups()
        action = "BTO" if bought_sold.upper() == "BOUGHT" else "STC"
        expiry = f"{month}/{day}"
        return {
            "asset": "option",
            "action": action,
            "qty": int(qty),
            "qty_specified": True,
            "symbol": symbol.upper(),
            "strike": float(strike),
            "opt_type": "C" if opt_type.upper() == "CALL" else "P",
            "expiry": expiry,
            "price": float(price),
            "is_market_order": False,
            "_jake_order_executed": True
        }
    
    def _parse_jake_price_update(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Jake's price update (tracking only): $ZS +44% @lim2.40"""
        symbol, price = match.groups()
        return {
            "asset": "option",
            "action": "UPDATE",  # Not actionable
            "symbol": symbol.upper(),
            "price": float(price),
            "_jake_price_update": True,
            "_tracking_only": True
        }
    
    def _parse_slem_option(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Slem's format: $TSLA 445p 4.18 1/9 exp"""
        groups = match.groups()
        symbol, strike, opt_type, price, month, day = groups[:6]
        year = groups[6] if len(groups) > 6 and groups[6] else None
        expiry = f"{month}/{day}"
        return {
            "asset": "option",
            "action": "BTO",  # Slem's callouts are entries
            "qty": 1,  # Default qty
            "qty_specified": False,
            "symbol": symbol.upper(),
            "strike": float(strike),
            "opt_type": opt_type.upper(),
            "expiry": expiry,
            "price": float(price),
            "is_market_order": False,
            "_slem_format": True
        }
    
    def _parse_slem_gain_update(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Slem's gain update (tracking only): $MDB 270% gain"""
        symbol, gain_pct = match.groups()
        return {
            "asset": "option",
            "action": "UPDATE",
            "symbol": symbol.upper(),
            "gain_pct": int(gain_pct),
            "_slem_gain_update": True,
            "_tracking_only": True
        }
    
    def _parse_stack_option(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse STACK$ format: BTO 1 NVDA 185p 01/16 @ 4.50"""
        action, qty, symbol, strike, opt_type, month, day, price = match.groups()
        expiry = f"{month}/{day}"
        return {
            "asset": "option",
            "action": action.upper(),
            "qty": int(qty),
            "qty_specified": True,
            "symbol": symbol.upper(),
            "strike": float(strike),
            "opt_type": opt_type.upper(),
            "expiry": expiry,
            "price": float(price),
            "is_market_order": False,
            "_stack_format": True
        }
    
    def _parse_stack_0dte(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse STACK$ 0DTE: BTO 1 SPX 6925c @ 1.90"""
        action, qty, symbol, strike, opt_type, price = match.groups()
        expiry = datetime.now().strftime("%m/%d")
        return {
            "asset": "option",
            "action": action.upper(),
            "qty": int(qty),
            "qty_specified": True,
            "symbol": symbol.upper(),
            "strike": float(strike),
            "opt_type": opt_type.upper(),
            "expiry": expiry,
            "price": float(price),
            "is_market_order": False,
            "_stack_0dte": True
        }
    
    def _parse_stack_tickerless(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse STACK$ ticker-less: STC 1 6935c @ 1.50"""
        action, qty, strike, opt_type, price = match.groups()
        strike_val = float(strike)
        symbol = "NDX" if strike_val >= 10000 else "SPX"
        expiry = datetime.now().strftime("%m/%d")
        return {
            "asset": "option",
            "action": action.upper(),
            "qty": int(qty),
            "qty_specified": True,
            "symbol": symbol,
            "strike": strike_val,
            "opt_type": opt_type.upper(),
            "expiry": expiry,
            "price": float(price),
            "is_market_order": False,
            "_stack_tickerless": True
        }
    
    # =========================================================================
    # FOXTRADES PARSER IMPLEMENTATIONS
    # =========================================================================
    
    def _parse_foxtrades_entry(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Foxtrades entry: Taking a position in $NAMM average $2.38"""
        groups = match.groups()
        symbol = groups[0].upper() if groups else None
        price = float(groups[1]) if len(groups) > 1 and groups[1] else None
        
        if not symbol:
            return None
        
        return {
            "asset": "stock",
            "action": "BTO",
            "qty": 1,
            "qty_specified": False,
            "symbol": symbol,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "price": price,
            "is_market_order": price is None,
            "confidence": 1.0,
            "_foxtrades_entry": True
        }
    
    def _parse_foxtrades_add(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Foxtrades add: Adding more to IBRX. Average is now 6.65"""
        groups = match.groups()
        symbol = groups[0].upper() if groups else None
        price = float(groups[1]) if len(groups) > 1 and groups[1] else None
        
        if not symbol:
            return None
        
        return {
            "asset": "stock",
            "action": "BTO",
            "qty": 1,
            "qty_specified": False,
            "symbol": symbol,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "price": price,
            "is_market_order": price is None,
            "is_add": True,  # Flag for adding to existing position
            "confidence": 1.0,
            "_foxtrades_add": True
        }
    
    def _parse_foxtrades_exit(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Foxtrades exit: All out of $ROLR"""
        groups = match.groups()
        symbol = groups[0].upper() if groups else None
        
        if not symbol:
            return None
        
        return {
            "asset": "stock",
            "action": "STC",
            "qty": 1,
            "qty_specified": False,
            "symbol": symbol,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "price": None,
            "is_market_order": True,
            "is_full_exit": True,
            "confidence": 1.0,
            "_foxtrades_exit": True
        }
    
    def _parse_foxtrades_trim(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Foxtrades trim: Taking some profits on SIDU"""
        groups = match.groups()
        symbol = groups[0].upper() if groups else None
        
        if not symbol:
            return None
        
        return {
            "asset": "stock",
            "action": "STC",
            "qty": 1,
            "qty_specified": False,
            "symbol": symbol,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "price": None,
            "is_market_order": True,
            "is_trim": True,
            "is_full_exit": False,
            "confidence": 0.9,  # Slightly lower for trims
            "_foxtrades_trim": True
        }
    
    # =========================================================================
    # BRONZE SWINGS PARSER IMPLEMENTATIONS
    # =========================================================================
    
    def _parse_bronze_entry(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Bronze Swings entry signals (starter position, entered, long swing)."""
        groups = match.groups()
        symbol = None
        price = None
        
        for g in groups:
            if g:
                if g.isalpha() and len(g) <= 5:
                    symbol = g.upper()
                elif g.replace('.', '').replace('$', '').isdigit():
                    try:
                        price = float(g.replace('$', ''))
                    except ValueError:
                        pass
        
        if not symbol:
            return None
        
        return {
            "asset": "stock",
            "action": "BTO",
            "qty": 1,
            "qty_specified": False,
            "symbol": symbol,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "price": price,
            "is_market_order": price is None,
            "confidence": 0.95,
            "_bronze_swings_entry": True
        }
    
    def _parse_bronze_add(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Bronze Swings add-to-position signals."""
        groups = match.groups()
        symbol = None
        price = None
        
        for g in groups:
            if g:
                if g.isalpha() and len(g) <= 5:
                    symbol = g.upper()
                elif g.replace('.', '').replace('$', '').isdigit():
                    try:
                        price = float(g.replace('$', ''))
                    except ValueError:
                        pass
        
        if not symbol:
            return None
        
        return {
            "asset": "stock",
            "action": "BTO",
            "qty": 1,
            "qty_specified": False,
            "symbol": symbol,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "price": price,
            "is_market_order": price is None,
            "is_add": True,
            "confidence": 0.95,
            "_bronze_swings_add": True
        }
    
    def _parse_bronze_exit(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Bronze Swings exit signals (closed position)."""
        groups = match.groups()
        symbol = None
        price = None
        
        for g in groups:
            if g:
                if g.isalpha() and len(g) <= 5:
                    symbol = g.upper()
                elif g.replace('.', '').replace('$', '').isdigit():
                    try:
                        price = float(g.replace('$', ''))
                    except ValueError:
                        pass
        
        if not symbol:
            return None
        
        return {
            "asset": "stock",
            "action": "STC",
            "qty": 1,
            "qty_specified": False,
            "symbol": symbol,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "price": price,
            "is_market_order": True,
            "is_full_exit": True,
            "confidence": 0.95,
            "_bronze_swings_exit": True
        }
    
    def _parse_bronze_trim(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Bronze Swings trim/profit-taking signals."""
        groups = match.groups()
        symbol = None
        percentage = None
        
        for g in groups:
            if g:
                if g.isalpha() and len(g) <= 5:
                    symbol = g.upper()
                elif g.isdigit():
                    try:
                        percentage = float(g)
                    except ValueError:
                        pass
        
        if not symbol:
            return None
        
        return {
            "asset": "stock",
            "action": "STC",
            "qty": 1,
            "qty_specified": False,
            "symbol": symbol,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "price": None,
            "is_market_order": True,
            "is_trim": True,
            "is_full_exit": False,
            "trim_percentage": percentage,
            "confidence": 0.9,
            "_bronze_swings_trim": True
        }
    
    # =========================================================================
    # PHOENIX PARSER IMPLEMENTATIONS
    # =========================================================================
    
    def _parse_phoenix_entry(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix entry: <@&role> PAVM over 21.50 SL 20"""
        groups = match.groups()
        symbol = groups[0].upper() if groups else None
        price = float(groups[1]) if len(groups) > 1 and groups[1] else None
        stop_loss = float(groups[2]) if len(groups) > 2 and groups[2] else None
        
        if not symbol:
            return None
        
        return {
            "asset": "stock",
            "action": "BTO",
            "qty": 1,
            "qty_specified": False,
            "symbol": symbol,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "price": price,
            "stop_loss": stop_loss,
            "is_market_order": price is None,
            "confidence": 1.0,
            "_phoenix_entry": True
        }
    
    def _parse_phoenix_entry_pct_sl(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix entry with percentage SL: <@&role> GITS 2.50 SL 9%"""
        groups = match.groups()
        symbol = groups[0].upper() if groups else None
        price = float(groups[1]) if len(groups) > 1 and groups[1] else None
        stop_loss_pct = float(groups[2]) if len(groups) > 2 and groups[2] else None
        
        if not symbol:
            return None
        
        # Calculate SL price from percentage
        stop_loss = None
        if price and stop_loss_pct:
            stop_loss = price * (1 - stop_loss_pct / 100)
        
        return {
            "asset": "stock",
            "action": "BTO",
            "qty": 1,
            "qty_specified": False,
            "symbol": symbol,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "price": price,
            "stop_loss": stop_loss,
            "stop_loss_pct": stop_loss_pct,
            "is_market_order": price is None,
            "confidence": 1.0,
            "_phoenix_entry": True
        }
    
    def _parse_phoenix_entry_over_pct_sl(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix entry: <@&role> PHEG over 7.50 SL 10%"""
        groups = match.groups()
        symbol = groups[0].upper() if groups else None
        price = float(groups[1]) if len(groups) > 1 and groups[1] else None
        stop_loss_pct = float(groups[2]) if len(groups) > 2 and groups[2] else None
        
        if not symbol:
            return None
        
        # Calculate SL price from percentage
        stop_loss = None
        if price and stop_loss_pct:
            stop_loss = price * (1 - stop_loss_pct / 100)
        
        return {
            "asset": "stock",
            "action": "BTO",
            "qty": 1,
            "qty_specified": False,
            "symbol": symbol,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "price": price,
            "stop_loss": stop_loss,
            "stop_loss_pct": stop_loss_pct,
            "is_market_order": False,
            "trigger_price": price,
            "confidence": 1.0,
            "_phoenix_entry": True
        }
    
    def _parse_phoenix_entry_in_at(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix entry: in XHLD at 2.13"""
        groups = match.groups()
        symbol = groups[0].upper() if groups else None
        price = float(groups[1]) if len(groups) > 1 and groups[1] else None
        
        if not symbol:
            return None
        
        return {
            "asset": "stock",
            "action": "BTO",
            "qty": 1,
            "qty_specified": False,
            "symbol": symbol,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "price": price,
            "is_market_order": True,
            "confidence": 1.0,
            "_phoenix_entry": True
        }
    
    def _parse_phoenix_let_rest_run(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix runner signal: let the rest run"""
        return {
            "asset": "stock",
            "action": "RUNNER",
            "qty": 1,
            "qty_specified": False,
            "symbol": None,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "price": None,
            "is_market_order": False,
            "is_runner_signal": True,
            "confidence": 0.8,
            "_phoenix_runner": True,
            "_needs_position_context": True
        }
    
    def _parse_phoenix_trim(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix trim: selling 80% here PAVM"""
        groups = match.groups()
        percentage = float(groups[0]) if groups else None
        symbol = groups[1].upper() if len(groups) > 1 and groups[1] else None
        
        if not symbol:
            return None
        
        return {
            "asset": "stock",
            "action": "STC",
            "qty": 1,
            "qty_specified": False,
            "symbol": symbol,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "price": None,
            "is_market_order": True,
            "is_trim": True,
            "is_full_exit": False,
            "trim_percentage": percentage,
            "confidence": 1.0,
            "_phoenix_trim": True
        }
    
    def _parse_phoenix_leaving(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix leaving: leaving 10% here GITS (means selling 90%)"""
        groups = match.groups()
        leaving_pct = float(groups[0]) if groups else None
        symbol = groups[1].upper() if len(groups) > 1 and groups[1] else None
        
        if not symbol:
            return None
        
        # "Leaving 10%" means selling 90%
        sell_pct = 100 - leaving_pct if leaving_pct else None
        
        return {
            "asset": "stock",
            "action": "STC",
            "qty": 1,
            "qty_specified": False,
            "symbol": symbol,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "price": None,
            "is_market_order": True,
            "is_trim": True,
            "is_full_exit": False,
            "trim_percentage": sell_pct,
            "leaving_percentage": leaving_pct,
            "confidence": 1.0,
            "_phoenix_trim": True
        }
    
    def _parse_phoenix_hit_sl(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix stop loss hit: hit SL (requires context for symbol)"""
        # This needs position context to determine symbol
        # Return a special flag so pipeline can check open positions
        return {
            "asset": "stock",
            "action": "STC",
            "qty": 1,
            "qty_specified": False,
            "symbol": None,  # Needs context from open positions
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "price": None,
            "is_market_order": True,
            "is_full_exit": True,
            "stop_loss_hit": True,
            "confidence": 0.7,  # Lower confidence since no symbol
            "_phoenix_exit": True,
            "_needs_position_context": True
        }
    
    def _parse_phoenix_exit(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix exit: got a loss with ADTX"""
        groups = match.groups()
        symbol = groups[0].upper() if groups else None
        
        if not symbol:
            return None
        
        return {
            "asset": "stock",
            "action": "STC",
            "qty": 1,
            "qty_specified": False,
            "symbol": symbol,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "price": None,
            "is_market_order": True,
            "is_full_exit": True,
            "confidence": 1.0,
            "_phoenix_exit": True
        }
    
    def _parse_learned_pattern_with_metadata(self, match: re.Match, text: str, pattern_name: str) -> Optional[Dict]:
        """Parse signals using learned patterns with database metadata."""
        import re as _re
        groups = match.groups()
        symbol = None
        price = None
        strike = None
        opt_type = None
        expiry = None
        
        metadata = self._learned_pattern_metadata.get(pattern_name, {})
        action = metadata.get('action', 'BTO')
        asset_type = metadata.get('asset_type', 'stock')
        confidence = metadata.get('confidence', 0.85)
        admin_approved = metadata.get('admin_approved', False)
        
        for g in groups:
            if not g:
                continue
            g_stripped = g.strip()
            
            if g_stripped.isalpha() and len(g_stripped) <= 6:
                if not symbol:
                    symbol = g_stripped.upper()
            elif _re.match(r'^(\d+(?:\.\d+)?)\s*([CcPp])$', g_stripped):
                m = _re.match(r'^(\d+(?:\.\d+)?)\s*([CcPp])$', g_stripped)
                strike = float(m.group(1))
                opt_type = m.group(2).upper()
                asset_type = 'option'
            elif _re.match(r'^(\d+(?:\.\d+)?)\s+([CcPp])$', g_stripped):
                m = _re.match(r'^(\d+(?:\.\d+)?)\s+([CcPp])$', g_stripped)
                strike = float(m.group(1))
                opt_type = m.group(2).upper()
                asset_type = 'option'
            elif g_stripped.replace('.', '').isdigit():
                try:
                    val = float(g_stripped)
                    if price is None:
                        price = val
                except ValueError:
                    pass
            elif _re.match(r'^\d+(?:\.\d+)?%$', g_stripped):
                pass
            elif _re.match(r'^\d{1,2}/\d{1,2}(?:/\d{2,4})?$', g_stripped):
                expiry = g_stripped
        
        if not symbol:
            return None
        
        return {
            "asset": asset_type,
            "action": action,
            "qty": 1,
            "qty_specified": False,
            "symbol": symbol,
            "strike": strike,
            "opt_type": opt_type,
            "expiry": expiry,
            "price": price,
            "is_market_order": price is None,
            "confidence": confidence,
            "_learned_pattern": True,
            "_admin_approved": admin_approved,
            "_requires_approval": True,
            "_execution_allowed": admin_approved
        }
    
    def _parse_learned_pattern(self, match: re.Match, text: str) -> Optional[Dict]:
        """Legacy parser for learned patterns (fallback)."""
        return self._parse_learned_pattern_with_metadata(match, text, 'unknown')
    
    def _month_name_to_num(self, month_name: str) -> str:
        """Convert month name to number."""
        months = {
            'JAN': '01', 'FEB': '02', 'MAR': '03', 'APR': '04',
            'MAY': '05', 'JUN': '06', 'JUL': '07', 'AUG': '08',
            'SEP': '09', 'OCT': '10', 'NOV': '11', 'DEC': '12'
        }
        return months.get(month_name.upper(), '01')


# Global singleton instance
_registry_instance: Optional[SignalFormatRegistry] = None


def get_signal_format_registry() -> SignalFormatRegistry:
    """Get the global signal format registry instance."""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = SignalFormatRegistry()
    return _registry_instance


def parse_with_registry(text: str) -> Optional[Dict[str, Any]]:
    """
    Convenience function to parse text using the global registry.
    
    Args:
        text: Signal text to parse
        
    Returns:
        Parsed signal dict or None
    """
    return get_signal_format_registry().parse(text)
