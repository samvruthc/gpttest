from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, List
import httpx
import time
from datetime import datetime

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

YF_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "*/*",
    "Referer": "https://finance.yahoo.com"
}

CACHE = {}

DEFAULT_UNIVERSE = [
    {"ticker": "NVDA", "name": "NVIDIA Corporation", "sector": "Semiconductors"},
    {"ticker": "AAPL", "name": "Apple Inc", "sector": "Consumer Tech"},
    {"ticker": "MSFT", "name": "Microsoft Corporation", "sector": "Software"},
    {"ticker": "AMZN", "name": "Amazon.com Inc", "sector": "E-Commerce"},
    {"ticker": "META", "name": "Meta Platforms", "sector": "Internet"},
    {"ticker": "GOOGL", "name": "Alphabet Inc", "sector": "Internet"},
    {"ticker": "TSLA", "name": "Tesla Inc", "sector": "Automotive"},
    {"ticker": "AMD", "name": "Advanced Micro Devices", "sector": "Semiconductors"},
]

CUSTOM_TICKERS = []


def _cache_get(key, ttl=30):
    item = CACHE.get(key)

    if not item:
        return None

    value, ts = item

    if time.time() - ts > ttl:
        del CACHE[key]
        return None

    return value


def _cache_set(key, value):
    CACHE[key] = (value, time.time())


def get_universe():
    seen = set()
    result = []

    for c in DEFAULT_UNIVERSE + CUSTOM_TICKERS:
        if c["ticker"] not in seen:
            seen.add(c["ticker"])
            result.append(c)

    return result


# ---------------- FIXED YAHOO FINANCE FETCH ----------------

async def yf_v7_quote(tickers: List[str]) -> Dict[str, Any]:

    symbols = ",".join(tickers)

    key = f"v7:{symbols}"

    cached = _cache_get(key, 15)

    if cached:
        return cached

    try:

        url = (
            f"https://query1.finance.yahoo.com/v7/finance/quote"
            f"?symbols={symbols}"
        )

        async with httpx.AsyncClient(
            timeout=15,
            headers=YF_HEADERS,
            follow_redirects=True
        ) as client:

            r = await client.get(url)

        if r.status_code != 200:
            print("Yahoo status error:", r.status_code)
            return {}

        data = r.json()

        results = data.get("quoteResponse", {}).get("result", [])

        out = {}

        for q in results:

            symbol = q.get("symbol")

            if not symbol:
                continue

            out[symbol] = {
                "price": q.get("regularMarketPrice"),
                "change": q.get("regularMarketChange"),
                "changePct": q.get("regularMarketChangePercent"),
                "marketCap": q.get("marketCap"),
                "peRatio": q.get("trailingPE"),
                "volume": q.get("regularMarketVolume"),
                "fiftyTwoWeekHigh": q.get("fiftyTwoWeekHigh"),
                "fiftyTwoWeekLow": q.get("fiftyTwoWeekLow"),
                "name": q.get("longName") or q.get("shortName"),
                "sector": q.get("sector")
            }

        _cache_set(key, out)

        return out

    except Exception as e:

        print("YF ERROR:", e)

        return {}


# ---------------- CHART ----------------

async def yf_chart(ticker: str, rng: str = "6mo"):

    try:

        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
            f"?range={rng}&interval=1d"
        )

        async with httpx.AsyncClient(
            timeout=15,
            headers=YF_HEADERS
        ) as client:

            r = await client.get(url)

        data = r.json()

        result = data["chart"]["result"][0]

        timestamps = result.get("timestamp", [])

        closes = (
            result["indicators"]
            ["quote"][0]
            .get("close", [])
        )

        return {
            "timestamps": timestamps,
            "closes": closes
        }

    except Exception as e:

        print("CHART ERROR:", e)

        return {
            "timestamps": [],
            "closes": []
        }


# ---------------- ROUTES ----------------

@app.get("/")
async def root():
    return {"status": "ORION backend online"}


@app.get("/api/orion/universe")
async def universe():
    return {"companies": get_universe()}


@app.get("/api/orion/quotes")
async def quotes(tickers: str):

    ticker_list = [
        t.strip().upper()
        for t in tickers.split(",")
    ]

    data = await yf_v7_quote(ticker_list)

    out = []

    for t in ticker_list:

        q = data.get(t, {})

        out.append({
            "ticker": t,
            "price": q.get("price"),
            "change": q.get("change"),
            "changePct": q.get("changePct"),
            "marketCap": q.get("marketCap"),
            "peRatio": q.get("peRatio"),
            "volume": q.get("volume"),
            "fiftyTwoWeekHigh": q.get("fiftyTwoWeekHigh"),
            "fiftyTwoWeekLow": q.get("fiftyTwoWeekLow")
        })

    return {"quotes": out}


@app.get("/api/orion/quote/{ticker}")
async def quote(ticker: str):

    ticker = ticker.upper()

    data = await yf_v7_quote([ticker])

    q = data.get(ticker, {})

    return {
        "ticker": ticker,
        "price": q.get("price"),
        "change": q.get("change"),
        "changePct": q.get("changePct"),
        "marketCap": q.get("marketCap"),
        "peRatio": q.get("peRatio"),
        "volume": q.get("volume"),
        "fiftyTwoWeekHigh": q.get("fiftyTwoWeekHigh"),
        "fiftyTwoWeekLow": q.get("fiftyTwoWeekLow"),
        "name": q.get("name"),
        "sector": q.get("sector")
    }


@app.get("/api/orion/chart/{ticker}")
async def chart(ticker: str, rng: str = "6mo"):
    return await yf_chart(ticker.upper(), rng)


@app.get("/api/orion/dashboard/{ticker}")
async def dashboard(ticker: str):

    ticker = ticker.upper()

    data = await yf_v7_quote([ticker])

    q = data.get(ticker, {})

    chart = await yf_chart(ticker)

    score = 50
    signals = []

    pe = q.get("peRatio")
    chg = q.get("changePct")

    if pe and pe < 25:
        score += 10
        signals.append({
            "type": "VALUATION",
            "label": f"Attractive valuation — P/E {pe:.1f}x",
            "confidence": 0.77,
            "severity": "info"
        })

    if chg and chg > 2:
        score += 8
        signals.append({
            "type": "MOMENTUM",
            "label": f"Strong momentum session +{chg:.2f}%",
            "confidence": 0.81,
            "severity": "info"
        })

    if chg and chg < -2:
        score -= 8
        signals.append({
            "type": "PRICE_ACTION",
            "label": f"Weak session {chg:.2f}%",
            "confidence": 0.72,
            "severity": "warn"
        })

    score = max(10, min(95, score))

    return {
        "quote": {
            "ticker": ticker,
            "price": q.get("price"),
            "change": q.get("change"),
            "changePct": q.get("changePct"),
            "marketCap": q.get("marketCap"),
            "peRatio": q.get("peRatio"),
            "volume": q.get("volume"),
            "fiftyTwoWeekHigh": q.get("fiftyTwoWeekHigh"),
            "fiftyTwoWeekLow": q.get("fiftyTwoWeekLow")
        },

        "chart": chart,

        "signals": {
            "score": score,
            "signals": signals
        },

        "filings": [
            {
                "form": "10-K",
                "date": "2025-01-31",
                "description": "Annual report",
                "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={ticker}"
            },
            {
                "form": "10-Q",
                "date": "2025-04-30",
                "description": "Quarterly report",
                "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={ticker}"
            }
        ]
    }


@app.get("/api/orion/news")
async def news(ticker: str = None):

    base = ticker or "Markets"

    return {
        "news": [
            {
                "title": f"{base}: Analysts weigh in ahead of earnings",
                "link": f"https://finance.yahoo.com/quote/{base}/news/",
                "source": "Yahoo Finance",
                "published": str(datetime.utcnow())
            },
            {
                "title": f"Institutional flows into {base} accelerate",
                "link": f"https://finance.yahoo.com/quote/{base}/news/",
                "source": "Reuters",
                "published": str(datetime.utcnow())
            }
        ]
    }


@app.get("/api/orion/agents/activity")
async def agents():

    return {
        "events": [
            {
                "agent": "CRAWLER",
                "action": "Fetched Yahoo Finance live quote data",
                "target": "UNIVERSE",
                "level": "info",
                "ts": str(datetime.utcnow())
            },
            {
                "agent": "SIGNAL",
                "action": "Generated signal scoring",
                "target": "SELECTED",
                "level": "info",
                "ts": str(datetime.utcnow())
            },
            {
                "agent": "SYNTHESIS",
                "action": "Updated investment intelligence",
                "target": "DASHBOARD",
                "level": "info",
                "ts": str(datetime.utcnow())
            }
        ]
    }


@app.get("/api/orion/memo/{ticker}")
async def memo(ticker: str):

    ticker = ticker.upper()

    data = await yf_v7_quote([ticker])

    q = data.get(ticker, {})

    price = q.get("price") or 0
    pe = q.get("peRatio")
    cap = q.get("marketCap") or 0

    recommendation = "HOLD"

    if pe and pe < 25:
        recommendation = "BUY"

    if pe and pe > 50:
        recommendation = "SELL"

    return {
        "generated_at": str(datetime.utcnow()),
        "ticker": ticker,
        "memo": {
            "recommendation": recommendation,
            "conviction": 7,
            "thesis": f"{ticker} trades at ${price:.2f} with market cap ${cap/1e9:.1f}B.",
            "bull_case": [
                "Institutional quality balance sheet",
                "Strong momentum and liquidity"
            ],
            "bear_case": [
                "Macro volatility risk",
                "High valuation sensitivity"
            ],
            "catalysts": [
                "Upcoming earnings",
                "AI infrastructure growth"
            ],
            "risks": [
                "Multiple compression",
                "Market-wide correction"
            ]
        }
    }


if __name__ == "__main__":

    import uvicorn
    import os

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000))
    )
