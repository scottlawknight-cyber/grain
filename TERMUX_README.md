# بوت الحجز - نسخة Termux للموبايل 📱

## الملفات المطلوبة بجانب `termux_engine.py`:

| الملف | الوصف | المصدر |
|-------|--------|--------|
| `accounts.json` | الحسابات (كوكيز + توكن) | يُنسخ من الكمبيوتر بعد سحب التوكن |
| `transactions.json` | المعاملات المطلوب حجزها | تنشئه يدوياً أو تنسخه |

### مثال accounts.json (يُنسخ من الكمبيوتر كما هو):
```json
[
  {
    "name": "حساب1",
    "cookies": [...],
    "token": "CfDJ8..."
  }
]
```

### مثال transactions.json:
```json
[
  {
    "client_name": "اسم الفلاح",
    "silo_id": "123",
    "center_id": "456",
    "is_outer": "false",
    "account_name": "حساب1",
    "status": "pending"
  }
]
```

---

## تثبيت Termux:

```bash
# تحديث
pkg update && pkg upgrade -y

# تثبيت Python
pkg install python -y

# تثبيت المكتبات
pip install requests beautifulsoup4 urllib3
```

---

## أوامر التشغيل:

### 1. تشغيل عادي (يتوقف عند إغلاق Termux):
```bash
python termux_engine.py
```

### 2. تشغيل في الخلفية (يستمر حتى لو أغلقت Termux):
```bash
nohup python termux_engine.py > /dev/null 2>&1 &
```

### 3. تشغيل يستمر حتى لو أغلقت الجهاز (مع termux-wake-lock):
```bash
# أولاً: تثبيت termux-api
pkg install termux-api -y

# تفعيل wake-lock (يمنع الجهاز من إيقاف العمليات)
termux-wake-lock

# ثم شغل البوت
nohup python termux_engine.py > /dev/null 2>&1 &

# للتأكد أنه يعمل
cat engine.pid
```

### 4. أفضل طريقة (tmux - جلسة دائمة):
```bash
# تثبيت tmux
pkg install tmux -y

# إنشاء جلسة جديدة
tmux new -s bot

# داخل الجلسة:
termux-wake-lock
python termux_engine.py

# للخروج من الجلسة بدون إيقافها: اضغط Ctrl+B ثم D

# للرجوع للجلسة لاحقاً:
tmux attach -t bot
```

---

## مشاهدة اللوغ (السجل):

```bash
# مشاهدة اللوغ مباشرة (يتحدث لحظة بلحظة):
tail -f engine.log

# مشاهدة آخر 50 سطر:
tail -50 engine.log

# مشاهدة كل اللوغ:
cat engine.log

# البحث عن حجز ناجح:
grep "🎉" engine.log

# البحث عن أخطاء:
grep "❌" engine.log
```

---

## إيقاف البوت:

```bash
# الطريقة 1: بالـ PID
kill $(cat engine.pid)

# الطريقة 2: إيقاف كل عمليات Python
pkill -f termux_engine.py

# الطريقة 3: إذا كنت في tmux
tmux attach -t bot
# ثم Ctrl+C
```

---

## إلغاء wake-lock:
```bash
termux-wake-unlock
```

---

## التحقق أن البوت يعمل:
```bash
# هل العملية موجودة؟
ps aux | grep termux_engine

# أو بالـ PID:
cat engine.pid && ps -p $(cat engine.pid)
```

---

## ملاحظات مهمة:

1. **التأخير**: 0.5 - 2 ثانية عشوائي (سريع جداً)
2. **المحرك**: يدور على المعاملات بالترتيب، عند نجاح حجز → يرسل لكل المتبقية
3. **تحديث المعاملات**: يمكنك تعديل `transactions.json` أثناء عمل البوت (يعيد تحميله كل دورة)
4. **الحسابات**: إذا انتهى التوكن، عدّل `accounts.json` بتوكن جديد من الكمبيوتر
5. **النتائج**: المعاملات المحجوزة تتحول لـ `"status": "booked"` في الملف

---

## نقل الملفات من الكمبيوتر للموبايل:

### عبر USB:
1. انسخ `accounts.json` و `transactions.json` إلى مجلد Termux:
   - المسار: `/data/data/com.termux/files/home/`

### عبر WiFi (scp):
```bash
# على الكمبيوتر (Windows PowerShell):
scp accounts.json transactions.json termux_engine.py user@phone-ip:~/
```

### عبر تلجرام/واتساب:
- أرسل الملفات لنفسك
- انسخها إلى مجلد Termux:
```bash
cp /storage/emulated/0/Download/accounts.json ~/
cp /storage/emulated/0/Download/transactions.json ~/
```

---

## هيكل المجلد النهائي:
```
~/
├── termux_engine.py      ← الكود
├── accounts.json         ← الحسابات (من الكمبيوتر)
├── transactions.json     ← المعاملات
├── engine.log            ← السجل (يتولد تلقائياً)
└── engine.pid            ← رقم العملية (يتولد تلقائياً)
```
