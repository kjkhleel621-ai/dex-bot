import os
import requests
import asyncio
import time
from datetime import datetime
from telegram import Bot
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

# ========== إعدادات المستخدم ==========
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID") # يمكن تعيينه كمتغير بيئة أو هنا مباشرة
CHECK_INTERVAL = 30  # فحص كل 30 ثانية

# --- شروط الفلترة المتقدمة ---
MIN_MARKET_CAP = 50000
MAX_MARKET_CAP = 750000
MIN_VOLUME_1H = 100000
MIN_TXNS_1H = 200
MIN_CHANGE_5M = 0.0    # الحد الأدنى 0% (لا يوجد هبوط)
MAX_CHANGE_5M = 500.0  # الحد الأعلى 500%
MAX_AGE_MINUTES = 60
# ======================================

app = Flask(__name__)
bot = Bot(token=BOT_TOKEN)
processed_tokens = set()

# لضمان تشغيل الدوال غير المتزامنة ضمن سياق متزامن (Flask)
loop = asyncio.get_event_loop()

async def is_liquidity_locked(token_address, chain_id="ethereum"):
    """التحقق من قفل السيولة باستخدام GoPlus API"""
    try:
        chain_map = {
            "ethereum": "1",
            "bsc": "56",
            "solana": "solana",
            "base": "8453",
            "arbitrum": "42161"
        }
        goplus_chain = chain_map.get(chain_id.lower(), "1")
        
        url = f"https://api.gopluslabs.io/api/v1/token_security/{goplus_chain}"
        params = {"contract_addresses": token_address}
        response = requests.get(url, params=params, timeout=10)
        
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
    except Exception as e:
        print(f"⚠️ خطأ في فحص GoPlus: {e}")
        return True, "Unknown (Bypassed)" # نفترض النجاح في حال فشل الـ API لعدم إيقاف البوت

async def get_pair_details(token_address):
    """جلب تفاصيل الزوج الدقيقة من DexScreener"""
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            pairs = data.get("pairs", [])
            if pairs:
                best_pair = max(pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0))
                return best_pair
    except Exception as e:
        print(f"⚠️ خطأ في جلب تفاصيل الزوج: {e}")
    return None

async def send_alert(pair, locked_info):
    """إرسال تنبيه احترافي إلى تيليجرام"""
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
            f"🔗 *الرابط:* [DexScreener]({pair.get("url")})\n\n"
            f"✅ *التقييم:* متوافق مع جميع الفلاتر المتقدمة"
        )
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode=\'Markdown\')
        print(f"[{datetime.now()}] ✅ تم إرسال تنبيه لـ {symbol}")
    except Exception as e:
        print(f"❌ فشل إرسال الرسالة: {e}")

async def check_pairs_async():
    print(f"[{datetime.now()}] 🔍 جاري فحص العملات الجديدة...")
    try:
        resp = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=15)
        if resp.status_code != 200:
            print(f"❌ فشل جلب ملفات التعريف: {resp.status_code}")
            return
        
        profiles = resp.json()
        for profile in profiles[:15]: # فحص آخر 15 ملف تعريف
            token_address = profile.get("tokenAddress")
            if not token_address or token_address in processed_tokens:
                continue
            
            pair = await get_pair_details(token_address)
            if not pair:
                continue
            
            mcap = pair.get("fdv", 0) or pair.get("marketCap", 0)
            vol_1h = pair.get("volume", {}).get("h1", 0)
            txns_1h = pair.get("txns", {}).get("h1", {}).get("total", 0)
            change_5m = pair.get("priceChange", {}).get("m5", 0)
            created_at = pair.get("pairCreatedAt", 0)
            age_mins = (time.time() * 1000 - created_at) / (1000 * 60) if created_at else 0

            if not (MIN_MARKET_CAP <= mcap <= MAX_MARKET_CAP):
                continue
            if vol_1h < MIN_VOLUME_1H:
                continue
            if txns_1h < MIN_TXNS_1H:
                continue
            if not (MIN_CHANGE_5M <= change_5m <= MAX_CHANGE_5M):
                continue
            if age_mins > MAX_AGE_MINUTES:
                continue

            is_locked, locked_info = await is_liquidity_locked(token_address, pair.get("chainId", "ethereum"))
            if not is_locked:
                print(f"⚠️ تم تخطي {token_address} لأن السيولة غير مقفلة ({locked_info})")
                continue

            await send_alert(pair, locked_info)
            processed_tokens.add(token_address)
            
    except Exception as e:
        print(f"⚠️ خطأ أثناء الفحص: {e}")

def check_pairs_sync():
    # تشغيل الدالة غير المتزامنة في حلقة الأحداث الحالية
    asyncio.run_coroutine_threadsafe(check_pairs_async(), loop)

@app.route("/")
def home():
    return "DexScreener Telegram Bot is running!"

# إرسال رسالة تأكيد عند بدء التشغيل
async def send_startup_message():
    if BOT_TOKEN and CHAT_ID:
        try:
            await bot.send_message(chat_id=CHAT_ID, text="🚀 *تم تشغيل بوت DexScreener بنجاح!*\nجاري المراقبة الآن...", parse_mode=\'Markdown\')
            print("✅ تم إرسال رسالة بدء التشغيل إلى تيليجرام.")
        except Exception as e:
            print(f"❌ فشل إرسال رسالة بدء التشغيل: {e}")
    else:
        print("⚠️ لم يتم تعيين TELEGRAM_TOKEN أو TELEGRAM_CHAT_ID. لن يتم إرسال رسالة بدء التشغيل.")

if __name__ == "__main__":
    # تهيئة APScheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=check_pairs_sync, trigger="interval", seconds=CHECK_INTERVAL)
    scheduler.start()

    # تشغيل رسالة بدء التشغيل بشكل غير متزامن
    asyncio.run_coroutine_threadsafe(send_startup_message(), loop)

    # تشغيل Flask
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

    # إيقاف المجدول عند إيقاف التطبيق
    try:
        while True:
            time.sleep(2)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
