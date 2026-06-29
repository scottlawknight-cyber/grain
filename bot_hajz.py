"""
بوت الحجز التلقائي الذكي - نظام حجز الحبوب العراقي
الإصدار: 2026.06.30
- إلغاء SSL Verify لحل مشكلة الشهادة
- زر سحب التوكن من المتصفح (يدوي)
- قوائم جاهزة + خيار جلب من السيرفر
"""
import sys
import json
import time
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
    QComboBox, QGroupBox, QProgressBar
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
# القوائم الجاهزة (من الموقع مباشرة)
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
# دالة إنشاء جلسة مع إلغاء SSL
# ==========================================
def create_session():
    """إنشاء جلسة requests مع إلغاء التحقق من SSL"""
    s = requests.Session()
    s.verify = False  # إلغاء SSL Verify
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 Chrome/146.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "ar",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": BOOKING_PAGE_URL,
    })
    return s


def load_cookies_to_session(session):
    """تحميل الكوكيز من الملف إلى الجلسة"""
    try:
        with open('cookies.json', 'r', encoding='utf-8') as f:
            cookies = json.load(f)
            for c in cookies:
                session.cookies.set(c['name'], c['value'],
                                    domain=c.get('domain', ''))
        return True
    except FileNotFoundError:
        return False


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
# تسجيل الدخول عبر تلجرام + سحب التوكن من المتصفح
# ==========================================
class BrowserWorker(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool)

    def __init__(self, mode="login"):
        """mode: 'login' لتسجيل الدخول, 'token' لسحب التوكن"""
        super().__init__()
        self.mode = mode

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
            self.finished_signal.emit(False)

    def _do_login(self, driver):
        """تسجيل الدخول عبر تلجرام"""
        self.log_signal.emit("🌐 تم فتح المتصفح. سجل الدخول عبر تلجرام.")
        driver.get(LOGIN_URL)

        # حقن سكريبت لمنع المنبثقات الخارجية
        POPUP_SCRIPT = """
        (function() {
            var orig = window.open;
            window.open = function(url, name, features) {
                if (url && (url.indexOf('oauth') !== -1 ||
                    url.indexOf('telegram') !== -1)) {
                    window.location.href = url;
                    return window;
                }
                return orig.call(window, url, '_blank', '');
            };
        })();
        """
        try:
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument",
                                   {"source": POPUP_SCRIPT})
        except Exception:
            pass
        driver.execute_script(POPUP_SCRIPT)

        self.log_signal.emit("⏳ بانتظار إتمام تسجيل الدخول... (لا تغلق المتصفح)")

        # انتظار كوكي المصادقة
        max_wait = 300
        start = time.time()
        confirmed = False

        while (time.time() - start) < max_wait:
            try:
                handles = driver.window_handles
                if not handles:
                    time.sleep(2)
                    continue
                for handle in handles:
                    try:
                        driver.switch_to.window(handle)
                    except Exception:
                        continue
                    for c in driver.get_cookies():
                        if (c['name'] == '.AspNetCore.Identity.Application'
                                and len(c.get('value', '')) > 50):
                            confirmed = True
                            break
                    if confirmed:
                        break
                if confirmed:
                    break
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
                    seen.add(c['name'])
                    unique.append(c)

            with open('cookies.json', 'w', encoding='utf-8') as f:
                json.dump(unique, f, ensure_ascii=False, indent=2)

            self.log_signal.emit(f"✅ تم استخراج الكوكيز بنجاح! العدد: {len(unique)}")
            self.finished_signal.emit(True)
        else:
            self.log_signal.emit("⚠️ انتهت المهلة. حاول مرة أخرى.")
            self.finished_signal.emit(False)

        try:
            driver.quit()
        except Exception:
            pass

    def _extract_token(self, driver):
        """سحب التوكن من المتصفح عبر فتح صفحة الحجز"""
        self.log_signal.emit("🔑 جاري فتح صفحة الحجز لسحب التوكن...")

        # تحميل الكوكيز المحفوظة للمتصفح
        driver.get(BASE_URL)
        time.sleep(2)

        try:
            with open('cookies.json', 'r', encoding='utf-8') as f:
                cookies = json.load(f)
                for c in cookies:
                    cookie_dict = {
                        'name': c['name'],
                        'value': c['value'],
                        'domain': c.get('domain', '.grainboardiq.com'),
                    }
                    if 'path' in c:
                        cookie_dict['path'] = c['path']
                    try:
                        driver.add_cookie(cookie_dict)
                    except Exception:
                        pass
        except Exception:
            pass

        driver.get(BOOKING_PAGE_URL)
        time.sleep(3)

        # استخراج التوكن من الصفحة
        page_source = driver.page_source
        soup = BeautifulSoup(page_source, 'html.parser')
        token_input = soup.find('input', {'name': '__RequestVerificationToken'})

        if token_input:
            token = token_input['value']
            with open('token.txt', 'w', encoding='utf-8') as f:
                f.write(token)
            self.log_signal.emit(f"✅ تم سحب التوكن بنجاح! (محفوظ في token.txt)")
            self.log_signal.emit(f"🔑 التوكن: {token[:50]}...")
            self.finished_signal.emit(True)
        else:
            self.log_signal.emit("❌ فشل سحب التوكن - تأكد من صلاحية الجلسة")
            self.finished_signal.emit(False)

        try:
            driver.quit()
        except Exception:
            pass



# ==========================================
# جلب البيانات من الموقع (مع إلغاء SSL)
# ==========================================
class DataFetchWorker(QThread):
    result_signal = pyqtSignal(str, list)
    error_signal = pyqtSignal(str)

    def __init__(self, fetch_type, params=None):
        super().__init__()
        self.fetch_type = fetch_type
        self.params = params or {}
        self.session = create_session()
        load_cookies_to_session(self.session)

    def run(self):
        try:
            if self.fetch_type == "governorates":
                res = self.session.get(BOOKING_PAGE_URL, timeout=15)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, 'html.parser')
                    select = soup.find('select', {'id': 'modalGovernorateId'})
                    if select:
                        options = []
                        for opt in select.find_all('option'):
                            val = opt.get('value', '')
                            if val:
                                options.append({
                                    'id': val,
                                    'name': opt.text.strip(),
                                    'outer': opt.get('data-enable-outer-plan', 'false')
                                })
                        self.result_signal.emit("governorates", options)
                        return
                self.error_signal.emit("فشل جلب المحافظات من السيرفر")

            elif self.fetch_type == "directorates":
                res = self.session.get(DIRECTORATES_API,
                    params={"governorateId": self.params.get("governorateId")}, timeout=10)
                if res.status_code == 200:
                    self.result_signal.emit("directorates", res.json())
                else:
                    self.error_signal.emit("فشل جلب المديريات")

            elif self.fetch_type == "centers":
                res = self.session.get(CENTERS_API,
                    params={"directorateId": self.params.get("directorateId")}, timeout=10)
                if res.status_code == 200:
                    self.result_signal.emit("centers", res.json())
                else:
                    self.error_signal.emit("فشل جلب الشعب")

            elif self.fetch_type == "silos":
                res = self.session.get(SILOS_API,
                    params={"marketingCenterId": self.params.get("marketingCenterId")}, timeout=10)
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
                res = self.session.get(SEARCH_API_URL, params=params, timeout=15)
                if res.status_code == 200:
                    self.result_signal.emit("farmers", res.json().get("results", []))
                else:
                    self.error_signal.emit("فشل جلب الفلاحين")

        except Exception as e:
            self.error_signal.emit(f"خطأ اتصال: {str(e)}")



# ==========================================
# محرك المراقبة والحجز (مع إلغاء SSL + توكن من ملف)
# ==========================================
class MonitoringWorker(QThread):
    log_signal = pyqtSignal(str)

    def __init__(self, db_name='alghanem_transactions.db'):
        super().__init__()
        self.db_name = db_name
        self.running = True
        self.session = create_session()

    def stop(self):
        self.running = False

    def search_farmer(self, name, center_id, silo_id, is_outer):
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
                    "q": q, "limit": 50
                }
                res = self.session.get(SEARCH_API_URL, params=params, timeout=15)
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

    def get_token(self):
        """سحب التوكن من الملف المحفوظ (المستخرج بالمتصفح)"""
        try:
            with open('token.txt', 'r', encoding='utf-8') as f:
                token = f.read().strip()
                if token:
                    return token
        except FileNotFoundError:
            pass
        # fallback: سحب من requests
        try:
            res = self.session.get(BOOKING_PAGE_URL, timeout=15)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, 'html.parser')
                inp = soup.find('input', {'name': '__RequestVerificationToken'})
                if inp:
                    return inp['value']
        except Exception:
            pass
        return None

    def submit_booking(self, token, farmer_id, silo_id, is_outer):
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
        res = self.session.post(BOOKING_POST_URL, data=payload, timeout=20)
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

    def run(self):
        if not load_cookies_to_session(self.session):
            self.log_signal.emit("❌ ملف الكوكيز غير موجود!")
            return

        # التحقق من الجلسة
        try:
            res = self.session.get(BOOKING_PAGE_URL, timeout=10, allow_redirects=False)
            if res.status_code == 302 and "login" in res.headers.get("Location", "").lower():
                self.log_signal.emit("❌ الجلسة منتهية! جدد الكوكيز.")
                return
        except Exception as e:
            self.log_signal.emit(f"❌ خطأ اتصال: {e}")
            return

        self.log_signal.emit("🚀 المحرك يعمل (24/7)... ✅")

        while self.running:
            try:
                conn = sqlite3.connect(self.db_name)
                txs = conn.cursor().execute(
                    "SELECT id, client_name, silo_id, center_id, is_outer "
                    "FROM transactions WHERE status = 'pending'").fetchall()
                conn.close()

                if not txs:
                    self.log_signal.emit("🔄 لا معاملات. فحص بعد 30 ثانية...")
                    time.sleep(30)
                    continue

                for tx in txs:
                    if not self.running: break
                    tx_id, name, silo_id, center_id, is_outer = tx
                    self.log_signal.emit(f"🔍 فحص ({silo_id}) - {name}...")

                    try:
                        sr = self.session.get(SLOTS_API_URL,
                            params={"siloId": silo_id, "isOuterPlanReservation": is_outer},
                            timeout=10)
                    except Exception as e:
                        self.log_signal.emit(f"⚠️ اتصال: {e}")
                        continue

                    if sr.status_code == 401:
                        self.log_signal.emit("❌ الجلسة انتهت!")
                        self.running = False; break

                    days = sr.json() if sr.status_code == 200 else []
                    if not any(d.get("isSelectable") for d in days):
                        self.log_signal.emit(f"⏳ لا حصص ({silo_id})")
                        continue

                    self.log_signal.emit(f"🎯 حصة متاحة! سحب ({name})...")
                    fid, fname = self.search_farmer(name, center_id, silo_id, is_outer)
                    if not fid:
                        self.log_signal.emit(f"⚠️ ({name}) غير موجود باللائحة!")
                        continue

                    self.log_signal.emit(f"✅ {fname} (ID:{fid})")
                    token = self.get_token()
                    if not token:
                        self.log_signal.emit("❌ لا توكن! اسحبه من المتصفح.")
                        continue

                    self.log_signal.emit("📤 إرسال الحجز...")
                    ok, detail = self.submit_booking(token, fid, silo_id, is_outer)

                    if ok:
                        self.log_signal.emit(f"🎉 تم الحجز: {fname} ({detail})")
                        conn = sqlite3.connect(self.db_name)
                        conn.cursor().execute(
                            "UPDATE transactions SET status='booked' WHERE id=?", (tx_id,))
                        conn.commit(); conn.close()
                    else:
                        self.log_signal.emit(f"❌ فشل: {detail}")
                        # إذا فشل بسبب التوكن، حذف الملف لإجبار السحب اليدوي
                        if "token" in detail.lower() or "verification" in detail.lower():
                            try:
                                import os
                                os.remove('token.txt')
                            except Exception:
                                pass
                            self.log_signal.emit("⚠️ التوكن منتهي! اسحب توكن جديد من المتصفح.")

                if self.running: time.sleep(10)
            except Exception as e:
                self.log_signal.emit(f"⚠️ {str(e)}")
                time.sleep(15)



# ==========================================
# الواجهة الرسومية
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
                if 'center_id' not in cols:
                    cur.execute('DROP TABLE transactions')
            cur.execute('''CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_name TEXT NOT NULL,
                silo_id TEXT NOT NULL,
                center_id TEXT NOT NULL,
                is_outer TEXT DEFAULT 'false',
                status TEXT DEFAULT 'pending'
            )''')
            conn.commit()

    def init_ui(self):
        self.setWindowTitle("مكتب الغانم - بوت الحجز v2026")
        self.resize(1000, 780)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.tab_engine = QWidget()
        self.tab_add = QWidget()
        self.tab_list = QWidget()
        self.tabs.addTab(self.tab_engine, "🎮 المحرك")
        self.tabs.addTab(self.tab_add, "➕ إضافة معاملة")
        self.tabs.addTab(self.tab_list, "📋 المعاملات")

        self._setup_engine_tab()
        self._setup_add_tab()
        self._setup_list_tab()

    def _setup_engine_tab(self):
        layout = QVBoxLayout(self.tab_engine)

        # صف 1: تسجيل الدخول وسحب التوكن
        row1 = QHBoxLayout()
        self.btn_session = QPushButton("🔐 تسجيل الدخول (تلجرام)")
        self.btn_session.setStyleSheet("background:#2b579a;color:white;font-weight:bold;padding:12px;border-radius:5px;")
        self.btn_session.clicked.connect(self._run_login)

        self.btn_token = QPushButton("🔑 سحب التوكن من المتصفح")
        self.btn_token.setStyleSheet("background:#6f42c1;color:white;font-weight:bold;padding:12px;border-radius:5px;")
        self.btn_token.clicked.connect(self._run_token_extract)

        row1.addWidget(self.btn_session)
        row1.addWidget(self.btn_token)
        layout.addLayout(row1)

        # صف 2: تشغيل/إيقاف المحرك
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


    def _setup_add_tab(self):
        layout = QVBoxLayout(self.tab_add)

        # القوائم الجاهزة + جلب من السيرفر
        loc_group = QGroupBox("📍 اختيار الموقع (قوائم جاهزة + جلب من السيرفر)")
        loc_layout = QFormLayout(loc_group)

        # زر جلب من السيرفر
        btn_row = QHBoxLayout()
        self.btn_load_server = QPushButton("🌐 جلب من السيرفر")
        self.btn_load_server.setStyleSheet("background:#0078d4;color:white;font-weight:bold;padding:8px;border-radius:4px;")
        self.btn_load_server.clicked.connect(self._load_from_server)
        self.btn_load_local = QPushButton("📋 استخدام القوائم الجاهزة")
        self.btn_load_local.setStyleSheet("background:#6c757d;color:white;font-weight:bold;padding:8px;border-radius:4px;")
        self.btn_load_local.clicked.connect(self._load_local_govs)
        btn_row.addWidget(self.btn_load_server)
        btn_row.addWidget(self.btn_load_local)
        loc_layout.addRow(QLabel("المصدر:"), btn_row)

        # القوائم المنسدلة
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

        # الفلاح
        farmer_group = QGroupBox("👤 الفلاح (بحث من لائحة الموقع)")
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

        # حفظ
        self.btn_save = QPushButton("💾 حفظ المعاملة")
        self.btn_save.setStyleSheet("background:#0d6efd;color:white;font-weight:bold;padding:14px;border-radius:6px;font-size:12pt;")
        self.btn_save.clicked.connect(self._save_transaction)
        layout.addWidget(self.btn_save)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        # تحميل القوائم الجاهزة تلقائياً
        self._load_local_govs()


    def _setup_list_tab(self):
        layout = QVBoxLayout(self.tab_list)
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["ID", "الفلاح", "السايلو", "الشعبة", "خارج الخطة", "الحالة"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        btn_r = QPushButton("🔄 تحديث")
        btn_r.clicked.connect(self._refresh_table)
        btn_d = QPushButton("🗑️ حذف")
        btn_d.clicked.connect(self._delete_selected)
        row.addWidget(btn_r); row.addWidget(btn_d)
        layout.addLayout(row)
        self._refresh_table()

    # ==========================================
    # القوائم الجاهزة المحلية
    # ==========================================
    def _load_local_govs(self):
        """تحميل المحافظات من القائمة الجاهزة"""
        self.cmb_gov.clear()
        self.cmb_gov.addItem("-- اختر المحافظة --", "")
        for g in GOVERNORATES:
            self.cmb_gov.addItem(g['name'], g['id'])
        self.log_viewer.append(f"📋 تم تحميل {len(GOVERNORATES)} محافظة (جاهزة)")

    def _load_from_server(self):
        """جلب المحافظات من السيرفر"""
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        w = DataFetchWorker("governorates")
        w.result_signal.connect(self._on_data)
        w.error_signal.connect(self._on_error)
        w.finished.connect(lambda: self.progress.setVisible(False))
        self.fetch_threads.append(w)
        w.start()

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
            self.progress.setVisible(True); self.progress.setRange(0, 0)
            w = DataFetchWorker("directorates", {"governorateId": gov_id})
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
            self.progress.setVisible(True); self.progress.setRange(0, 0)
            w = DataFetchWorker("centers", {"directorateId": dir_id})
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
            self.progress.setVisible(True); self.progress.setRange(0, 0)
            w = DataFetchWorker("silos", {"marketingCenterId": center_id})
            w.result_signal.connect(self._on_data)
            w.error_signal.connect(self._on_error)
            w.finished.connect(lambda: self.progress.setVisible(False))
            self.fetch_threads.append(w); w.start()

    def _search_farmers(self):
        q = self.input_farmer.text().strip()
        center_id = self.cmb_center.currentData()
        silo_id = self.cmb_silo.currentData()
        if not q:
            QMessageBox.warning(self, "!", "اكتب حرفاً على الأقل"); return
        if not center_id or not silo_id:
            QMessageBox.warning(self, "!", "اختر الشعبة والسايلو أولاً"); return
        is_outer = "true" if self.chk_outer.isChecked() else "false"
        self.progress.setVisible(True); self.progress.setRange(0, 0)
        w = DataFetchWorker("farmers", {
            "marketingCenterId": center_id, "siloId": silo_id,
            "isOuter": is_outer, "query": q
        })
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
                self.cmb_dir.addItem(item.get('name',''), str(item.get('id','')))
            self.cmb_dir.setEnabled(True)
        elif dtype == "centers":
            self.cmb_center.clear()
            self.cmb_center.addItem("-- اختر الشعبة --", "")
            for item in data:
                self.cmb_center.addItem(item.get('name',''), str(item.get('id','')))
            self.cmb_center.setEnabled(True)
        elif dtype == "silos":
            self.cmb_silo.clear()
            self.cmb_silo.addItem("-- اختر السايلو --", "")
            for item in data:
                self.cmb_silo.addItem(item.get('name',''), str(item.get('id','')))
            self.cmb_silo.setEnabled(True)
        elif dtype == "farmers":
            self.cmb_farmer.clear()
            self.cmb_farmer.addItem("-- اختر الفلاح --", "")
            for item in data:
                self.cmb_farmer.addItem(item.get('text',''), str(item.get('id','')))
            self.cmb_farmer.setEnabled(bool(data))
            self.log_viewer.append(f"{'✅' if data else '⚠️'} {len(data)} نتيجة")

    def _on_error(self, msg):
        self.progress.setVisible(False)
        self.log_viewer.append(f"❌ {msg}")

    def _save_transaction(self):
        farmer_text = self.cmb_farmer.currentText()
        silo_id = self.cmb_silo.currentData()
        center_id = self.cmb_center.currentData()
        is_outer = "true" if self.chk_outer.isChecked() else "false"
        if not farmer_text or farmer_text.startswith("--"):
            farmer_text = self.input_farmer.text().strip()
        if not farmer_text:
            QMessageBox.warning(self, "!", "اختر فلاحاً أو اكتب اسمه"); return
        if not silo_id or not center_id:
            QMessageBox.warning(self, "!", "اختر الشعبة والسايلو"); return
        with sqlite3.connect(self.db_name) as conn:
            conn.cursor().execute(
                "INSERT INTO transactions (client_name,silo_id,center_id,is_outer) VALUES(?,?,?,?)",
                (farmer_text, silo_id, center_id, is_outer))
            conn.commit()
        QMessageBox.information(self, "✅", f"تم إضافة ({farmer_text})")
        self.input_farmer.clear()
        self._refresh_table()

    def _refresh_table(self):
        with sqlite3.connect(self.db_name) as conn:
            rows = conn.cursor().execute(
                "SELECT id,client_name,silo_id,center_id,is_outer,status FROM transactions ORDER BY id DESC").fetchall()
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

    # أحداث الأزرار
    def _run_login(self):
        self.btn_session.setEnabled(False)
        self.browser_thread = BrowserWorker("login")
        self.browser_thread.log_signal.connect(self.log_viewer.append)
        self.browser_thread.finished_signal.connect(lambda s: self.btn_session.setEnabled(True))
        self.browser_thread.start()

    def _run_token_extract(self):
        self.btn_token.setEnabled(False)
        self.browser_thread = BrowserWorker("token")
        self.browser_thread.log_signal.connect(self.log_viewer.append)
        self.browser_thread.finished_signal.connect(lambda s: self.btn_token.setEnabled(True))
        self.browser_thread.start()

    def _start_engine(self):
        self.monitoring_thread = MonitoringWorker(self.db_name)
        self.monitoring_thread.log_signal.connect(self.log_viewer.append)
        self.monitoring_thread.start()
        self.btn_start.setEnabled(False); self.btn_stop.setEnabled(True)

    def _stop_engine(self):
        if self.monitoring_thread:
            self.monitoring_thread.stop()
            self.log_viewer.append("🛑 إيقاف.")
            self.btn_start.setEnabled(True); self.btn_stop.setEnabled(False)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    gui = AlGhanemBotGUI()
    gui.show()
    sys.exit(app.exec())
