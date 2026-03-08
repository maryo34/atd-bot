import asyncio
import aiohttp
import pandas as pd
import numpy as np
from datetime import datetime
import logging

# === AYARLAR ===
TELEGRAM_TOKEN = "8387861414:AAH0LVF3QSssHi9j5DhlkapznjNAjzAeQyo"
CHAT_ID = "6267792856"
RSI_LEN = 14
RSI_SIG_LEN = 9
RSI_OB = 70
RSI_OS = 30
CHECK_INTERVAL = 60  # saniye (1H mum kapanışını kontrol sıklığı)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# === TELEGRAM ===
async def send_telegram(session, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        async with session.post(url, json=payload) as r:
            if r.status == 200:
                log.info(f"Telegram gönderildi: {text[:50]}")
    except Exception as e:
        log.error(f"Telegram hata: {e}")

# === BİNANCE ===
async def get_futures_symbols(session):
    url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    try:
        async with session.get(url) as r:
            data = await r.json()
            symbols = [
                s["symbol"] for s in data["symbols"]
                if s["status"] == "TRADING" and s["symbol"].endswith("USDT")
            ]
            return symbols
    except Exception as e:
        log.error(f"Sembol listesi hatası: {e}")
        return []

async def get_klines(session, symbol, interval="1h", limit=100):
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        async with session.get(url, params=params) as r:
            data = await r.json()
            closes = [float(k[4]) for k in data]
            return closes
    except Exception as e:
        log.error(f"{symbol} kline hatası: {e}")
        return []

# === RSI HESAPLAMA ===
def calc_rsi(closes, period=14):
    closes = pd.Series(closes)
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def check_rsi_signal(closes):
    if len(closes) < 50:
        return None

    rsi = calc_rsi(closes, RSI_LEN)
    rsi_sig = calc_ema(rsi, RSI_SIG_LEN)

    # Son 2 bar
    rsi_now  = rsi.iloc[-1]
    rsi_prev = rsi.iloc[-2]
    sig_now  = rsi_sig.iloc[-1]
    sig_prev = rsi_sig.iloc[-2]

    # RSI sinyal çizgisini 30 ALTINDA yukarı kesti = LONG
    cross_up = (rsi_prev <= sig_prev) and (rsi_now > sig_now) and (rsi_now <= RSI_OS)

    # RSI sinyal çizgisini 70 ÜSTÜNDE aşağı kesti = SHORT
    cross_down = (rsi_prev >= sig_prev) and (rsi_now < sig_now) and (rsi_now >= RSI_OB)

    if cross_up:
        return ("LONG", round(rsi_now, 2))
    if cross_down:
        return ("SHORT", round(rsi_now, 2))
    return None

# === ANA DÖNGÜ ===
async def main():
    log.info("ATD Bot başlatıldı...")
    alerted = {}  # son sinyal zamanını tut (spam önleme)

    async with aiohttp.ClientSession() as session:
        await send_telegram(session, "🤖 <b>ATD Bot Başlatıldı</b>\nBinance Vadeli tüm coinler izleniyor...\n\n🟢 LONG = RSI 30 altında kesişim\n🔴 SHORT = RSI 70 üstünde kesişim")

        while True:
            try:
                symbols = await get_futures_symbols(session)
                log.info(f"{len(symbols)} coin kontrol ediliyor...")

                # Paralel istek için sembol grupları
                batch_size = 20
                for i in range(0, len(symbols), batch_size):
                    batch = symbols[i:i + batch_size]
                    tasks = [get_klines(session, sym) for sym in batch]
                    results = await asyncio.gather(*tasks)

                    for sym, closes in zip(batch, results):
                        if not closes:
                            continue

                        signal = check_rsi_signal(closes)
                        if signal is None:
                            continue

                        direction, rsi_val = signal
                        now = datetime.utcnow()

                        # Aynı coin için son 4 saatte tekrar gönderme
                        last = alerted.get(sym)
                        if last and (now - last).seconds < 14400:
                            continue

                        alerted[sym] = now
                        price = closes[-1]

                        if direction == "LONG":
                            msg = (
                                f"🟢 <b>LONG SİNYALİ</b>\n"
                                f"Coin: <b>{sym}</b>\n"
                                f"RSI: {rsi_val} (30 altında kesişim)\n"
                                f"Fiyat: {price}\n"
                                f"Zaman: {now.strftime('%H:%M UTC')}"
                            )
                        else:
                            msg = (
                                f"🔴 <b>SHORT SİNYALİ</b>\n"
                                f"Coin: <b>{sym}</b>\n"
                                f"RSI: {rsi_val} (70 üstünde kesişim)\n"
                                f"Fiyat: {price}\n"
                                f"Zaman: {now.strftime('%H:%M UTC')}"
                            )

                        await send_telegram(session, msg)
                        await asyncio.sleep(0.3)

                    await asyncio.sleep(0.5)

                log.info(f"Tarama tamamlandı. {CHECK_INTERVAL}s bekleniyor...")
                await asyncio.sleep(CHECK_INTERVAL)

            except Exception as e:
                log.error(f"Ana döngü hatası: {e}")
                await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
