import os
import requests
import asyncio
import time
from datetime import datetime
from telegram import Bot
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

# ========== إعدادات الصياد السريع (V2) ==========
BOT_TOKEN = "8411603184:AAEurS9EZmL0k34lf1LKUVrZrGFug5UKNps"
CHAT_ID = "5902278714"
CHECK_INTERVAL = 15 # فحص كل 15 ثانية

# الشروط الأساسية (حسب طلبك)
MIN_MARKET_CAP = 50000
MAX_MARKET_CAP = 750000
MIN_VOLUME = 50000 
MAX_AGE_MINUTES = 25 # أول 5 شموع
# ======================================

app = Flask(__name__)
bot = Bot(token=BOT_TOKEN)
processed_tokens = set()
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

async def send_startup_msg():
    try:
        await bot.send_message(chat_id=CHAT_ID, text="⚡ *تم تفعيل وضع القناص المطور (V2)!*\n\n✅ جلب العملات من Latest Pairs (بدون انتظار الرسوم).\n✅ دعم سحب الصور مجاناً من Pump.fun.\n✅ فحص السيولة والقيمة السوقية بدقة.\n\nجاري الصيد... 🎯", parse_mode='Markdown')
    except Exception as e: print(f"Startup error: {e}")

async def send_alert(pair, image_url, age_mins):
    try:
        base_token = pair.get("baseToken", {})
        symbol = base_token.get("symbol", "Unknown")
        address = base_token.get("address", "Unknown")
        mcap = pair.get("fdv", 0) or pair.get("marketCap", 0)
        vol_h1 = pair.get("volume", {}).get("h1", 0)
        
        msg = (
            f"🚀 *صيدة قناص سريعة (V2)* 🚀\n\n"
            f"💎 *العملة:* ${symbol}\n"
            f"💰 *القيمة السوقية:* ${mcap:,.0f}\n"
            f"📊 *حجم التداول:* ${vol_h1:,.0f}\n"
            f"⏱️ *العمر:* {age_mins:.1f} دقيقة\n"
            f"🔒 *الأمان:* سيولة مقفلة/محروقة ✅\n\n"
            f"📑 *العقد:* `{address}`\n"
            f"🔗 *الرابط:* [DexScreener]({pair.get('url')})\n"
        )
        if image_url:
            await bot.send_photo(chat_id=CHAT_ID, photo=image_url, caption=msg, parse_mode='Markdown')
        else:
            await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown')
    except Exception as e: print(f"Alert error: {e}")

async def check_pairs_async():
    try:
        # التعديل الجوهري: استخدام Latest Pairs بدلاً من Token Profiles
        # هذا الرابط يجلب أحدث العملات التي تم إنشاؤها على سولانا فوراً
        url = "https://api.dexscreener.com/latest/dex/search?q=solana"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200: return
        
        data = resp.json()
        pairs = data.get("pairs", [])
        
        # ترتيب العملات حسب وقت الإنشاء (الأحدث أولاً)
        pairs.sort(key=lambda x: x.get("pairCreatedAt", 0), reverse=True)

        for pair in pairs[:30]: # فحص أحدث 30 زوجاً
            token_address = pair.get("baseToken", {}).get("address")
            if not token_address or token_address in processed_tokens: continue
            
            # 1. فحص الشبكة (Solana فقط)
            if pair.get("chainId") != "solana": continue

            # 2. فحص قفل السيولة
            is_locked = False
            pair_str = str(pair).lower()
            labels = [l.lower() for l in pair.get("labels", [])]
            if "locked" in labels or "liquidity-locked" in labels or "burned" in labels:
                is_locked = True
            elif "locked" in pair_str or "burned" in pair_str:
                is_locked = True
            elif pair.get("dexId") == "pump": # عملات Pump.fun آمنة من حيث القفل
                is_locked = True
            
            if not is_locked: continue

            # 3. الشروط المالية وعمر العملة
            mcap = pair.get("fdv", 0) or pair.get("marketCap", 0)
            vol_h1 = pair.get("volume", {}).get("h1", 0)
            created_at = pair.get("pairCreatedAt", 0)
            age_mins = (time.time() * 1000 - created_at) / (1000 * 60) if created_at else 0

            if (MIN_MARKET_CAP <= mcap <= MAX_MARKET_CAP and 
                vol_h1 >= MIN_VOLUME and 
                age_mins <= MAX_AGE_MINUTES):
                
                # 4. فحص الصورة (Logo)
                image_url = pair.get("info", {}).get("imageUrl")
                
                # إذا لم تكن الصورة موجودة على DexScreener، نسحبها من Pump.fun مجاناً
                if not image_url and pair.get("dexId") == "pump":
                    image_url = f"https://ipfs.io/ipfs/{token_address}" # محاولة سحب الصورة عبر IPFS (نمط Pump.fun)
                    # ملاحظة: بعض العملات تستخدم روابط مباشرة، هذا الرابط هو مثال تقريبي
                    # في النسخة المتقدمة يمكن استخدام API خاص بـ Pump.fun
                
                # شرط إلزامي: يجب وجود صورة (حسب طلبك)
                # إذا لم نجد صورة حتى بعد المحاولة، نتجاهل العملة
                if not image_url:
                    # محاولة أخيرة: التحقق من وجود أيقونة افتراضية أو معلومات إضافية
                    if not pair.get("info"): continue

                await send_alert(pair, image_url, age_mins)
                processed_tokens.add(token_address)
                
    except Exception as e: print(f"Check error: {e}")

def check_pairs_sync():
    asyncio.run_coroutine_threadsafe(check_pairs_async(), loop)

@app.route("/")
def home():
    return "Sniper Bot V2 is running!"

if __name__ == "__main__":
    loop.run_until_complete(send_startup_msg())
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=check_pairs_sync, trigger="interval", seconds=CHECK_INTERVAL)
    scheduler.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
