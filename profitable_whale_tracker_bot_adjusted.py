#!/usr/bin/env python3
"""
Whale 17 Position Tracker V2 - RAILWAY VERSION (FIXED NOTIFICATIONS)
- Double-checks position closes before sending notifications
- Bold formatting for token/direction
- Whale name as clickable link, no preview cards
- Better price handling
"""

import asyncio
import json
import requests
from datetime import datetime, timedelta, timezone
import os
import logging
from collections import defaultdict

# RAILWAY ENVIRONMENT VARIABLES
# These will be set in Railway's dashboard
WHALE_ADDRESS = os.environ.get('WHALE_ADDRESS', '')
WHALE_NAME = os.environ.get('WHALE_NAME', 'Whale Trader')
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

# Validate configuration
if not WHALE_ADDRESS:
    print("❌ ERROR: WHALE_ADDRESS environment variable not set!")
    print("Please set it in Railway's Variables section")
    exit(1)

if not TELEGRAM_TOKEN:
    print("❌ ERROR: TELEGRAM_TOKEN environment variable not set!")
    print("Please set it in Railway's Variables section")
    exit(1)

if not TELEGRAM_CHAT_ID:
    print("❌ ERROR: TELEGRAM_CHAT_ID environment variable not set!")
    print("Please set it in Railway's Variables section")
    exit(1)

# Force files to be saved in the same directory as this script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Windows-safe logging
log_file = os.path.join(SCRIPT_DIR, 'whale_tracker.log')
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class WhaleTracker:
    """
    Whale Position Tracker V2 - Railway Version (FIXED NOTIFICATIONS)
    """
    def __init__(self):
        # Use environment variables from Railway
        self.whale_address = WHALE_ADDRESS
        self.whale_name = WHALE_NAME
        
        # Position value thresholds (can also be env vars if you want)
        self.MIN_POSITION_VALUE = int(os.environ.get('MIN_POSITION_VALUE', '100000'))  # Default $100K
        self.PARTIAL_CHANGE_THRESHOLD = float(os.environ.get('PARTIAL_CHANGE_THRESHOLD', '0.15'))  # Default 15%
        
        # VERIFICATION SETTINGS
        self.POSITION_CLOSE_VERIFY_ATTEMPTS = 3  # Number of times to check before confirming close
        self.POSITION_CLOSE_VERIFY_DELAY = 5  # Seconds between verification attempts
        
        # Load config
        self.load_config()
        
        # Tracking
        self.seen_trades = set()
        self.positions = {}
        self.btc_price = 0
        self.running = False
        
        # Fill aggregation tracking
        self.pending_fills = defaultdict(list)
        self.fill_timers = {}
        
        # Track positions pending close verification
        self.pending_close_verification = {}  # {coin: {'attempts': 0, 'first_detected': timestamp}}
        
        # Load saved positions
        self.load_positions()
        
        print("WHALE POSITION TRACKER V2 - RAILWAY VERSION (FIXED NOTIFICATIONS)")
        print(f"Tracking: {self.whale_name}")
        print(f"Address: {self.whale_address[:8]}...{self.whale_address[-6:]}")  # Show partial address
        print(f"Min position: ${self.MIN_POSITION_VALUE:,}")
        print(f"Partial change threshold: {self.PARTIAL_CHANGE_THRESHOLD*100:.0f}%")
        print(f"Close verification: {self.POSITION_CLOSE_VERIFY_ATTEMPTS} attempts")
        print(f"Environment: Railway")
        
        # Test Telegram
        self.test_telegram()
        print()
    
    def test_telegram(self):
        """Test Telegram connection"""
        try:
            coinglass_url = f"https://www.coinglass.com/hyperliquid/{self.whale_address}"
            self.send_telegram_message(
                f"🚀 <b>Whale Position Tracker V2 Started!</b>\n"
                f"📊 Real-time position alerts enabled\n"
                f"🎯 Tracking opens, closes, and partial changes ({self.PARTIAL_CHANGE_THRESHOLD*100:.0f}%+)\n"
                f"💰 Minimum position: ${self.MIN_POSITION_VALUE:,}\n"
                f"🔧 Position verification enabled (double-check closes)\n"
                f"☁️ Running on Railway\n\n"
                f"🐋 <b>Tracking:</b> <a href='{coinglass_url}'>{self.whale_name}</a>"
            )
            print("✅ Telegram connection successful!")
            return True
        except Exception as e:
            print(f"❌ Telegram error: {e}")
            return False
    
    async def test_api_connection(self):
        """Test API connection"""
        print("Testing Hyperliquid API connection...")
        try:
            url = "https://api.hyperliquid.xyz/info"
            payload = {"type": "meta"}
            headers = {
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            
            if response.status_code == 200:
                print("✅ API connection successful!")
                return True
            else:
                print(f"⚠️  API returned status {response.status_code}")
                if response.status_code == 502:
                    print("   This usually means Hyperliquid is under maintenance")
                return False
        except Exception as e:
            print(f"❌ API connection failed: {e}")
            return False
    
    def load_positions(self):
        """Load saved positions from file"""
        positions_file = os.path.join(SCRIPT_DIR, 'whale_positions.json')
        if os.path.exists(positions_file):
            try:
                with open(positions_file, 'r') as f:
                    self.positions = json.load(f)
                if self.positions:
                    print(f"Loaded {len(self.positions)} saved positions")
                    for coin, pos in self.positions.items():
                        print(f"  {coin}: ${pos['value']:,.0f} ({pos['side']})")
            except Exception as e:
                print(f"Error loading positions: {e}")
                self.positions = {}
    
    def save_positions(self):
        """Save current positions to file"""
        positions_file = os.path.join(SCRIPT_DIR, 'whale_positions.json')
        try:
            with open(positions_file, 'w') as f:
                json.dump(self.positions, f, indent=2)
        except Exception as e:
            print(f"Error saving positions: {e}")
    
    def get_asset_price(self, coin):
        """Get current price for an asset"""
        url = "https://api.hyperliquid.xyz/info"
        payload = {"type": "allMids"}
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=5)
            if response.status_code == 200:
                prices = response.json()
                price = float(prices.get(coin, 0))
                if price > 0:
                    return price
        except:
            pass
        
        # Return a default or last known price if API fails
        return 0
    
    def send_telegram_message(self, message):
        """Send text message to Telegram"""
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            data = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True  # Changed to disable link previews
            }
            response = requests.post(url, data=data)
            if not response.ok:
                print(f"Telegram message error: {response.text}")
        except Exception as e:
            print(f"Telegram message error: {e}")
    
    def load_config(self):
        self.config = {
            "check_interval_seconds": float(os.environ.get('CHECK_INTERVAL', '2.0')),
            "max_trade_age_seconds": int(os.environ.get('MAX_TRADE_AGE', '300')),
            "whale_address": self.whale_address,
            "fill_aggregation_window": int(os.environ.get('FILL_AGGREGATION_WINDOW', '30'))
        }
        
        config_file = os.path.join(SCRIPT_DIR, 'whale_tracker_config.json')
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    loaded = json.load(f)
                    self.config.update(loaded)
                print("Config loaded from file")
            except Exception as e:
                print(f"Config error: {e}")
        
        # Save config
        try:
            with open(config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
            print(f"Config saved to: {config_file}")
        except Exception as e:
            print(f"Config save error: {e}")
    
    async def get_whale_trades(self):
        try:
            url = "https://api.hyperliquid.xyz/info"
            payload = {"type": "userFills", "user": self.whale_address}
            
            headers = {
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            
            if response.status_code == 200:
                return response.json()[:100]
            else:
                logger.error(f"API Error: {response.status_code} - {response.text[:100]}")
                return []
                
        except requests.exceptions.Timeout:
            logger.error("API Timeout - Hyperliquid may be slow")
            return []
        except requests.exceptions.ConnectionError:
            logger.error("Connection Error - Check internet or API status")
            return []
        except Exception as e:
            logger.error(f"API Error: {e}")
            return []
    
    async def get_whale_positions(self):
        """Get current positions from clearinghouse state"""
        try:
            url = "https://api.hyperliquid.xyz/info"
            payload = {"type": "clearinghouseState", "user": self.whale_address}
            headers = {
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                positions = {}
                
                asset_positions = data.get('assetPositions', [])
                for asset_position in asset_positions:
                    position = asset_position.get('position', {})
                    if position:
                        coin = position.get('coin', '')
                        size = float(position.get('szi', 0))
                        if size != 0:
                            entry_px = float(position.get('entryPx', 0))
                            mark_px = float(position.get('markPx', entry_px)) if 'markPx' in position else entry_px
                            
                            # Use mark price if available, otherwise use entry price
                            current_price = mark_px if mark_px > 0 else entry_px
                            
                            positions[coin] = {
                                'size': abs(size),
                                'side': 'LONG' if size > 0 else 'SHORT',
                                'value': abs(size * current_price),
                                'avg_price': entry_px,
                                'current_price': current_price
                            }
                
                return positions
            return {}
        except Exception as e:
            print(f"Error getting whale positions: {e}")
            return {}
    
    async def verify_position_closed(self, coin):
        """Verify if a position is actually closed with multiple checks"""
        print(f"\n🔍 Verifying if {coin} position is actually closed...")
        
        for attempt in range(self.POSITION_CLOSE_VERIFY_ATTEMPTS):
            print(f"   Verification attempt {attempt + 1}/{self.POSITION_CLOSE_VERIFY_ATTEMPTS}...")
            
            # Wait before checking (except first attempt)
            if attempt > 0:
                await asyncio.sleep(self.POSITION_CLOSE_VERIFY_DELAY)
            
            current_positions = await self.get_whale_positions()
            
            # If we get empty positions, it might be API issue
            if not current_positions and attempt < self.POSITION_CLOSE_VERIFY_ATTEMPTS - 1:
                print(f"   ⚠️ API returned no positions, might be temporary issue")
                continue
            
            # Check if position exists
            if coin in current_positions:
                position = current_positions[coin]
                print(f"   ✅ Position still exists: {coin} {position['side']} ${position['value']:,.0f}")
                return False  # Position NOT closed
        
        # After all attempts, position is confirmed closed
        print(f"   ✅ Confirmed: {coin} position is CLOSED")
        return True  # Position IS closed
    
    async def verify_all_positions(self):
        """Verify all tracked positions still exist on exchange"""
        print("🔍 Verifying all tracked positions...")
        positions_closed = 0
        
        if not self.positions:
            return 0
            
        current_positions = await self.get_whale_positions()
        
        # If API returns empty, don't assume everything is closed
        if not current_positions:
            print("   ⚠️ API returned no positions - skipping verification")
            return 0
        
        coins_to_verify_close = []
        for coin, tracked_pos in self.positions.items():
            if coin not in current_positions:
                coins_to_verify_close.append(coin)
        
        # Verify each potential close
        for coin in coins_to_verify_close:
            tracked_pos = self.positions[coin]
            
            # Double-check if position is really closed
            is_closed = await self.verify_position_closed(coin)
            
            if is_closed:
                print(f"\n🚨 CONFIRMED CLOSED POSITION: {coin}")
                print(f"   Was tracking: ${tracked_pos['value']:,.0f}")
                
                self.btc_price = await self.get_btc_price()
                current_price = self.get_asset_price(coin)
                if current_price == 0:
                    current_price = tracked_pos.get('current_price', tracked_pos.get('avg_price', 0))
                
                self.send_close_alert(
                    coin, 
                    tracked_pos['side'], 
                    tracked_pos['value'], 
                    current_price,
                    tracked_pos.get('avg_price')
                )
                
                del self.positions[coin]
                positions_closed += 1
            else:
                print(f"   ℹ️ {coin} position still exists (false close avoided)")
        
        if positions_closed > 0:
            print(f"✅ Confirmed {positions_closed} closed positions")
            self.save_positions()
        
        return positions_closed
    
    async def get_btc_price(self):
        """Get current BTC price"""
        try:
            url = "https://api.hyperliquid.xyz/info"
            payload = {"type": "meta"}
            
            headers = {
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                universe = data.get('universe', [])
                for asset in universe:
                    if asset.get('name') == 'BTC':
                        asset_ctx = data.get('assetCtxs', [])
                        for ctx in asset_ctx:
                            if ctx.get('coin') == 'BTC':
                                mark_px = float(ctx.get('markPx', 0))
                                if mark_px > 0:
                                    self.btc_price = mark_px
                                    return mark_px
            
            payload = {"type": "allMids"}
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code == 200:
                mids = response.json()
                if 'BTC' in mids:
                    price = float(mids['BTC'])
                    if price > 0:
                        self.btc_price = price
                        return price
            
            return self.btc_price or 100000
        except:
            return self.btc_price or 100000
    
    def get_position_emoji_and_tier(self, coin, value):
        """Get emoji and tier based on coin and value"""
        if coin in ['BTC', 'ETH']:
            if value >= 50_000_000:
                return "🚀🚀🚀🚀", "50M+"
            elif value >= 10_000_000:
                return "🚨🚨🚨", "10M+"
            elif value >= 1_000_000:
                return "👽👽", "1M+"
            elif value >= 100_000:
                return "🟡", "100K+"
        else:
            if value >= 100_000:
                return "🤡🤡", "100K+"
        
        return "", ""
    
    def format_value(self, value):
        """Format value for display"""
        if value >= 1_000_000:
            return f"${value/1_000_000:.1f}M"
        elif value >= 1_000:
            return f"${value/1_000:.0f}K"
        else:
            return f"${value:.0f}"
    
    def format_price(self, price):
        """Format price for display"""
        if price == 0:
            return "N/A"
        elif price >= 1000:
            return f"${price:,.0f}"
        elif price >= 1:
            return f"${price:,.2f}"
        elif price >= 0.01:
            return f"${price:.4f}"
        else:
            return f"${price:.8f}"
    
    async def process_aggregated_fills(self, coin, side):
        """Process and send alert for aggregated fills"""
        await asyncio.sleep(self.config['fill_aggregation_window'])
        
        key = (coin, side)
        fills = self.pending_fills.get(key, [])
        
        if not fills:
            return
        
        total_size = sum(float(fill['sz']) for fill in fills)
        avg_price = sum(float(fill['px']) * float(fill['sz']) for fill in fills) / total_size
        num_fills = len(fills)
        
        position_value = avg_price * total_size
        
        self.btc_price = await self.get_btc_price()
        
        current_positions = await self.get_whale_positions()
        
        if coin not in self.positions:
            self.positions[coin] = {'size': 0, 'value': 0, 'side': '', 'max_value': 0, 'avg_price': 0, 'current_price': 0}
        
        prev_size = self.positions[coin]['size']
        prev_value = self.positions[coin]['value']
        prev_side = self.positions[coin].get('side', '')
        
        has_position_on_exchange = coin in current_positions
        
        if prev_size == 0 and has_position_on_exchange:
            actual_position = current_positions[coin]
            actual_side = actual_position['side']
            
            if position_value >= self.MIN_POSITION_VALUE:
                alert_type = 'OPEN'
                self.positions[coin] = {
                    'size': actual_position['size'],
                    'value': actual_position['value'],
                    'side': actual_side,
                    'max_value': actual_position['value'],
                    'avg_price': actual_position.get('avg_price', avg_price),
                    'current_price': actual_position.get('current_price', avg_price)
                }
            else:
                del self.pending_fills[key]
                del self.fill_timers[key]
                return
                
        elif prev_size > 0 and not has_position_on_exchange:
            # Verify the close before sending alert
            is_closed = await self.verify_position_closed(coin)
            
            if is_closed and prev_value >= self.MIN_POSITION_VALUE:
                alert_type = 'CLOSE'
                closed_value = prev_value
                del self.positions[coin]
            else:
                # Position still exists or below threshold
                del self.pending_fills[key]
                del self.fill_timers[key]
                return
                
        elif prev_size > 0 and has_position_on_exchange:
            actual_position = current_positions[coin]
            new_size = actual_position['size']
            new_value = actual_position['value']
            
            if new_size > prev_size:
                change_pct = ((new_size - prev_size) / prev_size)
                if change_pct >= self.PARTIAL_CHANGE_THRESHOLD:
                    alert_type = 'PARTIAL_INCREASE'
                    self.positions[coin].update({
                        'size': new_size,
                        'value': new_value,
                        'avg_price': actual_position.get('avg_price', avg_price),
                        'current_price': actual_position.get('current_price', avg_price),
                        'max_value': max(new_value, self.positions[coin]['max_value'])
                    })
                else:
                    self.positions[coin].update({
                        'size': new_size,
                        'value': new_value,
                        'avg_price': actual_position.get('avg_price', avg_price),
                        'current_price': actual_position.get('current_price', avg_price)
                    })
                    del self.pending_fills[key]
                    del self.fill_timers[key]
                    return
            else:
                reduction_pct = ((prev_size - new_size) / prev_size)
                if reduction_pct >= self.PARTIAL_CHANGE_THRESHOLD:
                    alert_type = 'PARTIAL_CLOSE'
                    self.positions[coin].update({
                        'size': new_size,
                        'value': new_value,
                        'current_price': actual_position.get('current_price', avg_price)
                    })
                else:
                    self.positions[coin].update({
                        'size': new_size,
                        'value': new_value,
                        'current_price': actual_position.get('current_price', avg_price)
                    })
                    del self.pending_fills[key]
                    del self.fill_timers[key]
                    return
        else:
            del self.pending_fills[key]
            del self.fill_timers[key]
            return
        
        print(f"\n📊 Aggregated {num_fills} fills: {coin}")
        print(f"   Position value: ${position_value:,.0f}")
        if coin in self.positions:
            print(f"   Current total: ${self.positions[coin]['value']:,.0f}")
            print(f"   Position side: {self.positions[coin]['side']}")
        
        if 'alert_type' in locals():
            if alert_type == 'OPEN':
                self.send_open_alert(coin, self.positions[coin]['side'], 
                                   self.positions[coin]['value'], avg_price)
            elif alert_type == 'CLOSE':
                self.send_close_alert(coin, prev_side, closed_value, avg_price)
            elif alert_type == 'PARTIAL_INCREASE':
                increase_pct = ((new_size - prev_size) / prev_size)
                self.send_partial_increase_alert(coin, self.positions[coin]['side'], 
                                               prev_value, self.positions[coin]['value'], 
                                               increase_pct, avg_price)
            elif alert_type == 'PARTIAL_CLOSE':
                self.send_partial_close_alert(coin, self.positions[coin]['side'], 
                                            prev_value, self.positions[coin]['value'], 
                                            reduction_pct, avg_price)
            
            self.save_positions()
        
        del self.pending_fills[key]
        if key in self.fill_timers:
            del self.fill_timers[key]
    
    def send_open_alert(self, coin, side, value, price):
        """Send OPEN position alert with whale name as clickable link"""
        emoji, tier = self.get_position_emoji_and_tier(coin, value)
        coinglass_url = f"https://www.coinglass.com/hyperliquid/{self.whale_address}"
        
        # Escape any special HTML characters in whale name
        import html
        escaped_whale_name = html.escape(self.whale_name)
        
        message = f"""{emoji} OPEN POSITION <b>{coin} {side}</b>: {tier} {emoji}
📈 Action: <b>OPEN {coin} {side}</b>
🐋 Whale: {self.whale_address[:6]}...
📝 <a href='{coinglass_url}'>{escaped_whale_name}</a>
💵 Value: {self.format_value(value)}
💰 Price: {self.format_price(price)}
₿ BTC: ${self.btc_price:,.0f}"""
        
        self.send_telegram_message(message)
        print(f"\n{emoji} OPEN: {coin} {side} - {self.format_value(value)} @ {self.format_price(price)}")
    
    def send_close_alert(self, coin, side, value, price, entry_price=None):
        """Send CLOSE position alert with whale name as clickable link"""
        emoji, tier = self.get_position_emoji_and_tier(coin, value)
        coinglass_url = f"https://www.coinglass.com/hyperliquid/{self.whale_address}"
        
        # Escape any special HTML characters in whale name
        import html
        escaped_whale_name = html.escape(self.whale_name)
        
        if entry_price is None and coin in self.positions:
            entry_price = self.positions[coin].get('avg_price', 0)
        
        entry_price_text = f"\n📥 Entry Price: {self.format_price(entry_price)}" if entry_price and entry_price > 0 else ""
        
        message = f"""{emoji} CLOSE POSITION <b>{coin} {side}</b>: {tier} {emoji}
📉 Action: <b>CLOSE {coin} {side}</b>
🐋 Whale: {self.whale_address[:6]}...
📝 <a href='{coinglass_url}'>{escaped_whale_name}</a>
💵 Closed: {self.format_value(value)}{entry_price_text}
💰 Exit Price: {self.format_price(price)}
₿ BTC: ${self.btc_price:,.0f}"""
        
        self.send_telegram_message(message)
        print(f"\n{emoji} CLOSE: {coin} {side} - {self.format_value(value)} @ {self.format_price(price)}")
    
    def send_partial_close_alert(self, coin, side, prev_value, curr_value, reduction_pct, price):
        """Send PARTIAL CLOSE alert with whale name as clickable link"""
        max_value = self.positions[coin].get('max_value', prev_value)
        emoji, tier = self.get_position_emoji_and_tier(coin, max_value)
        coinglass_url = f"https://www.coinglass.com/hyperliquid/{self.whale_address}"
        
        # Escape any special HTML characters in whale name
        import html
        escaped_whale_name = html.escape(self.whale_name)
        
        entry_price = self.positions[coin].get('avg_price', 0)
        entry_price_text = f"\n📥 Entry Price: {self.format_price(entry_price)}" if entry_price and entry_price > 0 else ""
        
        message = f"""{emoji} PARTIAL CLOSE {reduction_pct*100:.1f}% (<b>{coin} {side}</b> {tier}) {emoji}
📉 Scaling Out: <b>{coin} {side}</b>
🐋 Whale: {self.whale_address[:6]}...
📝 <a href='{coinglass_url}'>{escaped_whale_name}</a>
📊 Previous: {self.format_value(prev_value)}
📊 Current: {self.format_value(curr_value)}
📉 Reduced: {reduction_pct*100:.1f}%{entry_price_text}
💰 Current Price: {self.format_price(price)}
₿ BTC: ${self.btc_price:,.0f}"""
        
        self.send_telegram_message(message)
        print(f"\n{emoji} PARTIAL CLOSE: {coin} {side} - Reduced {reduction_pct*100:.1f}% @ {self.format_price(price)}")
    
    def send_partial_increase_alert(self, coin, side, prev_value, curr_value, increase_pct, price):
        """Send PARTIAL INCREASE alert with whale name as clickable link"""
        max_value = self.positions[coin].get('max_value', curr_value)
        emoji, tier = self.get_position_emoji_and_tier(coin, max_value)
        coinglass_url = f"https://www.coinglass.com/hyperliquid/{self.whale_address}"
        
        # Escape any special HTML characters in whale name
        import html
        escaped_whale_name = html.escape(self.whale_name)
        
        message = f"""{emoji} PARTIAL INCREASE {increase_pct*100:.1f}% (<b>{coin} {side}</b> {tier}) {emoji}
📈 Adding to Position: <b>{coin} {side}</b>
🐋 Whale: {self.whale_address[:6]}...
📝 <a href='{coinglass_url}'>{escaped_whale_name}</a>
📊 Previous: {self.format_value(prev_value)}
📊 Current: {self.format_value(curr_value)}
📈 Increased: {increase_pct*100:.1f}%
💰 Price: {self.format_price(price)}
₿ BTC: ${self.btc_price:,.0f}"""
        
        self.send_telegram_message(message)
        print(f"\n{emoji} PARTIAL INCREASE: {coin} {side} - Increased {increase_pct*100:.1f}% @ {self.format_price(price)}")
    
    async def queue_fill_for_aggregation(self, trade):
        """Queue a fill for aggregation"""
        coin = trade.get('coin', '')
        side = trade.get('side', '')
        size = float(trade.get('sz', 0))
        price = float(trade.get('px', 0))
        value = size * price
        
        if value < 10000:
            return
        
        key = (coin, side)
        
        self.pending_fills[key].append(trade)
        
        if key in self.fill_timers:
            try:
                self.fill_timers[key].cancel()
            except:
                pass
        
        self.fill_timers[key] = asyncio.create_task(
            self.process_aggregated_fills(coin, side)
        )
    
    def show_stats(self):
        """Show current positions"""
        if not self.positions:
            print("\nNo open positions (double-check verification active)")
            return
        
        print(f"\nCURRENT POSITIONS:")
        total_value = 0
        for coin, pos in self.positions.items():
            print(f"  {coin} {pos['side']}: {self.format_value(pos['value'])}")
            total_value += pos['value']
        print(f"  Total: {self.format_value(total_value)}")
        print("\n✅ Position verification active (double-check closes)")
        print()
    
    async def monitor_loop(self):
        print("Starting whale monitoring...")
        print(f"Checking every {self.config['check_interval_seconds']} seconds")
        print(f"Min position value: ${self.MIN_POSITION_VALUE:,}")
        print(f"Partial change threshold: {self.PARTIAL_CHANGE_THRESHOLD*100}%")
        print(f"Fill aggregation window: {self.config['fill_aggregation_window']} seconds")
        print(f"Position verification: Every 30 seconds (double-check closes)")
        print()
        
        cycle = 0
        error_count = 0
        last_position_check = datetime.now()
        
        while self.running:
            try:
                cycle += 1
                
                if (datetime.now() - last_position_check).total_seconds() > 30:
                    await self.verify_all_positions()
                    last_position_check = datetime.now()
                
                trades = await self.get_whale_trades()
                
                if not trades:
                    if error_count == 0:
                        print("⚠️  API not responding - this is normal during maintenance")
                    error_count += 1
                    
                    wait_time = min(self.config['check_interval_seconds'] * (2 ** min(error_count, 5)), 60)
                    await asyncio.sleep(wait_time)
                    continue
                
                if error_count > 0:
                    print("✅ API connection restored!")
                    error_count = 0
                
                new_trades = 0
                queued_trades = 0
                
                for trade in trades:
                    trade_id = trade.get('tid', '')
                    
                    if trade_id in self.seen_trades:
                        continue
                    
                    new_trades += 1
                    self.seen_trades.add(trade_id)
                    
                    trade_time = datetime.fromtimestamp(trade.get('time', 0) / 1000)
                    age_seconds = (datetime.now() - trade_time).total_seconds()
                    
                    if age_seconds > self.config['max_trade_age_seconds']:
                        continue
                    
                    coin = trade.get('coin', '')
                    side = trade.get('side', '')
                    size = float(trade.get('sz', 0))
                    price = float(trade.get('px', 0))
                    value = size * price
                    
                    if value >= 10000:
                        side_text = "BUY" if side == 'B' else "SELL"
                        if cycle % 5 == 0 or value >= 100000:
                            print(f"  Trade: {coin} {side_text} ${value:,.0f} @ {self.format_price(price)} (age: {age_seconds:.0f}s)")
                    
                    if value >= 10000:
                        await self.queue_fill_for_aggregation(trade)
                        queued_trades += 1
                
                if queued_trades > 0 or new_trades > 0:
                    if queued_trades > 0:
                        print(f"\nQUEUED: {queued_trades} fills from {new_trades} new trades")
                    else:
                        print(f"\nMONITORING: {new_trades} new trades (all below thresholds)")
                
                if cycle % 10 == 0 and self.positions:
                    total_value = sum(pos['value'] for pos in self.positions.values())
                    print(f"POSITIONS: {len(self.positions)} open, total ${total_value:,.0f}")
                    print(f"✅ Position verification active (double-check closes)")
                
                if cycle % 50 == 0:
                    self.show_stats()
                    if self.pending_fills:
                        print("PENDING FILLS:")
                        for (coin, side), fills in self.pending_fills.items():
                            side_text = "BUY" if side == 'B' else "SELL"
                            total_value = sum(float(f['sz']) * float(f['px']) for f in fills)
                            print(f"  {coin} {side_text}: {len(fills)} fills, ${total_value:,.0f}")
                        print()
                
                if len(self.seen_trades) > 1000:
                    self.seen_trades = set(list(self.seen_trades)[-500:])
                
                await asyncio.sleep(self.config['check_interval_seconds'])
                
            except KeyboardInterrupt:
                print("\nSTOPPED by user")
                break
            except Exception as e:
                print(f"ERROR: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(self.config['check_interval_seconds'] * 2)
    
    async def sync_positions_on_startup(self):
        """Sync positions with whale's current positions on startup"""
        print("\nSyncing with whale's current positions...")
        try:
            current_positions = await self.get_whale_positions()
            
            if not current_positions:
                print("No positions found on exchange (API might be down)")
                # Don't clear positions if API is down
                return
            
            positions_found = 0
            for coin, position_data in current_positions.items():
                if position_data['value'] >= self.MIN_POSITION_VALUE:
                    self.positions[coin] = {
                        'size': position_data['size'],
                        'value': position_data['value'],
                        'side': position_data['side'],
                        'max_value': position_data['value'],
                        'avg_price': position_data['avg_price'],
                        'current_price': position_data.get('current_price', position_data['avg_price'])
                    }
                    print(f"  Found position: {coin} {position_data['side']} ${position_data['value']:,.0f}")
                    positions_found += 1
            
            if positions_found > 0:
                self.save_positions()
                print(f"Synced {positions_found} positions")
            else:
                print("No significant positions found (>$100K)")
                
        except Exception as e:
            print(f"Error syncing positions: {e}")
            import traceback
            traceback.print_exc()
    
    async def start(self):
        print(f"\nSTARTING WHALE POSITION TRACKER V2 (FIXED NOTIFICATIONS)")
        print("=" * 50)
        
        api_ok = await self.test_api_connection()
        if not api_ok:
            print("\n⚠️  WARNING: API is not responding. This often happens during:")
            print("   - Hyperliquid maintenance windows")
            print("   - High traffic periods")
            print("   - Network issues")
            print("\n   The bot will keep trying to connect...")
            print()
        else:
            await self.sync_positions_on_startup()
        
        print("\nCONFIGURATION:")
        print(f"  Whale: {self.whale_name}")
        print(f"  Address: {self.whale_address[:8]}...{self.whale_address[-6:]}")
        print(f"  Check interval: {self.config['check_interval_seconds']}s")
        print(f"  Max trade age: {self.config['max_trade_age_seconds']}s")
        print(f"  Min position: ${self.MIN_POSITION_VALUE:,}")
        print(f"  Partial change: {self.PARTIAL_CHANGE_THRESHOLD*100}%")
        print(f"  Fill aggregation: {self.config['fill_aggregation_window']}s window")
        print(f"  Close verification: {self.POSITION_CLOSE_VERIFY_ATTEMPTS} attempts")
        print(f"  Environment: Railway")
        print()
        
        print("ALERT THRESHOLDS:")
        print("  BTC/ETH:")
        print("    🚀🚀🚀🚀 $50M+")
        print("    🚨🚨🚨 $10M-$49.99M")
        print("    👽👽 $1M-$9.99M")
        print("    🟡 $100K-$999K")
        print("  Other tokens:")
        print("    🤡🤡 $100K+")
        print()
        
        print("Running on Railway...")
        print()
        
        self.running = True
        
        try:
            await self.monitor_loop()
        finally:
            self.running = False
            self.show_stats()
            self.save_positions()
            
            if self.positions:
                total_value = sum(pos['value'] for pos in self.positions.values())
                coinglass_url = f"https://www.coinglass.com/hyperliquid/{self.whale_address}"
                self.send_telegram_message(
                    f"🛑 <b>Whale Tracker V2 Stopped</b>\n"
                    f"📊 Open positions: {len(self.positions)}\n"
                    f"💰 Total value: {self.format_value(total_value)}\n"
                    f"🐋 <a href='{coinglass_url}'>{self.whale_name}</a>"
                )

def main():
    print("WHALE POSITION TRACKER V2 - RAILWAY (FIXED NOTIFICATIONS)")
    print("=" * 50)
    print("Features:")
    print("• Real-time position tracking")
    print("• Alerts for opens, closes, and partial changes")
    print("• Double-check verification for closes")
    print("• Clean notifications with clickable whale name")
    print("• No link preview cards")
    print("• Telegram notifications")
    print("• Running on Railway")
    print("=" * 50)
    print()
    
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    if now.hour in [4, 5]:
        print("⚠️  NOTE: Hyperliquid often has maintenance around 4-5 AM UTC")
        print("   If you're getting 502 errors, this might be why.")
        print()
    
    tracker = WhaleTracker()
    asyncio.run(tracker.start())

if __name__ == "__main__":
    main()