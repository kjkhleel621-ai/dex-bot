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

# --- الشروط المطلوبة ---
MIN_MARKET_CAP = 50000
MAX_MARKET_CAP = 750000
MIN_VOLUME = 100000
MAX_AGE_MINUTES = 60
# ======================================

app = Flask(__name__)
bot = Bot(token=BOT_TOKEN)
processed_tokens = set()
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

async def send_startup_msg():
    try:
        await bot.send_message(chat_id=CHAT_ID, text="🔒 *تم ضبط البوت على رمز القفل فقط!*\n\nسأرسل لك العملات التي يظهر عليها رمز القفل في DexScreener حصراً.\nجاري الصيد... 🎯", parse_mode='Markdown')
    except Exception: pass

async def send_alert(pair, image_url):
    try:
        base_token = pair.get("baseToken", {})
        symbol = base_token.get("symbol", "Unknown")
        address = base_token.get("address", "Unknown")
        mcap = pair.get("fdv", 0) or pair.get("marketCap", 0)
        vol_h1 = pair.get("volume", {}).get("h1", 0)
        
        msg = (
            f"🚨 *عملة مقفلة مكتشفة* 🚨\n\n"
            f"💎 *العملة:* ${symbol}\n"
            f"💰 *القيمة السوقية:* ${mcap:,.0f}\n"
            f"📊 *حجم (1 ساعة):* ${vol_h1:,.0f}\n"
            f"🔒 *الأمان:* رمز القفل ظاهر ✅\n\n"
            f"📑 *العقد:* `{address}`\n"
            f"🔗 *الرابط:* [DexScreener]({pair.get('url')})\n"
        )
        if image_url:
            await bot.send_photo(chat_id=CHAT_ID, photo=image_url, caption=msg, parse_mode='Markdown')
        else:
            await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown')
    except Exception: pass

async def check_pairs_async():
    try:
        # فحص أحدث العملات المضافة (أسرع مصدر للبيانات المالية وحالة القفل)
        url = "https://api.dexscreener.com/token-profiles/latest/v1"
        resp = requests.get(url, timeout=15 )
        if resp.status_code != 200: return
        profiles = resp.json()
        
        for profile in profiles[:50]:
            token_address = profile.get("tokenAddress")
            if not token_address or token_address in processed_tokens: continue
            
            # جلب تفاصيل الزوج (Pair)
            url_details = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            res = requests.get(url_details, timeout=10 )
            if res.status_code != 200: continue
            
            data = res.json()
            pairs = data.get("pairs", [])
            if not pairs: continue
            
            # نختار الزوج الأساسي (الأعلى سيولة)
            pair = max(pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0))
            
            # --- شرط رمز القفل الصارم ---
            # في الـ API، رمز القفل يظهر كعلامة 'liquidity-locked' في حقل labels
            labels = [l.lower() for l in pair.get("labels", [])]
            if "liquidity-locked" not in labels:
                continue

            # الشروط المالية
            mcap = pair.get("fdv", 0) or pair.get("marketCap", 0)
            vol_h1 = pair.get("volume", {}).get("h1", 0)
            
            if MIN_MARKET_CAP <= mcap <= MAX_MARKET_CAP and vol_h1 >= MIN_VOLUME:
                image_url = pair.get("info", {}).get("imageUrl")
                await send_alert(pair, image_url)
                processed_tokens.add(token_address)
    except Exception: pass

def check_pairs_sync():
    asyncio.run_coroutine_threadsafe(check_pairs_async(), loop)

@app.route("/")
def home():
    return "Official Lock Only Bot is running!"

if __name__ == "__main__":
    loop.run_until_complete(send_startup_msg())
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=check_pairs_sync, trigger="interval", seconds=CHECK_INTERVAL)
    scheduler.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
