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
CHECK_INTERVAL = 20 # تسريع الفحص لـ 20 ثانية

# --- شروط الفلترة الفائقة ---
MIN_MARKET_CAP = 50000
MAX_MARKET_CAP = 750000
MIN_VOLUME = 50000 
MAX_AGE_MINUTES = 60
# ======================================

app = Flask(__name__)
bot = Bot(token=BOT_TOKEN)
processed_tokens = set()
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

async def send_startup_msg():
    try:
        await bot.send_message(chat_id=CHAT_ID, text="⚡ *تم تفعيل الفحص فائق السرعة!*\n\nالبوت الآن يراقب أحدث الإضافات على سولانا مباشرة.\nجاري الصيد... 🎯", parse_mode='Markdown')
    except Exception: pass

async def send_alert(pair, image_url):
    try:
        base_token = pair.get("baseToken", {})
        symbol = base_token.get("symbol", "Unknown")
        address = base_token.get("address", "Unknown")
        mcap = pair.get("fdv", 0) or pair.get("marketCap", 0)
        vol_h1 = pair.get("volume", {}).get("h1", 0)
        
        msg = (
            f"🚨 *صيدة سريعة مكتشفة* 🚨\n\n"
            f"💎 *العملة:* ${symbol}\n"
            f"💰 *القيمة السوقية:* ${mcap:,.0f}\n"
            f"📊 *حجم (1 ساعة):* ${vol_h1:,.0f}\n"
            f"⏱️ *العمر:* جديد جداً\n\n"
            f"📑 *العقد:* `{address}`\n"
            f"🔗 *الرابط:* [DexScreener]({pair.get('url')})\n\n"
            f"✅ *التقييم:* مطابق لشروطك"
        )
        if image_url:
            await bot.send_photo(chat_id=CHAT_ID, photo=image_url, caption=msg, parse_mode='Markdown')
        else:
            await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown')
    except Exception: pass

async def check_pairs_async():
    try:
        # فحص أحدث العملات المضافة على سولانا مباشرة (أسرع مصدر)
        url = "https://api.dexscreener.com/token-boosts/latest/v1"
        resp = requests.get(url, timeout=15 )
        if resp.status_code != 200: return
        boosts = resp.json()
        
        for item in boosts[:50]:
            token_address = item.get("tokenAddress")
            if not token_address or token_address in processed_tokens: continue
            
            # جلب تفاصيل العملة
            url_details = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            res = requests.get(url_details, timeout=10 )
            if res.status_code != 200: continue
            
            data = res.json()
            pairs = data.get("pairs", [])
            if not pairs: continue
            
            pair = max(pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0))
            if pair.get("chainId") != "solana": continue

            mcap = pair.get("fdv", 0) or pair.get("marketCap", 0)
            vol_h1 = pair.get("volume", {}).get("h1", 0)
            
            # فلترة مالية مرنة جداً
            if MIN_MARKET_CAP <= mcap <= MAX_MARKET_CAP and vol_h1 >= MIN_VOLUME:
                image_url = pair.get("info", {}).get("imageUrl")
                await send_alert(pair, image_url)
                processed_tokens.add(token_address)
    except Exception: pass

def check_pairs_sync():
    asyncio.run_coroutine_threadsafe(check_pairs_async(), loop)

@app.route("/")
def home():
    return "Ultra Fast Bot is running!"

if __name__ == "__main__":
    loop.run_until_complete(send_startup_msg())
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=check_pairs_sync, trigger="interval", seconds=CHECK_INTERVAL)
    scheduler.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
