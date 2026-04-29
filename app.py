import os
import requests
import asyncio
import time
from datetime import datetime
from telegram import Bot
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

# ========== إعدادات الصياد السريع ==========
BOT_TOKEN = "8411603184:AAEurS9EZmL0k34lf1LKUVrZrGFug5UKNps"
CHAT_ID = "5902278714"
CHECK_INTERVAL = 15 # فحص فائق السرعة كل 15 ثانية

# شروط الدخول السريع
MIN_MARKET_CAP = 50000
MAX_MARKET_CAP = 750000
MIN_VOLUME = 50000 
MAX_AGE_MINUTES = 25 # التركيز على أول 5 شموع (25 دقيقة)
# ======================================

app = Flask(__name__)
bot = Bot(token=BOT_TOKEN)
processed_tokens = set()
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

async def send_startup_msg():
    try:
        await bot.send_message(chat_id=CHAT_ID, text="⚡ *تم تفعيل وضع القناص (Sniper Mode)!*\n\nسأصطاد العملات في أول دقائقها بمجرد ظهور القفل.\nجاري الصيد السريع... 🎯", parse_mode='Markdown')
    except Exception: pass

async def send_alert(pair, image_url, age_mins):
    try:
        base_token = pair.get("baseToken", {})
        symbol = base_token.get("symbol", "Unknown")
        address = base_token.get("address", "Unknown")
        mcap = pair.get("fdv", 0) or pair.get("marketCap", 0)
        vol_h1 = pair.get("volume", {}).get("h1", 0)
        
        msg = (
            f"🚀 *صيدة قناص سريعة* 🚀\n\n"
            f"💎 *العملة:* ${symbol}\n"
            f"💰 *القيمة السوقية:* ${mcap:,.0f}\n"
            f"📊 *حجم التداول:* ${vol_h1:,.0f}\n"
            f"⏱️ *العمر:* {age_mins:.1f} دقيقة (جديدة!)\n"
            f"🔒 *الأمان:* رمز القفل مكتشف ✅\n\n"
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
        # فحص أحدث العملات المضافة على سولانا مباشرة (أسرع مصدر للإطلاق الجديد)
        url = "https://api.dexscreener.com/token-profiles/latest/v1"
        resp = requests.get(url, timeout=10 )
        if resp.status_code != 200: return
        profiles = resp.json()
        
        for profile in profiles[:40]:
            token_address = profile.get("tokenAddress")
            if not token_address or token_address in processed_tokens: continue
            
            # جلب تفاصيل الزوج فوراً
            url_details = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            res = requests.get(url_details, timeout=10 )
            if res.status_code != 200: continue
            
            data = res.json()
            pairs = data.get("pairs", [])
            if not pairs: continue
            
            # اختيار الزوج النشط على سولانا
            pair = next((p for p in pairs if p.get("chainId") == "solana"), pairs[0])
            
            # --- فحص القفل المبكر ---
            is_locked = False
            pair_str = str(pair).lower()
            labels = [l.lower() for l in pair.get("labels", [])]
            
            if "locked" in labels or "liquidity-locked" in labels or "burned" in labels:
                is_locked = True
            elif "locked" in pair_str or "burned" in pair_str: # فحص البيانات الخام
                is_locked = True
            elif pair.get("dexId") == "pump": # عملات Pump.fun مقفلة تلقائياً
                is_locked = True

            if not is_locked: continue

            # الشروط المالية وعمر العملة
            mcap = pair.get("fdv", 0) or pair.get("marketCap", 0)
            vol_h1 = pair.get("volume", {}).get("h1", 0)
            created_at = pair.get("pairCreatedAt", 0)
            age_mins = (time.time() * 1000 - created_at) / (1000 * 60) if created_at else 0

            if (MIN_MARKET_CAP <= mcap <= MAX_MARKET_CAP and vol_h1 >= MIN_VOLUME and 
                age_mins <= MAX_AGE_MINUTES):
                image_url = pair.get("info", {}).get("imageUrl")
                await send_alert(pair, image_url, age_mins)
                processed_tokens.add(token_address)
    except Exception: pass

def check_pairs_sync():
    asyncio.run_coroutine_threadsafe(check_pairs_async(), loop)

@app.route("/")
def home():
    return "Sniper Bot is running!"

if __name__ == "__main__":
    loop.run_until_complete(send_startup_msg())
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=check_pairs_sync, trigger="interval", seconds=CHECK_INTERVAL)
    scheduler.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
