# نسخة Termux 📱

## الملفات المطلوبة (نفس المجلد):
```
~/bot/
├── termux_engine.py      ← الكود
├── accounts.json         ← من الكمبيوتر
└── transactions.json     ← من الكمبيوتر
```

---

## تثبيت (مرة وحدة):
```bash
pkg update -y && pkg install python -y
pip install requests
```

---

## ▶️ تشغيل (يستمر مع إغلاق الجهاز):
```bash
termux-wake-lock
nohup python termux_engine.py &
```

## 📺 مشاهدة اللوغ:
```bash
tail -f engine.log
```

## ⏹️ إيقاف:
```bash
kill $(cat engine.pid)
```

## ✅ هل يعمل؟
```bash
cat engine.pid
```

---

## نقل الملفات من الكمبيوتر:
```bash
# من تلجرام/واتساب بعد التحميل:
cp /storage/emulated/0/Download/accounts.json ~/bot/
cp /storage/emulated/0/Download/transactions.json ~/bot/
```
