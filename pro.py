import ccxt
import time
from telegram import Bot
from flask import Flask
import threading

# --- CONFIGURATION ---
TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
CHAT_ID = "YOUR_TELEGRAM_CHAT_ID"
EXCHANGE = ccxt.bybit({
    'apiKey': 'YOUR_BYBIT_API_KEY',
    'secret': 'YOUR_BYBIT_SECRET_KEY',
})
RISK_REWARD_RATIO = 3  # 1:3 RR
TRAILING_STOP_PERCENT = 1.0  # Adjust as needed

bot = Bot(token=TELEGRAM_TOKEN)
app = Flask(__name__)

# --- FETCH MARKET DATA ---
def get_candles(symbol, timeframe='30m', limit=100):
    return EXCHANGE.fetch_ohlcv(symbol, timeframe, limit=limit)

# --- SUPPLY & DEMAND ZONES ---
def find_zones(candles):
    supply_zones, demand_zones = [], []
    for i in range(2, len(candles)-2):
        high, low, close = candles[i][2], candles[i][3], candles[i][4]
        prev_high, prev_low = candles[i-1][2], candles[i-1][3]
        
        if low < prev_low and close > (candles[i-2][4] + candles[i+1][4]) / 2:
            demand_zones.append((low, close))
        if high > prev_high and close < (candles[i-2][4] + candles[i+1][4]) / 2:
            supply_zones.append((high, close))
    return supply_zones, demand_zones

# --- INDUCEMENT DETECTION ---
def detect_inducement(candles, zones):
    for zone in zones:
        zone_price = zone[0]
        for i in range(len(candles)-1):
            wick_high, wick_low = candles[i][2], candles[i][3]
            
            if wick_low < zone_price < candles[i+1][4]:
                return "Demand Inducement Detected"
            if wick_high > zone_price > candles[i+1][4]:
                return "Supply Inducement Detected"
    return None

# --- TRADE EXECUTION ---
def place_trade(symbol, side, entry, stop_loss):
    risk = abs(entry - stop_loss)
    take_profit = entry + (risk * RISK_REWARD_RATIO) if side == "buy" else entry - (risk * RISK_REWARD_RATIO)
    
    order = EXCHANGE.create_order(symbol, 'market', side, 1)
    EXCHANGE.create_order(symbol, 'stop', side="sell" if side=="buy" else "buy", amount=1, price=stop_loss)
    EXCHANGE.create_order(symbol, 'limit', side="sell" if side=="buy" else "buy", amount=1, price=take_profit)
    
    bot.send_message(CHAT_ID, f"Trade Placed: {side.upper()} @ {entry}, SL: {stop_loss}, TP: {take_profit}")
    return entry, stop_loss

# --- TRAILING STOP ---
def update_trailing_stop(symbol, entry, stop_loss, side):
    current_price = EXCHANGE.fetch_ticker(symbol)['last']
    risk = abs(entry - stop_loss)
    new_stop = current_price - risk if side == "buy" else current_price + risk
    
    if (side == "buy" and new_stop > stop_loss) or (side == "sell" and new_stop < stop_loss):
        EXCHANGE.create_order(symbol, 'stop', side="sell" if side=="buy" else "buy", amount=1, price=new_stop)
        bot.send_message(CHAT_ID, f"Trailing Stop Updated: {new_stop}")
        return new_stop
    return stop_loss

# --- MAIN BOT LOOP ---
def run_bot(symbol="LINK/USDT"):
    while True:
        candles = get_candles(symbol)
        supply_zones, demand_zones = find_zones(candles)
        inducement = detect_inducement(candles, supply_zones + demand_zones)
        
        if inducement:
            side = "buy" if "Demand" in inducement else "sell"
            entry = candles[-1][4]
            stop_loss = demand_zones[-1][0] if side == "buy" else supply_zones[-1][0]
            
            entry, stop_loss = place_trade(symbol, side, entry, stop_loss)
            
            # Monitor and update trailing stop
            while True:
                time.sleep(60)  # Check every 1 minute
                stop_loss = update_trailing_stop(symbol, entry, stop_loss, side)

# --- KEEP-ALIVE FLASK SERVER ---
@app.route('/')
def home():
    return "Bot is running!"

def start_bot():
    run_bot()

thread = threading.Thread(target=start_bot)
thread.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
