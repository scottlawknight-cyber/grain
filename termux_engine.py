"""
بوت الحجز - نسخة Termux للموبايل
==================================
يعمل بدون واجهة رسومية - يقرأ الملفات ويشغل المحرك فقط.
التأخير: 0.5 - 2 ثانية (سريع جداً)

الملفات المطلوبة بجانب هذا الكود:
1. accounts.json  ← الحسابات (كوكيز + توكن) - يُنسخ من الكمبيوتر
2. transactions.json ← المعاملات المطلوب حجزها

المحرك:
- يدور على المعاملات بالترتيب (واحدة كل دورة)
- عند نجاح حجز → يرسل لكل المعاملات المتبقية (burst)
- التأخير: 0.5 - 2 ثانية عشوائي
"""

import os
import sys
import json
import time
import random
import signal
import logging
import requests
import urllib3
from datetime import datetime
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# إعدادات
# ==========================================
BASE_URL = "https://hajz.grainboardiq.com"
BOOKING_PAGE_URL = f"{BASE_URL}/Reservation/Create"
BOOKING_POST_URL = f"{BASE_URL}/Reservation/CreateReservation"
SEARCH_API_URL = f"{BASE_URL}/api/LocationApi/SearchFarmersByMarketingCenter"
SLOTS_API_URL = f"{BASE_URL}/Reservation/GetReservationDayOptions"

ACCOUNTS_FILE = "accounts.json"
TRANSACTIONS_FILE = "transactions.json"
LOG_FILE = "engine.log"
PID_FILE = "engine.pid"

MIN_DELAY = 0.5  # نصف ثانية
MAX_DELAY = 2.0  # ثانيتين

# ==========================================
# التسجيل (Log)
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger(__name__)


# ==========================================
# إشارة الإيقاف
# ==========================================
running = True

def signal_handler(sig, frame):
    global running
    log.info("🛑 تم استلام إشارة الإيقاف...")
    running = False

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


# ==========================================
# تحميل الملفات
# ==========================================
def load_accounts():
    """تحميل الحسابات من accounts.json"""
    if not os.path.exists(ACCOUNTS_FILE):
        log.error(f"❌ ملف الحسابات غير موجود: {ACCOUNTS_FILE}")
        sys.exit(1)
    with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
        accounts = json.load(f)
    log.info(f"📋 تم تحميل {len(accounts)} حساب")
    return accounts


def load_transactions():
    """تحميل المعاملات من transactions.json"""
    if not os.path.exists(TRANSACTIONS_FILE):
        log.error(f"❌ ملف المعاملات غير موجود: {TRANSACTIONS_FILE}")
        sys.exit(1)
    with open(TRANSACTIONS_FILE, 'r', encoding='utf-8') as f:
        txs = json.load(f)
    pending = [t for t in txs if t.get('status', 'pending') == 'pending']
    log.info(f"📋 تم تحميل {len(pending)} معاملة (pending) من أصل {len(txs)}")
    return txs


def save_transactions(txs):
    """حفظ المعاملات بعد التحديث"""
    with open(TRANSACTIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(txs, f, ensure_ascii=False, indent=2)


def get_account_by_name(accounts, name):
    """إيجاد حساب بالاسم"""
    for acc in accounts:
        if acc['name'] == name:
            return acc
    return None


# ==========================================
# إنشاء جلسة
# ==========================================
def create_session(acc):
    """إنشاء جلسة requests بكوكيز الحساب"""
    s = requests.Session()
    s.verify = False
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 Chrome/146.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "ar",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": BOOKING_PAGE_URL,
    })
    for c in acc.get('cookies', []):
        s.cookies.set(c['name'], c['value'], domain=c.get('domain', ''))
    return s


# ==========================================
# البحث عن الفلاح
# ==========================================
def search_farmer(session, name, center_id, silo_id, is_outer):
    """بحث عن الفلاح بالاسم"""
    parts = name.strip().split()
    queries = [name]
    if len(parts) > 1:
        queries.append(parts[0])
        queries.append(" ".join(parts[:2]))

    for q in queries:
        try:
            params = {
                "marketingCenterId": center_id,
                "siloId": silo_id,
                "hasOtherSiloApproval": "false",
                "isOuterPlanReservation": is_outer,
                "q": q,
                "limit": 50
            }
            res = session.get(SEARCH_API_URL, params=params, timeout=60)
            if res.status_code == 200:
                results = res.json().get("results", [])
                if results:
                    for r in results:
                        if name in r.get("text", ""):
                            return r.get("id"), r.get("text", "")
                    return results[0].get("id"), results[0].get("text", "")
        except Exception:
            continue
    return None, None


# ==========================================
# إرسال الحجز
# ==========================================
def submit_booking(session, token, farmer_id, silo_id, is_outer):
    """إرسال طلب الحجز"""
    payload = {
        "__RequestVerificationToken": token,
        "FarmerId": farmer_id,
        "SiloId": silo_id,
        "HasOtherSiloApproval": "false",
        "IsOuterPlanReservation": is_outer,
        "SelectedMarketingReservedDayNum": "",
        "HasVehicleInfo": "false",
        "VehicleLetter": "",
        "VehicleNumber": "",
        "VehicleGovernorate": "",
        "VehicleNumberGovernorate": "",
        "PlateType": "",
        "DriverName": "",
        "VehicleType": ""
    }
    try:
        res = session.post(BOOKING_POST_URL, data=payload, timeout=60)
        if res.status_code == 200:
            try:
                result = res.json()
                if result.get("success"):
                    return True, result.get("id", "OK")
                return False, result.get("message", "خطأ غير معروف")
            except Exception:
                if "Print" in res.url or "MyReservations" in res.url:
                    return True, "redirect_success"
        return False, f"HTTP {res.status_code}"
    except Exception as e:
        return False, str(e)


# ==========================================
# محاولة حجز معاملة واحدة
# ==========================================
def try_book_one(tx, accounts):
    """محاولة حجز معاملة واحدة. يرجع True عند النجاح."""
    name = tx['client_name']
    silo_id = tx['silo_id']
    center_id = tx['center_id']
    is_outer = tx.get('is_outer', 'false')
    account_name = tx['account_name']

    acc = get_account_by_name(accounts, account_name)
    if not acc:
        log.warning(f"⚠️ حساب ({account_name}) غير موجود!")
        return False
    if not acc.get('cookies'):
        log.warning(f"⚠️ [{account_name}] بدون كوكيز!")
        return False
    if not acc.get('token'):
        log.warning(f"⚠️ [{account_name}] بدون توكن!")
        return False

    session = create_session(acc)
    token = acc['token']

    # فحص الحصص
    log.info(f"🔍 [{account_name}] فحص ({silo_id}) - {name}")
    try:
        sr = session.get(SLOTS_API_URL,
            params={"siloId": silo_id, "isOuterPlanReservation": is_outer},
            timeout=60)
    except Exception as e:
        log.warning(f"⚠️ اتصال: {e}")
        return False

    if sr.status_code == 401:
        log.error(f"❌ جلسة منتهية [{account_name}]!")
        return False

    days = sr.json() if sr.status_code == 200 else []
    if not any(d.get("isSelectable") for d in days):
        log.info(f"⏳ لا حصص ({silo_id}) [{account_name}]")
        return False

    # حصة متاحة!
    log.info(f"🎯 حصة متاحة! [{account_name}] بحث ({name})...")
    fid, fname = search_farmer(session, name, center_id, silo_id, is_outer)
    if not fid:
        log.warning(f"⚠️ ({name}) غير موجود في اللائحة!")
        return False

    log.info(f"✅ {fname} → إرسال حجز...")
    ok, detail = submit_booking(session, token, fid, silo_id, is_outer)

    if ok:
        log.info(f"🎉🎉🎉 تم الحجز: {fname} [{account_name}] ({detail})")
        return True
    else:
        log.error(f"❌ فشل: {detail}")
        if "token" in detail.lower() or "verification" in detail.lower():
            log.error(f"⚠️ التوكن منتهي [{account_name}]!")
        return False


# ==========================================
# المحرك الرئيسي
# ==========================================
def main():
    global running

    # حفظ PID
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

    log.info("=" * 50)
    log.info("🚀 بوت الحجز - نسخة Termux")
    log.info(f"⏱️  التأخير: {MIN_DELAY}-{MAX_DELAY} ثانية")
    log.info(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 50)

    accounts = load_accounts()
    all_txs = load_transactions()

    current_index = 0

    while running:
        # إعادة تحميل المعاملات (لو تم تعديلها)
        try:
            all_txs = load_transactions()
        except Exception:
            pass

        pending = [t for t in all_txs if t.get('status', 'pending') == 'pending']

        if not pending:
            delay = random.uniform(MIN_DELAY, MAX_DELAY)
            log.info(f"🔄 لا معاملات pending. انتظار {delay:.1f}ث...")
            time.sleep(delay)
            continue

        # دورة: معاملة واحدة بالترتيب
        if current_index >= len(pending):
            current_index = 0

        tx = pending[current_index]
        current_index += 1

        success = try_book_one(tx, accounts)

        if success:
            # تحديث الحالة
            tx['status'] = 'booked'
            tx['booked_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            save_transactions(all_txs)

            # عند نجاح حجز → إرسال لكل المتبقية (burst)
            remaining = [t for t in all_txs if t.get('status', 'pending') == 'pending']
            if remaining:
                log.info(f"🚀 حجز ناجح! إرسال burst لـ {len(remaining)} معاملة...")
                for rtx in remaining:
                    if not running:
                        break
                    r_success = try_book_one(rtx, accounts)
                    if r_success:
                        rtx['status'] = 'booked'
                        rtx['booked_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        save_transactions(all_txs)
                    time.sleep(0.3)  # تأخير بسيط بين الطلبات في burst

            current_index = 0

        # تأخير عشوائي
        if running:
            delay = random.uniform(MIN_DELAY, MAX_DELAY)
            time.sleep(delay)

    # تنظيف
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)
    log.info("🛑 تم إيقاف المحرك.")


if __name__ == '__main__':
    main()
