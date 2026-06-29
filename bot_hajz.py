"""
بوت الحجز التلقائي الذكي - نظام حجز الحبوب العراقي
الإصدار: 2026.06.29
الوصف: أتمتة كاملة للحجز مع جلب المحافظات والمديريات والشعب والسايلوات
       والفلاحين تلقائياً من الموقع كقوائم منسدلة.
"""
import sys
import json
import time
import sqlite3
import logging
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

# ==========================================
# إعدادات الروابط والموقع الثابتة
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
# تخصيص الـ Logging لإرسال البيانات للواجهة
# ==========================================
class SignallingLogHandler(logging.Handler):
    def __init__(self, signal):
        super().__init__()
        self.signal = signal

    def emit(self, record):
        msg = self.format(record)
        self.signal.emit(msg)


# ==========================================
# [إصلاح 1+3] مسار تسجيل الدخول عبر تلجرام
# ==========================================
class BrowserWorker(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool)

    def run(self):
        self.log_signal.emit("🔍 جاري التحقق من إصدار الكروم وتحميل الدرايفر...")
        options = uc.ChromeOptions()
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-popup-blocking")
        options.add_experimental_option("prefs", {
            "profile.default_content_setting_values.popups": 1,
        })

        try:
            driver_path = ChromeDriverManager().install()
            driver = uc.Chrome(driver_executable_path=driver_path, options=options)

            self.log_signal.emit("🌐 تم فتح المتصفح. يرجى تسجيل الدخول عبر تلجرام.")
            driver.get(LOGIN_URL)

            # حقن سكريبت لتحويل المنبثقات إلى نفس التبويبة
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

            # انتظار كوكي المصادقة الحقيقي
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

                        cookies = driver.get_cookies()
                        for c in cookies:
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

                self.log_signal.emit(
                    f"✅ تم استخراج الكوكيز بنجاح! العدد: {len(unique)}")
                self.finished_signal.emit(True)
            else:
                self.log_signal.emit("⚠️ انتهت المهلة (5 دقائق). حاول مرة أخرى.")
                self.finished_signal.emit(False)

            try:
                driver.quit()
            except Exception:
                pass
        except Exception as e:
            self.log_signal.emit(f"❌ خطأ: {str(e)}")
            self.finished_signal.emit(False)



# ==========================================
# عامل جلب البيانات من الموقع (للقوائم المنسدلة)
# ==========================================
class DataFetchWorker(QThread):
    """جلب البيانات من APIs الموقع لملء القوائم المنسدلة"""
    result_signal = pyqtSignal(str, list)  # (نوع البيانات, النتائج)
    error_signal = pyqtSignal(str)

    def __init__(self, fetch_type, params=None):
        super().__init__()
        self.fetch_type = fetch_type
        self.params = params or {}
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 Chrome/146.0.0.0 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "ar",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": BOOKING_PAGE_URL,
        })
        self._load_cookies()

    def _load_cookies(self):
        try:
            with open('cookies.json', 'r', encoding='utf-8') as f:
                cookies = json.load(f)
                for c in cookies:
                    self.session.cookies.set(c['name'], c['value'],
                                            domain=c.get('domain', ''))
        except FileNotFoundError:
            pass

    def run(self):
        try:
            if self.fetch_type == "governorates":
                # المحافظات تُستخرج من صفحة الحجز مباشرة
                res = self.session.get(BOOKING_PAGE_URL, timeout=15)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, 'html.parser')
                    select = soup.find('select', {'id': 'modalGovernorateId'})
                    if select:
                        options = []
                        for opt in select.find_all('option'):
                            val = opt.get('value', '')
                            if val:
                                outer = opt.get('data-enable-outer-plan', 'false')
                                options.append({
                                    'id': val,
                                    'name': opt.text.strip(),
                                    'outer_enabled': outer
                                })
                        self.result_signal.emit("governorates", options)
                        return
                self.error_signal.emit("فشل جلب المحافظات - تأكد من صلاحية الجلسة")

            elif self.fetch_type == "directorates":
                gov_id = self.params.get("governorateId")
                res = self.session.get(DIRECTORATES_API,
                                       params={"governorateId": gov_id}, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    self.result_signal.emit("directorates", data)
                else:
                    self.error_signal.emit("فشل جلب المديريات")

            elif self.fetch_type == "centers":
                dir_id = self.params.get("directorateId")
                res = self.session.get(CENTERS_API,
                                       params={"directorateId": dir_id}, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    self.result_signal.emit("centers", data)
                else:
                    self.error_signal.emit("فشل جلب الشعب الزراعية")

            elif self.fetch_type == "silos":
                center_id = self.params.get("marketingCenterId")
                res = self.session.get(SILOS_API,
                                       params={"marketingCenterId": center_id},
                                       timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    self.result_signal.emit("silos", data)
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
                    data = res.json()
                    results = data.get("results", [])
                    self.result_signal.emit("farmers", results)
                else:
                    self.error_signal.emit("فشل جلب قائمة الفلاحين")

        except Exception as e:
            self.error_signal.emit(f"خطأ اتصال: {str(e)}")



# ==========================================
# محرك المراقبة والحجز التلقائي
# ==========================================
class MonitoringWorker(QThread):
    log_signal = pyqtSignal(str)

    def __init__(self, db_name='alghanem_transactions.db'):
        super().__init__()
        self.db_name = db_name
        self.running = True
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 Chrome/146.0.0.0 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "ar",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": BOOKING_PAGE_URL,
        })

    def stop(self):
        self.running = False

    def load_cookies(self):
        try:
            with open('cookies.json', 'r', encoding='utf-8') as f:
                cookies = json.load(f)
                for c in cookies:
                    self.session.cookies.set(c['name'], c['value'],
                                            domain=c.get('domain', ''))
            return True
        except FileNotFoundError:
            return False

    def verify_session(self):
        try:
            res = self.session.get(BOOKING_PAGE_URL, timeout=10,
                                   allow_redirects=False)
            if res.status_code == 302:
                loc = res.headers.get("Location", "").lower()
                if "login" in loc:
                    return False
            return res.status_code == 200
        except Exception:
            return False

    def search_farmer(self, name, center_id, silo_id, is_outer):
        """البحث عن الفلاح من لائحة الموقع"""
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
            "FarmerId": farmer_id,
            "SiloId": silo_id,
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
        if not self.load_cookies():
            self.log_signal.emit("❌ ملف الكوكيز غير موجود! استخرج الجلسة أولاً.")
            return

        if not self.verify_session():
            self.log_signal.emit("❌ الجلسة منتهية! جدد الكوكيز.")
            return

        self.log_signal.emit("🚀 المحرك يعمل الآن (24/7)... الجلسة فعالة ✅")

        while self.running:
            try:
                conn = sqlite3.connect(self.db_name)
                cur = conn.cursor()
                cur.execute(
                    "SELECT id, client_name, silo_id, center_id, is_outer "
                    "FROM transactions WHERE status = 'pending'")
                txs = cur.fetchall()
                conn.close()

                if not txs:
                    self.log_signal.emit("🔄 لا معاملات معلقة. الفحص بعد 30 ثانية...")
                    time.sleep(30)
                    continue

                for tx in txs:
                    if not self.running:
                        break
                    tx_id, name, silo_id, center_id, is_outer = tx

                    self.log_signal.emit(f"🔍 فحص السايلو ({silo_id}) - {name}...")

                    try:
                        sr = self.session.get(SLOTS_API_URL,
                                             params={"siloId": silo_id,
                                                     "isOuterPlanReservation": is_outer},
                                             timeout=10)
                    except Exception as e:
                        self.log_signal.emit(f"⚠️ خطأ اتصال: {e}")
                        continue

                    if sr.status_code == 401 or "login" in sr.url.lower():
                        self.log_signal.emit("❌ الجلسة انتهت!")
                        self.running = False
                        break

                    days = sr.json() if sr.status_code == 200 else []
                    available = any(d.get("isSelectable") for d in days)

                    if not available:
                        self.log_signal.emit(f"⏳ لا حصص للسايلو ({silo_id})")
                        continue

                    self.log_signal.emit(f"🎯 حصة متاحة! جاري سحب ({name}) من اللائحة...")

                    fid, fname = self.search_farmer(name, center_id, silo_id, is_outer)
                    if not fid:
                        self.log_signal.emit(f"⚠️ لم يُعثر على ({name}) في اللائحة!")
                        continue

                    self.log_signal.emit(f"✅ وُجد: {fname} (ID:{fid})")

                    token = self.get_token()
                    if not token:
                        self.log_signal.emit("❌ فشل سحب التوكن!")
                        continue

                    self.log_signal.emit("📤 إرسال طلب الحجز...")
                    ok, detail = self.submit_booking(token, fid, silo_id, is_outer)

                    if ok:
                        self.log_signal.emit(f"🎉 تم الحجز بنجاح: {fname} ({detail})")
                        conn = sqlite3.connect(self.db_name)
                        conn.cursor().execute(
                            "UPDATE transactions SET status='booked' WHERE id=?",
                            (tx_id,))
                        conn.commit()
                        conn.close()
                    else:
                        self.log_signal.emit(f"❌ فشل الحجز: {detail}")

                if self.running:
                    time.sleep(10)

            except Exception as e:
                self.log_signal.emit(f"⚠️ خطأ: {str(e)}")
                time.sleep(15)



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
        self.setWindowTitle("مكتب الغانم - بوت الحجز التلقائي v2026")
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

        # أزرار التحكم
        btn_row = QHBoxLayout()
        self.btn_session = QPushButton("🔐 تسجيل الدخول (تلجرام)")
        self.btn_session.setStyleSheet(
            "background:#2b579a;color:white;font-weight:bold;padding:12px;border-radius:5px;")
        self.btn_session.clicked.connect(self.run_browser_auth)

        self.btn_start = QPushButton("▶️ تشغيل المحرك")
        self.btn_start.setStyleSheet(
            "background:#107c41;color:white;font-weight:bold;padding:12px;border-radius:5px;")
        self.btn_start.clicked.connect(self.start_monitoring)

        self.btn_stop = QPushButton("⏹️ إيقاف")
        self.btn_stop.setStyleSheet(
            "background:#a80000;color:white;font-weight:bold;padding:12px;border-radius:5px;")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_monitoring)

        btn_row.addWidget(self.btn_session)
        btn_row.addWidget(self.btn_start)
        btn_row.addWidget(self.btn_stop)
        layout.addLayout(btn_row)

        layout.addWidget(QLabel("📺 سجل العمليات:"))
        self.log_viewer = QTextEdit()
        self.log_viewer.setReadOnly(True)
        self.log_viewer.setStyleSheet(
            "background:#1e1e1e;color:#00ff00;font-family:Consolas;"
            "font-size:11pt;border-radius:5px;")
        layout.addWidget(self.log_viewer)


    def _setup_add_tab(self):
        """تبويبة إضافة معاملة مع قوائم منسدلة تُجلب من الموقع"""
        layout = QVBoxLayout(self.tab_add)

        # مجموعة اختيار الموقع (قوائم منسدلة تلقائية)
        loc_group = QGroupBox("📍 اختيار الموقع (يُجلب تلقائياً من الموقع)")
        loc_layout = QFormLayout(loc_group)

        self.cmb_gov = QComboBox()
        self.cmb_gov.addItem("-- اختر المحافظة --", "")
        self.cmb_gov.currentIndexChanged.connect(self._on_gov_changed)

        self.cmb_dir = QComboBox()
        self.cmb_dir.addItem("-- اختر المديرية --", "")
        self.cmb_dir.setEnabled(False)
        self.cmb_dir.currentIndexChanged.connect(self._on_dir_changed)

        self.cmb_center = QComboBox()
        self.cmb_center.addItem("-- اختر الشعبة الزراعية --", "")
        self.cmb_center.setEnabled(False)
        self.cmb_center.currentIndexChanged.connect(self._on_center_changed)

        self.cmb_silo = QComboBox()
        self.cmb_silo.addItem("-- اختر السايلو --", "")
        self.cmb_silo.setEnabled(False)

        self.chk_outer = QCheckBox("حجز خارج الخطة")

        self.btn_load_govs = QPushButton("🔄 تحميل المحافظات من الموقع")
        self.btn_load_govs.setStyleSheet(
            "background:#0078d4;color:white;font-weight:bold;padding:8px;border-radius:4px;")
        self.btn_load_govs.clicked.connect(self._load_governorates)

        loc_layout.addRow(self.btn_load_govs)
        loc_layout.addRow("المحافظة:", self.cmb_gov)
        loc_layout.addRow("المديرية:", self.cmb_dir)
        loc_layout.addRow("الشعبة الزراعية:", self.cmb_center)
        loc_layout.addRow("السايلو:", self.cmb_silo)
        loc_layout.addRow("", self.chk_outer)

        layout.addWidget(loc_group)

        # مجموعة الفلاح
        farmer_group = QGroupBox("👤 اسم الفلاح")
        farmer_layout = QVBoxLayout(farmer_group)

        search_row = QHBoxLayout()
        self.input_farmer_search = QLineEdit()
        self.input_farmer_search.setPlaceholderText("اكتب جزءاً من اسم الفلاح ثم اضغط بحث...")
        self.btn_search_farmer = QPushButton("🔍 بحث في اللائحة")
        self.btn_search_farmer.setStyleSheet(
            "background:#107c41;color:white;font-weight:bold;padding:8px;border-radius:4px;")
        self.btn_search_farmer.clicked.connect(self._search_farmers)
        search_row.addWidget(self.input_farmer_search)
        search_row.addWidget(self.btn_search_farmer)
        farmer_layout.addLayout(search_row)

        self.cmb_farmer = QComboBox()
        self.cmb_farmer.addItem("-- اختر الفلاح من نتائج البحث --", "")
        self.cmb_farmer.setEnabled(False)
        farmer_layout.addWidget(self.cmb_farmer)

        note = QLabel("💡 اكتب حرفاً واحداً على الأقل واضغط بحث لجلب القائمة من الموقع")
        note.setStyleSheet("color:#0d6efd;font-size:9pt;")
        farmer_layout.addWidget(note)

        layout.addWidget(farmer_group)

        # زر الحفظ
        self.btn_save = QPushButton("💾 حفظ المعاملة وبدء المراقبة التلقائية")
        self.btn_save.setStyleSheet(
            "background:#0d6efd;color:white;font-weight:bold;"
            "padding:14px;border-radius:6px;font-size:12pt;")
        self.btn_save.clicked.connect(self._save_transaction)
        layout.addWidget(self.btn_save)

        # شريط التقدم
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)


    def _setup_list_tab(self):
        """تبويبة عرض المعاملات"""
        layout = QVBoxLayout(self.tab_list)
        layout.addWidget(QLabel("📋 جميع المعاملات المسجلة:"))

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["ID", "اسم الفلاح", "السايلو", "الشعبة", "خارج الخطة", "الحالة"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        btn_refresh = QPushButton("🔄 تحديث")
        btn_refresh.clicked.connect(self._refresh_table)
        btn_del = QPushButton("🗑️ حذف المحدد")
        btn_del.clicked.connect(self._delete_selected)
        btn_row.addWidget(btn_refresh)
        btn_row.addWidget(btn_del)
        layout.addLayout(btn_row)

        self._refresh_table()

    # ==========================================
    # أحداث القوائم المنسدلة (جلب تلقائي)
    # ==========================================
    def _load_governorates(self):
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        w = DataFetchWorker("governorates")
        w.result_signal.connect(self._on_data_received)
        w.error_signal.connect(self._on_fetch_error)
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
            self.progress.setVisible(True)
            self.progress.setRange(0, 0)
            w = DataFetchWorker("directorates", {"governorateId": gov_id})
            w.result_signal.connect(self._on_data_received)
            w.error_signal.connect(self._on_fetch_error)
            w.finished.connect(lambda: self.progress.setVisible(False))
            self.fetch_threads.append(w)
            w.start()

    def _on_dir_changed(self, idx):
        dir_id = self.cmb_dir.currentData()
        self.cmb_center.clear()
        self.cmb_center.addItem("-- اختر الشعبة --", "")
        self.cmb_silo.clear()
        self.cmb_silo.addItem("-- اختر السايلو --", "")
        self.cmb_center.setEnabled(False)
        self.cmb_silo.setEnabled(False)

        if dir_id:
            self.progress.setVisible(True)
            self.progress.setRange(0, 0)
            w = DataFetchWorker("centers", {"directorateId": dir_id})
            w.result_signal.connect(self._on_data_received)
            w.error_signal.connect(self._on_fetch_error)
            w.finished.connect(lambda: self.progress.setVisible(False))
            self.fetch_threads.append(w)
            w.start()

    def _on_center_changed(self, idx):
        center_id = self.cmb_center.currentData()
        self.cmb_silo.clear()
        self.cmb_silo.addItem("-- اختر السايلو --", "")
        self.cmb_silo.setEnabled(False)

        if center_id:
            self.progress.setVisible(True)
            self.progress.setRange(0, 0)
            w = DataFetchWorker("silos", {"marketingCenterId": center_id})
            w.result_signal.connect(self._on_data_received)
            w.error_signal.connect(self._on_fetch_error)
            w.finished.connect(lambda: self.progress.setVisible(False))
            self.fetch_threads.append(w)
            w.start()

    def _search_farmers(self):
        query = self.input_farmer_search.text().strip()
        center_id = self.cmb_center.currentData()
        silo_id = self.cmb_silo.currentData()

        if not query:
            QMessageBox.warning(self, "تنبيه", "اكتب حرفاً واحداً على الأقل للبحث")
            return
        if not center_id or not silo_id:
            QMessageBox.warning(self, "تنبيه", "اختر الشعبة والسايلو أولاً")
            return

        is_outer = "true" if self.chk_outer.isChecked() else "false"
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        w = DataFetchWorker("farmers", {
            "marketingCenterId": center_id,
            "siloId": silo_id,
            "isOuter": is_outer,
            "query": query
        })
        w.result_signal.connect(self._on_data_received)
        w.error_signal.connect(self._on_fetch_error)
        w.finished.connect(lambda: self.progress.setVisible(False))
        self.fetch_threads.append(w)
        w.start()


    def _on_data_received(self, data_type, data):
        """معالجة البيانات المستلمة من الموقع وملء القوائم"""
        if data_type == "governorates":
            self.cmb_gov.clear()
            self.cmb_gov.addItem("-- اختر المحافظة --", "")
            for item in data:
                self.cmb_gov.addItem(item['name'], item['id'])
            self.log_viewer.append(f"✅ تم تحميل {len(data)} محافظة من الموقع")

        elif data_type == "directorates":
            self.cmb_dir.clear()
            self.cmb_dir.addItem("-- اختر المديرية --", "")
            for item in data:
                self.cmb_dir.addItem(item.get('name', ''), str(item.get('id', '')))
            self.cmb_dir.setEnabled(True)

        elif data_type == "centers":
            self.cmb_center.clear()
            self.cmb_center.addItem("-- اختر الشعبة --", "")
            for item in data:
                self.cmb_center.addItem(item.get('name', ''), str(item.get('id', '')))
            self.cmb_center.setEnabled(True)

        elif data_type == "silos":
            self.cmb_silo.clear()
            self.cmb_silo.addItem("-- اختر السايلو --", "")
            for item in data:
                self.cmb_silo.addItem(item.get('name', ''), str(item.get('id', '')))
            self.cmb_silo.setEnabled(True)

        elif data_type == "farmers":
            self.cmb_farmer.clear()
            self.cmb_farmer.addItem("-- اختر الفلاح --", "")
            if data:
                for item in data:
                    self.cmb_farmer.addItem(item.get('text', ''), str(item.get('id', '')))
                self.cmb_farmer.setEnabled(True)
                self.log_viewer.append(f"✅ تم العثور على {len(data)} فلاح")
            else:
                self.cmb_farmer.addItem("لا توجد نتائج", "")
                self.log_viewer.append("⚠️ لا نتائج - جرب اسم آخر أو تأكد من الشعبة/السايلو")

    def _on_fetch_error(self, msg):
        self.progress.setVisible(False)
        self.log_viewer.append(f"❌ {msg}")

    def _save_transaction(self):
        """حفظ المعاملة في قاعدة البيانات"""
        farmer_text = self.cmb_farmer.currentText()
        farmer_id = self.cmb_farmer.currentData()
        silo_id = self.cmb_silo.currentData()
        center_id = self.cmb_center.currentData()
        is_outer = "true" if self.chk_outer.isChecked() else "false"

        # السماح بإدخال الاسم يدوياً إذا لم يُختر من القائمة
        if not farmer_id or farmer_id == "":
            farmer_text = self.input_farmer_search.text().strip()
            if not farmer_text:
                QMessageBox.warning(self, "تنبيه",
                                    "اختر فلاحاً من القائمة أو اكتب اسمه في حقل البحث")
                return

        if not silo_id or not center_id:
            QMessageBox.warning(self, "تنبيه", "يرجى اختيار الشعبة والسايلو")
            return

        # حفظ اسم الفلاح (سيتم مطابقته مجدداً عند الحجز)
        name = farmer_text if farmer_text != "-- اختر الفلاح --" else self.input_farmer_search.text().strip()

        with sqlite3.connect(self.db_name) as conn:
            conn.cursor().execute(
                "INSERT INTO transactions (client_name, silo_id, center_id, is_outer) "
                "VALUES (?, ?, ?, ?)", (name, silo_id, center_id, is_outer))
            conn.commit()

        QMessageBox.information(self, "✅ تم",
                                f"تمت إضافة ({name}) للمراقبة التلقائية.\n"
                                f"السايلو: {silo_id} | الشعبة: {center_id}")
        self.input_farmer_search.clear()
        self.cmb_farmer.clear()
        self.cmb_farmer.addItem("-- اختر الفلاح --", "")
        self._refresh_table()

    def _refresh_table(self):
        with sqlite3.connect(self.db_name) as conn:
            rows = conn.cursor().execute(
                "SELECT id, client_name, silo_id, center_id, is_outer, status "
                "FROM transactions ORDER BY id DESC").fetchall()

        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                item.setFlags(item.flags() ^ Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, c, item)

    def _delete_selected(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "تنبيه", "اختر معاملة أولاً")
            return
        tx_id = self.table.item(row, 0).text()
        reply = QMessageBox.question(self, "تأكيد", f"حذف المعاملة رقم {tx_id}؟")
        if reply == QMessageBox.StandardButton.Yes:
            with sqlite3.connect(self.db_name) as conn:
                conn.cursor().execute("DELETE FROM transactions WHERE id=?", (tx_id,))
                conn.commit()
            self._refresh_table()


    # ==========================================
    # أحداث المحرك
    # ==========================================
    def run_browser_auth(self):
        self.btn_session.setEnabled(False)
        self.browser_thread = BrowserWorker()
        self.browser_thread.log_signal.connect(self.log_viewer.append)
        self.browser_thread.finished_signal.connect(self._on_browser_done)
        self.browser_thread.start()

    def _on_browser_done(self, success):
        self.btn_session.setEnabled(True)
        if success:
            self.log_viewer.append("✅ الجلسة جاهزة! يمكنك الآن تحميل البيانات وتشغيل المحرك.")

    def start_monitoring(self):
        self.monitoring_thread = MonitoringWorker(self.db_name)
        self.monitoring_thread.log_signal.connect(self.log_viewer.append)
        self.monitoring_thread.start()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

    def stop_monitoring(self):
        if self.monitoring_thread:
            self.monitoring_thread.stop()
            self.log_viewer.append("🛑 تم إيقاف المحرك.")
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)


# ==========================================
# نقطة البداية
# ==========================================
if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    gui = AlGhanemBotGUI()
    gui.show()
    sys.exit(app.exec())
