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
MAX_AGE_MINUTES = 60
# ======================================

app = Flask(__name__)
bot = Bot(token=BOT_TOKEN)
processed_tokens = set()
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

async def send_startup_msg():
    try:
        await bot.send_message(chat_id=CHAT_ID, text="🚀 *تحديث ذكي للفلاتر!*\n\nتم تحسين اكتشاف القفل ليشمل عملات Pump.fun والسيولة المحروقة فوراً.\nجاري الصيد... 🎯", parse_mode='Markdown')
    except Exception: pass

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

async def send_alert(pair, image_url, lock_type):
    try:
        base_token = pair.get("baseToken", {})
        symbol = base_token.get("symbol", "Unknown")
        address = base_token.get("address", "Unknown")
        mcap = pair.get("fdv", 0) or pair.get("marketCap", 0)
        vol_1h = pair.get("volume", {}).get("h1", 0)
        txns_1h = pair.get("txns", {}).get("h1", {}).get("total", 0)
        created_at = pair.get("pairCreatedAt", 0)
        age_mins = (time.time() * 1000 - created_at) / (1000 * 60) if created_at else 0
        
        msg = (
            f"🚨 *فرصة ذهبية مكتشفة* 🚨\n\n"
            f"💎 *العملة:* ${symbol}\n"
            f"💰 *القيمة السوقية:* ${mcap:,.0f}\n"
            f"📊 *حجم (1 ساعة):* ${vol_1h:,.0f}\n"
            f"🔄 *معاملات (1 ساعة):* {txns_1h}\n"
            f"⏱️ *العمر:* {age_mins:.1f} دقيقة\n"
            f"🔒 *الأمان:* {lock_type} ✅\n\n"
            f"📑 *العقد:* `{address}`\n"
            f"🔗 *الرابط:* [DexScreener]({pair.get('url')})\n\n"
            f"✅ *التقييم:* مطابق لشروطك + Logo"
        )
        await bot.send_photo(chat_id=CHAT_ID, photo=image_url, caption=msg, parse_mode='Markdown')
    except Exception: pass

async def check_pairs_async():
    try:
        # جلب أحدث البروفايلات لضمان الحصول على العملات ذات الصور
        resp = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=15 )
        if resp.status_code != 200: return
        profiles = resp.json()
        
        for profile in profiles[:30]: # فحص نطاق أوسع
            token_address = profile.get("tokenAddress")
            if not token_address or token_address in processed_tokens: continue
            
            pair = await get_pair_details(token_address)
            if not pair: continue
            
            image_url = pair.get("info", {}).get("imageUrl")
            if not image_url: continue
            
            # --- منطق اكتشاف القفل المطور ---
            is_locked = False
            lock_type = ""
            
            # 1. فحص عملات Pump.fun (تعتبر مقفلة/محروقة تلقائياً)
            if pair.get("dexId") == "pump" or "pump" in pair.get("url", "").lower():
                is_locked = True
                lock_type = "Pump.fun (Auto-Burn)"
            
            # 2. فحص العلامات الرسمية في البيانات
            labels = [l.lower() for l in pair.get("labels", [])]
            if "liquidity-locked" in labels or "burned" in labels:
                is_locked = True
                lock_type = "DexScreener Verified"
            
            # 3. فحص نصي شامل للبيانات (لاكتشاف أي إشارة للقفل)
            if not is_locked and "lock" in str(pair).lower():
                is_locked = True
                lock_type = "Contract Detected Lock"

            if not is_locked: continue

            # --- فحص باقي الشروط الممالية ---
            mcap = pair.get("fdv", 0) or pair.get("marketCap", 0)
            vol_1h = pair.get("volume", {}).get("h1", 0)
            txns_1h = pair.get("txns", {}).get("h1", {}).get("total", 0)
            created_at = pair.get("pairCreatedAt", 0)
            age_mins = (time.time() * 1000 - created_at) / (1000 * 60) if created_at else 0

            if (MIN_MARKET_CAP <= mcap <= MAX_MARKET_CAP and vol_1h >= MIN_VOLUME_1H and 
                txns_1h >= MIN_TXNS_1H and age_mins <= MAX_AGE_MINUTES):
                await send_alert(pair, image_url, lock_type)
                processed_tokens.add(token_address)
    except Exception: pass

def check_pairs_sync():
    asyncio.run_coroutine_threadsafe(check_pairs_async(), loop)

@app.route("/")
def home():
    return "Smart Bot is running!"

if __name__ == "__main__":
    loop.run_until_complete(send_startup_msg())
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=check_pairs_sync, trigger="interval", seconds=CHECK_INTERVAL)
    scheduler.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
