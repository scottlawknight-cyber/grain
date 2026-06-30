"""
بوت الحجز - نسخة Termux (موبايل)
=================================
كود بسيط جداً: يقرأ accounts.json + transactions.json ويشغل المحرك.
التأخير: 0.5 - 2 ثانية
"""
import os
import sys
import json
import time
import random
import signal
import requests
import urllib3
from datetime import datetime

urllib3.disable_warnings()

# ==========================================
# الروابط
# ==========================================
BASE = "https://hajz.grainboardiq.com"
BOOKING_URL = f"{BASE}/Reservation/Create"
POST_URL = f"{BASE}/Reservation/CreateReservation"
SEARCH_URL = f"{BASE}/api/LocationApi/SearchFarmersByMarketingCenter"
SLOTS_URL = f"{BASE}/Reservation/GetReservationDayOptions"

# ==========================================
# الملفات (نفس المجلد)
# ==========================================
ACCOUNTS_FILE = "accounts.json"
TRANSACTIONS_FILE = "transactions.json"
LOG_FILE = "engine.log"
PID_FILE = "engine.pid"

running = True

def stop(sig, frame):
    global running
    running = False
    print("\n🛑 إيقاف...")

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)


def log(msg):
    line = f"{datetime.now().strftime('%H:%M:%S')} | {msg}"
    print(line)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def make_session(acc):
    s = requests.Session()
    s.verify = False
    s.headers.update({
        "User-Agent": "Mozilla/5.0 Chrome/146.0.0.0",
        "Accept": "application/json, */*",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": BOOKING_URL,
    })
    for c in acc.get('cookies', []):
        s.cookies.set(c['name'], c['value'], domain=c.get('domain', ''))
    return s


def find_farmer(s, name, center, silo, outer):
    for q in [name, name.split()[0] if ' ' in name else name]:
        try:
            r = s.get(SEARCH_URL, params={
                "marketingCenterId": center, "siloId": silo,
                "hasOtherSiloApproval": "false",
                "isOuterPlanReservation": outer,
                "q": q, "limit": 50
            }, timeout=30)
            if r.status_code == 200:
                results = r.json().get("results", [])
                if results:
                    for x in results:
                        if name in x.get("text", ""):
                            return x["id"], x["text"]
                    return results[0]["id"], results[0]["text"]
        except:
            pass
    return None, None


def book(s, token, fid, silo, outer):
    try:
        r = s.post(POST_URL, data={
            "__RequestVerificationToken": token,
            "FarmerId": fid, "SiloId": silo,
            "HasOtherSiloApproval": "false",
            "IsOuterPlanReservation": outer,
            "SelectedMarketingReservedDayNum": "",
            "HasVehicleInfo": "false",
            "VehicleLetter": "", "VehicleNumber": "",
            "VehicleGovernorate": "", "VehicleNumberGovernorate": "",
            "PlateType": "", "DriverName": "", "VehicleType": ""
        }, timeout=30)
        if r.status_code == 200:
            j = r.json()
            if j.get("success"):
                return True, j.get("id", "OK")
            return False, j.get("message", "فشل")
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)


def try_one(tx, accounts):
    acc = next((a for a in accounts if a['name'] == tx['account_name']), None)
    if not acc or not acc.get('cookies') or not acc.get('token'):
        return False

    s = make_session(acc)

    try:
        r = s.get(SLOTS_URL, params={
            "siloId": tx['silo_id'],
            "isOuterPlanReservation": tx.get('is_outer', 'false')
        }, timeout=30)
    except:
        return False

    if r.status_code != 200:
        return False

    days = r.json()
    if not any(d.get("isSelectable") for d in days):
        log(f"⏳ لا حصص ({tx['silo_id']}) [{tx['account_name']}]")
        return False

    log(f"🎯 حصة! [{tx['account_name']}] {tx['client_name']}")
    fid, fname = find_farmer(s, tx['client_name'], tx['center_id'], tx['silo_id'], tx.get('is_outer','false'))
    if not fid:
        log(f"⚠️ لم يُعثر على: {tx['client_name']}")
        return False

    ok, detail = book(s, acc['token'], fid, tx['silo_id'], tx.get('is_outer','false'))
    if ok:
        log(f"🎉 تم الحجز: {fname} ({detail})")
        return True
    else:
        log(f"❌ فشل: {detail}")
        return False


# ==========================================
# المحرك
# ==========================================
def main():
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

    if not os.path.exists(ACCOUNTS_FILE):
        print(f"❌ ملف غير موجود: {ACCOUNTS_FILE}")
        sys.exit(1)
    if not os.path.exists(TRANSACTIONS_FILE):
        print(f"❌ ملف غير موجود: {TRANSACTIONS_FILE}")
        sys.exit(1)

    accounts = load_json(ACCOUNTS_FILE)
    log(f"🚀 المحرك يعمل | {len(accounts)} حساب")

    idx = 0

    while running:
        txs = load_json(TRANSACTIONS_FILE)
        pending = [t for t in txs if t.get('status','pending') == 'pending']

        if not pending:
            time.sleep(random.uniform(0.5, 2))
            continue

        if idx >= len(pending):
            idx = 0

        tx = pending[idx]
        idx += 1

        ok = try_one(tx, accounts)

        if ok:
            tx['status'] = 'booked'
            tx['booked_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            save_json(TRANSACTIONS_FILE, txs)

            # burst: إرسال لكل المتبقية
            for t in txs:
                if not running:
                    break
                if t.get('status','pending') == 'pending':
                    if try_one(t, accounts):
                        t['status'] = 'booked'
                        t['booked_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        save_json(TRANSACTIONS_FILE, txs)
                    time.sleep(0.3)
            idx = 0

        if running:
            time.sleep(random.uniform(0.5, 2))

    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)
    log("🛑 توقف.")


if __name__ == '__main__':
    main()
