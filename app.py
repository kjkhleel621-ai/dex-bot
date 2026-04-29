import os
import requests
import asyncio
import time
from datetime import datetime
from telegram import Bot
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

# ========== إعدادات المستخدم ==========
BOT_TOKEN = "8411603184:AAEurS9EZmL0k34lf1LKUVrZrGFug5UKNps"
CHAT_ID = "5902278714"
CHECK_INTERVAL = 30 

# --- شروط الفلترة المتقدمة ---
MIN_MARKET_CAP = 50000
MAX_MARKET_CAP = 750000
MIN_VOLUME_1H = 100000
MIN_TXNS_1H = 200
MIN_CHANGE_5M = 0.0
MAX_CHANGE_5M = 500.0
MAX_AGE_MINUTES = 60
# ======================================

app = Flask(__name__)
bot = Bot(token=BOT_TOKEN)
processed_tokens = set()
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

async def send_startup_msg():
    """إرسال رسالة تأكيد فورية عند بدء التشغيل"""
    try:
        await bot.send_message(chat_id=CHAT_ID, text="✅ *بوت DexScreener يعمل الآن!*\n\nالمراقبة مفعلة كل 30 ثانية.\nسيتم إرسال التنبيهات هنا فور مطابقة الشروط.", parse_mode='Markdown')
        print("Startup message sent!")
    except Exception as e:
        print(f"Error sending startup msg: {e}")

async def is_liquidity_locked(token_address, chain_id="ethereum"):
    try:
        chain_map = {"ethereum": "1", "bsc": "56", "solana": "solana", "base": "8453", "arbitrum": "42161"}
        goplus_chain = chain_map.get(chain_id.lower(), "1")
        url = f"https://api.gopluslabs.io/api/v1/token_security/{goplus_chain}"
        params = {"contract_addresses": token_address}
        response = requests.get(url, params=params, timeout=10 )
        if response.status_code == 200:
            data = response.json()
            result = data.get("result", {}).get(token_address.lower(), {})
            lp_holders = result.get("lp_holders", [])
            locked_percent = 0
            for holder in lp_holders:
                if holder.get("is_locked") == 1:
                    locked_percent += float(holder.get("percent", 0)) * 100
            if locked_percent >= 90:
                return True, f"{locked_percent:.1f}%"
        return False, "0%"
    except Exception:
        return True, "Unknown (Bypassed)"

async def get_pair_details(token_address):
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        response = requests.get(url, timeout=10 )
        if response.status_code == 200:
            data = response.json()
            pairs = data.get("pairs", [])
            if pairs:
                return max(pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0))
    except Exception: pass
    return None

async def send_alert(pair, locked_info):
    try:
        base_token = pair.get("baseToken", {})
        symbol = base_token.get("symbol", "Unknown")
        address = base_token.get("address", "Unknown")
        mcap = pair.get("fdv", 0) or pair.get("marketCap", 0)
        vol_1h = pair.get("volume", {}).get("h1", 0)
        txns_1h = pair.get("txns", {}).get("h1", {}).get("total", 0)
        change_5m = pair.get("priceChange", {}).get("m5", 0)
        created_at = pair.get("pairCreatedAt", 0)
        age_mins = (time.time() * 1000 - created_at) / (1000 * 60) if created_at else 0
        
        msg = (
            f"🚨 *فرصة ذهبية مكتشفة* 🚨\n\n"
            f"💎 *العملة:* ${symbol}\n"
            f"💰 *القيمة السوقية:* ${mcap:,.0f}\n"
            f"📊 *حجم (1 ساعة):* ${vol_1h:,.0f}\n"
            f"🔄 *معاملات (1 ساعة):* {txns_1h}\n"
            f"📈 *تغير (5 دقائق):* {change_5m}%\n"
            f"⏱️ *العمر:* {age_mins:.1f} دقيقة\n"
            f"🔒 *السيولة المقفلة:* {locked_info}\n\n"
            f"📑 *العقد:* `{address}`\n"
            f"🔗 *الرابط:* [DexScreener]({pair.get('url')})\n\n"
            f"✅ *التقييم:* متوافق مع الفلاتر"
        )
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown')
    except Exception: pass

async def check_pairs_async():
    try:
        resp = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=15 )
        if resp.status_code != 200: return
        profiles = resp.json()
        for profile in profiles[:15]:
            token_address = profile.get("tokenAddress")
            if not token_address or token_address in processed_tokens: continue
            pair = await get_pair_details(token_address)
            if not pair: continue
            mcap = pair.get("fdv", 0) or pair.get("marketCap", 0)
            vol_1h = pair.get("volume", {}).get("h1", 0)
            txns_1h = pair.get("txns", {}).get("h1", {}).get("total", 0)
            created_at = pair.get("pairCreatedAt", 0)
            age_mins = (time.time() * 1000 - created_at) / (1000 * 60) if created_at else 0

            if (MIN_MARKET_CAP <= mcap <= MAX_MARKET_CAP and vol_1h >= MIN_VOLUME_1H and 
                txns_1h >= MIN_TXNS_1H and age_mins <= MAX_AGE_MINUTES):
                is_locked, locked_info = await is_liquidity_locked(token_address, pair.get("chainId", "ethereum"))
                if is_locked:
                    await send_alert(pair, locked_info)
                    processed_tokens.add(token_address)
    except Exception: pass

def check_pairs_sync():
    asyncio.run_coroutine_threadsafe(check_pairs_async(), loop)

@app.route("/")
def home():
    return "Bot is running!"

if __name__ == "__main__":
    # إرسال رسالة الترحيب عند البدء
    loop.run_until_complete(send_startup_msg())
    
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=check_pairs_sync, trigger="interval", seconds=CHECK_INTERVAL)
    scheduler.start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
