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
        text = re.sub(r'^@\w+\s+', '', text)
        return text.strip()
    
    _ROLE_AWARE_FORMATS = frozenset({
        'temple_zz_structured_entry', 'temple_zz_structured_entry_no_targets',
        'temple_zz_single_line_entry', 'temple_zz_inline_role_entry',
        'temple_zz_swing_update',
    })

    def parse(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Parse text using registered formats in priority order.

        Returns:
            Parsed signal dict with '_format_name' indicating which format matched,
            or None if no format matched.
        """
        raw_text = text.strip()
        clean_text = self._strip_discord_mentions(raw_text)

        for fmt in self._sorted_formats:
            if not fmt.enabled:
                continue

            match_text = raw_text if fmt.name in self._ROLE_AWARE_FORMATS else clean_text
            match = fmt.pattern.search(match_text)
            if match:
                try:
                    result = fmt.parser(match, match_text)
                    if result:
                        result['_format_name'] = fmt.name
                        print(f"[FORMAT REGISTRY] ✓ Matched '{fmt.name}': {result.get('action')} {result.get('symbol')} {result.get('strike')}{result.get('opt_type', '')}")
                        return result
                except Exception as e:
                    print(f"[FORMAT REGISTRY] Error in {fmt.name} parser: {e}")
                    continue

        return None

    def parse_all(self, text: str) -> List[Dict[str, Any]]:
        """Parse text for ALL signals (multi-plan messages like $GOVX...\\n\\n$CISS...).

        Splits on blank-line-then-$TICKER boundaries and parses each segment.
        Returns list of parsed signal dicts (may be empty).
        """
        segments = re.split(r'\n\n+(?=\$[A-Z])', text.strip())
        if len(segments) <= 1:
            result = self.parse(text)
            return [result] if result else []

        results = []
        for seg in segments:
            result = self.parse(seg.strip())
            if result:
                results.append(result)
        return results

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
            pattern=r'entered\s+\$?(?!LONG|SHORT|long|short)([A-Z]{1,5})\s*(?:@?\s*\$?([\d.]+))?\s*(?:average\s+price)?',
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
        
        # Phoenix entry: SYMBOL over PRICE + SL X% (percentage stop loss) — MUST be checked before price SL
        self.register(
            name="phoenix_entry_over_pct_sl",
            description="Phoenix entry with 'over' price trigger and percentage stop loss",
            priority=55,
            pattern=r'^\s*\$?([A-Z]{1,5})\s+(?:over|ocer|ocver|ober|ovre|ovwe|ovr|iver)\s+\$?([\d.]+)\s*\n?\s*SL\s+(\d+)%',
            parser=self._parse_phoenix_over_pct_sl_conditional,
            examples=["PHEG over 7.50 SL 10%", "MOVE ober 30 SL 10%", "ARTV iver 4.60 SL 8%", "CURV ocver 1.80 SL 10%"],
            flags=re.IGNORECASE | re.DOTALL
        )
        
        # Phoenix entry: SYMBOL over PRICE + SL PRICE (role ping stripped by parse())
        self.register(
            name="phoenix_entry_over",
            description="Phoenix entry with 'over' price trigger and stop loss",
            priority=56,
            pattern=r'^\s*\$?([A-Z]{1,5})\s+(?:over|ocer|ocver|ober|ovre|ovwe|ovr|iver)\s+\$?([\d.]+)\s*\n?\s*SL\s+\$?([\d.]+)(?!\s*%)',
            parser=self._parse_phoenix_over_conditional,
            examples=["PAVM over 21.50 SL 20", "AMZE ocer 0.67 SL 0.62"],
            flags=re.IGNORECASE | re.DOTALL
        )
        
        # Phoenix entry: SYMBOL over PRICE (no SL specified)
        self.register(
            name="phoenix_entry_over_no_sl",
            description="Phoenix entry with 'over' price trigger, no stop loss",
            priority=58,
            pattern=r'^\s*\$?([A-Z]{1,5})\s+(?:over|ocer|ocver|ober|ovre|ovwe|ovr|iver)\s+\$?([\d.]+)',
            parser=self._parse_phoenix_over_no_sl_conditional,
            examples=["ENVB over 12.80", "ENVB over 13"],
            flags=re.IGNORECASE | re.DOTALL
        )
        
        # Phoenix entry: taking position SYMBOL PRICE + SL X%
        self.register(
            name="phoenix_entry_taking",
            description="Phoenix entry - taking position SYMBOL PRICE",
            priority=58,
            pattern=r'taking\s+(?:small\s+)?position[g]?\s+\$?([A-Z]{1,5})\s+(?:here\s+(?:avg\s+)?)?\$?([\d.]+)\s*\n?\s*SL\s+(\d+)%',
            parser=self._parse_phoenix_entry_over_pct_sl,
            examples=["taking small position BBGI 7.85 SL 10%", "taking small positiong BTTC here avg 9.26 SL 10%"],
            flags=re.IGNORECASE | re.DOTALL
        )
        
        # Phoenix entry: taking position SYMBOL PRICE (no SL)
        self.register(
            name="phoenix_entry_taking_no_sl",
            description="Phoenix entry - taking position SYMBOL PRICE (no SL)",
            priority=58,
            pattern=r'taking\s+(?:small\s+)?position[g]?\s+\$?([A-Z]{1,5})\s+(?:here\s+(?:avg\s+)?)?\$?([\d.]+)',
            parser=self._parse_phoenix_entry_no_sl,
            examples=["taking small position BBGI 7.85"],
            flags=re.IGNORECASE | re.DOTALL
        )
        
        # Phoenix entry: SYMBOL PRICE + SL X% (role ping stripped by parse())
        self.register(
            name="phoenix_entry_price",
            description="Phoenix entry with direct price and percentage stop loss",
            priority=59,
            pattern=r'^\s*\$?([A-Z]{1,5})\s+\$?([\d.]+)\s*\n?\s*SL\s+(\d+)%',
            parser=self._parse_phoenix_entry_pct_sl,
            examples=["GITS 2.50 SL 9%"],
            flags=re.IGNORECASE | re.DOTALL
        )
        
        # Phoenix entry: SYMBOL PRICE + SL PRICE (price-based SL, no "over")
        self.register(
            name="phoenix_entry_price_sl",
            description="Phoenix entry with direct price and price stop loss",
            priority=60,
            pattern=r'^\s*\$?([A-Z]{1,5})\s+\$?([\d.]+)\s*\n?\s*SL\s+\$?([\d.]+)(?!%)',
            parser=self._parse_phoenix_entry,
            examples=["PETS 2.60 SL 2.40"],
            flags=re.IGNORECASE | re.DOTALL
        )
        
        # Phoenix entry: in SYMBOL PRICE + SL X% (e.g., "in MNTS 1.08 SL 10%")
        self.register(
            name="phoenix_entry_in_sl",
            description="Phoenix entry - in SYMBOL PRICE SL",
            priority=61,
            pattern=r'^\s*(?:in\s+(?:on\s+)?)\$?([A-Z]{1,5})\s+(?:avg\s+)?\$?([\d.]+)\s*\n?\s*SL\s+(\d+)%',
            parser=self._parse_phoenix_entry_over_pct_sl,
            examples=["in MNTS 1.08 SL 10%", "in AMCI avg 7.35 SL 9%"],
            flags=re.IGNORECASE | re.DOTALL
        )
        
        # Phoenix entry: in SYMBOL at/avg PRICE
        self.register(
            name="phoenix_entry_in_at",
            description="Phoenix entry - in SYMBOL at PRICE",
            priority=62,
            pattern=r'\bin\s+\$?([A-Z]{1,5})\s+(?:at\s+|avg\s+)?\$?([\d.]+)',
            parser=self._parse_phoenix_entry_in_at,
            examples=["in XHLD at 2.13", "in GITS at 5.60", "in MNTS 1.08", "in AMCI avg 7.35"],
            flags=re.IGNORECASE
        )
        
        # Phoenix trim: selling/sold X% here SYMBOL
        self.register(
            name="phoenix_trim_here",
            description="Phoenix partial exit - selling X% here SYMBOL",
            priority=63,
            pattern=r'(?:selling|sold)\s+(\d+)%\s+here\s+(?:(?:at|for|in)\s+[\d.]+\s+)?\$?((?!HERE\b|MORE\b|NOW\b|ON\b|THE\b|MY\b|OF\b|ALL\b|REST\b|AT\b|FIRST\b|IN\b|TO\b|FOR\b|WITH\b|PROFIT\b|SOME\b)[A-Z]{1,5})(?![a-z])',
            parser=self._parse_phoenix_trim,
            examples=["selling 80% here PAVM", "selling 80% here IBRX", "sold 80% here PAVM"],
            flags=re.IGNORECASE
        )
        
        # Phoenix trim: selling/sold X% here (no symbol — needs position context)
        self.register(
            name="phoenix_trim_here_no_sym",
            description="Phoenix partial exit - selling X% here (no symbol)",
            priority=63,
            pattern=r'(?:selling|sold)\s+(\d+)%\s+here(?:\s|$|[.,!])',
            parser=self._parse_phoenix_trim_no_sym,
            examples=["selling 80% here", "Selling 80% here", "sold 50% here"],
            flags=re.IGNORECASE
        )
        
        # Phoenix trim: selling/sold X% more SYMBOL (skip "here"/"for" before symbol)
        self.register(
            name="phoenix_trim_more",
            description="Phoenix partial exit - selling X% more",
            priority=64,
            pattern=r'(?:selling|sold)\s+(\d+)%\s+more\s+(?:(?:here|for)\s+)?\$?((?!HERE\b|MORE\b|NOW\b|ON\b|THE\b|MY\b|OF\b|ALL\b|REST\b|AT\b|FIRST\b|IN\b|TO\b|FOR\b|WITH\b|PROFIT\b|SOME\b|EARLY\b|LATE\b|IF\b|AND\b|BUT\b|THEN\b|ALSO\b|JUST\b|WHEN\b|THIS\b|THAT\b|THEM\b|BEEN\b|WILL\b|FROM\b)[A-Z]{1,5})(?![a-z])',
            parser=self._parse_phoenix_trim,
            examples=["selling 10% more GITS", "selling 10% more CRVS", "selling 10% more here ARTV", "selling 10% more for CHOW"],
            flags=re.IGNORECASE
        )
        
        # Phoenix trim: selling/sold half/quarter/third SYMBOL
        self.register(
            name="phoenix_trim_fraction",
            description="Phoenix partial exit - selling half/quarter/third",
            priority=64,
            pattern=r'(?:selling|sold)\s+(half|quarter|third)\s+(?:(?:of\s+)?(?:my\s+)?(?:position\s+)?(?:in\s+)?(?:here\s+)?)?(?:\$?([A-Z]{1,5})(?![a-z]))',
            parser=self._parse_phoenix_trim_fraction,
            examples=["selling half here GITS", "selling half PAVM", "sold half ENVB"],
            flags=re.IGNORECASE
        )
        
        # Phoenix trim: selling/sold X% SYMBOL (simple — SYMBOL must not be reserved word)
        self.register(
            name="phoenix_trim_simple",
            description="Phoenix partial exit - selling X% SYMBOL (simple format)",
            priority=65,
            pattern=r'(?:selling|sold)\s+(\d+)%\s+\$?((?!HERE\b|MORE\b|NOW\b|ON\b|THE\b|MY\b|OF\b|ALL\b|REST\b|AT\b|FIRST\b|IN\b|TO\b|FOR\b|WITH\b|PROFIT\b|SOME\b|EARLY\b|LATE\b|IF\b|AND\b|BUT\b|THEN\b|ALSO\b|JUST\b|WHEN\b|THIS\b|THAT\b|THEM\b|BEEN\b|WILL\b|FROM\b|WOW\b|AS\b|LET\b|SO\b|YET\b|TOO\b|NOT\b|ITS\b)[A-Z]{1,5})(?:\s|$)',
            parser=self._parse_phoenix_trim,
            examples=["selling 80% XHLD", "selling 10% GITS", "sold 50% ENVB"],
            flags=re.IGNORECASE
        )
        
        # Phoenix trim: selling/sold X% (no symbol — needs position context)
        self.register(
            name="phoenix_trim_pct_no_sym",
            description="Phoenix partial exit - selling X% (no symbol)",
            priority=65,
            pattern=r'(?:selling|sold)\s+(\d+)%(?:\s|$|[.,!])',
            parser=self._parse_phoenix_trim_no_sym,
            examples=["selling 80%", "sold 50%"],
            flags=re.IGNORECASE
        )
        
        # Phoenix trim: trimming SYMBOL (natural language, implies partial exit)
        self.register(
            name="phoenix_trimming",
            description="Phoenix partial exit - trimming SYMBOL",
            priority=65,
            pattern=r'trimm?(?:ing|ed)\s+\$?((?!HERE\b|MORE\b|NOW\b|ON\b|THE\b|MY\b|OF\b)[A-Z]{1,5})(?![a-z])',
            parser=self._parse_phoenix_trimming,
            examples=["trimming GITS", "trimmed PAVM"],
            flags=re.IGNORECASE
        )
        
        # Phoenix trim: leaving X% SYMBOL (must not capture reserved words)
        self.register(
            name="phoenix_leaving",
            description="Phoenix partial exit - leaving X% (meaning selling rest)",
            priority=66,
            pattern=r'leaving\s+(\d+)%\s+(?:here\s+)?(?:of\s+)?(?:my\s+)?(?:position\s+)?(?:in\s+)?\$?((?!HERE\b|NOW\b|ON\b|MORE\b|THE\b|MY\b)[A-Z]{1,5})(?![a-z])',
            parser=self._parse_phoenix_leaving,
            examples=["leaving 10% here GITS", "leaving 20% PAVM"],
            flags=re.IGNORECASE
        )
        
        # Phoenix trim: leaving X% (no symbol — needs position context)
        self.register(
            name="phoenix_leaving_no_sym",
            description="Phoenix partial exit - leaving X% (no symbol)",
            priority=66,
            pattern=r'leaving\s+(\d+)%\s*(?:here|now)?(?:\s|$)',
            parser=self._parse_phoenix_leaving_no_sym,
            examples=["leaving 5% now", "leaving 5% here", "leaving 10%"],
            flags=re.IGNORECASE
        )
        
        # Phoenix trim: let the rest run (runner signal)
        self.register(
            name="phoenix_let_rest_run",
            description="Phoenix leave runner signal",
            priority=67,
            pattern=r'let\s+(?:the\s+)?rest\s+run',
            parser=self._parse_phoenix_let_rest_run,
            examples=["let the rest run", "let rest run"],
            flags=re.IGNORECASE
        )
        
        # Phoenix exit: SL hit with SYMBOL / SYMBOL SL hit (exclude "No SL hit" and "SL hit but")
        self.register(
            name="phoenix_sl_hit_with",
            description="Phoenix stop loss hit with symbol",
            priority=68,
            pattern=r'(?:(?:hit\s+(?:my\s+)?SL\s+with|(?<!No\s)SL\s+hit\s+(?:with)?)\s+\$?([A-Z]{1,5})|([A-Z]{1,5})\s+(?<!No\s)SL\s+hit(?!\s+but))',
            parser=self._parse_phoenix_sl_hit_with,
            examples=["hit SL with MIGI", "SL hit with NIVF", "ENVB SL hit"],
            flags=re.IGNORECASE
        )
        
        # Phoenix exit: hit SL (no symbol — needs position context)
        self.register(
            name="phoenix_hit_sl",
            description="Phoenix stop loss hit (full exit)",
            priority=69,
            pattern=r'hit\s+(?:my\s+)?SL(?!\s+with)',
            parser=self._parse_phoenix_hit_sl,
            examples=["hit SL", "hit my SL"],
            flags=re.IGNORECASE
        )
        
        # Phoenix exit: out of SYMBOL (with optional reason)
        self.register(
            name="phoenix_out_of",
            description="Phoenix exit - out of SYMBOL",
            priority=70,
            pattern=r'\bout\s+(?:of\s+)?\$?((?!WITH|ON\b)[A-Z]{1,5})(?![a-z])',
            parser=self._parse_phoenix_exit,
            examples=["out of PHGE", "out of PHGE with a loss", "out PAVM"],
            flags=re.IGNORECASE
        )
        
        # Phoenix exit: stopped out SYMBOL
        self.register(
            name="phoenix_stopped_out",
            description="Phoenix stopped out exit",
            priority=70,
            pattern=r'stopped?\s+out\s+(?:of\s+)?\$?([A-Z]{1,5})(?![a-z])',
            parser=self._parse_phoenix_exit,
            examples=["stopped out MIGI", "stopped out of ENVB"],
            flags=re.IGNORECASE
        )
        
        # Phoenix exit: stop out with SYMBOL (e.g. "stop out with POLa")
        self.register(
            name="phoenix_stop_out_with",
            description="Phoenix stop out with SYMBOL",
            priority=69,
            pattern=r'stop(?:ped)?\s+out\s+(?:with|on)\s+\$?([A-Z]{1,5})(?![a-z])',
            parser=self._parse_phoenix_exit,
            examples=["stop out with POLA", "stopped out with ENVB", "stop out on MIGI"],
            flags=re.IGNORECASE
        )
        
        
        # Phoenix exit: got a loss with SYMBOL
        self.register(
            name="phoenix_loss",
            description="Phoenix loss exit",
            priority=71,
            pattern=r'got\s+a\s+loss\s+with\s+\$?([A-Z]{1,5})',
            parser=self._parse_phoenix_exit,
            examples=["got a loss with ADTX"],
            flags=re.IGNORECASE
        )
        
        # Phoenix SL update: moving (my) SL to (my) entry for (the remaining) SYMBOL
        self.register(
            name="phoenix_sl_to_entry",
            description="Phoenix SL update - moving SL to entry (breakeven)",
            priority=55,
            pattern=r'mov(?:ing|e)\s+(?:my\s+)?SL\s+to\s+(?:my\s+)?entry\s*,?\s*(?:fro?m?\s+)?(?:for\s+)?(?:(?:the\s+)?(?:re?ma(?:in)?(?:ing|aning|ining|ning)\s+)?(?:shares?\s+)?)?(?:\$?((?!IF|IT|THIS|THE|AND|BUT|FOR)[A-Z]{2,5})(?![a-z]))?',
            parser=self._parse_phoenix_sl_to_entry,
            examples=["moving my SL to my entry for AIFF", "moving SL to my entry for the remaining ACXP",
                       "moving my SL to my entry for the remaning shares AEHL", "moving SL to my entry fro remaning shares KNRX",
                       "moving my SL to my entry for the remaining"],
            flags=re.IGNORECASE
        )

        # Phoenix SL update: moving SL for SYMBOL (to/at) PRICE
        self.register(
            name="phoenix_sl_move_price_for",
            description="Phoenix SL update - moving SL for SYMBOL to PRICE",
            priority=55,
            pattern=r'moving\s+(?:my\s+)?SL\s+(?:for\s+)\$?([A-Z]{1,5})\s+(?:to\s+|at\s+)?\$?([\d.]+)',
            parser=self._parse_phoenix_sl_move_price,
            examples=["moving SL for TPET 2.13", "moving SL for CDIo to 6.90", "moving SL for IONQ at 39.20",
                       "moving SL for PYPG  5.60", "moving my SL for CHOW at 0.86"],
            flags=re.IGNORECASE
        )

        # Phoenix SL update: moving SL to X% (must check BEFORE price parser)
        self.register(
            name="phoenix_sl_move_pct",
            description="Phoenix SL update - moving SL to percentage",
            priority=54,
            pattern=r'mov(?:ing|e)\s+(?:my\s+)?SL\s+to\s+(\d+)%',
            parser=self._parse_phoenix_sl_move_pct,
            examples=["moving SL to 8%", "move SL to 9%"],
            flags=re.IGNORECASE
        )

        # Phoenix SL update: moving SL to PRICE (for SYMBOL) — excludes percent
        self.register(
            name="phoenix_sl_move_price_to",
            description="Phoenix SL update - moving SL to specific price",
            priority=55,
            pattern=r'mov(?:ing|e)\s+(?:my\s+)?SL\s+to\s+\$?([\d.]+)(?!\s*%)',
            parser=self._parse_phoenix_sl_move_price_to,
            examples=["moving SL to 0.41", "moving SL to 0.73", "moving SL to 4.98 for CATX",
                       "moving my SL to 1.04 for now with LGVN",
                       "moving my SL to 1.88 just below VWAP"],
            flags=re.IGNORECASE
        )

        # Phoenix target update: first/second/next target (for SYMBOL) PRICE(-PRICE)
        self.register(
            name="phoenix_target_update_sym",
            description="Phoenix target update with symbol",
            priority=56,
            pattern=r'(?:first|second|third|next)\s+targ(?:et|ets|ert|er)s?\s+(?:for\s+)?\$?((?!AT|FOR|MY|THE|IS|IT|OF)[A-Z]{2,5})\s+\$?([\d.]+)(?:\s*[-–—]\s*\$?([\d.]+))?',
            parser=self._parse_phoenix_target_update,
            examples=["first target for QCLS 4.25-4.35", "targets for NXPL 0.76-0.80",
                       "second target LGVN 0.72-0.75", "first target KLTO 0.77"],
            flags=re.IGNORECASE
        )

        # Phoenix target update: first/second/next target PRICE(-PRICE) (for SYMBOL)
        self.register(
            name="phoenix_target_update_price",
            description="Phoenix target update price first",
            priority=56,
            pattern=r'(?:first|second|third|next)\s+targ(?:et|ets|ert|er)s?\s+\$?([\d.]+)(?:\s*[-–—]\s*\$?([\d.]+))?\s*(?:for\s+\$?([A-Z]{2,5}))?',
            parser=self._parse_phoenix_target_update_price_first,
            examples=["first target 5.85-6", "second target 0.68-0.72", "first target 0.49-0.52",
                       "first target 2.5", "first target 3.20-3.30 for NCI"],
            flags=re.IGNORECASE
        )

        # Phoenix target update: targets (for SYMBOL) PRICE(-PRICE)
        self.register(
            name="phoenix_targets_price",
            description="Phoenix targets update",
            priority=56,
            pattern=r'targets?\s+(?:for\s+\$?([A-Z]{2,5})\s+)?\$?([\d.]+)(?:\s*[-–—]\s*\$?([\d.]+))?(?:\s|$)',
            parser=self._parse_phoenix_targets_generic,
            examples=["targets 1.04", "targets 3.25-3.50", "targets for NXPL 0.76-0.80"],
            flags=re.IGNORECASE
        )

        # Phoenix full exit: (Im/I'm) selling SYMBOL (here) — no percentage = 100%
        self.register(
            name="phoenix_selling_full",
            description="Phoenix full exit - selling SYMBOL (no percentage)",
            priority=66,
            pattern=r"(?:i['\u2019]?m\s+)?selling\s+(?:now\s+)?\$?((?!HERE\b|NOW\b|MORE\b|SOON\b|MOST\b|HALF\b)[A-Z]{1,5})(?:\s+here)?(?:\s|$|[.,!])",
            parser=self._parse_phoenix_selling_full,
            examples=["selling TPET", "Im selling MOBX here", "selling CHOW",
                       "im selling LIMN", "im selling now AGAE", "selling ABP"],
            flags=re.IGNORECASE
        )

        # Phoenix exit: selling here SYMBOL (no percentage = 100%)
        self.register(
            name="phoenix_selling_here_sym",
            description="Phoenix full exit - selling here SYMBOL",
            priority=66,
            pattern=r'selling\s+(?:here\s+)\$?((?!AT\b|NOW\b|MORE\b)[A-Z]{1,5})(?![a-z])',
            parser=self._parse_phoenix_selling_full,
            examples=["selling here  SYNX"],
            flags=re.IGNORECASE
        )

        # Phoenix trim: selling SYMBOL X% (reversed order)
        self.register(
            name="phoenix_trim_reversed",
            description="Phoenix trim - selling SYMBOL X% (reversed)",
            priority=65,
            pattern=r'(?:selling|sold)\s+\$?((?!HERE\b|MORE\b|NOW\b)[A-Z]{1,5})\s+(?:here\s+)?(\d+)%',
            parser=self._parse_phoenix_trim_reversed,
            examples=["selling SUNE 70%", "selling FUSE 70%", "selling GXAI here 80%"],
            flags=re.IGNORECASE
        )

        # Phoenix trim: selling here X% SYMBOL
        self.register(
            name="phoenix_trim_here_before_pct",
            description="Phoenix trim - selling here X% SYMBOL",
            priority=64,
            pattern=r'(?:selling|sold)\s+here\s+(\d+)%\s+\$?([A-Z]{1,5})(?![a-z])',
            parser=self._parse_phoenix_trim,
            examples=["selling here 80%  FATBB"],
            flags=re.IGNORECASE
        )

        # Phoenix trim: selling another X% (like "more")
        self.register(
            name="phoenix_trim_another",
            description="Phoenix trim - selling another X%",
            priority=64,
            pattern=r'(?:selling|sold)\s+another\s+(\d+)%\s*(?:\$?([A-Z]{1,5})(?![a-z]))?',
            parser=self._parse_phoenix_trim_another,
            examples=["selling another 10%", "selling another 10% ACXP"],
            flags=re.IGNORECASE
        )

        # Phoenix trim: selling X%here (no space typo)
        self.register(
            name="phoenix_trim_nospace",
            description="Phoenix trim with no space before 'here'",
            priority=63,
            pattern=r'(?:selling|sold)\s+(\d+)%here(?:\s+\$?([A-Z]{1,5})(?![a-z]))?',
            parser=self._parse_phoenix_trim_nospace,
            examples=["selling 90%here", "selling 90%here SWVL"],
            flags=re.IGNORECASE
        )

        # Phoenix exit: knifed with/out of SYMBOL
        self.register(
            name="phoenix_knifed_sym",
            description="Phoenix knifed exit with symbol",
            priority=69,
            pattern=r'(?:(?:^|\s)\$?((?!ANOTHER|JUST|ALSO|BIG|THE|AND|BUT|OTHER)[A-Z]{2,5})\s+)?(?:knifed|kinfe)\s*(?:out\s+(?:of\s+)?(?:my\s+)?(?:position\s+)?)?(?:with\s+)?(?:(?:the\s+)?(?:remaining\s+)?)?(?:\$?((?!TIME|HERE|BIG|ROUGH|MISSED|MY|OUT)[A-Z]{2,5})(?![a-z]))?',
            parser=self._parse_phoenix_knifed,
            examples=["CDIO Knifed missed my goal", "knifed", "AUST knifed out of my position",
                       "another knifed with FUSE", "SGN knifed big time"],
            flags=re.IGNORECASE
        )

        # Phoenix exit: selling SYMBOL here at PRICE (full exit with price)
        self.register(
            name="phoenix_selling_at_price",
            description="Phoenix selling at specific price",
            priority=65,
            pattern=r'selling\s+(?:here\s+)?(?:at\s+)?\$?([\d.]+)\s*(?:dont|don)',
            parser=self._parse_phoenix_selling_at_price,
            examples=["selling here at 1.98 dont like it breaking even"],
            flags=re.IGNORECASE
        )

        # Phoenix add: "SYMBOL buying/adding ... shares" (ticker BEFORE verb)
        self.register(
            name="phoenix_adding_pre",
            description="Phoenix add - ticker before verb: SYMBOL buying/adding shares",
            priority=68,
            pattern=r'\$?([A-Z]{2,5})\s+(?:buying|adding)\s+(?:small\s+|more\s+)?(?:shares?)?(?:\s+(?:at|here|avg)\s+\$?([\d.]+))?',
            parser=self._parse_phoenix_adding_v2,
            examples=["SWMR buying small shares", "PHOE adding more shares", "JBDI buying shares at 5.50"],
            flags=re.IGNORECASE
        )

        # Phoenix add: "adding more to SYMBOL position" (explicit 'to SYMBOL' form)
        self.register(
            name="phoenix_adding_to",
            description="Phoenix add - adding more to SYMBOL position",
            priority=68,
            pattern=r'(?:adding|buying)\s+(?:more\s+)?(?:to\s+)(?:my\s+)?\$?([A-Z]{2,5})\s+(?:position|shares?)',
            parser=self._parse_phoenix_adding_v2,
            examples=["adding more to LGVN position", "adding to PHOE shares"],
            flags=re.IGNORECASE
        )

        # Phoenix add: "adding (here/more) SYMBOL (at PRICE)" (ticker AFTER verb, no 'to')
        self.register(
            name="phoenix_adding",
            description="Phoenix adding to position",
            priority=67,
            pattern=r'(?:adding|buying)\s+(?:here\s+)?(?:more\s+)?(?:shares?\s+)?\$?([A-Z]{2,5})(?:\s+shares?)?(?:\s+(?:at|here)\s+\$?([\d.]+))?',
            parser=self._parse_phoenix_adding_v2,
            examples=["adding here SMX at 11.50", "adding more PHOE shares", "buying more shares JBDI"],
            flags=re.IGNORECASE
        )

        # =====================================================================
        # JACOB FORMAT (Stock signals — exits, trims, SL updates)
        # Priority 52-55 — before Phoenix entries but after Phoenix SL patterns
        # =====================================================================

        self.register(
            name="jacob_cutting",
            description="Jacob exit - cutting SYMBOL (full exit)",
            priority=55,
            pattern=r'(?:^|[.!?\n]\s*)(?:personally\s+)?cutting\s+\$?((?!IT\b|MY\b|THE\b|AND\b|OUT\b|THIS\b|VERY\b|TOO\b|ALL\b|HALF\b|SOME\b|IF\b|AT\b|AROUND\b|HERE\b|NOW\b)[A-Z]{2,5})(?![a-z])',
            parser=self._parse_jacob_exit,
            examples=["cutting EONR", "Cutting NVTS", "personally cutting IBRX",
                       "Personally cutting PDYN", "Cutting AIM", "personally cutting RILY here"],
            flags=re.IGNORECASE
        )

        self.register(
            name="jacob_sold_pct_at_target",
            description="Jacob trim - sold/selling X% at first target (on SYMBOL)",
            priority=53,
            pattern=r'(?:selling|sold)\s+(\d+)%\s+(?:at\s+)?(?:first|1st|second|2nd|third|3rd)?\s*(?:target|targ)[\s!]*(?:on\s+\$?((?!THE|MY|OF|THIS)[A-Z]{2,5})(?![a-z]))?',
            parser=self._parse_jacob_trim_at_target,
            examples=["Selling 90% at First Target!", "Sold 90% at First Target on FEED",
                       "selling 90% at first target", "Selling 90% at first target!",
                       "Sold 90% at first target"],
            flags=re.IGNORECASE
        )

        self.register(
            name="jacob_sold_pct_of_sym",
            description="Jacob trim - selling/sold X% of SYMBOL",
            priority=53,
            pattern=r'(?:selling|sold)\s+(\d+)%\s+(?:of\s+)\$?((?!MY|THE|THIS|ALL)[A-Z]{2,5})(?![a-z])',
            parser=self._parse_phoenix_trim,
            examples=["Selling 50% of SKYQ to mitigate", "Selling 90% of SLGB",
                       "Selling 90% of IVF", "Sold 90% of IMTE at first target"],
            flags=re.IGNORECASE
        )

        self.register(
            name="jacob_sold_pct_sym_direct",
            description="Jacob trim - sold/selling X% SYMBOL (before 'at' catches it)",
            priority=53,
            pattern=r'(?:selling|sold)\s+(\d+)%\s+\$?((?!HERE\b|MORE\b|NOW\b|ON\b|THE\b|MY\b|OF\b|ALL\b|REST\b|AT\b|FIRST\b|IN\b|TO\b|FOR\b|WITH\b|PROFIT\b|SOME\b|EARLY\b|LATE\b|IF\b|AND\b|BUT\b|THEN\b|ALSO\b|JUST\b|WHEN\b|THIS\b|THAT\b|THEM\b|BEEN\b|WILL\b|FROM\b|WOW\b|AS\b|LET\b|SO\b|YET\b|TOO\b|NOT\b|ITS\b)[A-Z]{2,5})(?:\s|$|[.,!])',
            parser=self._parse_phoenix_trim,
            examples=["Selling 90% HCWC", "Selling 90% POLA at first target also"],
            flags=re.IGNORECASE
        )

        self.register(
            name="jacob_moved_stoploss",
            description="Jacob SL update - moved/moving/amended stoploss to PRICE",
            priority=54,
            pattern=r'(?:mov(?:ed|ing)|amended)\s+(?:my\s+)?stoploss\s+(?:to\s+)?\$?([\d.]+)',
            parser=self._parse_jacob_stoploss_update,
            examples=["Moving Stoploss to 8.90", "Amended stoploss to 2.73",
                       "Moving stoploss to 9.60", "Moved stoploss to 5.84"],
            flags=re.IGNORECASE
        )

        self.register(
            name="jacob_stoploss_price",
            description="Jacob SL info - stoploss PRICE (standalone SL reference)",
            priority=54,
            pattern=r'(?:^|\n)\s*(?:stoploss|stop\s*loss)\s+\$?([\d.]+)',
            parser=self._parse_jacob_stoploss_update,
            examples=["Stoploss 0.3780", "stoploss 3.60"],
            flags=re.IGNORECASE
        )

        self.register(
            name="jacob_plan_cut_breakeven",
            description="Jacob planning to cut at breakeven",
            priority=54,
            pattern=r'(?:planning\s+to\s+cut|plan\s+on\s+cutting)\s+\$?((?!IT\b|MY\b|THE\b)[A-Z]{2,5})\s+(?:at\s+|around\s+)?(?:breakeven|break\s*even|b/e)',
            parser=self._parse_jacob_exit,
            examples=["planning to cut UOKA around breakeven", "plan on cutting BANL at breakeven"],
            flags=re.IGNORECASE
        )

        self.register(
            name="jacob_selling_to_safe",
            description="Jacob trim - selling X% in profit to be safe",
            priority=53,
            pattern=r'(?:^|[.!?\n]\s*)(?:selling|sold)\s+(\d+)%\s+(?:in\s+profit|to\s+(?:be\s+)?safe|to\s+mitigate)',
            parser=self._parse_phoenix_trim_no_sym,
            examples=["Selling 50% in profit to be safe", "selling 50% to mitigate"],
            flags=re.IGNORECASE
        )

        self.register(
            name="jacob_out_and_all",
            description="Jacob exit - out of SYMBOL, and all other positions",
            priority=38,
            pattern=r'[Oo]ut\s+of\s+\$?([A-Z]{2,5}),?\s+and\s+all\s+other\s+positions',
            parser=self._parse_foxtrades_exit,
            examples=["Out of AIOS, and all other positions"],
            flags=re.IGNORECASE
        )

        # =====================================================================
        # PROTRADER FORMAT (Stock conditional orders with entry ranges, SL, targets)
        # =====================================================================
        
        self.register(
            name="protrader_structured",
            description="ProTrader structured: Ticker/Entey range/SL/Targs",
            priority=9,
            pattern=r'Ticker\s*:\s*\$?([A-Z]{1,5})\s*\n\s*Ent(?:e|r)y\s+range\s*:\s*(.+)',
            parser=self._parse_protrader_structured,
            examples=[
                "Ticker: VCIG\nEntey range: 15.50-15.25\nSL below 15.00\nTargs:15.75-16.00-16.25-16.50+",
                "Ticker: TTD\nEntey range: Break 31.71\nSL below manage your SL\nTargs:31.91-32.00-32.30-32.50-32.75",
            ]
        )

        self.register(
            name="protrader_inline_buying",
            description="ProTrader inline: SYMBOL - Buying X-Y / SL below Z - Targs",
            priority=58,
            pattern=r'(?:^|\n)\s*\$?([A-Z]{1,5})\s*[-–—]\s*(?:Swing\s*[-–—]?\s*)?(?:Buying\s+(?:support\s+)?|Buy\s+)([\d.]+)\s*[-–—]\s*([\d.]+)',
            parser=self._parse_protrader_inline,
            examples=[
                "RIME - Buying 3.37-3.20- SL below 3.10- Targs : 3.50-3.60-3.75+",
                "EZRA - Buying 0.3044-0.26/ SL below 0.24- Targs : 0.33-0.35-0.37-0.40+",
            ]
        )

        self.register(
            name="protrader_breakout",
            description="ProTrader breakout: SYMBOL - Buying break of X for a move to Y-Z",
            priority=75,
            pattern=r'(?:^|\n)\s*\$?([A-Z]{1,5})\s*[-–—_\s]+(?:Buying\s+)?[Bb](?:uy(?:ing)?)\s+break\s+of\s+([\d.]+)\s+for\s+a\s+move\s+to\s+([\d.]+(?:\s*[-–—]\s*[\d.]+)*)',
            parser=self._parse_protrader_breakout,
            examples=[
                "AEHL - Buying break of 1.04 for a move to 1.10-1.15-1.17",
                "RRGB - Buying break of 4.41 for a move to 4.45-4.50-4.52",
            ]
        )

        self.register(
            name="protrader_cancel",
            description="ProTrader cancel alert (all variations)",
            priority=72,
            pattern=r'(?:(?:^|\n)\s*\$?([A-Z]{1,5})\s*[-–—.\s]+.*?(?:[Pp]lease\s+)?[Cc]ancel(?:ling)?\s+(?:the\s+|this\s+)?(?:alert|this)|[Cc]ancel(?:ling)?\s+(?:the\s+|this\s+)?\$?([A-Z]{1,5})\s+(?:alert|swing\s+alert))',
            parser=self._parse_protrader_cancel_v2,
            flags=0,
            examples=[
                "Cancel the AZI alert",
                "RMSG - Ran up from 0.6327 .. cancel this alert please",
                "DRMA - Please cancel the alert",
                "LIMN- cancelling this alert",
                "LWLG - cancel this alert please",
                "JDZG - please cancel this",
                "NAMM - Cancel this swing alert.",
            ]
        )

        self.register(
            name="protrader_exit",
            description="ProTrader exit/sell signals: sold all, scale out, take profits, do secure",
            priority=57,
            pattern=r'(?:^|\n)\s*\$?([A-Z]{1,5})\s*[-–—.\s]+.*?(?:[Ss]old\s+[Aa]ll|(?:[Ss]tart\s+[Tt]o\s+)?[Ss]cale\s+[Oo]ut|(?:[Dd]o\s+)?(?:[Tt]ake|[Ss]ecure)\s+(?:[Pp]rofits|[Gg]ains)|[Dd]o\s+[Ss]ecure|[Ww]e\s+[Aa]re\s+[Oo]ut)',
            parser=self._parse_protrader_exit,
            flags=0,
            examples=[
                "UCAR sold all from our low 0.70s entry",
                "ELPW - start to scale out and take profits",
                "RRGB - Went BOOM - hit 4.60- do take profits",
                "ACXP hit 5.54 from 3.84 break.. do secure",
            ]
        )

        # QUICK-SWING-ALERTS FORMAT (Embed-based: Title="NOTE", Entry: range (...), Target: (...), Stop loss: Below X)
        self.register(
            name="quick_swing_entry",
            description="Quick-Swing-Alerts: Ticker/Entry range/Target/Stop loss",
            priority=74,
            pattern=r'(?:Swing\s*:\s*)?Ticker\s*:\s*\$?([A-Z]{1,5})\s*\n\s*Entry\s*:\s*range\s*\((.+?)\)',
            parser=self._parse_quick_swing_entry,
            examples=[
                "Ticker: $TDOC\nEntry: range (4.90-4.50/4.00-3.90)\nTarget: (5.30-5.50-5.75-6.00+)\nStop loss: Below  3.50",
                "Ticker: $TURB\nEntry: range (3.82-3.71)\nTarget:  (3.90-4.00-4.10-4.20-4.30++)\nStop loss: Below  3.50",
                "Swing : Ticker: $CETX\nEntry: range (Add half size -100 shares 1.76-1.60/ Add another half size 100 shares 1.45-1.35)\nTarget: (1.85-1.90-2.00-2.10-2.10+)\nStop loss: Below 1.20",
            ],
            flags=re.IGNORECASE
        )

        self.register(
            name="quick_swing_cancel",
            description="Quick-Swing-Alerts cancel: Cancel/remove SYMBOL alert",
            priority=73,
            pattern=r'(?:cancel|remove)\s+(?:the\s+)?\$?([A-Z]{1,5})\s+(?:alert|swing)',
            parser=self._parse_quick_swing_cancel,
            flags=re.IGNORECASE,
            examples=[
                "Cancel the TDOC alert",
                "Remove the MARA swing",
            ]
        )

        self.register(
            name="quick_swing_exit",
            description="Quick-Swing-Alerts exit: sold/out of SYMBOL",
            priority=38,
            pattern=r'(?:sold\s+(?:all|out)|(?:all\s+)?out\s+of|exited?|we\s+are\s+out)\s+(?:of\s+)?\$?([A-Z]{1,5})',
            parser=self._parse_quick_swing_exit,
            flags=re.IGNORECASE,
            examples=[
                "Sold all TDOC",
                "Out of MARA",
            ]
        )

        # =====================================================================
        # TEMPLE OF BOOM FORMATS (priority 76-79)
        # =====================================================================
        from src.signals.temple_parser import (
            parse_temple_zz_emoji_entry, parse_temple_zz_emoji_exit,
            parse_temple_zz_emoji_target, parse_temple_zz_stock_entry,
            parse_temple_zz_stock_exit, parse_temple_zz_trim,
            parse_temple_rf_options, parse_temple_options_standard,
            parse_temple_zz_options_a, parse_temple_zz_options_b,
            parse_temple_ts_options, parse_temple_options_exit,
            parse_temple_zz_breakout, parse_temple_zz_breakout_reverse,
            parse_temple_zz_ticker_price_now,
            parse_temple_zz_range_entry, parse_temple_zz_sl_update_new,
            parse_temple_zz_sl_update_move,
            parse_temple_zz_structured_entry, parse_temple_zz_plain_entry,
            parse_temple_zz_inline_role_entry,
            parse_temple_zz_structured_entry_no_targets,
            parse_temple_zz_single_line_entry,
            parse_temple_zz_will_enter_break,
            parse_temple_zz_will_enter_if_breaks,
            parse_temple_zz_breakout_shorthand,
            parse_temple_zz_scalp, parse_temple_zz_lotto,
            parse_temple_zz_small_entry,
            parse_temple_zz_swing_update, parse_temple_zz_standalone_targets,
        )

        # --- Stock channel (⚡│zz) ---

        self.register(
            name="temple_zz_emoji_entry",
            description="Temple stock entry with ▶ emoji: ▶ SYMBOL $PRICE",
            priority=76,
            pattern=r'▶\s*(?:In\s+)?\$?([A-Z]{1,5})\s+\$?(\d+(?:\.\d+)?)',
            parser=parse_temple_zz_emoji_entry,
            examples=["▶ PLTR $22.50", "▶ In SOFI $8.30 SL $7.90 PT $9.50"],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_zz_emoji_exit",
            description="Temple stock exit with ⛔ emoji: ⛔ SYMBOL",
            priority=76,
            pattern=r'⛔\s*(?:Out\s+|SL\s+out\s+|Cut\s+)?\$?([A-Z]{1,5})',
            parser=parse_temple_zz_emoji_exit,
            examples=["⛔ PLTR", "⛔ Out SOFI", "⛔ SL out RIVN"],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_zz_emoji_target",
            description="Temple stock target hit with 🎯 emoji (trim)",
            priority=76,
            pattern=r'🎯\s*\$?([A-Z]{1,5})',
            parser=parse_temple_zz_emoji_target,
            examples=["🎯 PLTR", "🎯 SOFI"],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_zz_stock_entry",
            description="Temple stock entry: In SYMBOL $PRICE",
            priority=77,
            pattern=r'\b[Ii]n\s+\$?([A-Z]{1,5})\s+(?:\$|avg\s*\$?)(\d+(?:\.\d+)?)',
            parser=parse_temple_zz_stock_entry,
            examples=["In PLTR $22.50", "In SOFI avg $8.30"],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_zz_stock_exit",
            description="Temple stock exit: Out/SL out/Cut SYMBOL",
            priority=77,
            pattern=r'\b(?:Out|SL\s+out|Cut)\s+\$?([A-Z]{1,5})\b',
            parser=parse_temple_zz_stock_exit,
            examples=["Out PLTR", "SL out SOFI", "Cut RIVN"],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_zz_trim_pct",
            description="Temple stock trim: Trim 35% / Trim SYMBOL 50%",
            priority=77,
            pattern=r'\b[Tt]rim\s+(?:\$?([A-Z]{1,5})\s+)?(\d+(?:\.\d+)?)\s*%',
            parser=parse_temple_zz_trim,
            examples=["Trim 35%", "Trim PLTR 50%"],
            flags=re.IGNORECASE
        )

        # --- Trading floor (🔥│trading-floor — traderzz1m conversational) ---

        self.register(
            name="temple_zz_breakout",
            description="Temple ZZ breakout: SYMBOL break PRICE for TARGET",
            priority=75,
            pattern=r'(?:^|\n)\s*\$?([A-Z]{2,5})\s+(?:(\d+(?:\.\d+)?)\s+)?(?:only\s+if\s+(?:it\s+)?)?break(?:s)?\s*(?:of\s+)?(?:(\d+(?:\.\d+)?)\s+)?(?:for\s+|takes?\s+(?:it\s+)?to\s+)\$?(\d+(?:\.\d+)?)',
            parser=parse_temple_zz_breakout,
            examples=["PMAX break 2.82 for 3.12", "EZGO 3.11 break takes it to 3.41",
                       "PMAX only if it breaks 2.82 for 3.00", "MASK break of 1.80 takes it to 2.00"],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_zz_breakout_reverse",
            description="Temple ZZ breakout reverse: PRICE break for TARGET SYMBOL",
            priority=74,
            pattern=r'(?:^|\n)\s*\$?(\d+(?:\.\d+)?)\s+(?:has\s+to\s+|must\s+)?break(?:s)?\s+(?:only\s+)?(?:for\s+|takes?\s+(?:it\s+)?to\s+)\$?(\d+(?:\.\d+)?)\s+\$?([A-Z]{2,5})\b',
            parser=parse_temple_zz_breakout_reverse,
            examples=["2.50 must break for 2.71 OCG", "21.50 break takes it to 25 AVTX",
                       "3.80 break only for 4.43 WAI"],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_zz_ticker_price_now",
            description="Temple ZZ immediate entry: $SYMBOL PRICE now",
            priority=76,
            pattern=r'^\$?([A-Z]{2,5})\s+(\d+(?:\.\d+)?)\s+now$',
            parser=parse_temple_zz_ticker_price_now,
            examples=["$EZGO 3.28 now", "ERNA 5.50 now"],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_zz_range_entry",
            description="Temple ZZ range entry: SYMBOL LOW-HIGH (with optional trailing text)",
            priority=77,
            pattern=r'^\$?([A-Z]{2,5})\s+(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)',
            parser=parse_temple_zz_range_entry,
            examples=["CRE 2.80-3.91", "SDOT 0.36-0.50", "BLZE 5.70-6.47", "SPAI 3.80-4.15 already"],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_zz_sl_update_new",
            description="Temple ZZ SL update: PRICE should be your new SYMBOL SL",
            priority=55,
            pattern=r'(\d+(?:\.\d+)?)\s+should\s+be\s+your\s+(?:new\s+)?\$?([A-Z]{2,5})\s+SL',
            parser=parse_temple_zz_sl_update_new,
            examples=["5.50 should be your new ERNA SL", "9.67 should be your SKK SL"],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_zz_sl_update_move",
            description="Temple ZZ SL update: Move your SL to PRICE",
            priority=55,
            pattern=r'[Mm]ove\s+your\s+(?:mental\s+)?(?:stop\s+loss|SL)\s+(?:up\s+)?(?:for\s+\$?([A-Z]{2,5})\s+)?to\s+\$?(\d+(?:\.\d+)?)',
            parser=parse_temple_zz_sl_update_move,
            examples=["Move your SL up to 5.00 if in", "You can move your mental stop loss for ERNA to 5.30",
                       "Move your SL to 9.67"],
            flags=re.IGNORECASE
        )

        # --- ZZ scalp/inline entries ---

        self.register(
            name="temple_zz_scalp_at",
            description="ZZ scalp: SYMBOL scalping/scalp at PRICE",
            priority=74,
            pattern=r'^\$?([A-Z]{2,5})\s+(?:scalp(?:ing)?|will\s+scalp\s+it\s+here)\s+(?:again\s+)?at\s+\$?(\d+(?:\.\d+)?)',
            parser=self._parse_temple_zz_scalp_at,
            examples=["RECT scalping at 1.68 for 1.80", "CREG scalp again at 0.688 looking for", "MGN will scalp it here at 0.20"],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_zz_in_small",
            description="ZZ inline: $SYMBOL in small at PRICE / Small $SYMBOL PRICE",
            priority=74,
            pattern=r'(?:^\$?([A-Z]{2,5})\s+in\s+(?:small\s+)?(?:at\s+)\$?(\d+(?:\.\d+)?)|\b[Ss]mall\s+\$([A-Z]{2,5})\s+(?:for\s+.*?)?\$?(\d+(?:\.\d+)?))',
            parser=self._parse_temple_zz_in_small,
            examples=["$EDBL in small at 0.45", "Small $IPST for a <@&role> 5.22"],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_zz_bird_inline",
            description="ZZ inline: $SYMBOL in $PRICE small/for role SL PRICE",
            priority=73,
            pattern=r'^\$?([A-Z]{2,5})\s+in\s+\$?(\d+(?:\.\d+)?)\s+(?:small|for)',
            parser=self._parse_temple_zz_bird_inline,
            examples=["$BIRD in $12.00 small for a <@&role> SL 11.80"],
            flags=re.IGNORECASE
        )

        # --- ZZ structured emoji (✅/❌/🎯 format — author "ZZ") ---

        self.register(
            name="temple_zz_structured_entry",
            description="ZZ structured: $TICKER @role / ✅ entry / ❌ SL (optional) / 🎯 targets",
            priority=50,
            pattern=r'^\$?([A-Z]{1,5})[ \t]*(?:<@&\d+>[ \t]*(?:/\w+)?[ \t]*)*[^\n]*\n?.*?✅[ \t]*(?:around[ \t]+|(?:clear[ \t]+)?bre?a?k[ \t]+(?:of[ \t]+)?|in[ \t]+(?:again[ \t]+|back[ \t]+)?at[ \t]+)?(?:\$[ \t]*)?(\d+(?:\.\d+)?)(?:ish|s)?[ \t]*(?:-[ \t]*(\d+(?:\.\d+)?))?[^\n]*\n(?:(?:❌|➕)[ \t]*(?:(?:under|below)\s+)?(?:\$\s*)?-?(\d+(?:\.\d+)?)[ \t]*%?(?:\s*(?:suggested|mental))?\s*\n)?🎯[ \t]*([\d.,\s%+\-]+(?:\.{2,}[\d.,\s%+\-]+)*)',
            parser=parse_temple_zz_structured_entry,
            examples=[
                "$AREB <@&1330929339134640179> \n✅ 0.30\n❌ 0.28\n🎯 0.33...0.37...0.40",
                "$BIYA\n✅ 1.55\n❌ 1.45\n🎯 1.64...1.74...1.88...2.00",
                "XOS\n✅ 4.30\n❌ -10%\n🎯 4.53...5.15...5.43...6.00..6.50+",
                "GMEX\n✅ clear break of 3.50\n🎯 4.00...4.21...4.38...5.83",
                "RKTO \n✅ clear brak of 2.53\n🎯 2.77...3.03...3.50",
                "RKTO\n✅ in again at 2.10\n🎯 2.21....2.35...2.43....2.53...3.00+",
                "MSAI lotto ✅ $6.20s ❌ 5.80 🎯 6.75...7.57...8.00",
                "YMAT will enter for the 7th time around ✅ 1.00 again. ❌ 0.78 🎯 5% 10% 15%+",
                "$SUGP\n✅ 1.30ish\n❌ 1.23\n🎯 1.50...1.80",
            ],
            flags=re.IGNORECASE | re.MULTILINE
        )

        self.register(
            name="temple_zz_structured_entry_no_targets",
            description="ZZ structured without targets: $TICKER @role / ✅ entry / ❌ SL (optional)",
            priority=51,
            pattern=r'^\$?([A-Z]{1,5})[ \t]*(?:<@&\d+>[ \t]*(?:/\w+)?[ \t]*)*[^\n]*\n?.*?✅[ \t]*(?:around[ \t]+|(?:clear[ \t]+)?bre?a?k[ \t]+(?:of[ \t]+)?|in[ \t]+(?:again[ \t]+|back[ \t]+)?at[ \t]+)?(?:\$[ \t]*)?(\d+(?:\.\d+)?)(?:ish|s)?[ \t]*(?:-[ \t]*(\d+(?:\.\d+)?))?[^\n]*(?:\n(?:❌|➕)[ \t]*(?:(?:under|below)\s+)?(?:\$\s*)?-?(\d+(?:\.\d+)?)[ \t]*%?(?:\s*(?:suggested|mental))?)?',
            parser=parse_temple_zz_structured_entry_no_targets,
            examples=[
                "$CYAB <@&swing>\n✅ 0.66",
                "BNRG\n✅ 1.60\n❌ 1.45",
                "$VIVO <@&swing>\n✅ 3.45\n❌ 3.10",
            ],
            flags=re.IGNORECASE | re.MULTILINE
        )

        self.register(
            name="temple_zz_single_line_entry",
            description="ZZ single-line: $SYMBOL @role [✅] PRICE[-PRICE]",
            priority=52,
            pattern=r'^\$?([A-Z]{1,5})\s*(?:<@&\d+>\s*)+(?:✅\s*)?(?:\$\s*)?(\d+(?:\.\d+)?)(?:\s*-\s*(\d+(?:\.\d+)?))?',
            parser=parse_temple_zz_single_line_entry,
            examples=[
                "$ACXP <@&swing> ✅ 1.75-1.80",
                "CTNT <@&momentum> <@&swing> 2.18",
            ],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_zz_single_line_structured",
            description="ZZ single-line: $SYMBOL [text] ✅ PRICE 🎯 TARGETS (no newlines)",
            priority=51,
            pattern=r'^\$?([A-Z]{1,5})\s+.*?✅\s*(?:\$\s*)?(\d+(?:\.\d+)?)(?:ish|s)?\s+🎯\s*([\d.,\s%+\-]+(?:\.{2,}[\d.,\s%+\-]+)*)',
            parser=parse_temple_zz_structured_entry,
            examples=[
                "$AIM ✅ 0.81 🎯 0.86-1.00",
                "$SBEV ✅ clear break of 0.33 for 0.35 🎯 0.41",
            ],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_zz_plain_entry",
            description="ZZ plain text entry: SYMBOL in [again] at PRICE [@Tag]",
            priority=50,
            pattern=r'^\$?([A-Z]{1,5})\s+in\s+(?:again\s+|back\s+|small\s+)?at\s+\$?(\d+(?:\.\d+)?)\s*(?:@(\w+))?',
            parser=parse_temple_zz_plain_entry,
            examples=[
                "MREO in at 2.50",
                "NCEL in at 3.80 @Momentum",
                "YMAT in again at 1.15 @Swing",
                "SNGX in at 0.95",
            ],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_zz_inline_role_entry",
            description="ZZ inline entry with role: SYMBOL price @Momentum/@Swing",
            priority=51,
            pattern=r'^\$?([A-Z]{1,5})\s+(?:(?:in\s+(?:small\s+)?(?:at\s+)?)?\$?(\d+(?:\.\d+)?)\s*(?:!?\s*)?<@&(\d+)>|(?:<@&(\d+)>\s*)+(?:/\w+\s*)?\$?(\d+(?:\.\d+)?))',
            parser=parse_temple_zz_inline_role_entry,
            examples=[
                "OCG  in at 2.12 <@&1330929339134640179>",
                "MNTS 4.8 <@&1330929339134640179>",
                "$EDHL <@&1330929339134640179> 2.67",
                "OUST 29.26 <@&1330915546513805463>",
            ],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_zz_will_enter_break",
            description="ZZ will-enter: SYMBOL will enter break of PRICE for TARGETS",
            priority=49,
            pattern=r'^\$?([A-Z]{1,5})\s+will\s+enter\s+bre?a?k\s+(?:of\s+)?\$?(\d+(?:\.\d+)?)\s+for\s+(.+)',
            parser=parse_temple_zz_will_enter_break,
            examples=[
                "RKTO will enter break of 2.02 for 2.12...2.21...2.35..2.53",
            ],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_zz_structured_entry_for_targets",
            description="ZZ structured with 'for' targets: SYMBOL ✅ break of PRICE for TARGETS",
            priority=49,
            pattern=r'^\$?([A-Z]{1,5})\s*\n✅[ \t]*(?:clear[ \t]+)?bre?a?k[ \t]+(?:of[ \t]+)?\$?(\d+(?:\.\d+)?)\s+for\s+(.+)',
            parser=parse_temple_zz_will_enter_break,
            examples=[
                "RKTO \n✅ clear brak of 2.53 for 2.77 retest and 3.03-3.50",
            ],
            flags=re.IGNORECASE | re.MULTILINE
        )

        self.register(
            name="temple_zz_will_enter_if_breaks",
            description="ZZ will enter if breaks: SYMBOL will enter [only] if [it] breaks PRICE for TARGETS",
            priority=48,
            pattern=r'^\$?([A-Z]{1,5})\s+(?:I\s+)?will\s+(?:only\s+)?(?:re-?)?enter\s+(?:only\s+)?(?:if\s+)?(?:it\s+)?(?:give[s]?\s+(?:us\s+)?(?:a\s+)?)?(?:clear\s+)?(?:strong\s+)?(?:bre?a?k(?:s)?(?:\s+(?:and\s+)?holds?)?\s+(?:of\s+)?|(?:at\s+(?:a\s+)?)?(?:clear\s+)?)\$?(\d+(?:\.\d+)?)\s+(?:for|(?:bre?a?k\s+)?for)\s+(.+)',
            parser=parse_temple_zz_will_enter_if_breaks,
            examples=[
                "SMTK will enter only if it breaks 0.55 for 0.60...0.65....0.68 retest",
                "FFAI I will enter only if it breaks 0.45 for 0.47...0.52",
                "STAK I will enter if it give us a clear break of 2.43 for 2.86-3.50",
                "$MIMI will enter at a $4.00 clear break for 4.25-4.70-5.20",
                "$DRTS good news - will enter a strong 10.19 break for 11.10-11.97",
                "ALGS will enter if it breaks 9.16 for 10.23...11.97",
            ],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_zz_will_enter_no_targets",
            description="ZZ will enter if breaks without 'for' targets: SYMBOL will enter [if] breaks PRICE",
            priority=48,
            pattern=r'^\$?([A-Z]{1,5})\s+(?:I\s+)?will\s+(?:only\s+)?(?:re-?)?enter\s+(?:only\s+)?(?:if\s+)?(?:it\s+)?(?:bre?a?k(?:s)?(?:\s+(?:and\s+)?holds?)?\s+(?:of\s+)?|(?:at\s+))\$?(\d+(?:\.\d+)?)',
            parser=parse_temple_zz_will_enter_if_breaks,
            examples=[
                "RMSG I will enter if it breaks and holds 1.59",
                "ONFO will enter at 1.45 break",
                "CLRB will enter only if it breaks 6.30 again.",
                "IQST will re-enter if it breaks and holds 1.30",
            ],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_zz_breakout_shorthand",
            description="ZZ breakout shorthand: SYMBOL [clear] break [of] PRICE [only] for TARGETS",
            priority=48,
            pattern=r'^\$?([A-Z]{1,5})\s+(?:clear\s+)?bre?a?k\s+(?:of\s+)?\$?(\d+(?:\.\d+)?)\s+(?:only\s+)?for\s+(.+)',
            parser=parse_temple_zz_breakout_shorthand,
            examples=[
                "ASBP clear break of 0.26 for 0.269....0.30...0.32",
                "BBBY break of 6.40 only for 7.04",
                "BIYA break of 1.58 only for 2.00",
            ],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_zz_i_will_take_break",
            description="ZZ I will take/buy break: I will take/buy PRICE break or breaks PRICE",
            priority=48,
            pattern=r'^\$?([A-Z]{1,5})\s+I\s+will\s+(?:take|buy)\s+(?:(?:clear\s+)?bre?a?k\s+(?:of\s+)?)?\$?(\d+(?:\.\d+)?)\s*(?:bre?a?k)?(?:\s+for\s+(.+))?',
            parser=parse_temple_zz_will_enter_if_breaks,
            examples=[
                "DRCT I will take 3.67 break",
                "ABVE I will take clear break of 0.84 for 1.00",
                "$DARE I will buy if it breaks 2.80 for 3.00+",
            ],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_zz_scalp_here",
            description="ZZ scalping: Scalping SYMBOL [here] [at] PRICE",
            priority=73,
            pattern=r'[Ss]calping\s+\$?([A-Z]{2,5})\s+(?:here\s+)?(?:at\s+|from\s+)?\$?(\d+(?:\.\d+)?)?',
            parser=parse_temple_zz_scalp,
            examples=[
                "Scalping NCT here at 4.40",
                "Scalping $GDC here at 0.22",
                "Scalping ISPC 0.16",
                "Scalping $LABT from 16.00",
            ],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_zz_lotto_entry",
            description="ZZ lotto: [Small] [lotto] SYMBOL [at] PRICE",
            priority=73,
            pattern=r'(?:(?:[Ss]mall\s+)?[Ll]otto\s+(?:size\s+)?\$?([A-Z]{2,5})|\$?([A-Z]{2,5})\s+lotto(?:\s+(?:for\s+)?(?:day\s+\d+\s+)?)?)\s*(?:at\s+|@\s*)?\$?(\d+(?:\.\d+)?)',
            parser=parse_temple_zz_lotto,
            examples=[
                "$OTLK lotto at $0.54",
                "Small lotto $ADVB at 7.00",
                "$WLAC lotto at 13.65",
                "$ATER lotto for day 3 at $1.08",
                "Small lotto USEG on news at $1.03",
            ],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_zz_small_reversal",
            description="ZZ small entry: Small SYMBOL [for the reversal] [at/here] PRICE",
            priority=73,
            pattern=r'[Ss]mall\s+\$?([A-Z]{2,5})\s+(?:(?:for\s+)?(?:the\s+)?(?:reversal\s+)?)?(?:(?:here\s+)?(?:at\s+)?\$?(\d+(?:\.\d+)?))?',
            parser=parse_temple_zz_small_entry,
            examples=[
                "Small AGAE for the reversal 0.61",
                "Small EDHL for the reversal here",
                "Small $ABTS again 2.93",
            ],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_zz_ciss_reversal",
            description="ZZ reversal entry: SYMBOL for the reversal [here] at PRICE [SL -X%]",
            priority=73,
            pattern=r'^\$?([A-Z]{2,5})\s+for\s+the\s+reversal\s+(?:here\s+)?(?:at\s+)?\$?(\d+(?:\.\d+)?)',
            parser=parse_temple_zz_scalp,
            examples=[
                "$CISS for the reversal here at 2.55. SL -10%",
                "ASBP 0.32 for the reversal",
            ],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_zz_swing_update",
            description="ZZ swing update with targets/SL: $TICKER @Swing 🎯 targets ❌ SL",
            priority=51,
            pattern=r'\$?([A-Z]{1,5})\s*<@&(\d+)>.*?🎯\s*([\d.]+(?:\s*[-–]\s*[\d.]+)*)\s*❌\s*(?:below\s+)?\$?(\d+(?:\.\d+)?)',
            parser=parse_temple_zz_swing_update,
            examples=[
                "$TRUG <@&1330915546513805463> \nWill average down around these levels. 🎯 2.60-3.00 ❌ below 2.00",
            ],
            flags=re.IGNORECASE | re.DOTALL
        )

        self.register(
            name="temple_zz_standalone_targets",
            description="ZZ standalone targets: 🎯 T1...T2...T3 (no ticker)",
            priority=80,
            pattern=r'^🎯\s*([\d.]+(?:\s*\.{2,}\s*[\d.]+)+)\s*$',
            parser=parse_temple_zz_standalone_targets,
            examples=[
                "🎯 2.41...2.71",
                "🎯 0.33...0.37...0.40",
            ],
            flags=re.IGNORECASE
        )

        # --- Options channel (🚨│options-alerts💰) ---

        self.register(
            name="temple_rf_options",
            description="Temple RF options: buy TICKER STRIKE[+]C at PRICE for EXPIRY",
            priority=78,
            pattern=r'\bbuy\s+\$?([A-Z]{1,5})\s+(\d+(?:\.\d+)?)\s*\+?\s*([CcPp])\s+at\s+\$?(\d+(?:\.\d+)?)\s+for\s+(\d{1,2}/\d{1,2}(?:/\d{2,4})?)',
            parser=parse_temple_rf_options,
            examples=["buy QQQ 530+C at 2.50 for 5/16", "buy SPY 580+P at 1.20 for 5/9", "buy UNH 397.5C at 8.5 for 6/12"],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_ts_options",
            description="Temple Toughshit options: TICKER STRIKE Puts-.75 C SL .65",
            priority=78,
            pattern=r'\$?([A-Z]{1,5})\s+(\d+(?:\.\d+)?)\s+(Puts?|Calls?)\s*[-–]?\s*(\.?\d+(?:\.\d+)?)\s+C\b',
            parser=parse_temple_ts_options,
            examples=["QQQ 579 Puts-.75 C SL .65", "SPY 580 Calls-1.20 C"],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_zz_options_a",
            description="Temple zz options: TICKER C/P STRIKE daily/weekly",
            priority=78,
            pattern=r'\$?([A-Z]{1,5})\s+([CcPp])\s+(\d+(?:\.\d+)?)\s+(daily|weekly|\d{1,2}/\d{1,2}(?:/\d{2,4})?)',
            parser=parse_temple_zz_options_a,
            examples=["SPY P 653 daily", "QQQ C 480 5/16"],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_zz_options_b",
            description="Temple zz options: TICKER STRIKEc PRICE",
            priority=79,
            pattern=r'\$?([A-Z]{1,5})\s+(\d+(?:\.\d+)?)\s*([CcPp])\s+(\d+(?:\.\d+)?)(?!\s*/)(?!\d)',
            parser=parse_temple_zz_options_b,
            examples=["SPY 580c 1.80", "NVDA 135c 2.50"],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_options_standard",
            description="Temple options standard: TICKER STRIKEc @.PRICE",
            priority=79,
            pattern=r'\$?([A-Z]{1,5})\s+(\d+(?:\.\d+)?)\s*([CcPp])\s+@\s*\$?(\.?\d+(?:\.\d+)?)',
            parser=parse_temple_options_standard,
            examples=["TSLA 350c @.85", "SPY 580 C @1.80", "NVDA 135c @1.20"],
            flags=re.IGNORECASE
        )

        self.register(
            name="temple_options_exit",
            description="Temple options exit: out/sold TICKER STRIKEc",
            priority=69,
            pattern=r'\b(?:out|sold|cut|SL\s+out)\s+\$?([A-Z]{1,5})\s+(\d+(?:\.\d+)?)\s*([CcPp])',
            parser=parse_temple_options_exit,
            examples=["out TSLA 350c", "sold SPY 580c 2.50", "SL out QQQ 480p"],
            flags=re.IGNORECASE
        )

        # =====================================================================
        # ASHLEY OPTIONS FORMAT (RedAlert emoji)
        # =====================================================================

        self.register(
            name="ashley_option_entry",
            description="Ashley options: RedAlert SYMBOL - $STRIKE CALLS/PUTS EXPIRY $PRICE",
            priority=18,
            pattern=r'<a:[^>]+>\s*([A-Z]{1,5})\s*-\s*\$?(\d+(?:\.\d+)?)\s+(CALLS?|PUTS?)\s+(EXPIRATION\s+(?:THIS|NEXT)\s+WEEK|EXPIRATION\s+\d{1,2}/\d{1,2}(?:/\d{2,4})?|0DTE|\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s+\$?(\.?\d+(?:\.\d+)?)',
            parser=self._parse_ashley_entry,
            examples=[
                '<a:RedAlert:759583962237763595> SEDG - $60 CALLS 5/29 $1.15 @everyone',
                '<a:RedAlert:759583962237763595> GS - $985 CALLS EXPIRATION THIS WEEK $2.50',
                '<a:RedAlert:759583962237763595> SPY - $735 PUTS 0DTE $2.40 @everyone',
                '<a:RedAlert:759583962237763595> CSCO - $125 CALLS 6/18 .97',
            ]
        )

        self.register(
            name="ashley_trim",
            description="Ashley trim: TRIMMED/TRIM/TRIMMING with optional pct/price",
            priority=72,
            pattern=r'(?:([A-Z]{1,5})\s+)?(?:CALLS?\s+)?(?:TRIMM(?:ED|ING)|TRIM\s+PARTIAL)\b[^$\d]*(?:\$?([\d.]+)\b)?[^%\d]*(\d+%)?',
            parser=self._parse_ashley_trim,
            examples=[
                'TRIM PARTIAL HERE AT $1.65 @everyone',
                'GS CALLS TRIMMING LITTLE MORE @everyone',
                'AVGO TRIMMED MORE @everyone',
                'UP $100 PER CONTRACT, TRIMMED 50% HERE @everyone',
                'WMT TRIMMED PARTIAL AT $1.85 @everyone',
            ]
        )

        self.register(
            name="ashley_all_out",
            description="Ashley full exit: [SYMBOL] ALL OUT",
            priority=71,
            pattern=r'(?:([A-Z]{1,5})\s+(?:\S+\s+)?)?ALL\s+OUT',
            parser=self._parse_ashley_all_out,
            examples=[
                'FCEL ALL OUT @everyone',
                'PANW 217.5 CALLS ALL OUT @everyone',
                'ALL OUT @everyone',
                'SPX LOTTOS ALL OUT @everyone',
            ]
        )

        # =====================================================================
        # ANGELA OPTIONS FORMAT (siren_blue emoji)
        # =====================================================================

        self.register(
            name="angela_option_entry",
            description="Angela options: SYMBOL [lotto] calls/puts $STRIKE $PRICE EXPIRY added",
            priority=19,
            pattern=r'(?:<a:[^>]+>\s*)?([A-Z]{1,5})\s+(?:lotto\s+)?(?:calls?|puts?)\s+\$?(\d+(?:\.\d+)?)\s+\$?(\.?\d+(?:\.\d+)?)\s+(\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s+(?:added|aDDDED|lotto)',
            parser=self._parse_angela_entry,
            examples=[
                '<a:8375_siren_blue:785286170904625152> ENPH calls $50 $1.83 5/22 added SL 1.6',
                '<a:8375_siren_blue:785286170904625152> TSLA lotto calls $452.5 $1.14 5/13 added SL 0.8',
                'META calls $635 $2.26 5/15 added SL 1.9',
                '<a:8375_siren_blue:785286170904625152> F calls $14 $0.22 5/15 lotto',
            ]
        )

        self.register(
            name="angela_trim",
            description="Angela trim: SYMBOL [calls] [at $X] taking N%",
            priority=73,
            pattern=r'([A-Z]{1,5})\s+(?:calls?\s+|puts?\s+|swings?\s+)?(?:at\s*\$?[\d.]+\s*[.]?\s*)?(?:closing\s+|taking\s+(?:more\s+)?|down\s+to\s+)(\d+)%',
            parser=self._parse_angela_trim,
            examples=[
                'TSLA taking 40% at $2.84',
                'GOOGL calls at $2.30 taking more 20%',
                'MRVL calls at $2.75 taking 50%',
                'RKLB taking 50% at $3.20',
            ]
        )

        self.register(
            name="angela_trim_at_price",
            description="Angela trim: SYMBOL taking N% at $PRICE",
            priority=73,
            pattern=r'([A-Z]{1,5})\s+taking\s+(?:more\s+)?(\d+)%\s+at\s+\$?([\d.]+)',
            parser=self._parse_angela_trim,
            examples=[
                'AVGO taking 50% at $2.9',
                'TSLA taking 40% at $2.84',
            ]
        )

        self.register(
            name="angela_closed",
            description="Angela exit: CLOSED REST SYMBOL or SYMBOL closed",
            priority=72,
            pattern=r'(?:CLOSED\s+(?:REST\s+)?([A-Z]{1,5})|([A-Z]{1,5})\s+(?:clotto\s+)?closed)',
            parser=self._parse_angela_closed,
            examples=[
                'CLOSED REST TSLA',
                'SPX closed',
                'TSLA clotto closed',
            ]
        )

        self.register(
            name="angela_stop_hit",
            description="Angela stop: SYMBOL hit stop / SYMBOL stop hit",
            priority=72,
            pattern=r'([A-Z]{1,5})\s+(?:hit\s+stop|stop\s+hit)',
            parser=self._parse_angela_stop_hit,
            examples=[
                'TSLA hit stop',
                'TSLA stop hit. $448.40 support.',
            ]
        )

        # =====================================================================
        # ROCKY OPTIONS FORMAT (🚨 emoji)
        # =====================================================================

        self.register(
            name="rocky_flow_alert_reject",
            description="Rocky flow alert rejection: multi-line flow/sweep alerts",
            priority=5,
            pattern=r'(?:flow\s+(?:spotted|alert|sentiment)|massive\s+(?:bullish|bearish|call|put)\s+flow|call\s+buyer\s+(?:still\s+)?hold|sweep\s+activity|Put/Call\s+Ratio)',
            parser=self._parse_rocky_flow_reject,
            examples=[
                '$COIN massive bullish flow spotted',
                '$OKLO FLOW ALERT',
            ]
        )

        self.register(
            name="rocky_option_entry",
            description="Rocky options: 🚨 SYMBOL calls $STRIKE $PRICE EXPIRY expiry added",
            priority=17,
            pattern=r'🚨\s*([A-Z]{1,5})\s+(?:calls?|puts?)\s+\$?(\d+(?:\.\d+)?)\s+\$?(\d+(?:\.\d*)?)\s+(?:(\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s+expiry|(?:tomorrow|today|this\s+week|next\s+week)\s+expiry)\s+(?:added|aDDDED)',
            parser=self._parse_rocky_entry_std,
            examples=[
                '🚨 MU calls $850 $3.45 tomorrow expiry added only 3',
                '🚨 COIN calls $225 $2.45 this week expiry added here. Stop at $2',
                '🚨 NBIS calls $230 $2.88 5/15 expiry added SL 2.4',
                '🚨 TSLA calls $440 $2.  5/13 expiry added for swing. Stop at 1.6',
            ]
        )

        self.register(
            name="rocky_option_entry_strike_first",
            description="Rocky options: 🚨 SYMBOL $STRIKE calls $PRICE EXPIRY expiry added",
            priority=17,
            pattern=r'🚨\s*([A-Z]{1,5})\s+\$?(\d+(?:\.\d+)?)\s+(?:calls?|puts?)\s+\$?(\d+(?:\.\d*)?)\s+(?:(\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s+expiry|(?:tomorrow|today|this\s+week|next\s+week)\s+expiry)\s+(?:added|aDDDED)',
            parser=self._parse_rocky_entry_std,
            examples=[
                '🚨 MU $600 calls $3.35 this week expiry added 5 stop at 2.8',
            ]
        )

        self.register(
            name="rocky_option_entry_price_after",
            description="Rocky options: 🚨 SYMBOL calls $STRIKE EXPIRY expiry added at $PRICE",
            priority=17,
            pattern=r'🚨\s*([A-Z]{1,5})\s+(?:\$?(\d+(?:\.\d+)?)\s+)?(?:calls?|puts?)\s+(?:\$?(\d+(?:\.\d+)?)\s+)?(?:(\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s+expiry|(?:tomorrow|today|this\s+week|next\s+week)\s+expiry)\s+(?:added)\s+(?:\d+\s+)?(?:at\s+)?\$?(\d+(?:\.\d*)?)',
            parser=self._parse_rocky_entry_price_after,
            examples=[
                '🚨 BABA $150 calls 5/15 expiry added at $2.9 stop at $2.4',
                '🚨 AMZN calls $277.5 this week expiry added at $1.76 stop at $1.3',
            ]
        )

        self.register(
            name="rocky_trim",
            description="Rocky trim: taking 1/3rd/half/some at $PRICE",
            priority=73,
            pattern=r'([A-Z]{1,5})\s+(?:calls?\s+|puts?\s+|swings?\s+)?(?:at\s+\$?[\d.]+\s+|[\d.]+%[.]?\s+)?(?:heree?\s+)?(?:taking|took)\s+(1/3(?:rd)?|half|some|profits?)(?:\s+(?:at|here|out)?\s*\$?([\d.]+))?',
            parser=self._parse_rocky_trim,
            examples=[
                'COIN taking 1/3rd at $2.94',
                'QUBT calls at $1.05 heree taking 1/3rd',
                'NBIS took half at $4.60',
                'TSLA calls at $3.15 taking half. nice run',
            ]
        )

        # =====================================================================
        # INFRA TRADE / SMALL ACCOUNT FORMAT
        # =====================================================================

        # BTO: **SMALL ACCOUNT :** Bought SPX 6900C at 2.50( 5 Calls)
        # Also matches: **SMALL :** Bought ..., **SMALL ACCOUNT :** ,Other Bought ...
        self.register(
            name="infra_trade_buy",
            description="Infra Trade small account buy alert",
            priority=12,
            pattern=r'\*{0,2}SMALL(?:\s+ACCOUNT)?\s*(?::|\*{0,2}\s*:)\s*\*{0,2}\s*(?:,\s*\w+\s+)?(?:Bought\s+)?([A-Z]{1,5})\s+(\d+(?:\.\d+)?)([CPcp])\s+at\s*\.?\s*(\d*\.?\d+)',
            parser=self._parse_infra_trade_buy,
            examples=[
                "**SMALL ACCOUNT :** Bought MSFT 450C at 3.80 Exp: 06/18/2026( 2 Calls)",
                "**SMALL :** Bought SPX 6950C at 1.50( 5 Calls)",
                "**SMALL :** SPX 6860P at 2.10 ( 5 Puts)",
                "**SMALL ACCOUNT :** ,Other Bought NFLX 90C at 1.30 Exp: 03/20/2026 (10 Calls)",
            ]
        )

        # STC: @here Sold 3 GLD 450C at 3   /  Sold 5 NVDA 192.50C at 2.45
        # Matches: Sold [qty] SYMBOL STRIKEC/P at PRICE
        #          Sold [all/last] SYMBOL STRIKEC/P at PRICE
        self.register(
            name="infra_trade_sell",
            description="Infra Trade sell with symbol and strike",
            priority=13,
            pattern=r'[Ss]old\s+(?:(?:the\s+)?(?:last\s+)?)?(\d+|all)?\s*(?:more\s+)?([A-Z]{1,5})\s+(\d+(?:\.\d+)?)([CPcp])\s+(?:(?:runners?\s+)?at\s*\.?\s*(\d*\.?\d+))',
            parser=self._parse_infra_trade_sell,
            examples=[
                "@here Sold 3 GLD 450C at 3",
                "@here Sold 1 MSFT 450C at 4.80 Holding 1 call",
                "Sold 5 NVDA 192.50C at 2.45 ( Holding 5 )",
                "@here Sold last SPX 6810P at 2.80",
                "@here Sold all ASTS 100C at 4.40",
            ]
        )

        # STC: Sold SYMBOL at PRICE (no strike — close all matching)
        # e.g. "@here Sold all BABA at 4.20", "@here Sold all XPEV at 1.50"
        self.register(
            name="infra_trade_sell_symbol_only",
            description="Infra Trade sell by symbol only (no strike)",
            priority=72,
            pattern=r'[Ss]old\s+(?:(?:the\s+)?(?:last\s+)?)?(?:(?:all|\d+)\s+)?([A-Z]{1,5})\s+(?:calls?\s+|puts?\s+)?(?:at|around)\s+\.?\s*(\d*\.?\d+)',
            parser=self._parse_infra_trade_sell_symbol_only,
            examples=[
                "@here Sold all BABA at 4.20",
                "@here Sold all XPEV at 1.50",
                "@here Sold all XLF calls at 1.60",
                "@here Sold 3 PLTR calls around 3.55",
            ]
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

        # =====================================================================
        # ABTRADES FORMAT (bold-wrapped options entries, trims, exits)
        # =====================================================================
        from src.signals.abtrades_parser import (
            parse_abtrades_entry, parse_abtrades_trim, parse_abtrades_exit,
        )

        self.register(
            name="abtrades_entry",
            description="AbTrades bold option entry: **$SYMBOL MM/DD STRIKEc PRICE**",
            priority=82,
            pattern=r'\*\*\$([A-Z]{1,5})\s+(\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s+(\d+(?:\.\d+)?)([cpCP])\s+(\d*\.?\d+)(?:x(\d+))?\s*(?:\([^)]*\))?\s*\*\*',
            parser=parse_abtrades_entry,
            examples=[
                "**$MCHP 6/18 100c 3.65**",
                "**$OKLO 6/18 70c 1.85x10**",
                "**$MTCH 1/15/2027 40c 3.2**",
                "**$BAC 6/18 52.5c 1.06**",
            ],
        )

        self.register(
            name="abtrades_trim",
            description="AbTrades trim/profit update: $SYMBOL STRIKEc NN% (non-bold)",
            priority=83,
            pattern=r'(?<!\*)\$([A-Z]{1,5})\s+(\d+(?:\.\d+)?)([cpCP])\s+(\d+(?:\.\d+)?)%',
            parser=parse_abtrades_trim,
            examples=["$MSFT 450c 40%", "$IREN 50c 100%", "$OKLO 70c 150%"],
        )

        self.register(
            name="abtrades_exit",
            description="AbTrades full exit: ALL OUT / closing remaining (bidirectional)",
            priority=84,
            pattern=r'(?:(?:ALL\s+OUT|(?:I|i)(?:\'?m|m)\s+all\s+out|[Cc]losing\s+(?:the\s+)?(?:remaining|last\b[^$]*?\bon\b))[\s\S]{0,60}?\$([A-Z]{1,5})|\$([A-Z]{1,5})[^\n]{0,40}?(?:\n[^\n]{0,60}){0,2}?(?:all\s+out|(?:I|i)(?:\'?m|m)\s+all\s+out|closing\s+(?:the\s+)?remaining))',
            parser=parse_abtrades_exit,
            examples=[
                "ALL OUT: **$FROG**\n6/18 70c 100%",
                "Closing the remaining 5 $FSLR 9/18 280c for 500%",
                "$MRVL 110c 200%\nI'm all OUT.",
                "$GLW 150c all OUT for 550%",
                "$RGTI 20c: All out for 150%",
            ],
        )

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

        if symbol in self._COMMON_ENGLISH_WORDS:
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
    # JACOB PARSER IMPLEMENTATIONS
    # =========================================================================

    def _parse_jacob_exit(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Jacob exit: cutting SYMBOL, personally cutting SYMBOL"""
        groups = match.groups()
        symbol = None
        for g in groups:
            if g and g.upper() not in ('IT', 'MY', 'THE', 'AND', 'OUT', 'THIS', 'VERY', 'TOO', 'ALL', 'HALF', 'SOME'):
                symbol = g.upper()
                break

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
            "_jacob_exit": True
        }

    def _parse_jacob_trim_at_target(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Jacob trim at target: Sold 90% at First Target on FEED"""
        groups = match.groups()
        percentage = float(groups[0]) if groups[0] else 90.0
        symbol = groups[1].upper() if len(groups) > 1 and groups[1] else None

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
            "confidence": 0.9 if symbol else 0.7,
            "_jacob_trim": True,
            "_needs_position_context": symbol is None
        }

    def _parse_jacob_stoploss_update(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Jacob SL update: Moving Stoploss to 8.90"""
        groups = match.groups()
        price = float(groups[0]) if groups[0] else None

        if not price:
            return None

        return {
            "asset": "stock",
            "action": "SL_UPDATE",
            "qty": 0,
            "qty_specified": False,
            "symbol": None,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "price": None,
            "stop_loss": price,
            "is_market_order": False,
            "is_sl_update": True,
            "confidence": 0.8,
            "_jacob_sl_update": True,
            "_needs_position_context": True
        }

    # =========================================================================
    # BRONZE SWINGS PARSER IMPLEMENTATIONS
    # =========================================================================
    
    _BRONZE_BLOCKED_WORDS = frozenset({
        'LONG', 'SHORT', 'BUY', 'SELL', 'CALL', 'PUT', 'HOLD', 'EXIT',
        'STOP', 'TRIM', 'SOLD', 'ENTRY', 'AREA', 'FULL', 'HALF', 'ADD',
        'ADDED', 'CLOSE', 'CLOSED', 'NEW', 'NOW', 'TAKE', 'TOOK',
        'SWING', 'TRADE', 'WATCH', 'RISK', 'FREE', 'OVER', 'WITH',
        'FROM', 'INTO', 'DONE', 'BEEN', 'THIS', 'THAT', 'HAVE', 'JUST',
        'MORE', 'BACK', 'STILL', 'ALSO', 'WILL', 'ABOUT', 'ABOVE',
        'BELOW', 'HERE', 'AND', 'BUT', 'NOT', 'HIS', 'HER', 'ITS',
        'OUR', 'THE', 'WHEN', 'THEN', 'THAN', 'THEY', 'THEM', 'WHAT',
        'WHICH', 'WHERE', 'WHILE', 'WHO', 'HOW', 'WHY', 'WAS', 'WERE',
        'HAS', 'HAD', 'CAN', 'MAY', 'DID', 'DOES', 'COULD', 'WOULD',
        'SHALL', 'SHOULD', 'MIGHT', 'MUST', 'NEED', 'VERY', 'SOME',
        'MUCH', 'LIKE', 'ONLY', 'EVEN', 'MOST', 'ALSO', 'EACH',
        'EVERY', 'BOTH', 'SAME', 'OTHER', 'SUCH', 'THESE', 'THOSE',
        'AFTER', 'AGAIN', 'UNTIL', 'SINCE', 'ONCE', 'FIRST', 'LAST',
        'NEXT', 'GREAT', 'GOOD', 'LOOK', 'WANT', 'GIVE', 'GOING',
        'COME', 'CAME', 'MAKE', 'MADE', 'THINK', 'KNOW', 'SAID',
        'WENT', 'WELL', 'BEEN', 'YEAH', 'LETS', 'HUGE', 'NICE',
        'RUN', 'RUNS', 'SET', 'KEEP', 'KEPT', 'LEFT', 'MOVE',
        'WAIT', 'SIZE', 'GAIN', 'LOSS', 'LOTTO', 'PLAY', 'PLAYS',
        'ALERT', 'ALERTED', 'CALLS', 'PUTS', 'ENTER', 'STOCK',
        'SHARE', 'PRICE', 'TODAY', 'WEEK', 'MONTH', 'YEAR',
    })

    @classmethod
    def _is_valid_bronze_symbol(cls, symbol: str) -> bool:
        if not symbol or len(symbol) < 2:
            return False
        if symbol in cls._BRONZE_BLOCKED_WORDS:
            return False
        return True

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
        
        if not self._is_valid_bronze_symbol(symbol):
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
        
        if not self._is_valid_bronze_symbol(symbol):
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
        
        if not self._is_valid_bronze_symbol(symbol):
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
        
        if not self._is_valid_bronze_symbol(symbol):
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
    # TEMPLE ZZ SCALP/INLINE PARSER IMPLEMENTATIONS
    # =========================================================================

    def _parse_temple_zz_scalp_at(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse ZZ scalp: RECT scalping at 1.68 for 1.80...1.90..."""
        import re as _re
        symbol = match.group(1).upper()
        price = float(match.group(2))
        sl_match = _re.search(r'\bSL\s+\$?(\d+(?:\.\d+)?)', text, _re.IGNORECASE)
        stop_loss = float(sl_match.group(1)) if sl_match else None
        return {
            "asset": "stock", "action": "BTO", "qty": 1, "qty_specified": False,
            "symbol": symbol, "strike": None, "opt_type": None, "expiry": None,
            "price": price, "stop_loss": stop_loss,
            "is_market_order": False, "confidence": 0.85,
            "_bracket_order": bool(stop_loss), "_temple_entry": True,
        }

    def _parse_temple_zz_in_small(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse ZZ inline: $EDBL in small at 0.45 / Small $IPST 5.22"""
        groups = match.groups()
        symbol = (groups[0] or groups[2] or '').upper()
        price_str = groups[1] or groups[3]
        if not symbol or not price_str:
            return None
        price = float(price_str)
        import re as _re
        sl_match = _re.search(r'\bSL\s+\$?(\d+(?:\.\d+)?)', text, _re.IGNORECASE)
        stop_loss = float(sl_match.group(1)) if sl_match else None
        return {
            "asset": "stock", "action": "BTO", "qty": 1, "qty_specified": False,
            "symbol": symbol, "strike": None, "opt_type": None, "expiry": None,
            "price": price, "stop_loss": stop_loss,
            "is_market_order": False, "confidence": 0.85,
            "_bracket_order": bool(stop_loss), "_temple_entry": True,
        }

    def _parse_temple_zz_bird_inline(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse ZZ inline: $BIRD in $12.00 small for a <@&role> SL 11.80"""
        symbol = match.group(1).upper()
        price = float(match.group(2))
        import re as _re
        sl_match = _re.search(r'\bSL\s+\$?(\d+(?:\.\d+)?)', text, _re.IGNORECASE)
        stop_loss = float(sl_match.group(1)) if sl_match else None
        return {
            "asset": "stock", "action": "BTO", "qty": 1, "qty_specified": False,
            "symbol": symbol, "strike": None, "opt_type": None, "expiry": None,
            "price": price, "stop_loss": stop_loss,
            "is_market_order": False, "confidence": 0.85,
            "_bracket_order": bool(stop_loss), "_temple_entry": True,
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
            "trigger_price": price,
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
            "trigger_price": price,
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
    
    def _extract_targets_from_text(self, text: str) -> list:
        """Extract profit targets from text lines like 'first target 7.87' or 'targets 8.00 9.00'."""
        targets = []
        for line in text.split('\n'):
            m = re.search(r'(?:first\s+)?targets?\s+\$?([\d.]+(?:\s*[,/]\s*\$?[\d.]+)*)', line, re.IGNORECASE)
            if m:
                for p in re.split(r'[,/\s]+', m.group(1)):
                    p = p.strip().lstrip('$')
                    if p:
                        try:
                            targets.append(float(p))
                        except ValueError:
                            pass
        return targets

    def _parse_phoenix_over_conditional(self, match: re.Match, text: str) -> Optional[Dict]:
        result = self._parse_phoenix_entry(match, text)
        if not result:
            return None
        result['_conditional_order'] = True
        result['is_conditional'] = True
        result['trigger_type'] = 'over'
        targets = self._extract_targets_from_text(text)
        if targets:
            result['profit_targets'] = targets
        return result

    def _parse_phoenix_over_pct_sl_conditional(self, match: re.Match, text: str) -> Optional[Dict]:
        result = self._parse_phoenix_entry_over_pct_sl(match, text)
        if not result:
            return None
        result['_conditional_order'] = True
        result['is_conditional'] = True
        result['trigger_type'] = 'over'
        targets = self._extract_targets_from_text(text)
        if targets:
            result['profit_targets'] = targets
        return result

    def _parse_phoenix_over_no_sl_conditional(self, match: re.Match, text: str) -> Optional[Dict]:
        result = self._parse_phoenix_entry_no_sl(match, text)
        if not result:
            return None
        result['_conditional_order'] = True
        result['is_conditional'] = True
        result['trigger_type'] = 'over'
        targets = self._extract_targets_from_text(text)
        if targets:
            result['profit_targets'] = targets
        return result

    def _parse_phoenix_entry_no_sl(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix entry without SL: ENVB over 12.80"""
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
            "stop_loss": None,
            "is_market_order": False,
            "trigger_price": price,
            "confidence": 0.9,
            "_phoenix_entry": True
        }
    
    _PHOENIX_IN_AT_REJECT = frozenset({
        'AGAIN', 'AROUN', 'AROUND', 'THE', 'THIS', 'THAT', 'SOME', 'SMALL',
        'HERE', 'THERE', 'MORE', 'MOST', 'BACK', 'JUST', 'ALSO', 'BEEN',
        'WILL', 'HAVE', 'WITH', 'FROM', 'THEM', 'THEN', 'WHEN', 'WHAT',
        'FOR', 'BUT', 'NOT', 'ALL', 'CAN', 'HER', 'HIS', 'OUT', 'DAY',
    })

    def _parse_phoenix_entry_in_at(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix entry: in XHLD at 2.13"""
        import re as _re
        if _re.match(r'^\s*WL:', text, _re.IGNORECASE):
            return None
        groups = match.groups()
        symbol = groups[0].upper() if groups else None
        price = float(groups[1]) if len(groups) > 1 and groups[1] else None

        if not symbol:
            return None
        if symbol in self._PHOENIX_IN_AT_REJECT:
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
            "trigger_price": price,
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
    
    def _parse_phoenix_trim_with_sym(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix trim: selling 10% more AGRZ"""
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
    
    def _parse_phoenix_trim_no_sym(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix trim without symbol: selling 80% here, selling 80%"""
        groups = match.groups()
        percentage = float(groups[0]) if groups else None
        
        return {
            "asset": "stock",
            "action": "STC",
            "qty": 1,
            "qty_specified": False,
            "symbol": None,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "price": None,
            "is_market_order": True,
            "is_trim": True,
            "is_full_exit": False,
            "trim_percentage": percentage,
            "confidence": 0.7,
            "_phoenix_trim": True,
            "_needs_position_context": True
        }
    
    def _parse_phoenix_trim_fraction(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix trim with fraction: selling half here GITS"""
        groups = match.groups()
        fraction_word = groups[0].lower() if groups else None
        symbol = groups[1].upper() if len(groups) > 1 and groups[1] else None
        
        fraction_map = {"half": 50.0, "quarter": 25.0, "third": 33.0}
        percentage = fraction_map.get(fraction_word, 50.0)
        
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
    
    def _parse_phoenix_trimming(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix trimming: trimming GITS (implies 50% partial exit)"""
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
            "trim_percentage": 50.0,
            "confidence": 0.9,
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
    
    def _parse_phoenix_leaving_no_sym(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix leaving without symbol: leaving 5% now"""
        groups = match.groups()
        leaving_pct = float(groups[0]) if groups else None
        sell_pct = 100 - leaving_pct if leaving_pct else None
        
        return {
            "asset": "stock",
            "action": "STC",
            "qty": 1,
            "qty_specified": False,
            "symbol": None,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "price": None,
            "is_market_order": True,
            "is_trim": True,
            "is_full_exit": False,
            "trim_percentage": sell_pct,
            "leaving_percentage": leaving_pct,
            "confidence": 0.7,
            "_phoenix_trim": True,
            "_needs_position_context": True
        }
    
    def _parse_phoenix_sl_hit_with(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix SL hit with symbol: hit SL with MIGI, ENVB SL hit"""
        groups = match.groups()
        symbol = (groups[0] or groups[1]).upper() if groups else None
        
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
            "stop_loss_hit": True,
            "confidence": 1.0,
            "_phoenix_exit": True
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

        if symbol in self._COMMON_ENGLISH_WORDS:
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
    
    def _parse_phoenix_sl_to_entry(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix SL update: moving SL to entry (breakeven)"""
        groups = match.groups()
        symbol = groups[0].upper() if groups and groups[0] else None

        if symbol and symbol in self._COMMON_ENGLISH_WORDS:
            symbol = None

        result = {
            "asset": "stock",
            "action": "SL_UPDATE",
            "symbol": symbol,
            "sl_update_type": "breakeven",
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "confidence": 0.95,
            "_phoenix_sl_update": True,
            "_sl_to_entry": True,
        }
        if not symbol:
            result["_needs_position_context"] = True
        return result

    def _parse_phoenix_sl_move_price(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix SL update: moving SL for SYMBOL to PRICE"""
        groups = match.groups()
        symbol = groups[0].upper() if groups and groups[0] else None
        try:
            new_sl = float(groups[1]) if len(groups) > 1 and groups[1] else None
        except (ValueError, TypeError):
            new_sl = None

        if not symbol or not new_sl:
            return None

        return {
            "asset": "stock",
            "action": "SL_UPDATE",
            "symbol": symbol,
            "sl_update_type": "price",
            "new_stop_loss": new_sl,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "confidence": 0.95,
            "_phoenix_sl_update": True,
        }

    def _parse_phoenix_sl_move_price_to(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix SL update: moving SL to PRICE (for/with SYMBOL)"""
        groups = match.groups()
        try:
            new_sl = float(groups[0]) if groups and groups[0] else None
        except (ValueError, TypeError):
            new_sl = None

        symbol = None
        sym_patterns = [
            re.compile(r'(?:for|with)\s+(?:the\s+)?(?:remaining\s+)?(?:shares?\s+)?\$?([A-Z]{2,5})(?![a-z])', re.IGNORECASE),
        ]
        for sp in sym_patterns:
            for sym_match in sp.finditer(text):
                candidate = sym_match.group(1).upper()
                if candidate not in self._COMMON_ENGLISH_WORDS:
                    symbol = candidate
                    break
            if symbol:
                break

        if not new_sl:
            return None

        result = {
            "asset": "stock",
            "action": "SL_UPDATE",
            "symbol": symbol,
            "sl_update_type": "price",
            "new_stop_loss": new_sl,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "confidence": 0.95,
            "_phoenix_sl_update": True,
        }
        if not symbol:
            result["_needs_position_context"] = True
        return result

    def _parse_phoenix_sl_move_pct(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix SL update: moving SL to X%"""
        groups = match.groups()
        try:
            sl_pct = float(groups[0]) if groups and groups[0] else None
        except (ValueError, TypeError):
            sl_pct = None

        if not sl_pct:
            return None

        return {
            "asset": "stock",
            "action": "SL_UPDATE",
            "sl_update_type": "percent",
            "new_stop_loss_pct": sl_pct,
            "symbol": None,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "confidence": 0.90,
            "_phoenix_sl_update": True,
            "_needs_position_context": True,
        }

    def _parse_phoenix_target_update(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix target update: first/second target for SYMBOL PRICE-PRICE"""
        groups = match.groups()
        symbol = groups[0].upper() if groups and groups[0] else None
        try:
            target_low = float(groups[1]) if len(groups) > 1 and groups[1] else None
        except (ValueError, TypeError):
            target_low = None
        try:
            target_high = float(groups[2]) if len(groups) > 2 and groups[2] else None
        except (ValueError, TypeError):
            target_high = None

        if not symbol or not target_low:
            return None

        target_num_match = re.search(r'(first|second|third|next)', text, re.IGNORECASE)
        target_tier = {'first': 1, 'second': 2, 'third': 3, 'next': 2}.get(
            target_num_match.group(1).lower() if target_num_match else 'first', 1
        )

        return {
            "asset": "stock",
            "action": "TARGET_UPDATE",
            "symbol": symbol,
            "target_tier": target_tier,
            "target_price": target_high or target_low,
            "target_low": target_low,
            "target_high": target_high,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "confidence": 0.85,
            "_phoenix_target_update": True,
        }

    def _parse_phoenix_target_update_price_first(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix target update: first target PRICE-PRICE (for SYMBOL)"""
        groups = match.groups()
        try:
            target_low = float(groups[0]) if groups and groups[0] else None
        except (ValueError, TypeError):
            target_low = None
        try:
            target_high = float(groups[1]) if len(groups) > 1 and groups[1] else None
        except (ValueError, TypeError):
            target_high = None
        symbol = groups[2].upper() if len(groups) > 2 and groups[2] else None

        if not target_low:
            return None

        target_num_match = re.search(r'(first|second|third|next)', text, re.IGNORECASE)
        target_tier = {'first': 1, 'second': 2, 'third': 3, 'next': 2}.get(
            target_num_match.group(1).lower() if target_num_match else 'first', 1
        )

        result = {
            "asset": "stock",
            "action": "TARGET_UPDATE",
            "symbol": symbol,
            "target_tier": target_tier,
            "target_price": target_high or target_low,
            "target_low": target_low,
            "target_high": target_high,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "confidence": 0.85,
            "_phoenix_target_update": True,
        }
        if not symbol:
            result["_needs_position_context"] = True
        return result

    def _parse_phoenix_targets_generic(self, match: re.Match, text: str) -> Optional[Dict]:
        groups = match.groups()
        symbol = groups[0].upper() if groups[0] else None
        try:
            target_low = float(groups[1]) if groups[1] else None
        except (ValueError, TypeError):
            target_low = None
        try:
            target_high = float(groups[2]) if len(groups) > 2 and groups[2] else None
        except (ValueError, TypeError):
            target_high = None

        if not target_low:
            return None

        target_num_match = re.search(r'(first|second|third|next)', text, re.IGNORECASE)
        target_tier = {'first': 1, 'second': 2, 'third': 3, 'next': 2}.get(
            target_num_match.group(1).lower() if target_num_match else 'first', 1
        )

        result = {
            "asset": "stock",
            "action": "TARGET_UPDATE",
            "symbol": symbol,
            "target_tier": target_tier,
            "target_price": target_high or target_low,
            "target_low": target_low,
            "target_high": target_high,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "confidence": 0.85,
            "_phoenix_target_update": True,
        }
        if not symbol:
            result["_needs_position_context"] = True
        return result

    def _parse_phoenix_selling_full(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix full exit: selling SYMBOL (no percentage = 100%)"""
        groups = match.groups()
        symbol = None
        for g in groups:
            if g and re.match(r'^[A-Z]{1,5}$', g, re.IGNORECASE):
                symbol = g.upper()
                break

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
            "confidence": 0.90,
            "_phoenix_exit": True
        }

    def _parse_phoenix_trim_reversed(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix trim reversed: selling SYMBOL X%"""
        groups = match.groups()
        symbol = groups[0].upper() if groups and groups[0] else None
        try:
            percentage = float(groups[1]) if len(groups) > 1 and groups[1] else None
        except (ValueError, TypeError):
            percentage = None

        if not symbol or not percentage:
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
            "trim_percentage": percentage,
            "is_full_exit": percentage >= 100,
            "confidence": 0.95,
            "_phoenix_trim": True,
        }

    def _parse_phoenix_trim_another(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix trim: selling another X% (like 'more')"""
        groups = match.groups()
        try:
            percentage = float(groups[0]) if groups and groups[0] else None
        except (ValueError, TypeError):
            percentage = None
        symbol = groups[1].upper() if len(groups) > 1 and groups[1] else None

        if not percentage:
            return None

        result = {
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
            "trim_percentage": percentage,
            "is_full_exit": False,
            "confidence": 0.90,
            "_phoenix_trim": True,
        }
        if not symbol:
            result["_needs_position_context"] = True
        return result

    def _parse_phoenix_trim_nospace(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix trim with no space: selling 90%here"""
        groups = match.groups()
        try:
            percentage = float(groups[0]) if groups and groups[0] else None
        except (ValueError, TypeError):
            percentage = None
        symbol = groups[1].upper() if len(groups) > 1 and groups[1] else None

        if not percentage:
            return None

        result = {
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
            "trim_percentage": percentage,
            "is_full_exit": percentage >= 100,
            "confidence": 0.90,
            "_phoenix_trim": True,
        }
        if not symbol:
            result["_needs_position_context"] = True
        return result

    def _parse_phoenix_knifed(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix knifed exit: SYMBOL knifed / knifed with SYMBOL"""
        groups = match.groups()
        symbol = None
        for g in groups:
            if g and re.match(r'^[A-Z]{1,5}$', g, re.IGNORECASE):
                symbol = g.upper()
                break

        result = {
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
            "stop_loss_hit": True,
            "confidence": 0.80,
            "_phoenix_exit": True,
            "_phoenix_knifed": True,
        }
        if not symbol:
            result["_needs_position_context"] = True
        return result

    def _parse_phoenix_selling_at_price(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix selling at price: selling here at 1.98"""
        groups = match.groups()
        try:
            price = float(groups[0]) if groups and groups[0] else None
        except (ValueError, TypeError):
            price = None

        return {
            "asset": "stock",
            "action": "STC",
            "qty": 1,
            "qty_specified": False,
            "symbol": None,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "price": price,
            "is_market_order": False if price else True,
            "is_full_exit": True,
            "confidence": 0.85,
            "_phoenix_exit": True,
            "_needs_position_context": True,
        }

    def _parse_phoenix_adding(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse Phoenix adding to position: adding more SYMBOL shares"""
        groups = match.groups()
        symbol = None
        price = None
        for g in groups:
            if g and re.match(r'^[A-Z]{1,5}$', g, re.IGNORECASE):
                symbol = g.upper()
            elif g and re.match(r'^[\d.]+$', g):
                try:
                    price = float(g)
                except (ValueError, TypeError):
                    pass

        if not symbol:
            return None

        return {
            "asset": "stock",
            "action": "BTO",
            "symbol": symbol,
            "price": price,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "is_market_order": True if not price else False,
            "confidence": 0.80,
            "_phoenix_entry": True,
            "_phoenix_add_to_position": True,
        }

    _COMMON_ENGLISH_WORDS = frozenset({
        'HERE', 'MORE', 'AT', 'SHARES', 'SHARE', 'SMALL', 'SOME', 'INTO',
        'BACK', 'LONG', 'THIS', 'CALLS', 'PUTS', 'JUST', 'HEAVY', 'LIGHT',
        'TINY', 'HUGE', 'LARGE', 'FEW', 'THE', 'AND', 'BUT', 'FOR', 'WITH',
        'FROM', 'THAT', 'WILL', 'BEEN', 'HAVE', 'HAD', 'HAS', 'WAS', 'ARE',
        'NOT', 'ALL', 'CAN', 'HER', 'WAS', 'ONE', 'OUR', 'OUT', 'DAY', 'GET',
        'HIS', 'HOW', 'ITS', 'MAY', 'NEW', 'NOW', 'OLD', 'SEE', 'WAY', 'WHO',
        'DID', 'GOT', 'LET', 'SAY', 'SHE', 'TOO', 'USE', 'TO', 'MY', 'IN',
        'UP', 'SO', 'IF', 'DO', 'NO', 'GO', 'ME', 'HE', 'WE', 'BE',
        'STILL', 'ALSO', 'VERY', 'EVEN', 'MOST', 'MUCH', 'THEN', 'THEM',
        'THAN', 'EACH', 'MAKE', 'LIKE', 'OVER', 'SUCH', 'TAKE', 'ONLY',
        'COME', 'MADE', 'AFTER', 'YEAR', 'BEING', 'WHERE', 'ABOUT',
        'ENTRY', 'BREAK', 'STOP', 'HOLD', 'SELL', 'SOLD', 'TRIM',
        'SCALP', 'TRADE', 'WATCH', 'RISK', 'SLOW', 'FAST',
    })

    def _parse_phoenix_adding_v2(self, match: re.Match, text: str) -> Optional[Dict]:
        groups = match.groups()
        symbol = groups[0].upper() if groups[0] else None
        price = None
        try:
            price = float(groups[1]) if len(groups) > 1 and groups[1] else None
        except (ValueError, TypeError):
            pass

        if not symbol:
            return None

        if symbol in self._COMMON_ENGLISH_WORDS:
            return None

        return {
            "asset": "stock",
            "action": "BTO",
            "symbol": symbol,
            "price": price,
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "is_market_order": True if not price else False,
            "confidence": 0.80,
            "_phoenix_entry": True,
            "_phoenix_add_to_position": True,
        }

    def _extract_protrader_sl(self, text: str) -> Optional[float]:
        """Extract stop loss price from protrader text."""
        sl_match = re.search(r'SL\s+(?:below\s*:?\s*(?:below\s*)?)\$?([\d.]+)', text, re.IGNORECASE)
        if sl_match:
            try:
                return float(sl_match.group(1))
            except ValueError:
                pass
        return None

    def _extract_protrader_targets(self, text: str) -> list:
        """Extract profit targets from protrader text."""
        targets = []
        targ_match = re.search(r'Targs?\s*:?\s*(?:[A-Za-z\s]+[-–—]\s*)?([\d.,\s\-–—+]+)', text, re.IGNORECASE)
        if targ_match:
            raw = targ_match.group(1)
            for val in re.findall(r'([\d.]+)', raw):
                try:
                    targets.append(float(val))
                except ValueError:
                    pass
        if not targets:
            move_match = re.search(r'for\s+a\s+move\s+to\s+([\d.,\s\-–—+]+)', text, re.IGNORECASE)
            if move_match:
                raw = move_match.group(1)
                for val in re.findall(r'([\d.]+)', raw):
                    try:
                        targets.append(float(val))
                    except ValueError:
                        pass
        return targets

    def _extract_protrader_shares(self, text: str) -> Optional[int]:
        """Extract share size from protrader text."""
        share_match = re.search(r'(?:share\s+size\s*:\s*|[Bb]uying\s+(?:total\s+)?)(\d+)\s+[Ss]hares?', text)
        if share_match:
            try:
                return int(share_match.group(1))
            except ValueError:
                pass
        qty_match = re.search(r'(\d+)\s+[Ss]hares?\s+(?:for|in|total)', text)
        if qty_match:
            try:
                return int(qty_match.group(1))
            except ValueError:
                pass
        return None

    def _protrader_result(self, symbol: str, entry_high: float, entry_low: Optional[float],
                          stop_loss: Optional[float], targets: list, shares: Optional[int],
                          is_breakout: bool = False) -> Dict:
        """Build a conditional order result dict for protrader signals."""
        if is_breakout:
            trigger_price = entry_high
            trigger_type = 'over'
        else:
            trigger_price = entry_low if entry_low else entry_high
            trigger_type = 'over'

        result = {
            'format': 'PROTRADER',
            'is_conditional': True,
            '_conditional_order': True,
            '_protrader': True,
            'asset': 'stock',
            'asset_type': 'stock',
            'action': 'BTO',
            'ticker': symbol,
            'symbol': symbol,
            'trigger_type': trigger_type,
            'trigger_price': trigger_price,
            'entry_high': entry_high,
            'entry_low': entry_low,
            'stop_loss_type': 'fixed' if stop_loss else None,
            'stop_loss_value': stop_loss,
            'stop_loss_fixed': stop_loss,
            'stop_loss_pct': None,
            'profit_targets': targets,
            'target_ranges': [],
            'position_size_pct': None,
            'fixed_qty': shares,
            'size_mode': 'fixed_qty' if shares else None,
            'qty': shares or 1,
            'qty_specified': shares is not None,
            'price': entry_high,
            'confidence': 1.0,
        }
        return result

    def _parse_protrader_structured(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse structured protrader: Ticker: VCIG / Entey range: 15.50-15.25 / SL / Targs"""
        symbol = match.group(1).upper()
        entry_text = match.group(2).strip()

        is_breakout = False
        entry_high = None
        entry_low = None

        breakout_match = re.search(r'(?:[Bb](?:uy(?:ing)?\s+)?)?[Bb]reak\s+(?:of\s+)?([\d.]+)', entry_text)
        if not breakout_match:
            breakout_match = re.match(r'([\d.]+)\s+break\b', entry_text)
        if breakout_match:
            entry_high = float(breakout_match.group(1))
            is_breakout = True
        else:
            prices = re.findall(r'([\d.]+)', entry_text)
            if len(prices) >= 2:
                p1, p2 = float(prices[0]), float(prices[1])
                entry_high = max(p1, p2)
                entry_low = min(p1, p2)
            elif len(prices) == 1:
                entry_high = float(prices[0])

        if not entry_high:
            return None

        stop_loss = self._extract_protrader_sl(text)
        targets = self._extract_protrader_targets(text)
        shares = self._extract_protrader_shares(text)

        return self._protrader_result(symbol, entry_high, entry_low, stop_loss, targets, shares, is_breakout)

    def _parse_protrader_inline(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse inline protrader: RIME - Buying 3.37-3.20- SL below 3.10- Targs : 3.50-3.60"""
        text_upper = text.upper()
        has_sl = 'SL' in text_upper and 'BELOW' in text_upper
        has_targs = bool(re.search(r'TARGS?\s*:', text_upper))
        if not has_sl and not has_targs:
            return None

        symbol = match.group(1).upper()
        p1 = float(match.group(2))
        p2 = float(match.group(3))
        entry_high = max(p1, p2)
        entry_low = min(p1, p2)

        stop_loss = self._extract_protrader_sl(text)
        targets = self._extract_protrader_targets(text)
        shares = self._extract_protrader_shares(text)

        return self._protrader_result(symbol, entry_high, entry_low, stop_loss, targets, shares)

    def _parse_protrader_breakout(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse breakout protrader: AEHL - Buying break of 1.04 for a move to 1.10-1.15"""
        symbol = match.group(1).upper()
        breakout_price = float(match.group(2))
        targets_raw = match.group(3)

        targets = []
        for val in re.findall(r'([\d.]+)', targets_raw):
            try:
                targets.append(float(val))
            except ValueError:
                pass

        extended_targets = self._extract_protrader_targets(text)
        if len(extended_targets) > len(targets):
            targets = extended_targets

        stop_loss = self._extract_protrader_sl(text)
        shares = self._extract_protrader_shares(text)

        return self._protrader_result(symbol, breakout_price, None, stop_loss, targets, shares, is_breakout=True)

    def _parse_protrader_cancel(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse protrader cancel: Cancel the AZI alert"""
        symbol = match.group(1).upper()
        return {
            'format': 'PROTRADER',
            'asset': 'stock',
            'asset_type': 'stock',
            'action': 'CANCEL',
            'symbol': symbol,
            'ticker': symbol,
            '_protrader': True,
            '_protrader_cancel': True,
            'confidence': 1.0,
        }

    _COMMON_WORDS = frozenset({
        'THE', 'THIS', 'THAT', 'AND', 'FOR', 'BUT', 'NOT', 'ALL', 'ARE', 'WAS',
        'HAS', 'HAD', 'HIT', 'RAN', 'GOT', 'CAN', 'MAY', 'OUT', 'OUR', 'ITS',
        'HIS', 'HER', 'WHO', 'HOW', 'NOW', 'NEW', 'OLD', 'BIG', 'LOW', 'HIGH',
        'RUN', 'SET', 'GET', 'LET', 'PUT', 'SAY', 'SEE', 'TRY', 'USE', 'WAY',
        'DAY', 'MAN', 'ONE', 'TWO', 'FEW', 'ANY', 'TEAM', 'HOLD', 'SOLD',
        'WENT', 'BOOM', 'BANG', 'NICE', 'TAKE', 'GIVE', 'TOLD', 'GUYS',
        'FROM', 'WITH', 'JUST', 'ALSO', 'BEEN', 'HAVE', 'WILL', 'SOME',
        'THEM', 'THEN', 'THAN', 'WHAT', 'WHEN', 'YOUR', 'MORE', 'MUCH',
        'VERY', 'ONLY', 'OVER', 'SUCH', 'MAKE', 'LIKE', 'LONG', 'LOOK',
        'MANY', 'COME', 'COULD', 'WOULD', 'SHOULD', 'ABOUT',
    })

    def _is_valid_ticker(self, sym: str) -> bool:
        """Check if a string looks like a valid stock ticker, not a common word."""
        if not sym or not sym.isalpha():
            return False
        return sym.upper() not in self._COMMON_WORDS

    def _parse_protrader_cancel_v2(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse all protrader cancel variations."""
        symbol = None
        for g in match.groups():
            if g and self._is_valid_ticker(g):
                symbol = g.upper()
                break
        if not symbol:
            sym_match = re.search(r'(?:^|\n)\s*\$?([A-Z]{1,5})', text)
            if sym_match and self._is_valid_ticker(sym_match.group(1)):
                symbol = sym_match.group(1).upper()
        if not symbol:
            return None
        return {
            'format': 'PROTRADER',
            'asset': 'stock',
            'asset_type': 'stock',
            'action': 'CANCEL',
            'symbol': symbol,
            'ticker': symbol,
            '_protrader': True,
            '_protrader_cancel': True,
            'confidence': 1.0,
        }

    _EXIT_REJECT_KEYWORDS = re.compile(r'\b(?:[Bb]uying\b|[Bb]uy\s+(?:at|near|around|above|below)|[Bb]reak\s+of|[Bb]reakout|[Aa]lert\s+at|[Ee]ntering)\b')

    def _parse_protrader_exit(self, match: re.Match, text: str) -> Optional[Dict]:
        """Parse protrader exit signals: sold all, scale out, take profits."""
        symbol = match.group(1).upper()
        if not self._is_valid_ticker(symbol):
            return None
        if self._EXIT_REJECT_KEYWORDS.search(text):
            return None
        text_lower = text.lower()
        if 'sold all' in text_lower:
            exit_action = 'STC'
            exit_pct = 100
        elif 'scale out' in text_lower:
            exit_action = 'STC'
            exit_pct = 50
        elif 'take profits' in text_lower or 'secure profits' in text_lower or 'secure gains' in text_lower or 'do secure' in text_lower:
            exit_action = 'STC'
            exit_pct = 50
        elif 'we are out' in text_lower:
            exit_action = 'STC'
            exit_pct = 100
        else:
            return None
        return {
            'format': 'PROTRADER',
            'asset': 'stock',
            'asset_type': 'stock',
            'action': exit_action,
            'symbol': symbol,
            'ticker': symbol,
            'sell_pct': exit_pct,
            '_protrader': True,
            '_protrader_exit': True,
            'is_market_order': True,
            'confidence': 0.9,
        }

    def _extract_quick_swing_sl(self, text: str) -> Optional[float]:
        sl_match = re.search(r'Stop\s+loss\s*:\s*(?:Below\s+)?\$?([\d.]+)', text, re.IGNORECASE)
        if sl_match:
            try:
                return float(sl_match.group(1))
            except ValueError:
                pass
        return self._extract_protrader_sl(text)

    def _extract_quick_swing_targets(self, text: str) -> list:
        targets = []
        targ_match = re.search(r'Target\s*:\s*\(?([\d.,\s\-+]+)', text, re.IGNORECASE)
        if targ_match:
            raw = targ_match.group(1)
            for val in re.findall(r'([\d.]+)', raw):
                try:
                    targets.append(float(val))
                except ValueError:
                    pass
        if not targets:
            targets = self._extract_protrader_targets(text)
        return targets

    def _extract_quick_swing_shares(self, text: str) -> Optional[int]:
        share_match = re.search(r'[Bb]uy\s+(\d+)\s+shares?\s+total', text)
        if share_match:
            try:
                return int(share_match.group(1))
            except ValueError:
                pass
        size_match = re.search(r'[-–]?\s*(\d+)\s+shares?', text, re.IGNORECASE)
        if size_match:
            try:
                return int(size_match.group(1))
            except ValueError:
                pass
        return self._extract_protrader_shares(text)

    def _parse_quick_swing_entry(self, match: re.Match, text: str) -> Optional[Dict]:
        symbol = match.group(1).upper()
        entry_text = match.group(2).strip()

        cleaned_entry = re.sub(r'\b(\d+)\s+shares?\b', '', entry_text, flags=re.IGNORECASE)
        cleaned_entry = re.sub(r'\b(?:Add|half|another|full|size)\b', '', cleaned_entry, flags=re.IGNORECASE)
        prices = re.findall(r'(\d+\.?\d*)', cleaned_entry)
        if not prices:
            return None
        float_prices = []
        for p in prices:
            try:
                v = float(p)
                if v > 0.001:
                    float_prices.append(v)
            except ValueError:
                pass
        if not float_prices:
            return None
        if len(float_prices) > 1:
            median = sorted(float_prices)[len(float_prices) // 2]
            actual_prices = [p for p in float_prices if 0.1 * median <= p <= 10 * median]
        else:
            actual_prices = float_prices
        if not actual_prices:
            return None

        entry_high = max(actual_prices)
        entry_low = min(actual_prices) if len(actual_prices) > 1 else None

        stop_loss = self._extract_quick_swing_sl(text)
        targets = self._extract_quick_swing_targets(text)
        shares = self._extract_quick_swing_shares(text)

        trigger_price = entry_low if entry_low else entry_high
        result = {
            'format': 'QUICK_SWING',
            'is_conditional': True,
            '_conditional_order': True,
            '_quick_swing': True,
            'asset': 'stock',
            'asset_type': 'stock',
            'action': 'BTO',
            'ticker': symbol,
            'symbol': symbol,
            'trigger_type': 'over',
            'trigger_price': trigger_price,
            'entry_high': entry_high,
            'entry_low': entry_low,
            'stop_loss_type': 'fixed' if stop_loss else None,
            'stop_loss_value': stop_loss,
            'stop_loss_fixed': stop_loss,
            'stop_loss_pct': None,
            'profit_targets': targets,
            'target_ranges': [],
            'position_size_pct': None,
            'fixed_qty': shares,
            'size_mode': 'fixed_qty' if shares else None,
            'qty': shares or 1,
            'qty_specified': shares is not None,
            'price': entry_high,
            'confidence': 1.0,
        }
        return result

    def _parse_quick_swing_cancel(self, match: re.Match, text: str) -> Optional[Dict]:
        symbol = match.group(1).upper()
        if not self._is_valid_ticker(symbol):
            return None
        return {
            'format': 'QUICK_SWING',
            'action': 'CANCEL',
            'symbol': symbol,
            'ticker': symbol,
            '_quick_swing': True,
            '_protrader_cancel': True,
            'confidence': 1.0,
        }

    def _parse_quick_swing_exit(self, match: re.Match, text: str) -> Optional[Dict]:
        symbol = match.group(1).upper()
        if not self._is_valid_ticker(symbol):
            return None
        if self._EXIT_REJECT_KEYWORDS.search(text):
            return None
        text_lower = text.lower()
        if 'sold all' in text_lower or 'out of' in text_lower or 'we are out' in text_lower:
            exit_pct = 100
        elif 'scale out' in text_lower or 'take profits' in text_lower:
            exit_pct = 50
        else:
            exit_pct = 100
        return {
            'format': 'QUICK_SWING',
            'asset': 'stock',
            'asset_type': 'stock',
            'action': 'STC',
            'symbol': symbol,
            'ticker': symbol,
            'sell_pct': exit_pct,
            '_quick_swing': True,
            '_protrader_exit': True,
            'is_market_order': True,
            'confidence': 0.9,
        }

    # =========================================================================
    # ASHLEY / ANGELA / ROCKY PARSER IMPLEMENTATIONS
    # =========================================================================

    def _resolve_relative_expiry(self, expiry_text: str) -> str:
        from datetime import timedelta
        now = datetime.now()
        lower = expiry_text.lower().strip()
        if '0dte' in lower or 'today' in lower:
            return now.strftime("%m/%d")
        if 'tomorrow' in lower:
            return (now + timedelta(days=1)).strftime("%m/%d")
        if 'next week' in lower:
            days_to_monday = (7 - now.weekday()) % 7
            if days_to_monday == 0:
                days_to_monday = 7
            friday = now + timedelta(days=days_to_monday + 4)
            return friday.strftime("%m/%d")
        if 'this week' in lower:
            days_to_friday = (4 - now.weekday()) % 7
            if days_to_friday == 0:
                days_to_friday = 0
            friday = now + timedelta(days=days_to_friday)
            return friday.strftime("%m/%d")
        return expiry_text

    def _extract_stop_loss(self, text: str) -> float:
        m = re.search(r'(?:STOP\s+LOSS\s+AT|stop\s+at|SL|Stop)\s+\$?([\d.]+)', text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
        return None

    def _parse_ashley_entry(self, match: re.Match, text: str) -> Optional[Dict]:
        symbol, strike, opt_type_raw, expiry_raw, price = match.groups()
        opt_type = 'C' if 'CALL' in opt_type_raw.upper() else 'P'
        expiry = self._resolve_relative_expiry(expiry_raw)
        if '/' not in expiry:
            expiry = expiry_raw
        stop_loss = self._extract_stop_loss(text)
        try:
            price_f = float(price)
        except ValueError:
            return None
        return {
            "asset": "option",
            "action": "BTO",
            "qty": 1,
            "qty_specified": False,
            "symbol": symbol.upper(),
            "strike": float(strike),
            "opt_type": opt_type,
            "expiry": expiry,
            "price": price_f,
            "is_market_order": False,
            "stop_loss": stop_loss,
            "_ashley_format": True,
        }

    def _parse_ashley_trim(self, match: re.Match, text: str) -> Optional[Dict]:
        symbol, price, pct = match.groups()
        trim_pct = None
        if pct:
            try:
                trim_pct = int(pct.replace('%', ''))
            except ValueError:
                pass
        text_upper = text.upper()
        if 'MOST' in text_upper:
            trim_pct = trim_pct or 80
        elif 'LITTLE' in text_upper:
            trim_pct = trim_pct or 25
        elif 'PARTIAL' in text_upper:
            trim_pct = trim_pct or 50
        else:
            trim_pct = trim_pct or 50
        return {
            "asset": "option",
            "action": "STC",
            "symbol": symbol.upper() if symbol else None,
            "sell_pct": trim_pct,
            "trim_price": float(price) if price else None,
            "is_market_order": price is None,
            "_ashley_trim": True,
            "_tracking_only": symbol is None,
        }

    def _parse_ashley_all_out(self, match: re.Match, text: str) -> Optional[Dict]:
        symbol = match.group(1) or match.group(2) if match.lastindex and match.lastindex >= 2 else match.group(1)
        return {
            "asset": "option",
            "action": "STC",
            "symbol": symbol.upper() if symbol else None,
            "sell_pct": 100,
            "is_market_order": True,
            "_ashley_exit": True,
            "_tracking_only": symbol is None,
        }

    def _parse_angela_entry(self, match: re.Match, text: str) -> Optional[Dict]:
        symbol, strike, price, expiry = match.groups()
        text_lower = text.lower()
        opt_type = 'P' if 'put' in text_lower else 'C'
        stop_loss = self._extract_stop_loss(text)
        try:
            price_f = float(price)
        except ValueError:
            return None
        return {
            "asset": "option",
            "action": "BTO",
            "qty": 1,
            "qty_specified": False,
            "symbol": symbol.upper(),
            "strike": float(strike),
            "opt_type": opt_type,
            "expiry": expiry,
            "price": price_f,
            "is_market_order": False,
            "stop_loss": stop_loss,
            "_angela_format": True,
        }

    def _parse_angela_trim(self, match: re.Match, text: str) -> Optional[Dict]:
        symbol, pct = match.group(1), match.group(2)
        trim_pct = int(pct) if pct else 50
        price_m = re.search(r'at\s+\$?([\d.]+)', text, re.IGNORECASE)
        trim_price = None
        if price_m:
            price_str = price_m.group(1).rstrip('.')
            try:
                trim_price = float(price_str)
            except ValueError:
                pass
        return {
            "asset": "option",
            "action": "STC",
            "symbol": symbol.upper(),
            "sell_pct": trim_pct,
            "trim_price": trim_price,
            "is_market_order": trim_price is None,
            "_angela_trim": True,
        }

    def _parse_angela_closed(self, match: re.Match, text: str) -> Optional[Dict]:
        symbol = match.group(1) or match.group(2)
        if not symbol:
            return None
        return {
            "asset": "option",
            "action": "STC",
            "symbol": symbol.upper(),
            "sell_pct": 100,
            "is_market_order": True,
            "_angela_exit": True,
        }

    def _parse_angela_stop_hit(self, match: re.Match, text: str) -> Optional[Dict]:
        symbol = match.group(1)
        return {
            "asset": "option",
            "action": "STC",
            "symbol": symbol.upper(),
            "sell_pct": 100,
            "is_market_order": True,
            "_angela_stop": True,
        }

    def _parse_rocky_flow_reject(self, match: re.Match, text: str) -> Optional[Dict]:
        return {
            "asset": "option",
            "action": "SKIP",
            "symbol": None,
            "_flow_alert": True,
            "_tracking_only": True,
        }

    def _parse_rocky_entry_std(self, match: re.Match, text: str) -> Optional[Dict]:
        symbol, strike, price_raw, date_expiry = match.groups()
        text_lower = text.lower()
        opt_type = 'P' if 'put' in text_lower else 'C'
        price_clean = price_raw.rstrip('.')
        actual_price = float(price_clean) if price_clean else 0

        if date_expiry:
            expiry = date_expiry
        else:
            expiry_m = re.search(r'(tomorrow|today|this\s+week|next\s+week)\s+expiry', text, re.IGNORECASE)
            expiry = self._resolve_relative_expiry(expiry_m.group(1)) if expiry_m else datetime.now().strftime("%m/%d")

        stop_loss = self._extract_stop_loss(text)
        return {
            "asset": "option",
            "action": "BTO",
            "qty": 1,
            "qty_specified": False,
            "symbol": symbol.upper(),
            "strike": float(strike),
            "opt_type": opt_type,
            "expiry": expiry,
            "price": actual_price,
            "is_market_order": False,
            "stop_loss": stop_loss,
            "_rocky_format": True,
        }

    def _parse_rocky_entry_price_after(self, match: re.Match, text: str) -> Optional[Dict]:
        symbol = match.group(1)
        num_before_calls = match.group(2)
        num_after_calls = match.group(3)
        date_expiry = match.group(4)
        price_raw = match.group(5)

        strike = float(num_before_calls or num_after_calls or '0')
        price_clean = price_raw.rstrip('.') if price_raw else '0'
        actual_price = float(price_clean)

        text_lower = text.lower()
        opt_type = 'P' if 'put' in text_lower else 'C'

        if date_expiry:
            expiry = date_expiry
        else:
            expiry_m = re.search(r'(tomorrow|today|this\s+week|next\s+week)\s+expiry', text, re.IGNORECASE)
            expiry = self._resolve_relative_expiry(expiry_m.group(1)) if expiry_m else datetime.now().strftime("%m/%d")

        stop_loss = self._extract_stop_loss(text)
        return {
            "asset": "option",
            "action": "BTO",
            "qty": 1,
            "qty_specified": False,
            "symbol": symbol.upper(),
            "strike": strike,
            "opt_type": opt_type,
            "expiry": expiry,
            "price": actual_price,
            "is_market_order": False,
            "stop_loss": stop_loss,
            "_rocky_format": True,
        }

    def _parse_rocky_trim(self, match: re.Match, text: str) -> Optional[Dict]:
        symbol, fraction, price = match.groups()
        fraction_lower = fraction.lower()
        if '1/3' in fraction_lower:
            trim_pct = 33
        elif 'half' in fraction_lower:
            trim_pct = 50
        elif 'profit' in fraction_lower:
            trim_pct = 50
        else:
            trim_pct = 50
        return {
            "asset": "option",
            "action": "STC",
            "symbol": symbol.upper(),
            "sell_pct": trim_pct,
            "trim_price": float(price) if price else None,
            "is_market_order": price is None,
            "_rocky_trim": True,
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
                upper_g = g_stripped.upper()
                _RESERVED_WORDS = {'HERE', 'MORE', 'NOW', 'ON', 'THE', 'MY', 'OF', 'WITH', 'ALL', 'HALF', 'REST', 'SOME', 'AREA', 'HEREWI'}
                if not symbol and upper_g not in _RESERVED_WORDS:
                    symbol = upper_g
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

    # =========================================================================
    # INFRA TRADE / SMALL ACCOUNT PARSER IMPLEMENTATIONS
    # =========================================================================

    def _parse_infra_trade_buy(self, match: re.Match, text: str) -> Optional[Dict]:
        symbol, strike, opt_type, price = match.groups()

        if not symbol or not strike or not price:
            return None

        qty = 1
        qty_specified = False
        qty_match = re.search(r'\(\s*(?:Total[:\s\-]*)?(\d+)\s*(?:Calls?|Puts?)\s*\)', text, re.IGNORECASE)
        if qty_match:
            qty = int(qty_match.group(1))
            qty_specified = True

        expiry = None
        exp_match = re.search(r'Exp[;:\s]+\s*(\d{1,2})/(\d{1,2})/(\d{4})', text)
        if exp_match:
            expiry = f"{exp_match.group(1)}/{exp_match.group(2)}/{exp_match.group(3)}"
        else:
            from datetime import datetime
            today = datetime.now()
            expiry = f"{today.month:02d}/{today.day:02d}/{today.year}"

        return {
            "asset": "option",
            "action": "BTO",
            "qty": qty,
            "qty_specified": qty_specified,
            "symbol": symbol.upper(),
            "strike": float(strike),
            "opt_type": opt_type.upper(),
            "expiry": expiry,
            "price": float(price),
            "is_market_order": False,
            "_infra_trade_buy": True
        }

    def _parse_infra_trade_sell(self, match: re.Match, text: str) -> Optional[Dict]:
        qty_str, symbol, strike, opt_type, price_str = match.groups()

        if not symbol or not strike:
            return None

        qty = 1
        qty_specified = False
        is_full_exit = False
        if qty_str:
            if qty_str.lower() == 'all':
                is_full_exit = True
                qty_specified = False
            else:
                qty = int(qty_str)
                qty_specified = True

        price = float(price_str) if price_str else None

        return {
            "asset": "option",
            "action": "STC",
            "qty": qty,
            "qty_specified": qty_specified,
            "symbol": symbol.upper(),
            "strike": float(strike),
            "opt_type": opt_type.upper(),
            "expiry": None,
            "price": price,
            "is_market_order": price is None,
            "is_full_exit": is_full_exit,
            "_infra_trade_sell": True
        }

    def _parse_infra_trade_sell_symbol_only(self, match: re.Match, text: str) -> Optional[Dict]:
        symbol, price_str = match.groups()

        if not symbol:
            return None

        if symbol in self._COMMON_ENGLISH_WORDS:
            return None

        price = float(price_str) if price_str else None

        is_full_exit = bool(re.search(r'\ball\b', text, re.IGNORECASE))

        return {
            "asset": "option",
            "action": "STC",
            "qty": 1,
            "qty_specified": False,
            "symbol": symbol.upper(),
            "strike": None,
            "opt_type": None,
            "expiry": None,
            "price": price,
            "is_market_order": price is None,
            "is_full_exit": is_full_exit,
            "_infra_trade_sell_symbol_only": True
        }

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


def parse_all_with_registry(text: str) -> List[Dict[str, Any]]:
    """Parse text for ALL signals (handles multi-plan messages).

    Returns list of parsed signal dicts (may be empty).
    """
    return get_signal_format_registry().parse_all(text)
