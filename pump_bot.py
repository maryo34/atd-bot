"""
🚀 PUMP DETECTOR BOT
Binance'teki tüm coinleri 5 dakikada bir tarar.
Spot hacim spike + Open Interest artışı tespit edince Telegram'a bildirim atar.
"""

import asyncio
import aiohttp
import time
import logging
from datetime import datetime
from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    CHECK_INTERVAL_SECONDS,
    VOLUME_SPIKE_THRESHOLD,
    OI_CHANGE_THRESHOLD,
    PRICE_CHANGE_THRESHOLD,
    MIN_USDT_VOLUME,
    SIGNAL_COOLDOWN_MINUTES,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("pump_bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# Son sinyal zamanlarını tut (spam önleme)
last_signal: dict[str, float] = {}


# ─────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────
async def send_telegram(session: aiohttp.ClientSession, message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status != 200:
                text = await r.text()
                log.warning(f"Telegram hata: {r.status} - {text}")
    except Exception as e:
        log.error(f"Telegram gönderilemedi: {e}")


# ─────────────────────────────────────────────
# BİNANCE API
# ─────────────────────────────────────────────
async def get_spot_tickers(session: aiohttp.ClientSession) -> dict:
    """Tüm USDT spot paritelerinin 24s verisini çek."""
    url = "https://api.binance.com/api/v3/ticker/24hr"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
            data = await r.json()
            return {
                d["symbol"]: d
                for d in data
                if d["symbol"].endswith("USDT") and float(d.get("quoteVolume", 0)) > MIN_USDT_VOLUME
            }
    except Exception as e:
        log.error(f"Spot ticker hatası: {e}")
        return {}


async def get_futures_tickers(session: aiohttp.ClientSession) -> dict:
    """Tüm USDT futures paritelerinin 24s verisini çek."""
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
            data = await r.json()
            return {d["symbol"]: d for d in data if d["symbol"].endswith("USDT")}
    except Exception as e:
        log.error(f"Futures ticker hatası: {e}")
        return {}


async def get_open_interest(session: aiohttp.ClientSession) -> dict:
    """Tüm futures sembollerinin Open Interest verisini çek."""
    url = "https://fapi.binance.com/fapi/v1/openInterest"
    # OI için her sembolü ayrı çekmek gerekiyor — önce sembol listesini al
    info_url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    oi_data = {}
    try:
        async with session.get(info_url, timeout=aiohttp.ClientTimeout(total=15)) as r:
            info = await r.json()
            symbols = [
                s["symbol"]
                for s in info.get("symbols", [])
                if s["symbol"].endswith("USDT") and s["status"] == "TRADING"
            ]

        # Paralel OI çekimi (max 20 eş zamanlı istek)
        semaphore = asyncio.Semaphore(20)

        async def fetch_oi(sym):
            async with semaphore:
                try:
                    async with session.get(
                        url,
                        params={"symbol": sym},
                        timeout=aiohttp.ClientTimeout(total=8),
                    ) as r:
                        if r.status == 200:
                            d = await r.json()
                            oi_data[sym] = float(d.get("openInterest", 0))
                except Exception:
                    pass

        await asyncio.gather(*[fetch_oi(s) for s in symbols])
    except Exception as e:
        log.error(f"OI çekme hatası: {e}")
    return oi_data


# ─────────────────────────────────────────────
# ANA ANALİZ MOTORU
# ─────────────────────────────────────────────
class PumpDetector:
    def __init__(self):
        # Önceki döngüden kalan veriler
        self.prev_spot: dict = {}
        self.prev_oi: dict = {}
        self.prev_futures: dict = {}

    def analyze(
        self,
        spot: dict,
        futures: dict,
        oi: dict,
        prev_spot: dict,
        prev_oi: dict,
    ) -> list[dict]:
        """
        Pump sinyali kriterleri (konservatif — hepsi aynı anda olmalı):
          1. Spot fiyat son 5dk'da +%PRICE_CHANGE_THRESHOLD üzeri
          2. Spot hacim son döngüye göre xVOLUME_SPIKE_THRESHOLD katı
          3. Futures OI son döngüye göre +%OI_CHANGE_THRESHOLD artış
        """
        signals = []
        now = time.time()

        for symbol, ticker in spot.items():
            futures_sym = symbol  # BTCUSDT → BTCUSDT

            # Cooldown kontrolü
            if now - last_signal.get(symbol, 0) < SIGNAL_COOLDOWN_MINUTES * 60:
                continue

            try:
                price_now = float(ticker["lastPrice"])
                price_change_pct = float(ticker["priceChangePercent"])
                vol_now = float(ticker["quoteVolume"])  # USDT cinsinden hacim

                # Önceki veri yoksa atla
                if symbol not in prev_spot:
                    continue

                prev_ticker = prev_spot[symbol]
                vol_prev = float(prev_ticker.get("quoteVolume", 0))

                # ── Kriter 1: Fiyat değişimi ──
                if price_change_pct < PRICE_CHANGE_THRESHOLD:
                    continue

                # ── Kriter 2: Hacim spike ──
                if vol_prev <= 0:
                    continue
                vol_ratio = vol_now / vol_prev
                if vol_ratio < VOLUME_SPIKE_THRESHOLD:
                    continue

                # ── Kriter 3: OI artışı ──
                oi_now = oi.get(futures_sym, 0)
                oi_prev = prev_oi.get(futures_sym, 0)
                if oi_prev <= 0 or oi_now <= 0:
                    continue
                oi_change_pct = (oi_now - oi_prev) / oi_prev * 100
                if oi_change_pct < OI_CHANGE_THRESHOLD:
                    continue

                # Futures fiyatı
                fut_price = None
                if futures_sym in futures:
                    fut_price = float(futures[futures_sym].get("lastPrice", 0))

                signals.append({
                    "symbol": symbol,
                    "price": price_now,
                    "price_change_pct": price_change_pct,
                    "vol_now_m": vol_now / 1_000_000,
                    "vol_ratio": vol_ratio,
                    "oi_change_pct": oi_change_pct,
                    "oi_now": oi_now,
                    "fut_price": fut_price,
                })
                last_signal[symbol] = now

            except (ValueError, KeyError, ZeroDivisionError):
                continue

        # Güce göre sırala
        signals.sort(key=lambda x: x["price_change_pct"] + x["oi_change_pct"], reverse=True)
        return signals

    def format_message(self, sig: dict) -> str:
        coin = sig["symbol"].replace("USDT", "")
        now_str = datetime.now().strftime("%H:%M:%S")

        # Güç seviyesi
        score = sig["price_change_pct"] + sig["oi_change_pct"]
        if score > 20:
            strength = "🔥🔥🔥 ÇOK GÜÇLÜ"
        elif score > 12:
            strength = "🔥🔥 GÜÇLÜ"
        else:
            strength = "🔥 ORTA"

        msg = (
            f"⚡ <b>PUMP SİNYALİ — {coin}</b> [{now_str}]\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Fiyat:</b> ${sig['price']:,.4f}  "
            f"(<b>+{sig['price_change_pct']:.2f}%</b>)\n"
            f"📊 <b>Spot Hacim:</b> ${sig['vol_now_m']:.1f}M  "
            f"(x{sig['vol_ratio']:.1f} spike)\n"
            f"📈 <b>OI Artışı:</b> +{sig['oi_change_pct']:.2f}%\n"
        )
        if sig["fut_price"]:
            msg += f"🔮 <b>Futures:</b> ${sig['fut_price']:,.4f}\n"
        msg += (
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"{strength}\n"
            f"🔗 <a href='https://www.binance.com/tr/trade/{coin}_USDT'>Binance'te Aç</a>"
        )
        return msg


# ─────────────────────────────────────────────
# DÖNGÜ
# ─────────────────────────────────────────────
async def main():
    detector = PumpDetector()

    log.info("🚀 Pump Detector Bot başlatıldı!")
    log.info(f"   Tarama aralığı : {CHECK_INTERVAL_SECONDS}s")
    log.info(f"   Fiyat eşiği    : +{PRICE_CHANGE_THRESHOLD}%")
    log.info(f"   Hacim spike    : x{VOLUME_SPIKE_THRESHOLD}")
    log.info(f"   OI eşiği       : +{OI_CHANGE_THRESHOLD}%")

    async with aiohttp.ClientSession() as session:
        # Başlangıç mesajı
        await send_telegram(session, "✅ <b>Pump Detector Bot aktif!</b>\nBinance tüm coinler taranıyor...")

        while True:
            loop_start = time.time()
            log.info("─── Tarama başlıyor ───")

            try:
                # Tüm verileri paralel çek
                spot, futures, oi = await asyncio.gather(
                    get_spot_tickers(session),
                    get_futures_tickers(session),
                    get_open_interest(session),
                )

                log.info(f"Spot: {len(spot)} | Futures: {len(futures)} | OI: {len(oi)} sembol")

                # Analiz et
                signals = detector.analyze(
                    spot, futures, oi,
                    detector.prev_spot, detector.prev_oi,
                )

                if signals:
                    log.info(f"✅ {len(signals)} sinyal bulundu!")
                    for sig in signals[:5]:  # Max 5 sinyal gönder
                        msg = detector.format_message(sig)
                        await send_telegram(session, msg)
                        await asyncio.sleep(0.5)
                else:
                    log.info("Sinyal yok.")

                # Verileri güncelle
                detector.prev_spot = spot
                detector.prev_oi = oi
                detector.prev_futures = futures

            except Exception as e:
                log.error(f"Döngü hatası: {e}", exc_info=True)

            # Sonraki döngüye kadar bekle
            elapsed = time.time() - loop_start
            wait = max(0, CHECK_INTERVAL_SECONDS - elapsed)
            log.info(f"Tarama {elapsed:.1f}s sürdü. {wait:.0f}s bekleniyor...")
            await asyncio.sleep(wait)


if __name__ == "__main__":
    asyncio.run(main())
