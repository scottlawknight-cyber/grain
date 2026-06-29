"""
بوت الحجز التلقائي الذكي - نظام حجز الحبوب العراقي
الإصدار: 2026.06.30
الميزات:
- نظام حسابات متعددة (كل توكن = حساب باسم)
- اختيار حساب لكل معاملة
- زر إرسال مباشر (حجز فوري بدون انتظار المحرك)
- رانج مدة عشوائية للمحرك بين الفحوصات
- إلغاء SSL Verify
- سحب التوكن من المتصفح (يدوي)
- قوائم جاهزة + جلب من السيرفر
"""
import sys
import os
import json
import time
import random
import sqlite3
import logging
import urllib3
import requests
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from webdriver_manager.chrome import ChromeDriverManager

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QTextEdit, QTabWidget,
    QFormLayout, QMessageBox, QHeaderView, QCheckBox,
    QComboBox, QGroupBox, QProgressBar, QSpinBox,
    QInputDialog, QListWidget, QListWidgetItem, QSplitter
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt

# إلغاء تحذيرات SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ==========================================
# إعدادات الروابط
# ==========================================
BASE_URL = "https://hajz.grainboardiq.com"
LOGIN_URL = f"{BASE_URL}/Identity/Account/DriverLogin?returnUrl=%2F"
BOOKING_PAGE_URL = f"{BASE_URL}/Reservation/Create"
BOOKING_POST_URL = f"{BASE_URL}/Reservation/CreateReservation"
SEARCH_API_URL = f"{BASE_URL}/api/LocationApi/SearchFarmersByMarketingCenter"
SLOTS_API_URL = f"{BASE_URL}/Reservation/GetReservationDayOptions"
DIRECTORATES_API = f"{BASE_URL}/api/LocationApi/GetDirectoratesByGovernorate"
CENTERS_API = f"{BASE_URL}/api/LocationApi/GetMarketingCentersByDirectorate"
SILOS_API = f"{BASE_URL}/api/LocationApi/GetSilosByMarketingCenter"

# ==========================================
# القوائم الجاهزة
# ==========================================
GOVERNORATES = [
    {"id": "12", "name": "اربيل", "outer": "false"},
    {"id": "11", "name": "السليمانية", "outer": "false"},
    {"id": "13", "name": "حلبجة", "outer": "false"},
    {"id": "14", "name": "دهوك", "outer": "false"},
    {"id": "16", "name": "صلاح الدين", "outer": "false"},
    {"id": "15", "name": "كركوك", "outer": "true"},
    {"id": "2", "name": "نينوى", "outer": "true"},
]

# ==========================================
# ملف الحسابات
# ==========================================
ACCOUNTS_FILE = "accounts.json"



# ==========================================
# إدارة الحسابات
# ==========================================
def load_accounts():
    """تحميل الحسابات من الملف"""
    if os.path.exists(ACCOUNTS_FILE):
        with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def save_accounts(accounts):
    """حفظ الحسابات إلى الملف"""
    with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2)


def get_account_by_name(name):
    """إيجاد حساب بالاسم"""
    accounts = load_accounts()
    for acc in accounts:
        if acc['name'] == name:
            return acc
    return None


# ==========================================
# دالة إنشاء جلسة مع إلغاء SSL
# ==========================================
def create_session():
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
    return s


def load_cookies_to_session(session, cookies_list):
    """تحميل كوكيز من قائمة إلى الجلسة"""
    for c in cookies_list:
        session.cookies.set(c['name'], c['value'], domain=c.get('domain', ''))
    return True



# ==========================================
# Logging Handler
# ==========================================
class SignallingLogHandler(logging.Handler):
    def __init__(self, signal):
        super().__init__()
        self.signal = signal

    def emit(self, record):
        self.signal.emit(self.format(record))


# ==========================================
# تسجيل الدخول + سحب التوكن من المتصفح
# ==========================================
class BrowserWorker(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)  # success, account_name

    def __init__(self, mode="login", account_name=""):
        super().__init__()
        self.mode = mode
        self.account_name = account_name
        self.driver = None

    def run(self):
        options = uc.ChromeOptions()
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--ignore-ssl-errors")
        options.add_experimental_option("prefs", {
            "profile.default_content_setting_values.popups": 1,
        })
        try:
            self.log_signal.emit("🔍 جاري تشغيل المتصفح...")
            driver_path = ChromeDriverManager().install()
            driver = uc.Chrome(driver_executable_path=driver_path, options=options)
            if self.mode == "token":
                self._extract_token(driver)
            else:
                self._do_login(driver)
        except Exception as e:
            self.log_signal.emit(f"❌ خطأ: {str(e)}")
            self.finished_signal.emit(False, self.account_name)


    def _do_login(self, driver):
        """تسجيل الدخول عبر تلجرام وحفظ الكوكيز للحساب"""
        self.log_signal.emit(f"🌐 تسجيل دخول للحساب: {self.account_name}")
        driver.get(LOGIN_URL)

        POPUP_SCRIPT = """
        (function() {
            var orig = window.open;
            window.open = function(url, name, features) {
                if (url && (url.indexOf('oauth') !== -1 || url.indexOf('telegram') !== -1)) {
                    window.location.href = url; return window;
                }
                return orig.call(window, url, '_blank', '');
            };
        })();
        """
        try:
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": POPUP_SCRIPT})
        except Exception:
            pass
        driver.execute_script(POPUP_SCRIPT)

        self.log_signal.emit("⏳ بانتظار إتمام تسجيل الدخول... (لا تغلق المتصفح)")
        max_wait = 300
        start = time.time()
        confirmed = False

        while (time.time() - start) < max_wait:
            try:
                handles = driver.window_handles
                if not handles:
                    time.sleep(2); continue
                for handle in handles:
                    try:
                        driver.switch_to.window(handle)
                    except Exception:
                        continue
                    for c in driver.get_cookies():
                        if c['name'] == '.AspNetCore.Identity.Application' and len(c.get('value', '')) > 50:
                            confirmed = True; break
                    if confirmed: break
                if confirmed: break
            except Exception:
                pass
            time.sleep(2)

        if confirmed:
            time.sleep(3)
            all_cookies = []
            for handle in driver.window_handles:
                try:
                    driver.switch_to.window(handle)
                    all_cookies.extend(driver.get_cookies())
                except Exception:
                    pass
            seen = set()
            unique = []
            for c in all_cookies:
                if c['name'] not in seen:
                    seen.add(c['name']); unique.append(c)

            # حفظ الكوكيز في الحساب
            accounts = load_accounts()
            found = False
            for acc in accounts:
                if acc['name'] == self.account_name:
                    acc['cookies'] = unique
                    found = True; break
            if not found:
                accounts.append({'name': self.account_name, 'cookies': unique, 'token': ''})
            save_accounts(accounts)

            self.log_signal.emit(f"✅ تم حفظ الكوكيز للحساب ({self.account_name})! العدد: {len(unique)}")
            self.driver = driver
            self.finished_signal.emit(True, self.account_name)
        else:
            self.log_signal.emit("⚠️ انتهت المهلة.")
            self.driver = driver
            self.finished_signal.emit(False, self.account_name)


    def _extract_token(self, driver):
        """سحب التوكن من المتصفح وحفظه للحساب"""
        self.log_signal.emit(f"🔑 سحب التوكن للحساب: {self.account_name}")
        acc = get_account_by_name(self.account_name)
        if not acc or not acc.get('cookies'):
            self.log_signal.emit("❌ لا توجد كوكيز لهذا الحساب! سجل الدخول أولاً.")
            self.finished_signal.emit(False, self.account_name)
            return

        driver.get(BASE_URL)
        time.sleep(2)
        for c in acc['cookies']:
            cookie_dict = {'name': c['name'], 'value': c['value'],
                           'domain': c.get('domain', '.grainboardiq.com')}
            if 'path' in c:
                cookie_dict['path'] = c['path']
            try:
                driver.add_cookie(cookie_dict)
            except Exception:
                pass

        driver.get(BOOKING_PAGE_URL)
        time.sleep(3)
        page_source = driver.page_source
        soup = BeautifulSoup(page_source, 'html.parser')
        token_input = soup.find('input', {'name': '__RequestVerificationToken'})

        if token_input:
            token = token_input['value']
            accounts = load_accounts()
            for a in accounts:
                if a['name'] == self.account_name:
                    a['token'] = token; break
            save_accounts(accounts)
            self.log_signal.emit(f"✅ تم حفظ التوكن للحساب ({self.account_name})")
            self.log_signal.emit(f"🔑 التوكن: {token[:50]}...")
            self.driver = driver
            self.finished_signal.emit(True, self.account_name)
        else:
            self.log_signal.emit("❌ فشل سحب التوكن - تأكد من صلاحية الجلسة")
            self.driver = driver
            self.finished_signal.emit(False, self.account_name)



# ==========================================
# جلب البيانات من الموقع
# ==========================================
class DataFetchWorker(QThread):
    result_signal = pyqtSignal(str, list)
    error_signal = pyqtSignal(str)

    def __init__(self, fetch_type, params=None, account_name=""):
        super().__init__()
        self.fetch_type = fetch_type
        self.params = params or {}
        self.account_name = account_name
        self.session = create_session()
        # تحميل كوكيز الحساب المحدد
        acc = get_account_by_name(self.account_name)
        if acc and acc.get('cookies'):
            load_cookies_to_session(self.session, acc['cookies'])

    def run(self):
        try:
            if self.fetch_type == "governorates":
                res = self.session.get(BOOKING_PAGE_URL, timeout=200)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, 'html.parser')
                    select = soup.find('select', {'id': 'modalGovernorateId'})
                    if select:
                        options = []
                        for opt in select.find_all('option'):
                            val = opt.get('value', '')
                            if val:
                                options.append({'id': val, 'name': opt.text.strip(),
                                                'outer': opt.get('data-enable-outer-plan', 'false')})
                        self.result_signal.emit("governorates", options)
                        return
                self.error_signal.emit("فشل جلب المحافظات من السيرفر")

            elif self.fetch_type == "directorates":
                res = self.session.get(DIRECTORATES_API,
                    params={"governorateId": self.params.get("governorateId")}, timeout=150)
                if res.status_code == 200:
                    self.result_signal.emit("directorates", res.json())
                else:
                    self.error_signal.emit("فشل جلب المديريات")

            elif self.fetch_type == "centers":
                res = self.session.get(CENTERS_API,
                    params={"directorateId": self.params.get("directorateId")}, timeout=150)
                if res.status_code == 200:
                    self.result_signal.emit("centers", res.json())
                else:
                    self.error_signal.emit("فشل جلب الشعب")

            elif self.fetch_type == "silos":
                res = self.session.get(SILOS_API,
                    params={"marketingCenterId": self.params.get("marketingCenterId")}, timeout=150)
                if res.status_code == 200:
                    self.result_signal.emit("silos", res.json())
                else:
                    self.error_signal.emit("فشل جلب السايلوات")

            elif self.fetch_type == "farmers":
                params = {
                    "marketingCenterId": self.params.get("marketingCenterId"),
                    "siloId": self.params.get("siloId"),
                    "hasOtherSiloApproval": "false",
                    "isOuterPlanReservation": self.params.get("isOuter", "false"),
                    "q": self.params.get("query", "ا"),
                    "limit": 50
                }
                res = self.session.get(SEARCH_API_URL, params=params, timeout=200)
                if res.status_code == 200:
                    self.result_signal.emit("farmers", res.json().get("results", []))
                else:
                    self.error_signal.emit("فشل جلب الفلاحين")

        except Exception as e:
            self.error_signal.emit(f"خطأ اتصال: {str(e)}")



# ==========================================
# عامل الإرسال المباشر (حجز فوري)
# ==========================================
class DirectSendWorker(QThread):
    log_signal = pyqtSignal(str)
    done_signal = pyqtSignal(bool, int)  # success, tx_id

    def __init__(self, tx_id, client_name, silo_id, center_id, is_outer, account_name):
        super().__init__()
        self.tx_id = tx_id
        self.client_name = client_name
        self.silo_id = silo_id
        self.center_id = center_id
        self.is_outer = is_outer
        self.account_name = account_name
        self.session = create_session()

    def run(self):
        acc = get_account_by_name(self.account_name)
        if not acc:
            self.log_signal.emit(f"❌ الحساب ({self.account_name}) غير موجود!")
            self.done_signal.emit(False, self.tx_id); return
        if not acc.get('cookies'):
            self.log_signal.emit(f"❌ لا كوكيز للحساب ({self.account_name})!")
            self.done_signal.emit(False, self.tx_id); return
        if not acc.get('token'):
            self.log_signal.emit(f"❌ لا توكن للحساب ({self.account_name})! اسحبه من المتصفح.")
            self.done_signal.emit(False, self.tx_id); return

        load_cookies_to_session(self.session, acc['cookies'])
        token = acc['token']

        self.log_signal.emit(f"🔍 بحث عن ({self.client_name})...")
        fid, fname = self._search_farmer()
        if not fid:
            self.log_signal.emit(f"⚠️ ({self.client_name}) غير موجود!")
            self.done_signal.emit(False, self.tx_id); return

        self.log_signal.emit(f"✅ {fname} → إرسال حجز مباشر...")
        ok, detail = self._submit(token, fid)
        if ok:
            self.log_signal.emit(f"🎉 تم الحجز المباشر: {fname} ({detail})")
            self.done_signal.emit(True, self.tx_id)
        else:
            self.log_signal.emit(f"❌ فشل الحجز المباشر: {detail}")
            self.done_signal.emit(False, self.tx_id)

    def _search_farmer(self):
        parts = self.client_name.strip().split()
        queries = [self.client_name]
        if len(parts) > 1:
            queries.append(parts[0])
            queries.append(" ".join(parts[:2]))
        for q in queries:
            try:
                params = {"marketingCenterId": self.center_id, "siloId": self.silo_id,
                          "hasOtherSiloApproval": "false",
                          "isOuterPlanReservation": self.is_outer, "q": q, "limit": 50}
                res = self.session.get(SEARCH_API_URL, params=params, timeout=200)
                if res.status_code == 200:
                    results = res.json().get("results", [])
                    if results:
                        for r in results:
                            if self.client_name in r.get("text", ""):
                                return r.get("id"), r.get("text", "")
                        return results[0].get("id"), results[0].get("text", "")
            except Exception:
                continue
        return None, None

    def _submit(self, token, farmer_id):
        payload = {
            "__RequestVerificationToken": token,
            "FarmerId": farmer_id, "SiloId": self.silo_id,
            "HasOtherSiloApproval": "false",
            "IsOuterPlanReservation": self.is_outer,
            "SelectedMarketingReservedDayNum": "",
            "HasVehicleInfo": "false",
            "VehicleLetter": "", "VehicleNumber": "",
            "VehicleGovernorate": "", "VehicleNumberGovernorate": "",
            "PlateType": "", "DriverName": "", "VehicleType": ""
        }
        res = self.session.post(BOOKING_POST_URL, data=payload, timeout=200)
        if res.status_code == 200:
            try:
                result = res.json()
                if result.get("success"):
                    return True, result.get("id", "")
                return False, result.get("message", "خطأ")
            except Exception:
                if "Print" in res.url or "MyReservations" in res.url:
                    return True, ""
        return False, f"HTTP {res.status_code}"



# ==========================================
# محرك المراقبة والحجز (مع رانج عشوائي)
# ==========================================
class MonitoringWorker(QThread):
    log_signal = pyqtSignal(str)

    def __init__(self, db_name='alghanem_transactions.db', min_delay=5, max_delay=30):
        super().__init__()
        self.db_name = db_name
        self.running = True
        self.min_delay = min_delay
        self.max_delay = max_delay

    def stop(self):
        self.running = False

    def _get_delay(self):
        """مدة عشوائية بين min و max"""
        return random.randint(self.min_delay, self.max_delay)

    def run(self):
        self.log_signal.emit(f"🚀 المحرك يعمل (تأخير: {self.min_delay}-{self.max_delay} ثانية)... ✅")

        while self.running:
            try:
                conn = sqlite3.connect(self.db_name)
                txs = conn.cursor().execute(
                    "SELECT id, client_name, silo_id, center_id, is_outer, account_name "
                    "FROM transactions WHERE status = 'pending'").fetchall()
                conn.close()

                if not txs:
                    delay = self._get_delay()
                    self.log_signal.emit(f"🔄 لا معاملات. فحص بعد {delay} ثانية...")
                    time.sleep(delay)
                    continue

                for tx in txs:
                    if not self.running:
                        break
                    tx_id, name, silo_id, center_id, is_outer, account_name = tx

                    acc = get_account_by_name(account_name)
                    if not acc or not acc.get('cookies'):
                        self.log_signal.emit(f"⚠️ الحساب ({account_name}) بدون كوكيز!")
                        continue
                    if not acc.get('token'):
                        self.log_signal.emit(f"⚠️ الحساب ({account_name}) بدون توكن!")
                        continue

                    session = create_session()
                    load_cookies_to_session(session, acc['cookies'])

                    self.log_signal.emit(f"🔍 [{account_name}] فحص ({silo_id}) - {name}...")

                    try:
                        sr = session.get(SLOTS_API_URL,
                            params={"siloId": silo_id, "isOuterPlanReservation": is_outer},
                            timeout=300)
                    except Exception as e:
                        self.log_signal.emit(f"⚠️ اتصال: {e}")
                        continue

                    if sr.status_code == 401:
                        self.log_signal.emit(f"❌ الجلسة انتهت للحساب ({account_name})!")
                        continue

                    days = sr.json() if sr.status_code == 200 else []
                    if not any(d.get("isSelectable") for d in days):
                        self.log_signal.emit(f"⏳ لا حصص ({silo_id}) [{account_name}]")
                        continue

                    self.log_signal.emit(f"🎯 حصة متاحة! [{account_name}] بحث ({name})...")
                    fid, fname = self._search_farmer(session, name, center_id, silo_id, is_outer)
                    if not fid:
                        self.log_signal.emit(f"⚠️ ({name}) غير موجود!")
                        continue

                    self.log_signal.emit(f"✅ {fname} → إرسال حجز...")
                    token = acc['token']
                    ok, detail = self._submit(session, token, fid, silo_id, is_outer)

                    if ok:
                        self.log_signal.emit(f"🎉 تم الحجز: {fname} [{account_name}] ({detail})")
                        conn = sqlite3.connect(self.db_name)
                        conn.cursor().execute(
                            "UPDATE transactions SET status='booked' WHERE id=?", (tx_id,))
                        conn.commit(); conn.close()
                    else:
                        self.log_signal.emit(f"❌ فشل: {detail}")
                        if "token" in detail.lower() or "verification" in detail.lower():
                            self.log_signal.emit(f"⚠️ التوكن منتهي للحساب ({account_name})!")

                if self.running:
                    delay = self._get_delay()
                    self.log_signal.emit(f"⏱️ انتظار {delay} ثانية...")
                    time.sleep(delay)

            except Exception as e:
                self.log_signal.emit(f"⚠️ {str(e)}")
                time.sleep(15)


    def _search_farmer(self, session, name, center_id, silo_id, is_outer):
        parts = name.strip().split()
        queries = [name]
        if len(parts) > 1:
            queries.append(parts[0])
            queries.append(" ".join(parts[:2]))
        for q in queries:
            try:
                params = {"marketingCenterId": center_id, "siloId": silo_id,
                          "hasOtherSiloApproval": "false",
                          "isOuterPlanReservation": is_outer, "q": q, "limit": 50}
                res = session.get(SEARCH_API_URL, params=params, timeout=200)
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

    def _submit(self, session, token, farmer_id, silo_id, is_outer):
        payload = {
            "__RequestVerificationToken": token,
            "FarmerId": farmer_id, "SiloId": silo_id,
            "HasOtherSiloApproval": "false",
            "IsOuterPlanReservation": is_outer,
            "SelectedMarketingReservedDayNum": "",
            "HasVehicleInfo": "false",
            "VehicleLetter": "", "VehicleNumber": "",
            "VehicleGovernorate": "", "VehicleNumberGovernorate": "",
            "PlateType": "", "DriverName": "", "VehicleType": ""
        }
        res = session.post(BOOKING_POST_URL, data=payload, timeout=200)
        if res.status_code == 200:
            try:
                result = res.json()
                if result.get("success"):
                    return True, result.get("id", "")
                return False, result.get("message", "خطأ")
            except Exception:
                if "Print" in res.url or "MyReservations" in res.url:
                    return True, ""
        return False, f"HTTP {res.status_code}"



# ==========================================
# الواجهة الرسومية الرئيسية
# ==========================================
class AlGhanemBotGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db_name = 'alghanem_transactions.db'
        self._init_db()
        self.init_ui()
        handler = SignallingLogHandler(self.log_viewer.append)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s', '%H:%M:%S'))
        logging.getLogger().addHandler(handler)
        self.monitoring_thread = None
        self.browser_thread = None
        self.fetch_threads = []

    def _init_db(self):
        with sqlite3.connect(self.db_name) as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='transactions'")
            if cur.fetchone():
                cur.execute("PRAGMA table_info(transactions)")
                cols = [c[1] for c in cur.fetchall()]
                if 'account_name' not in cols:
                    cur.execute('DROP TABLE transactions')
            cur.execute('''CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_name TEXT NOT NULL,
                silo_id TEXT NOT NULL,
                center_id TEXT NOT NULL,
                is_outer TEXT DEFAULT 'false',
                account_name TEXT NOT NULL DEFAULT '',
                status TEXT DEFAULT 'pending'
            )''')
            conn.commit()


    def init_ui(self):
        self.setWindowTitle("مكتب الغانم - بوت الحجز v2026 (متعدد الحسابات)")
        self.resize(1050, 820)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.tab_accounts = QWidget()
        self.tab_engine = QWidget()
        self.tab_add = QWidget()
        self.tab_list = QWidget()
        self.tabs.addTab(self.tab_accounts, "👤 الحسابات")
        self.tabs.addTab(self.tab_engine, "🎮 المحرك")
        self.tabs.addTab(self.tab_add, "➕ إضافة معاملة")
        self.tabs.addTab(self.tab_list, "📋 المعاملات")

        self._setup_accounts_tab()
        self._setup_engine_tab()
        self._setup_add_tab()
        self._setup_list_tab()


    # ==========================================
    # تبويب الحسابات
    # ==========================================
    def _setup_accounts_tab(self):
        layout = QVBoxLayout(self.tab_accounts)

        layout.addWidget(QLabel("📋 الحسابات المسجلة (كل حساب = توكن + كوكيز مستقلة):"))

        self.accounts_list = QListWidget()
        self._refresh_accounts_list()
        layout.addWidget(self.accounts_list)

        # أزرار إدارة الحسابات
        btn_row1 = QHBoxLayout()
        self.btn_add_account = QPushButton("➕ إضافة حساب جديد")
        self.btn_add_account.setStyleSheet("background:#0d6efd;color:white;font-weight:bold;padding:10px;border-radius:5px;")
        self.btn_add_account.clicked.connect(self._add_account)

        self.btn_del_account = QPushButton("🗑️ حذف الحساب المحدد")
        self.btn_del_account.setStyleSheet("background:#dc3545;color:white;font-weight:bold;padding:10px;border-radius:5px;")
        self.btn_del_account.clicked.connect(self._delete_account)

        btn_row1.addWidget(self.btn_add_account)
        btn_row1.addWidget(self.btn_del_account)
        layout.addLayout(btn_row1)

        # أزرار تسجيل الدخول وسحب التوكن
        btn_row2 = QHBoxLayout()
        self.btn_login_account = QPushButton("🔐 تسجيل دخول للحساب المحدد")
        self.btn_login_account.setStyleSheet("background:#2b579a;color:white;font-weight:bold;padding:10px;border-radius:5px;")
        self.btn_login_account.clicked.connect(self._login_selected_account)

        self.btn_token_account = QPushButton("🔑 سحب التوكن للحساب المحدد")
        self.btn_token_account.setStyleSheet("background:#6f42c1;color:white;font-weight:bold;padding:10px;border-radius:5px;")
        self.btn_token_account.clicked.connect(self._token_selected_account)

        self.btn_close_browser = QPushButton("❌ إغلاق المتصفح")
        self.btn_close_browser.setStyleSheet("background:#dc3545;color:white;font-weight:bold;padding:10px;border-radius:5px;")
        self.btn_close_browser.clicked.connect(self._close_browser)
        self.btn_close_browser.setEnabled(False)

        btn_row2.addWidget(self.btn_login_account)
        btn_row2.addWidget(self.btn_token_account)
        btn_row2.addWidget(self.btn_close_browser)
        layout.addLayout(btn_row2)

        # حالة الحسابات
        self.lbl_account_status = QLabel("")
        layout.addWidget(self.lbl_account_status)


    def _refresh_accounts_list(self):
        self.accounts_list.clear()
        accounts = load_accounts()
        for acc in accounts:
            has_cookies = "✅ كوكيز" if acc.get('cookies') else "❌ لا كوكيز"
            has_token = "✅ توكن" if acc.get('token') else "❌ لا توكن"
            item = QListWidgetItem(f"  {acc['name']}  |  {has_cookies}  |  {has_token}")
            self.accounts_list.addItem(item)

    def _get_selected_account_name(self):
        item = self.accounts_list.currentItem()
        if not item:
            return None
        text = item.text().strip()
        # استخراج الاسم من النص
        name = text.split("|")[0].strip()
        return name

    def _add_account(self):
        name, ok = QInputDialog.getText(self, "حساب جديد", "اسم الحساب:")
        if ok and name.strip():
            name = name.strip()
            accounts = load_accounts()
            for a in accounts:
                if a['name'] == name:
                    QMessageBox.warning(self, "!", "الاسم موجود مسبقاً!")
                    return
            accounts.append({'name': name, 'cookies': [], 'token': ''})
            save_accounts(accounts)
            self._refresh_accounts_list()
            self.log_viewer.append(f"✅ تم إضافة الحساب: {name}")
            self._refresh_account_combos()

    def _delete_account(self):
        name = self._get_selected_account_name()
        if not name:
            QMessageBox.warning(self, "!", "اختر حساباً أولاً!"); return
        if QMessageBox.question(self, "؟", f"حذف الحساب ({name})؟") == QMessageBox.StandardButton.Yes:
            accounts = load_accounts()
            accounts = [a for a in accounts if a['name'] != name]
            save_accounts(accounts)
            self._refresh_accounts_list()
            self.log_viewer.append(f"🗑️ تم حذف الحساب: {name}")
            self._refresh_account_combos()

    def _login_selected_account(self):
        name = self._get_selected_account_name()
        if not name:
            QMessageBox.warning(self, "!", "اختر حساباً أولاً!"); return
        self.btn_login_account.setEnabled(False)
        self.browser_thread = BrowserWorker("login", name)
        self.browser_thread.log_signal.connect(self.log_viewer.append)
        self.browser_thread.finished_signal.connect(self._on_browser_done)
        self.browser_thread.start()

    def _token_selected_account(self):
        name = self._get_selected_account_name()
        if not name:
            QMessageBox.warning(self, "!", "اختر حساباً أولاً!"); return
        self.btn_token_account.setEnabled(False)
        self.browser_thread = BrowserWorker("token", name)
        self.browser_thread.log_signal.connect(self.log_viewer.append)
        self.browser_thread.finished_signal.connect(self._on_browser_done)
        self.browser_thread.start()

    def _on_browser_done(self, success, account_name):
        self.btn_login_account.setEnabled(True)
        self.btn_token_account.setEnabled(True)
        self.btn_close_browser.setEnabled(True)
        self._refresh_accounts_list()
        if success:
            self.log_viewer.append(f"✅ جاهز ({account_name})! اضغط 'إغلاق المتصفح' عند الانتهاء.")

    def _close_browser(self):
        if self.browser_thread and self.browser_thread.driver:
            try:
                self.browser_thread.driver.quit()
                self.browser_thread.driver = None
                self.log_viewer.append("✅ تم إغلاق المتصفح.")
            except Exception as e:
                self.log_viewer.append(f"⚠️ خطأ: {e}")
        else:
            self.log_viewer.append("ℹ️ لا يوجد متصفح مفتوح.")
        self.btn_close_browser.setEnabled(False)


    # ==========================================
    # تبويب المحرك
    # ==========================================
    def _setup_engine_tab(self):
        layout = QVBoxLayout(self.tab_engine)

        # رانج المدة العشوائية
        range_group = QGroupBox("⏱️ رانج المدة العشوائية بين الفحوصات (ثانية)")
        range_layout = QHBoxLayout(range_group)

        range_layout.addWidget(QLabel("الحد الأدنى:"))
        self.spin_min = QSpinBox()
        self.spin_min.setRange(1, 300)
        self.spin_min.setValue(5)
        range_layout.addWidget(self.spin_min)

        range_layout.addWidget(QLabel("الحد الأقصى:"))
        self.spin_max = QSpinBox()
        self.spin_max.setRange(1, 600)
        self.spin_max.setValue(30)
        range_layout.addWidget(self.spin_max)

        layout.addWidget(range_group)

        # أزرار التشغيل/الإيقاف
        row2 = QHBoxLayout()
        self.btn_start = QPushButton("▶️ تشغيل المحرك")
        self.btn_start.setStyleSheet("background:#107c41;color:white;font-weight:bold;padding:12px;border-radius:5px;")
        self.btn_start.clicked.connect(self._start_engine)

        self.btn_stop = QPushButton("⏹️ إيقاف")
        self.btn_stop.setStyleSheet("background:#a80000;color:white;font-weight:bold;padding:12px;border-radius:5px;")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_engine)

        row2.addWidget(self.btn_start)
        row2.addWidget(self.btn_stop)
        layout.addLayout(row2)

        layout.addWidget(QLabel("📺 سجل العمليات:"))
        self.log_viewer = QTextEdit()
        self.log_viewer.setReadOnly(True)
        self.log_viewer.setStyleSheet("background:#1e1e1e;color:#00ff00;font-family:Consolas;font-size:11pt;")
        layout.addWidget(self.log_viewer)


    # ==========================================
    # تبويب إضافة معاملة
    # ==========================================
    def _setup_add_tab(self):
        layout = QVBoxLayout(self.tab_add)

        # اختيار الحساب
        acc_group = QGroupBox("👤 اختيار الحساب للمعاملة")
        acc_layout = QHBoxLayout(acc_group)
        acc_layout.addWidget(QLabel("الحساب:"))
        self.cmb_account = QComboBox()
        self._refresh_account_combos()
        acc_layout.addWidget(self.cmb_account)
        layout.addWidget(acc_group)

        # القوائم المنسدلة
        loc_group = QGroupBox("📍 اختيار الموقع")
        loc_layout = QFormLayout(loc_group)

        btn_row = QHBoxLayout()
        self.btn_load_server = QPushButton("🌐 جلب من السيرفر")
        self.btn_load_server.setStyleSheet("background:#0078d4;color:white;font-weight:bold;padding:8px;border-radius:4px;")
        self.btn_load_server.clicked.connect(self._load_from_server)
        self.btn_load_local = QPushButton("📋 القوائم الجاهزة")
        self.btn_load_local.setStyleSheet("background:#6c757d;color:white;font-weight:bold;padding:8px;border-radius:4px;")
        self.btn_load_local.clicked.connect(self._load_local_govs)
        btn_row.addWidget(self.btn_load_server)
        btn_row.addWidget(self.btn_load_local)
        loc_layout.addRow(QLabel("المصدر:"), btn_row)

        self.cmb_gov = QComboBox()
        self.cmb_gov.addItem("-- اختر المحافظة --", "")
        self.cmb_gov.currentIndexChanged.connect(self._on_gov_changed)

        self.cmb_dir = QComboBox()
        self.cmb_dir.addItem("-- اختر المديرية --", "")
        self.cmb_dir.setEnabled(False)
        self.cmb_dir.currentIndexChanged.connect(self._on_dir_changed)

        self.cmb_center = QComboBox()
        self.cmb_center.addItem("-- اختر الشعبة --", "")
        self.cmb_center.setEnabled(False)
        self.cmb_center.currentIndexChanged.connect(self._on_center_changed)

        self.cmb_silo = QComboBox()
        self.cmb_silo.addItem("-- اختر السايلو --", "")
        self.cmb_silo.setEnabled(False)

        self.chk_outer = QCheckBox("حجز خارج الخطة")

        loc_layout.addRow("المحافظة:", self.cmb_gov)
        loc_layout.addRow("المديرية:", self.cmb_dir)
        loc_layout.addRow("الشعبة:", self.cmb_center)
        loc_layout.addRow("السايلو:", self.cmb_silo)
        loc_layout.addRow("", self.chk_outer)
        layout.addWidget(loc_group)

        # بحث الفلاح
        farmer_group = QGroupBox("👤 الفلاح")
        farmer_layout = QVBoxLayout(farmer_group)
        search_row = QHBoxLayout()
        self.input_farmer = QLineEdit()
        self.input_farmer.setPlaceholderText("اكتب جزءاً من الاسم...")
        self.btn_search = QPushButton("🔍 بحث")
        self.btn_search.setStyleSheet("background:#107c41;color:white;font-weight:bold;padding:8px;border-radius:4px;")
        self.btn_search.clicked.connect(self._search_farmers)
        search_row.addWidget(self.input_farmer)
        search_row.addWidget(self.btn_search)
        farmer_layout.addLayout(search_row)
        self.cmb_farmer = QComboBox()
        self.cmb_farmer.addItem("-- نتائج البحث --", "")
        self.cmb_farmer.setEnabled(False)
        farmer_layout.addWidget(self.cmb_farmer)
        layout.addWidget(farmer_group)

        # أزرار الحفظ والإرسال المباشر
        btns_row = QHBoxLayout()
        self.btn_save = QPushButton("💾 حفظ (انتظار المحرك)")
        self.btn_save.setStyleSheet("background:#0d6efd;color:white;font-weight:bold;padding:14px;border-radius:6px;font-size:11pt;")
        self.btn_save.clicked.connect(self._save_transaction)

        self.btn_direct_send = QPushButton("🚀 إرسال مباشر (حجز فوري)")
        self.btn_direct_send.setStyleSheet("background:#ff6600;color:white;font-weight:bold;padding:14px;border-radius:6px;font-size:11pt;")
        self.btn_direct_send.clicked.connect(self._direct_send)

        btns_row.addWidget(self.btn_save)
        btns_row.addWidget(self.btn_direct_send)
        layout.addLayout(btns_row)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self._load_local_govs()


    # ==========================================
    # تبويب المعاملات
    # ==========================================
    def _setup_list_tab(self):
        layout = QVBoxLayout(self.tab_list)
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["ID", "الفلاح", "السايلو", "الشعبة", "خارج الخطة", "الحساب", "الحالة"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        row = QHBoxLayout()
        btn_r = QPushButton("🔄 تحديث")
        btn_r.clicked.connect(self._refresh_table)

        btn_d = QPushButton("🗑️ حذف")
        btn_d.clicked.connect(self._delete_selected)

        self.btn_direct_from_list = QPushButton("🚀 إرسال مباشر للمحدد")
        self.btn_direct_from_list.setStyleSheet("background:#ff6600;color:white;font-weight:bold;padding:8px;border-radius:4px;")
        self.btn_direct_from_list.clicked.connect(self._direct_send_from_list)

        row.addWidget(btn_r)
        row.addWidget(btn_d)
        row.addWidget(self.btn_direct_from_list)
        layout.addLayout(row)
        self._refresh_table()


    # ==========================================
    # دوال مساعدة
    # ==========================================
    def _refresh_account_combos(self):
        """تحديث قوائم الحسابات في كل مكان"""
        accounts = load_accounts()
        if hasattr(self, 'cmb_account'):
            self.cmb_account.clear()
            self.cmb_account.addItem("-- اختر الحساب --", "")
            for acc in accounts:
                self.cmb_account.addItem(acc['name'], acc['name'])

    def _load_local_govs(self):
        self.cmb_gov.clear()
        self.cmb_gov.addItem("-- اختر المحافظة --", "")
        for g in GOVERNORATES:
            self.cmb_gov.addItem(g['name'], g['id'])
        self.log_viewer.append(f"📋 تم تحميل {len(GOVERNORATES)} محافظة (جاهزة)")

    def _load_from_server(self):
        acc_name = self.cmb_account.currentData()
        if not acc_name:
            QMessageBox.warning(self, "!", "اختر حساباً أولاً!"); return
        self.progress.setVisible(True); self.progress.setRange(0, 0)
        w = DataFetchWorker("governorates", account_name=acc_name)
        w.result_signal.connect(self._on_data)
        w.error_signal.connect(self._on_error)
        w.finished.connect(lambda: self.progress.setVisible(False))
        self.fetch_threads.append(w); w.start()

    def _on_gov_changed(self, idx):
        gov_id = self.cmb_gov.currentData()
        self.cmb_dir.clear()
        self.cmb_dir.addItem("-- اختر المديرية --", "")
        self.cmb_center.clear()
        self.cmb_center.addItem("-- اختر الشعبة --", "")
        self.cmb_silo.clear()
        self.cmb_silo.addItem("-- اختر السايلو --", "")
        self.cmb_dir.setEnabled(False)
        self.cmb_center.setEnabled(False)
        self.cmb_silo.setEnabled(False)
        if gov_id:
            acc_name = self.cmb_account.currentData() or ""
            self.progress.setVisible(True); self.progress.setRange(0, 0)
            w = DataFetchWorker("directorates", {"governorateId": gov_id}, acc_name)
            w.result_signal.connect(self._on_data)
            w.error_signal.connect(self._on_error)
            w.finished.connect(lambda: self.progress.setVisible(False))
            self.fetch_threads.append(w); w.start()

    def _on_dir_changed(self, idx):
        dir_id = self.cmb_dir.currentData()
        self.cmb_center.clear()
        self.cmb_center.addItem("-- اختر الشعبة --", "")
        self.cmb_silo.clear()
        self.cmb_silo.addItem("-- اختر السايلو --", "")
        self.cmb_center.setEnabled(False)
        self.cmb_silo.setEnabled(False)
        if dir_id:
            acc_name = self.cmb_account.currentData() or ""
            self.progress.setVisible(True); self.progress.setRange(0, 0)
            w = DataFetchWorker("centers", {"directorateId": dir_id}, acc_name)
            w.result_signal.connect(self._on_data)
            w.error_signal.connect(self._on_error)
            w.finished.connect(lambda: self.progress.setVisible(False))
            self.fetch_threads.append(w); w.start()

    def _on_center_changed(self, idx):
        center_id = self.cmb_center.currentData()
        self.cmb_silo.clear()
        self.cmb_silo.addItem("-- اختر السايلو --", "")
        self.cmb_silo.setEnabled(False)
        if center_id:
            acc_name = self.cmb_account.currentData() or ""
            self.progress.setVisible(True); self.progress.setRange(0, 0)
            w = DataFetchWorker("silos", {"marketingCenterId": center_id}, acc_name)
            w.result_signal.connect(self._on_data)
            w.error_signal.connect(self._on_error)
            w.finished.connect(lambda: self.progress.setVisible(False))
            self.fetch_threads.append(w); w.start()


    def _search_farmers(self):
        q = self.input_farmer.text().strip()
        center_id = self.cmb_center.currentData()
        silo_id = self.cmb_silo.currentData()
        acc_name = self.cmb_account.currentData()
        if not q:
            QMessageBox.warning(self, "!", "اكتب حرفاً على الأقل"); return
        if not center_id or not silo_id:
            QMessageBox.warning(self, "!", "اختر الشعبة والسايلو أولاً"); return
        if not acc_name:
            QMessageBox.warning(self, "!", "اختر حساباً أولاً!"); return
        is_outer = "true" if self.chk_outer.isChecked() else "false"
        self.progress.setVisible(True); self.progress.setRange(0, 0)
        w = DataFetchWorker("farmers", {
            "marketingCenterId": center_id, "siloId": silo_id,
            "isOuter": is_outer, "query": q
        }, acc_name)
        w.result_signal.connect(self._on_data)
        w.error_signal.connect(self._on_error)
        w.finished.connect(lambda: self.progress.setVisible(False))
        self.fetch_threads.append(w); w.start()

    def _on_data(self, dtype, data):
        if dtype == "governorates":
            self.cmb_gov.clear()
            self.cmb_gov.addItem("-- اختر المحافظة --", "")
            for item in data:
                self.cmb_gov.addItem(item['name'], item['id'])
            self.log_viewer.append(f"🌐 {len(data)} محافظة من السيرفر")
        elif dtype == "directorates":
            self.cmb_dir.clear()
            self.cmb_dir.addItem("-- اختر المديرية --", "")
            for item in data:
                self.cmb_dir.addItem(item.get('name', ''), str(item.get('id', '')))
            self.cmb_dir.setEnabled(True)
        elif dtype == "centers":
            self.cmb_center.clear()
            self.cmb_center.addItem("-- اختر الشعبة --", "")
            for item in data:
                self.cmb_center.addItem(item.get('name', ''), str(item.get('id', '')))
            self.cmb_center.setEnabled(True)
        elif dtype == "silos":
            self.cmb_silo.clear()
            self.cmb_silo.addItem("-- اختر السايلو --", "")
            for item in data:
                self.cmb_silo.addItem(item.get('name', ''), str(item.get('id', '')))
            self.cmb_silo.setEnabled(True)
        elif dtype == "farmers":
            self.cmb_farmer.clear()
            self.cmb_farmer.addItem("-- اختر الفلاح --", "")
            for item in data:
                self.cmb_farmer.addItem(item.get('text', ''), str(item.get('id', '')))
            self.cmb_farmer.setEnabled(bool(data))
            self.log_viewer.append(f"{'✅' if data else '⚠️'} {len(data)} نتيجة")

    def _on_error(self, msg):
        self.progress.setVisible(False)
        self.log_viewer.append(f"❌ {msg}")


    # ==========================================
    # حفظ المعاملة
    # ==========================================
    def _save_transaction(self):
        farmer_text = self.cmb_farmer.currentText()
        silo_id = self.cmb_silo.currentData()
        center_id = self.cmb_center.currentData()
        acc_name = self.cmb_account.currentData()
        is_outer = "true" if self.chk_outer.isChecked() else "false"

        if not farmer_text or farmer_text.startswith("--"):
            farmer_text = self.input_farmer.text().strip()
        if not farmer_text:
            QMessageBox.warning(self, "!", "اختر فلاحاً أو اكتب اسمه"); return
        if not silo_id or not center_id:
            QMessageBox.warning(self, "!", "اختر الشعبة والسايلو"); return
        if not acc_name:
            QMessageBox.warning(self, "!", "اختر حساباً!"); return

        with sqlite3.connect(self.db_name) as conn:
            conn.cursor().execute(
                "INSERT INTO transactions (client_name,silo_id,center_id,is_outer,account_name) VALUES(?,?,?,?,?)",
                (farmer_text, silo_id, center_id, is_outer, acc_name))
            conn.commit()
        QMessageBox.information(self, "✅", f"تم إضافة ({farmer_text}) للحساب ({acc_name})")
        self.input_farmer.clear()
        self._refresh_table()

    # ==========================================
    # إرسال مباشر (حجز فوري)
    # ==========================================
    def _direct_send(self):
        """إرسال مباشر من تبويب الإضافة"""
        farmer_text = self.cmb_farmer.currentText()
        silo_id = self.cmb_silo.currentData()
        center_id = self.cmb_center.currentData()
        acc_name = self.cmb_account.currentData()
        is_outer = "true" if self.chk_outer.isChecked() else "false"

        if not farmer_text or farmer_text.startswith("--"):
            farmer_text = self.input_farmer.text().strip()
        if not farmer_text:
            QMessageBox.warning(self, "!", "اختر فلاحاً أو اكتب اسمه"); return
        if not silo_id or not center_id:
            QMessageBox.warning(self, "!", "اختر الشعبة والسايلو"); return
        if not acc_name:
            QMessageBox.warning(self, "!", "اختر حساباً!"); return

        # حفظ كـ pending ثم إرسال فوري
        with sqlite3.connect(self.db_name) as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO transactions (client_name,silo_id,center_id,is_outer,account_name) VALUES(?,?,?,?,?)",
                (farmer_text, silo_id, center_id, is_outer, acc_name))
            conn.commit()
            tx_id = cur.lastrowid

        self._refresh_table()
        self._execute_direct_send(tx_id, farmer_text, silo_id, center_id, is_outer, acc_name)

    def _direct_send_from_list(self):
        """إرسال مباشر من الجدول"""
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "!", "اختر معاملة أولاً!"); return
        tx_id = int(self.table.item(row, 0).text())
        client_name = self.table.item(row, 1).text()
        silo_id = self.table.item(row, 2).text()
        center_id = self.table.item(row, 3).text()
        is_outer = self.table.item(row, 4).text()
        acc_name = self.table.item(row, 5).text()
        status = self.table.item(row, 6).text()

        if status == 'booked':
            QMessageBox.warning(self, "!", "هذه المعاملة محجوزة مسبقاً!"); return

        self._execute_direct_send(tx_id, client_name, silo_id, center_id, is_outer, acc_name)

    def _execute_direct_send(self, tx_id, client_name, silo_id, center_id, is_outer, acc_name):
        """تنفيذ الإرسال المباشر"""
        self.log_viewer.append(f"🚀 إرسال مباشر: {client_name} [{acc_name}]...")
        worker = DirectSendWorker(tx_id, client_name, silo_id, center_id, is_outer, acc_name)
        worker.log_signal.connect(self.log_viewer.append)
        worker.done_signal.connect(self._on_direct_done)
        self.fetch_threads.append(worker)
        worker.start()

    def _on_direct_done(self, success, tx_id):
        if success:
            with sqlite3.connect(self.db_name) as conn:
                conn.cursor().execute("UPDATE transactions SET status='booked' WHERE id=?", (tx_id,))
                conn.commit()
        self._refresh_table()


    # ==========================================
    # جدول المعاملات
    # ==========================================
    def _refresh_table(self):
        with sqlite3.connect(self.db_name) as conn:
            rows = conn.cursor().execute(
                "SELECT id,client_name,silo_id,center_id,is_outer,account_name,status "
                "FROM transactions ORDER BY id DESC").fetchall()
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                item.setFlags(item.flags() ^ Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, c, item)

    def _delete_selected(self):
        row = self.table.currentRow()
        if row < 0: return
        tx_id = self.table.item(row, 0).text()
        if QMessageBox.question(self, "؟", f"حذف {tx_id}؟") == QMessageBox.StandardButton.Yes:
            with sqlite3.connect(self.db_name) as conn:
                conn.cursor().execute("DELETE FROM transactions WHERE id=?", (tx_id,))
                conn.commit()
            self._refresh_table()

    # ==========================================
    # المحرك
    # ==========================================
    def _start_engine(self):
        min_d = self.spin_min.value()
        max_d = self.spin_max.value()
        if min_d > max_d:
            QMessageBox.warning(self, "!", "الحد الأدنى أكبر من الأقصى!"); return
        self.monitoring_thread = MonitoringWorker(self.db_name, min_d, max_d)
        self.monitoring_thread.log_signal.connect(self.log_viewer.append)
        self.monitoring_thread.start()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

    def _stop_engine(self):
        if self.monitoring_thread:
            self.monitoring_thread.stop()
            self.log_viewer.append("🛑 إيقاف المحرك.")
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)


# ==========================================
# التشغيل
# ==========================================
if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    gui = AlGhanemBotGUI()
    gui.show()
    sys.exit(app.exec())
