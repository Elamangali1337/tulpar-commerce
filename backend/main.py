from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
import sqlite3
import smtplib
import time
import httpx
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_NAME = "contacts.db"

def init_db():
    # Initialize database and create table if it doesn't exist
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            business_name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

class ContactForm(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    business_name: str = Field(..., min_length=2, max_length=150)
    email: EmailStr 
    phone: str = Field(..., pattern=r'^\+?1?\d{9,15}$') 
    message: str = Field(..., min_length=10, max_length=3000)

# Function to send email notifications
def send_email_notification(form_data: ContactForm):
    api_key = os.getenv("BREVO_API_KEY")
    sender = os.getenv("EMAIL_SENDER")
    receiver = os.getenv("EMAIL_RECEIVER")

    if not api_key or not sender or not receiver:
        print("[-] Email credentials are not configured.")
        return

    payload = {
        "sender": {"name": "Tulpar Commerce Website", "email": sender},
        "to": [{"email": receiver}],
        "subject": f"New website inquiry from {form_data.business_name}",
        "textContent": (
            "A new inquiry has been submitted on the website!\n\n"
            f"Name: {form_data.name}\n"
            f"Business: {form_data.business_name}\n"
            f"Email: {form_data.email}\n"
            f"Phone: {form_data.phone}\n\n"
            f"Message:\n{form_data.message}"
        ),
    }

    try:
        resp = httpx.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"api-key": api_key, "content-type": "application/json"},
            json=payload,
            timeout=15,
        )
        if resp.status_code in (200, 201):
            print("[+] Email notification sent successfully via Brevo!")
        else:
            print(f"[-] Brevo error {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"[-] Error sending email: {e}")

# Note the added background_tasks parameter
@app.post("/api/contact")
async def submit_contact_form(form_data: ContactForm, background_tasks: BackgroundTasks):
    
    # 1. Save to the SQLite database
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO contacts (name, business_name, email, phone, message)
        VALUES (?, ?, ?, ?, ?)
    ''', (form_data.name, form_data.business_name, form_data.email, form_data.phone, form_data.message))
    conn.commit()
    conn.close()

    print(f"\n[+] New inquiry saved to DB from: {form_data.name}\n")
    
    # 2. Pass the email sending task to the background
    background_tasks.add_task(send_email_notification, form_data)
    
    return {"status": "success", "message": "Form submitted successfully"}


# ============================================================
#  CRYPTO CONVERTER
#  Курсы берутся с публичного API CoinGecko (без API-ключа)
#  и кэшируются в памяти, чтобы не упереться в лимиты.
# ============================================================

# Тикер -> id монеты в CoinGecko
CRYPTO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "USDT": "tether",
    "USDC": "usd-coin",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "LTC": "litecoin",
    "TON": "the-open-network",
    "TRX": "tron",
}

# Поддерживаемые фиатные валюты (нижний регистр — так требует CoinGecko)
FIAT_CURRENCIES = ["usd", "eur", "gbp", "aed", "try"]

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"

# Простой кэш в памяти процесса
_rates_cache = {"data": None, "timestamp": 0.0}
RATES_CACHE_TTL = 300  # секунд


async def get_rates() -> dict:
    """Вернуть курсы вида {"BTC": {"usd": 97000, "eur": ...}, ...}.
    Использует кэш; при недоступности CoinGecko отдаёт последние
    известные данные, если они есть."""
    now = time.time()
    if _rates_cache["data"] and now - _rates_cache["timestamp"] < RATES_CACHE_TTL:
        return _rates_cache["data"]

    params = {
        "ids": ",".join(CRYPTO_IDS.values()),
        "vs_currencies": ",".join(FIAT_CURRENCIES),
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(COINGECKO_URL, params=params)
            resp.raise_for_status()
            raw = resp.json()
    except Exception as e:
        print(f"[-] CoinGecko error: {e}")
        if _rates_cache["data"]:
            # Отдаём устаревший кэш — лучше, чем ничего
            return _rates_cache["data"]
        raise HTTPException(status_code=503, detail="Rates provider is unavailable")

    # Переводим id монет обратно в тикеры
    rates = {}
    for ticker, gecko_id in CRYPTO_IDS.items():
        if gecko_id in raw:
            rates[ticker] = raw[gecko_id]

    _rates_cache["data"] = rates
    _rates_cache["timestamp"] = now
    return rates


def _to_usd(currency: str, amount: float, rates: dict) -> float:
    """Перевести сумму в USD (внутренняя 'базовая' валюта)."""
    if currency in CRYPTO_IDS:
        return amount * rates[currency]["usd"]
    # Фиат: кросс-курс через BTC (у CoinGecko нет прямых фиатных пар)
    btc = rates["BTC"]
    usd_per_unit = btc["usd"] / btc[currency.lower()]
    return amount * usd_per_unit


def _from_usd(currency: str, usd_amount: float, rates: dict) -> float:
    """Перевести сумму из USD в целевую валюту."""
    if currency in CRYPTO_IDS:
        return usd_amount / rates[currency]["usd"]
    btc = rates["BTC"]
    usd_per_unit = btc["usd"] / btc[currency.lower()]
    return usd_amount / usd_per_unit


@app.get("/api/rates")
async def api_rates():
    """Все курсы разом — фронтенд кэширует их и считает локально."""
    rates = await get_rates()
    return {
        "rates": rates,
        "cryptos": list(CRYPTO_IDS.keys()),
        "fiats": [f.upper() for f in FIAT_CURRENCIES],
        "updated_at": int(_rates_cache["timestamp"]),
    }


@app.get("/api/convert")
async def api_convert(
    from_currency: str = Query(..., alias="from", min_length=2, max_length=6),
    to_currency: str = Query(..., alias="to", min_length=2, max_length=6),
    amount: float = Query(..., gt=0, le=1e15),
):
    """Конвертация: крипта<->фиат и крипта<->крипта."""
    src = from_currency.upper()
    dst = to_currency.upper()
    supported = set(CRYPTO_IDS) | {f.upper() for f in FIAT_CURRENCIES}

    if src not in supported or dst not in supported:
        raise HTTPException(status_code=400, detail="Unsupported currency")
    if src == dst:
        return {"from": src, "to": dst, "amount": amount, "result": amount, "rate": 1}

    rates = await get_rates()
    usd_value = _to_usd(src, amount, rates)
    result = _from_usd(dst, usd_value, rates)

    return {
        "from": src,
        "to": dst,
        "amount": amount,
        "result": result,
        "rate": result / amount,
        "updated_at": int(_rates_cache["timestamp"]),
    }