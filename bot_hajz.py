"""
بوت الحجز التلقائي - نظام حجز الحبوب العراقي v2026.07.01
- نظام حسابات متعددة (كل حساب = كوكيز + توكن)
- زر إرسال مباشر + محرك مراقبة بتأخير عشوائي
- إلغاء SSL + لا إغلاق تلقائي للمتصفح
"""
import sys, os, json, time, random, sqlite3, logging, urllib3, requests
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from webdriver_manager.chrome import ChromeDriverManager
from PyQt6.QtWidgets import *
from PyQt6.QtCore import QThread, pyqtSignal, Qt

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://hajz.grainboardiq.com"
LOGIN_URL = f"{BASE_URL}/Identity/Account/DriverLogin?returnUrl=%2F"
BOOKING_PAGE_URL = f"{BASE_URL}/Reservation/Create"
BOOKING_POST_URL = f"{BASE_URL}/Reservation/CreateReservation"
SEARCH_API_URL = f"{BASE_URL}/api/LocationApi/SearchFarmersByMarketingCenter"
SLOTS_API_URL = f"{BASE_URL}/Reservation/GetReservationDayOptions"
DIRECTORATES_API = f"{BASE_URL}/api/LocationApi/GetDirectoratesByGovernorate"
CENTERS_API = f"{BASE_URL}/api/LocationApi/GetMarketingCentersByDirectorate"
SILOS_API = f"{BASE_URL}/api/LocationApi/GetSilosByMarketingCenter"
ACCOUNTS_DIR = "accounts"

GOVERNORATES = [
    {"id": "12", "name": "اربيل"}, {"id": "11", "name": "السليمانية"},
    {"id": "13", "name": "حلبجة"}, {"id": "14", "name": "دهوك"},
    {"id": "16", "name": "صلاح الدين"}, {"id": "15", "name": "كركوك"},
    {"id": "2", "name": "نينوى"},
]

# === إدارة الحسابات ===
def get_accounts():
    os.makedirs(ACCOUNTS_DIR, exist_ok=True)
    return sorted([d for d in os.listdir(ACCOUNTS_DIR) if os.path.isdir(os.path.join(ACCOUNTS_DIR, d))])

def account_path(name):
    p = os.path.join(ACCOUNTS_DIR, name)
    os.makedirs(p, exist_ok=True)
    return p

def save_cookies(name, cookies):
    with open(os.path.join(account_path(name), 'cookies.json'), 'w', encoding='utf-8') as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)

def save_token(name, token):
    with open(os.path.join(account_path(name), 'token.txt'), 'w', encoding='utf-8') as f:
        f.write(token)

def load_token(name):
    try:
        with open(os.path.join(ACCOUNTS_DIR, name, 'token.txt'), 'r') as f:
            t = f.read().strip()
            return t if len(t) > 20 else None
    except: return None

def make_session(name):
    s = requests.Session()
    s.verify = False
    s.headers.update({"User-Agent": "Mozilla/5.0 Chrome/146.0.0.0", "Accept-Language": "ar",
                      "X-Requested-With": "XMLHttpRequest", "Referer": BOOKING_PAGE_URL})
    try:
        with open(os.path.join(ACCOUNTS_DIR, name, 'cookies.json'), 'r') as f:
            for c in json.load(f):
                s.cookies.set(c['name'], c['value'], domain=c.get('domain', ''))
    except: pass
    return s

def search_farmer(session, name, center_id, silo_id, is_outer):
    for q in [name] + (name.split()[:1] if ' ' in name else []):
        try:
            r = session.get(SEARCH_API_URL, params={"marketingCenterId": center_id, "siloId": silo_id,
                "hasOtherSiloApproval": "false", "isOuterPlanReservation": is_outer, "q": q, "limit": 50}, timeout=15)
            if r.status_code == 200:
                results = r.json().get("results", [])
                if results:
                    for x in results:
                        if name in x.get("text", ""): return x.get("id"), x.get("text", "")
                    return results[0].get("id"), results[0].get("text", "")
        except: pass
    return None, None

class SignallingLogHandler(logging.Handler):
    def __init__(self, sig): super().__init__(); self.sig = sig
    def emit(self, r): self.sig.emit(self.format(r))

# === BrowserWorker ===
class BrowserWorker(QThread):
    log = pyqtSignal(str)
    done = pyqtSignal(bool)
    def __init__(self, mode, account):
        super().__init__(); self.mode = mode; self.account = account; self.driver = None
    def run(self):
        opts = uc.ChromeOptions()
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--disable-popup-blocking")
        opts.add_argument("--ignore-certificate-errors")
        try:
            self.log.emit(f"🔍 [{self.account}] تشغيل المتصفح...")
            dp = ChromeDriverManager().install()
            drv = uc.Chrome(driver_executable_path=dp, options=opts)
            if self.mode == "token": self._token(drv)
            else: self._login(drv)
        except Exception as e:
            self.log.emit(f"❌ {e}"); self.done.emit(False)

    def _login(self, drv):
        self.log.emit(f"🌐 [{self.account}] سجل الدخول عبر تلجرام.")
        drv.get(LOGIN_URL)
        PS = "(function(){var o=window.open;window.open=function(u,n,f){if(u&&(u.indexOf('oauth')!==-1||u.indexOf('telegram')!==-1)){window.location.href=u;return window}return o.call(window,u,'_blank','')};})();"
        try: drv.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": PS})
        except: pass
        drv.execute_script(PS)
        self.log.emit(f"⏳ [{self.account}] بانتظار تسجيل الدخول...")
        end = time.time() + 300
        ok = False
        while time.time() < end:
            try:
                for h in drv.window_handles:
                    try: drv.switch_to.window(h)
                    except: continue
                    for c in drv.get_cookies():
                        if c['name'] == '.AspNetCore.Identity.Application' and len(c.get('value','')) > 50:
                            ok = True; break
                    if ok: break
                if ok: break
            except: pass
            time.sleep(2)
        if ok:
            time.sleep(3)
            cks = []
            for h in drv.window_handles:
                try: drv.switch_to.window(h); cks.extend(drv.get_cookies())
                except: pass
            seen = set()
            uniq = [c for c in cks if c['name'] not in seen and not seen.add(c['name'])]
            save_cookies(self.account, uniq)
            self.log.emit(f"✅ [{self.account}] كوكيز ({len(uniq)}) محفوظة!")
        else:
            self.log.emit(f"⚠️ [{self.account}] انتهت المهلة.")
        self.log.emit("💡 اضغط 'إغلاق المتصفح' عند الانتهاء.")
        self.driver = drv; self.done.emit(ok)

    def _token(self, drv):
        self.log.emit(f"🔑 [{self.account}] سحب التوكن...")
        drv.get(BASE_URL); time.sleep(2)
        try:
            for c in json.load(open(os.path.join(ACCOUNTS_DIR, self.account, 'cookies.json'))):
                try: drv.add_cookie({'name':c['name'],'value':c['value'],'domain':c.get('domain','.grainboardiq.com'),'path':c.get('path','/')})
                except: pass
        except: pass
        drv.get(BOOKING_PAGE_URL); time.sleep(3)
        soup = BeautifulSoup(drv.page_source, 'html.parser')
        inp = soup.find('input', {'name': '__RequestVerificationToken'})
        if inp:
            save_token(self.account, inp['value'])
            self.log.emit(f"✅ [{self.account}] توكن محفوظ! ({inp['value'][:30]}...)")
        else:
            self.log.emit(f"❌ [{self.account}] فشل سحب التوكن")
        self.log.emit("💡 اضغط 'إغلاق المتصفح'.")
        self.driver = drv; self.done.emit(bool(inp))

# === DirectBookingWorker ===
class DirectBookingWorker(QThread):
    log = pyqtSignal(str)
    done = pyqtSignal(bool, str)
    def __init__(self, account, farmer, silo, center, outer):
        super().__init__()
        self.account=account; self.farmer=farmer; self.silo=silo; self.center=center; self.outer=outer
    def run(self):
        s = make_session(self.account)
        token = load_token(self.account)
        if not token:
            self.log.emit(f"❌ [{self.account}] لا توكن!"); self.done.emit(False,""); return
        self.log.emit(f"🔍 [{self.account}] بحث ({self.farmer})...")
        fid, fn = search_farmer(s, self.farmer, self.center, self.silo, self.outer)
        if not fid:
            self.log.emit(f"⚠️ لم يُعثر على ({self.farmer})"); self.done.emit(False,""); return
        self.log.emit(f"📤 [{self.account}] إرسال حجز {fn}...")
        payload = {"__RequestVerificationToken": token, "FarmerId": fid, "SiloId": self.silo,
                   "HasOtherSiloApproval":"false","IsOuterPlanReservation":self.outer,
                   "SelectedMarketingReservedDayNum":"","HasVehicleInfo":"false",
                   "VehicleLetter":"","VehicleNumber":"","VehicleGovernorate":"",
                   "VehicleNumberGovernorate":"","PlateType":"","DriverName":"","VehicleType":""}
        try:
            r = s.post(BOOKING_POST_URL, data=payload, timeout=20)
            if r.status_code == 200:
                j = r.json()
                if j.get("success"):
                    self.log.emit(f"🎉 [{self.account}] حجز ناجح! ({j.get('id','')})")
                    self.done.emit(True, str(j.get('id',''))); return
                self.log.emit(f"❌ {j.get('message','خطأ')}"); self.done.emit(False, j.get('message','')); return
            self.log.emit(f"❌ HTTP {r.status_code}"); self.done.emit(False,"")
        except Exception as e:
            self.log.emit(f"❌ {e}"); self.done.emit(False,"")

# === MonitoringWorker (رانج عشوائي) ===
class MonitoringWorker(QThread):
    log = pyqtSignal(str)
    def __init__(self, db, dmin, dmax):
        super().__init__(); self.db=db; self.running=True; self.dmin=dmin; self.dmax=dmax
    def stop(self): self.running = False
    def run(self):
        self.log.emit(f"🚀 المحرك يعمل (تأخير {self.dmin}-{self.dmax}ث)")
        while self.running:
            try:
                conn = sqlite3.connect(self.db)
                txs = conn.cursor().execute("SELECT id,client_name,silo_id,center_id,is_outer,account FROM transactions WHERE status='pending'").fetchall()
                conn.close()
                if not txs:
                    d=random.randint(20,40); self.log.emit(f"🔄 لا معاملات ({d}ث)"); time.sleep(d); continue
                for tx in txs:
                    if not self.running: break
                    tid,name,silo,center,outer,acct = tx
                    if not acct: self.log.emit(f"⚠️ #{tid} بدون حساب!"); continue
                    token = load_token(acct)
                    if not token: self.log.emit(f"❌ [{acct}] لا توكن!"); continue
                    s = make_session(acct)
                    self.log.emit(f"🔍 [{acct}] فحص ({silo}) - {name}")
                    try:
                        sr = s.get(SLOTS_API_URL, params={"siloId":silo,"isOuterPlanReservation":outer}, timeout=10)
                    except Exception as e: self.log.emit(f"⚠️ {e}"); continue
                    if sr.status_code==401: self.log.emit(f"❌ [{acct}] جلسة منتهية!"); continue
                    days = sr.json() if sr.status_code==200 else []
                    if not any(d.get("isSelectable") for d in days):
                        self.log.emit(f"⏳ [{acct}] لا حصص"); continue
                    self.log.emit(f"🎯 [{acct}] حصة! بحث ({name})...")
                    fid,fn = search_farmer(s, name, center, silo, outer)
                    if not fid: self.log.emit(f"⚠️ ({name}) غير موجود"); continue
                    self.log.emit(f"📤 [{acct}] حجز {fn}...")
                    payload = {"__RequestVerificationToken":token,"FarmerId":fid,"SiloId":silo,
                               "HasOtherSiloApproval":"false","IsOuterPlanReservation":outer,
                               "SelectedMarketingReservedDayNum":"","HasVehicleInfo":"false",
                               "VehicleLetter":"","VehicleNumber":"","VehicleGovernorate":"",
                               "VehicleNumberGovernorate":"","PlateType":"","DriverName":"","VehicleType":""}
                    try:
                        r = s.post(BOOKING_POST_URL, data=payload, timeout=20)
                        if r.status_code==200:
                            j=r.json()
                            if j.get("success"):
                                self.log.emit(f"🎉 [{acct}] حجز ناجح: {fn}")
                                conn=sqlite3.connect(self.db); conn.cursor().execute("UPDATE transactions SET status='booked' WHERE id=?",(tid,)); conn.commit(); conn.close()
                            else: self.log.emit(f"❌ {j.get('message','')}")
                        else: self.log.emit(f"❌ HTTP {r.status_code}")
                    except Exception as e: self.log.emit(f"❌ {e}")
                    d=random.randint(self.dmin,self.dmax); time.sleep(d)
                if self.running: time.sleep(random.randint(self.dmin,self.dmax))
            except Exception as e: self.log.emit(f"⚠️ {e}"); time.sleep(10)

# === DataFetchWorker ===
class DataFetchWorker(QThread):
    result = pyqtSignal(str, list)
    error = pyqtSignal(str)
    def __init__(self, ftype, params=None, account=""):
        super().__init__(); self.ftype=ftype; self.params=params or {}; self.account=account
    def run(self):
        s = make_session(self.account) if self.account else requests.Session()
        s.verify = False
        try:
            if self.ftype=="governorates":
                r=s.get(BOOKING_PAGE_URL,timeout=15)
                if r.status_code==200:
                    soup=BeautifulSoup(r.text,'html.parser')
                    sel=soup.find('select',{'id':'modalGovernorateId'})
                    if sel:
                        self.result.emit("governorates",[{'id':o.get('value',''),'name':o.text.strip()} for o in sel.find_all('option') if o.get('value','')]); return
                self.error.emit("فشل جلب المحافظات")
            elif self.ftype=="directorates":
                r=s.get(DIRECTORATES_API,params={"governorateId":self.params.get("gid")},timeout=10)
                self.result.emit("directorates",r.json()) if r.status_code==200 else self.error.emit("فشل")
            elif self.ftype=="centers":
                r=s.get(CENTERS_API,params={"directorateId":self.params.get("did")},timeout=10)
                self.result.emit("centers",r.json()) if r.status_code==200 else self.error.emit("فشل")
            elif self.ftype=="silos":
                r=s.get(SILOS_API,params={"marketingCenterId":self.params.get("cid")},timeout=10)
                self.result.emit("silos",r.json()) if r.status_code==200 else self.error.emit("فشل")
            elif self.ftype=="farmers":
                p={"marketingCenterId":self.params.get("cid"),"siloId":self.params.get("sid"),
                   "hasOtherSiloApproval":"false","isOuterPlanReservation":self.params.get("outer","false"),
                   "q":self.params.get("q","ا"),"limit":50}
                r=s.get(SEARCH_API_URL,params=p,timeout=15)
                self.result.emit("farmers",r.json().get("results",[])) if r.status_code==200 else self.error.emit("فشل")
        except Exception as e: self.error.emit(str(e))

# === الواجهة الرسومية ===
class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = 'bot.db'; self._init_db()
        self.setWindowTitle("بوت الحجز v2026"); self.resize(1050, 800)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.browser_thread = None; self.monitor_thread = None; self.fetch_threads = []
        central = QWidget(); self.setCentralWidget(central)
        lay = QVBoxLayout(central)
        self.tabs = QTabWidget(); lay.addWidget(self.tabs)
        self.tab1 = QWidget(); self.tab2 = QWidget(); self.tab3 = QWidget()
        self.tabs.addTab(self.tab1, "🎮 المحرك"); self.tabs.addTab(self.tab2, "➕ إضافة"); self.tabs.addTab(self.tab3, "📋 المعاملات")
        self._ui_engine(); self._ui_add(); self._ui_list()
        handler = SignallingLogHandler(self.log.append)
        handler.setFormatter(logging.Formatter('%(asctime)s %(message)s', '%H:%M:%S'))
        logging.getLogger().addHandler(handler)

    def _init_db(self):
        with sqlite3.connect(self.db) as c:
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='transactions'")
            if c.fetchone():
                cols = [x[1] for x in c.execute("PRAGMA table_info(transactions)").fetchall()]
                if 'account' not in cols: c.execute('DROP TABLE transactions')
            c.execute('''CREATE TABLE IF NOT EXISTS transactions(
                id INTEGER PRIMARY KEY AUTOINCREMENT, client_name TEXT, silo_id TEXT,
                center_id TEXT, is_outer TEXT DEFAULT 'false', account TEXT, status TEXT DEFAULT 'pending')''')

    def _ui_engine(self):
        L = QVBoxLayout(self.tab1)
        # حساب
        g1 = QGroupBox("👤 الحساب النشط"); gl = QHBoxLayout(g1)
        self.cmb_acct = QComboBox(); self._refresh_accounts()
        btn_new = QPushButton("➕ حساب جديد"); btn_new.clicked.connect(self._new_account)
        gl.addWidget(QLabel("الحساب:")); gl.addWidget(self.cmb_acct); gl.addWidget(btn_new)
        L.addWidget(g1)
        # أزرار
        r1 = QHBoxLayout()
        self.btn_login = QPushButton("🔐 تسجيل الدخول"); self.btn_login.setStyleSheet("background:#2b579a;color:white;font-weight:bold;padding:10px;")
        self.btn_login.clicked.connect(lambda: self._browser("login"))
        self.btn_token = QPushButton("🔑 سحب التوكن"); self.btn_token.setStyleSheet("background:#6f42c1;color:white;font-weight:bold;padding:10px;")
        self.btn_token.clicked.connect(lambda: self._browser("token"))
        self.btn_close = QPushButton("❌ إغلاق المتصفح"); self.btn_close.setStyleSheet("background:#dc3545;color:white;font-weight:bold;padding:10px;")
        self.btn_close.clicked.connect(self._close_browser); self.btn_close.setEnabled(False)
        r1.addWidget(self.btn_login); r1.addWidget(self.btn_token); r1.addWidget(self.btn_close)
        L.addLayout(r1)
        # محرك + رانج
        g2 = QGroupBox("⚙️ المحرك (رانج تأخير عشوائي)"); g2l = QHBoxLayout(g2)
        g2l.addWidget(QLabel("من:")); self.spin_min = QSpinBox(); self.spin_min.setRange(1,120); self.spin_min.setValue(5)
        g2l.addWidget(self.spin_min); g2l.addWidget(QLabel("إلى:"))
        self.spin_max = QSpinBox(); self.spin_max.setRange(1,300); self.spin_max.setValue(20)
        g2l.addWidget(self.spin_max); g2l.addWidget(QLabel("ثانية"))
        self.btn_start = QPushButton("▶️ تشغيل"); self.btn_start.setStyleSheet("background:#107c41;color:white;font-weight:bold;padding:10px;")
        self.btn_start.clicked.connect(self._start)
        self.btn_stop = QPushButton("⏹️ إيقاف"); self.btn_stop.setStyleSheet("background:#a80000;color:white;font-weight:bold;padding:10px;")
        self.btn_stop.setEnabled(False); self.btn_stop.clicked.connect(self._stop)
        g2l.addWidget(self.btn_start); g2l.addWidget(self.btn_stop)
        L.addWidget(g2)
        # السجل
        self.log = QTextEdit(); self.log.setReadOnly(True)
        self.log.setStyleSheet("background:#1e1e1e;color:#00ff00;font-family:Consolas;font-size:11pt;")
        L.addWidget(self.log)

    def _ui_add(self):
        L = QVBoxLayout(self.tab2)
        # الحساب
        ar = QHBoxLayout(); ar.addWidget(QLabel("الحساب:")); self.cmb_acct2 = QComboBox(); self._refresh_accounts2()
        ar.addWidget(self.cmb_acct2); L.addLayout(ar)
        # الموقع
        g = QGroupBox("📍 الموقع"); gl = QFormLayout(g)
        br = QHBoxLayout()
        b1 = QPushButton("📋 جاهزة"); b1.clicked.connect(self._local_govs)
        b2 = QPushButton("🌐 سيرفر"); b2.clicked.connect(self._server_govs)
        br.addWidget(b1); br.addWidget(b2); gl.addRow("مصدر:", br)
        self.cmb_gov = QComboBox(); self.cmb_gov.currentIndexChanged.connect(self._gov_ch)
        self.cmb_dir = QComboBox(); self.cmb_dir.setEnabled(False); self.cmb_dir.currentIndexChanged.connect(self._dir_ch)
        self.cmb_ctr = QComboBox(); self.cmb_ctr.setEnabled(False); self.cmb_ctr.currentIndexChanged.connect(self._ctr_ch)
        self.cmb_silo = QComboBox(); self.cmb_silo.setEnabled(False)
        self.chk_outer = QCheckBox("خارج الخطة")
        gl.addRow("المحافظة:", self.cmb_gov); gl.addRow("المديرية:", self.cmb_dir)
        gl.addRow("الشعبة:", self.cmb_ctr); gl.addRow("السايلو:", self.cmb_silo)
        gl.addRow("", self.chk_outer); L.addWidget(g)
        # الفلاح
        fg = QGroupBox("👤 الفلاح"); fl = QVBoxLayout(fg)
        sr = QHBoxLayout(); self.inp_f = QLineEdit(); self.inp_f.setPlaceholderText("اكتب جزءاً من الاسم...")
        bs = QPushButton("🔍"); bs.clicked.connect(self._search_f); sr.addWidget(self.inp_f); sr.addWidget(bs)
        fl.addLayout(sr); self.cmb_f = QComboBox(); self.cmb_f.setEnabled(False); fl.addWidget(self.cmb_f)
        L.addWidget(fg)
        # أزرار
        btns = QHBoxLayout()
        self.btn_save = QPushButton("💾 حفظ للمراقبة"); self.btn_save.setStyleSheet("background:#0d6efd;color:white;font-weight:bold;padding:12px;font-size:11pt;")
        self.btn_save.clicked.connect(self._save)
        self.btn_direct = QPushButton("🚀 إرسال مباشر الآن"); self.btn_direct.setStyleSheet("background:#e65100;color:white;font-weight:bold;padding:12px;font-size:11pt;")
        self.btn_direct.clicked.connect(self._direct_send)
        btns.addWidget(self.btn_save); btns.addWidget(self.btn_direct)
        L.addLayout(btns)
        self.prog = QProgressBar(); self.prog.setVisible(False); L.addWidget(self.prog)
        self._local_govs()

    def _ui_list(self):
        L = QVBoxLayout(self.tab3)
        self.tbl = QTableWidget(); self.tbl.setColumnCount(7)
        self.tbl.setHorizontalHeaderLabels(["ID","الفلاح","السايلو","الشعبة","خارج","الحساب","الحالة"])
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        L.addWidget(self.tbl)
        r = QHBoxLayout()
        QPushButton("🔄", clicked=self._rtbl).also = r.addWidget(QPushButton("🔄 تحديث", clicked=self._rtbl))
        r.addWidget(QPushButton("🗑️ حذف", clicked=self._del))
        L.addLayout(r); self._rtbl()

    # === أحداث ===
    def _refresh_accounts(self):
        self.cmb_acct.clear(); self.cmb_acct.addItems(get_accounts() or ["(لا حسابات)"])
    def _refresh_accounts2(self):
        self.cmb_acct2.clear(); self.cmb_acct2.addItems(get_accounts() or ["(لا حسابات)"])
    def _new_account(self):
        name, ok = QInputDialog.getText(self, "حساب جديد", "اسم الحساب:")
        if ok and name.strip():
            account_path(name.strip())
            self._refresh_accounts(); self._refresh_accounts2()
            self.log.append(f"✅ حساب ({name.strip()}) تم إنشاؤه")

    def _browser(self, mode):
        acct = self.cmb_acct.currentText()
        if not acct or acct == "(لا حسابات)":
            QMessageBox.warning(self, "!", "أنشئ حساباً أولاً"); return
        self.btn_login.setEnabled(False); self.btn_token.setEnabled(False)
        self.browser_thread = BrowserWorker(mode, acct)
        self.browser_thread.log.connect(self.log.append)
        self.browser_thread.done.connect(self._browser_done)
        self.browser_thread.start()

    def _browser_done(self, ok):
        self.btn_login.setEnabled(True); self.btn_token.setEnabled(True); self.btn_close.setEnabled(True)

    def _close_browser(self):
        if self.browser_thread and self.browser_thread.driver:
            try: self.browser_thread.driver.quit(); self.log.append("✅ المتصفح أُغلق.")
            except Exception as e: self.log.append(f"⚠️ {e}")
            self.browser_thread.driver = None
        self.btn_close.setEnabled(False)

    def _start(self):
        self.monitor_thread = MonitoringWorker(self.db, self.spin_min.value(), self.spin_max.value())
        self.monitor_thread.log.connect(self.log.append)
        self.monitor_thread.start()
        self.btn_start.setEnabled(False); self.btn_stop.setEnabled(True)

    def _stop(self):
        if self.monitor_thread: self.monitor_thread.stop()
        self.log.append("🛑 إيقاف."); self.btn_start.setEnabled(True); self.btn_stop.setEnabled(False)

    def _local_govs(self):
        self.cmb_gov.clear(); self.cmb_gov.addItem("--", "")
        for g in GOVERNORATES: self.cmb_gov.addItem(g['name'], g['id'])

    def _server_govs(self):
        acct = self.cmb_acct2.currentText()
        w = DataFetchWorker("governorates", account=acct)
        w.result.connect(self._data); w.error.connect(lambda m: self.log.append(f"❌ {m}"))
        self.fetch_threads.append(w); w.start()

    def _gov_ch(self, i):
        gid = self.cmb_gov.currentData()
        self.cmb_dir.clear(); self.cmb_dir.addItem("--",""); self.cmb_dir.setEnabled(False)
        self.cmb_ctr.clear(); self.cmb_ctr.addItem("--",""); self.cmb_ctr.setEnabled(False)
        self.cmb_silo.clear(); self.cmb_silo.addItem("--",""); self.cmb_silo.setEnabled(False)
        if gid:
            w = DataFetchWorker("directorates",{"gid":gid},self.cmb_acct2.currentText())
            w.result.connect(self._data); w.error.connect(lambda m: self.log.append(f"❌ {m}"))
            self.fetch_threads.append(w); w.start()

    def _dir_ch(self, i):
        did = self.cmb_dir.currentData()
        self.cmb_ctr.clear(); self.cmb_ctr.addItem("--",""); self.cmb_ctr.setEnabled(False)
        self.cmb_silo.clear(); self.cmb_silo.addItem("--",""); self.cmb_silo.setEnabled(False)
        if did:
            w = DataFetchWorker("centers",{"did":did},self.cmb_acct2.currentText())
            w.result.connect(self._data); w.error.connect(lambda m: self.log.append(f"❌ {m}"))
            self.fetch_threads.append(w); w.start()

    def _ctr_ch(self, i):
        cid = self.cmb_ctr.currentData()
        self.cmb_silo.clear(); self.cmb_silo.addItem("--",""); self.cmb_silo.setEnabled(False)
        if cid:
            w = DataFetchWorker("silos",{"cid":cid},self.cmb_acct2.currentText())
            w.result.connect(self._data); w.error.connect(lambda m: self.log.append(f"❌ {m}"))
            self.fetch_threads.append(w); w.start()

    def _search_f(self):
        q = self.inp_f.text().strip(); cid = self.cmb_ctr.currentData(); sid = self.cmb_silo.currentData()
        if not q or not cid or not sid: QMessageBox.warning(self,"!","أكمل البيانات"); return
        outer = "true" if self.chk_outer.isChecked() else "false"
        w = DataFetchWorker("farmers",{"cid":cid,"sid":sid,"outer":outer,"q":q},self.cmb_acct2.currentText())
        w.result.connect(self._data); w.error.connect(lambda m: self.log.append(f"❌ {m}"))
        self.fetch_threads.append(w); w.start()

    def _data(self, t, d):
        if t=="governorates":
            self.cmb_gov.clear(); self.cmb_gov.addItem("--","")
            for x in d: self.cmb_gov.addItem(x['name'], x['id'])
        elif t=="directorates":
            self.cmb_dir.clear(); self.cmb_dir.addItem("--","")
            for x in d: self.cmb_dir.addItem(x.get('name',''), str(x.get('id','')))
            self.cmb_dir.setEnabled(True)
        elif t=="centers":
            self.cmb_ctr.clear(); self.cmb_ctr.addItem("--","")
            for x in d: self.cmb_ctr.addItem(x.get('name',''), str(x.get('id','')))
            self.cmb_ctr.setEnabled(True)
        elif t=="silos":
            self.cmb_silo.clear(); self.cmb_silo.addItem("--","")
            for x in d: self.cmb_silo.addItem(x.get('name',''), str(x.get('id','')))
            self.cmb_silo.setEnabled(True)
        elif t=="farmers":
            self.cmb_f.clear(); self.cmb_f.addItem("--","")
            for x in d: self.cmb_f.addItem(x.get('text',''), str(x.get('id','')))
            self.cmb_f.setEnabled(bool(d))
            self.log.append(f"{'✅' if d else '⚠️'} {len(d)} نتيجة")

    def _save(self):
        fn = self.cmb_f.currentText() if self.cmb_f.currentData() else self.inp_f.text().strip()
        sid = self.cmb_silo.currentData(); cid = self.cmb_ctr.currentData()
        acct = self.cmb_acct2.currentText()
        outer = "true" if self.chk_outer.isChecked() else "false"
        if not fn or fn=="--": QMessageBox.warning(self,"!","اختر/اكتب فلاح"); return
        if not sid or not cid: QMessageBox.warning(self,"!","اختر الشعبة والسايلو"); return
        if not acct or acct=="(لا حسابات)": QMessageBox.warning(self,"!","اختر حساب"); return
        with sqlite3.connect(self.db) as c:
            c.execute("INSERT INTO transactions(client_name,silo_id,center_id,is_outer,account) VALUES(?,?,?,?,?)",
                      (fn,sid,cid,outer,acct))
        QMessageBox.information(self,"✅",f"تم حفظ ({fn}) بحساب [{acct}]")
        self._rtbl()

    def _direct_send(self):
        """إرسال مباشر فوري"""
        fn = self.cmb_f.currentText() if self.cmb_f.currentData() else self.inp_f.text().strip()
        sid = self.cmb_silo.currentData(); cid = self.cmb_ctr.currentData()
        acct = self.cmb_acct2.currentText()
        outer = "true" if self.chk_outer.isChecked() else "false"
        if not fn or fn=="--": QMessageBox.warning(self,"!","اختر/اكتب فلاح"); return
        if not sid or not cid: QMessageBox.warning(self,"!","اختر الشعبة والسايلو"); return
        if not acct or acct=="(لا حسابات)": QMessageBox.warning(self,"!","اختر حساب"); return
        self.btn_direct.setEnabled(False)
        w = DirectBookingWorker(acct, fn, sid, cid, outer)
        w.log.connect(self.log.append)
        w.done.connect(lambda ok, d: self.btn_direct.setEnabled(True))
        self.fetch_threads.append(w); w.start()

    def _rtbl(self):
        with sqlite3.connect(self.db) as c:
            rows = c.execute("SELECT id,client_name,silo_id,center_id,is_outer,account,status FROM transactions ORDER BY id DESC").fetchall()
        self.tbl.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                self.tbl.setItem(r, c, QTableWidgetItem(str(v or "")))

    def _del(self):
        r = self.tbl.currentRow()
        if r < 0: return
        tid = self.tbl.item(r, 0).text()
        if QMessageBox.question(self,"؟",f"حذف #{tid}?") == QMessageBox.StandardButton.Yes:
            with sqlite3.connect(self.db) as c: c.execute("DELETE FROM transactions WHERE id=?",(tid,))
            self._rtbl()

if __name__ == '__main__':
    app = QApplication(sys.argv); app.setStyle("Fusion")
    w = App(); w.show(); sys.exit(app.exec())
