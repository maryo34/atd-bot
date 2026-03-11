# ============================================================
# ⚙️  PUMP DETECTOR BOT — AYARLAR
# ============================================================
# Telegram bilgilerini buraya gir
TELEGRAM_BOT_TOKEN = "8387861414:AAH0LVF3QSssHi9j5DhlkapznjNAjzAeQyo"
TELEGRAM_CHAT_ID   = "6267792856"

# ── Tarama aralığı ──────────────────────────────────────────
CHECK_INTERVAL_SECONDS = 300   # 5 dakika

# ── Sinyal eşikleri (konservatif) ───────────────────────────
# Fiyat: son 24 saatte en az +% artış
PRICE_CHANGE_THRESHOLD = 5.0    # %5 (daha hassas için 3.0)

# Hacim: önceki döngüye göre kaç kat artmalı
VOLUME_SPIKE_THRESHOLD = 2.5    # 2.5x (daha hassas için 1.8)

# Open Interest: önceki döngüye göre en az +% artış
OI_CHANGE_THRESHOLD = 3.0       # %3 (daha hassas için 2.0)

# ── Filtreler ────────────────────────────────────────────────
# Minimum 24 saatlik USDT hacmi (düşük hacimli coinleri ele)
MIN_USDT_VOLUME = 1_000_000     # 1 milyon USDT

# Aynı coin için tekrar sinyal göndermeden önce beklenecek süre
SIGNAL_COOLDOWN_MINUTES = 30    # 30 dakika

# ============================================================
# EŞİK AYAR REHBERİ:
#
#  Çok fazla sinyal geliyorsa → eşikleri artır
#    PRICE_CHANGE_THRESHOLD = 8.0
#    VOLUME_SPIKE_THRESHOLD = 3.5
#    OI_CHANGE_THRESHOLD    = 5.0
#
#  Hiç sinyal gelmiyorsa → eşikleri düşür
#    PRICE_CHANGE_THRESHOLD = 3.0
#    VOLUME_SPIKE_THRESHOLD = 1.8
#    OI_CHANGE_THRESHOLD    = 2.0
# ============================================================
