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
        await bot.send_message(chat_id=CHAT_ID, text="🔄 *تم تحديث البوت!*\n\n*الشرط الحالي:* يجب وجود رمز القفل (Logo) على DexScreener.\nجاري المراقبة...", parse_mode='Markdown')
    except Exception: pass

async def get_pair_details(token_address):
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        response = requests.get(url, timeout=10 )
        if response.status_code == 200:
            data = response.json()
            pairs = data.get("pairs", [])
            if pairs:
                # اختيار الزوج الأكثر سيولة
                return max(pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0))
    except Exception: pass
    return None

async def send_alert(pair, image_url):
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
            f"🚨 *تنبيه: عملة مقفلة مكتشفة* 🚨\n\n"
            f"💎 *العملة:* ${symbol}\n"
            f"💰 *القيمة السوقية:* ${mcap:,.0f}\n"
            f"📊 *حجم (1 ساعة):* ${vol_1h:,.0f}\n"
            f"🔄 *معاملات (1 ساعة):* {txns_1h}\n"
            f"⏱️ *العمر:* {age_mins:.1f} دقيقة\n"
            f"🔒 *الحالة:* مقفلة على DexScreener ✅\n\n"
            f"📑 *العقد:* `{address}`\n"
            f"🔗 *الرابط:* [DexScreener]({pair.get('url')})\n\n"
            f"✅ *التقييم:* متوافق مع شروط القفل والصورة"
        )
        
        await bot.send_photo(chat_id=CHAT_ID, photo=image_url, caption=msg, parse_mode='Markdown')
    except Exception: pass

async def check_pairs_async():
    try:
        resp = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=15 )
        if resp.status_code != 200: return
        profiles = resp.json()
        for profile in profiles[:20]: # فحص آخر 20 ملف تعريف
            token_address = profile.get("tokenAddress")
            if not token_address or token_address in processed_tokens: continue
            
            pair = await get_pair_details(token_address)
            if not pair: continue
            
            # --- فحص وجود الصورة ---
            image_url = pair.get("info", {}).get("imageUrl")
            if not image_url: continue
            
            # --- فحص وجود رمز القفل (Liquidity Status) ---
            # DexScreener API يعيد معلومات القفل في حقل 'liquidity'
            # إذا كان هناك أي معلومات عن القفل، سنعتبرها مقفلة
            is_locked = False
            if pair.get("liquidity", {}).get("base") or pair.get("liquidity", {}).get("quote"):
                # نتحقق من وجود أي إشارة للقفل في بيانات الزوج
                # ملاحظة: API دكس سكرينر يمرر حالة القفل ضمن معلومات الزوج
                if pair.get("labels") and "liquidty-locked" in [l.lower() for l in pair.get("labels", [])]:
                    is_locked = True
                # فحص بديل: Pump.fun عادة ما تحرق السيولة
                if pair.get("dexId") == "pump":
                    is_locked = True
                # فحص إضافي عبر الـ labels أو الـ info
                if "locked" in str(pair).lower():
                    is_locked = True

            if not is_locked: continue

            mcap = pair.get("fdv", 0) or pair.get("marketCap", 0)
            vol_1h = pair.get("volume", {}).get("h1", 0)
            txns_1h = pair.get("txns", {}).get("h1", {}).get("total", 0)
            created_at = pair.get("pairCreatedAt", 0)
            age_mins = (time.time() * 1000 - created_at) / (1000 * 60) if created_at else 0

            if (MIN_MARKET_CAP <= mcap <= MAX_MARKET_CAP and vol_1h >= MIN_VOLUME_1H and 
                txns_1h >= MIN_TXNS_1H and age_mins <= MAX_AGE_MINUTES):
                await send_alert(pair, image_url)
                processed_tokens.add(token_address)
    except Exception: pass

def check_pairs_sync():
    asyncio.run_coroutine_threadsafe(check_pairs_async(), loop)

@app.route("/")
def home():
    return "Bot is running with DexScreener Lock Filter!"

if __name__ == "__main__":
    loop.run_until_complete(send_startup_msg())
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=check_pairs_sync, trigger="interval", seconds=CHECK_INTERVAL)
    scheduler.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
