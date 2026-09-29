from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import pandas as pd
import numpy as np
from datetime import datetime, timezone

app = FastAPI(title="XAUUSD SMC Signal V1", version="1.0.0")

# V1 uses deterministic demo candles so the complete web application
# can be tested before connecting a live XAUUSD provider.
def make_demo_data(n=180):
    rng = np.random.default_rng(7)
    base = 3330.0
    rows = []
    price = base
    start = pd.Timestamp("2026-09-29 08:00:00", tz="UTC")
    for i in range(n):
        drift = 0.18 if i < 90 else -0.10
        shock = rng.normal(0, 2.6)
        o = price
        c = max(1, price + drift + shock)
        h = max(o, c) + abs(rng.normal(0, 1.6))
        l = min(o, c) - abs(rng.normal(0, 1.6))
        rows.append([start + pd.Timedelta(minutes=15*i), o, h, l, c])
        price = c
    return pd.DataFrame(rows, columns=["time","open","high","low","close"])

def swing_points(df, left=2, right=2):
    highs, lows = [], []
    for i in range(left, len(df)-right):
        h = df.high.iloc[i]
        l = df.low.iloc[i]
        if h == df.high.iloc[i-left:i+right+1].max():
            highs.append(i)
        if l == df.low.iloc[i-left:i+right+1].min():
            lows.append(i)
    return highs, lows

def analyze_smc(df):
    highs, lows = swing_points(df)
    last = df.iloc[-1]
    recent = df.iloc[-30:]
    prev_high = df.high.iloc[highs[-2]] if len(highs) >= 2 else recent.high.max()
    prev_low = df.low.iloc[lows[-2]] if len(lows) >= 2 else recent.low.min()

    # Liquidity sweep: last candle takes a recent swing and closes back inside.
    sweep_high = last.high > prev_high and last.close < prev_high
    sweep_low = last.low < prev_low and last.close > prev_low

    # Simple structure confirmation.
    bullish_mss = last.close > prev_high
    bearish_mss = last.close < prev_low

    range_high = recent.high.max()
    range_low = recent.low.min()
    midpoint = (range_high + range_low) / 2
    premium = last.close > midpoint
    discount = last.close < midpoint

    # V1 signal logic. It is intentionally conservative.
    direction = "WAIT"
    reasons = []
    entry = sl = tp1 = tp2 = None

    if sweep_high and (bearish_mss or premium):
        direction = "SELL"
        reasons += ["Buy-side liquidity sweep", "Premium zone"]
        entry = last.close
        sl = last.high + 0.8
        risk = sl - entry
        tp1 = entry - risk * 2
        tp2 = entry - risk * 3
    elif sweep_low and (bullish_mss or discount):
        direction = "BUY"
        reasons += ["Sell-side liquidity sweep", "Discount zone"]
        entry = last.close
        sl = last.low - 0.8
        risk = entry - sl
        tp1 = entry + risk * 2
        tp2 = entry + risk * 3
    else:
        # Show structural bias even if no entry is confirmed.
        if last.close > midpoint:
            direction = "WATCH SELL"
            reasons.append("Price in premium; waiting for bearish confirmation")
        else:
            direction = "WATCH BUY"
            reasons.append("Price in discount; waiting for bullish confirmation")

    # Basic FVG scan on the last 20 candles.
    fvg = None
    for i in range(max(2, len(df)-20), len(df)):
        if df.low.iloc[i] > df.high.iloc[i-2]:
            fvg = {"type":"bullish", "low":float(df.high.iloc[i-2]), "high":float(df.low.iloc[i])}
        if df.high.iloc[i] < df.low.iloc[i-2]:
            fvg = {"type":"bearish", "low":float(df.high.iloc[i]), "high":float(df.low.iloc[i-2])}

    confidence = min(95, 45 + 10*len(reasons))
    return {
        "symbol": "XAUUSD",
        "timeframe": "M15",
        "price": round(float(last.close), 2),
        "direction": direction,
        "bias": "BULLISH" if last.close > midpoint else "BEARISH",
        "premium": bool(premium),
        "discount": bool(discount),
        "liquidity_sweep": "BUY-SIDE" if sweep_high else ("SELL-SIDE" if sweep_low else None),
        "mss": "BULLISH" if bullish_mss else ("BEARISH" if bearish_mss else None),
        "fvg": fvg,
        "entry": round(entry,2) if entry else None,
        "sl": round(sl,2) if sl else None,
        "tp1": round(tp1,2) if tp1 else None,
        "tp2": round(tp2,2) if tp2 else None,
        "rr_tp1": 2.0 if entry else None,
        "rr_tp2": 3.0 if entry else None,
        "confidence": confidence,
        "reasons": reasons,
        "engine": "SMC V1 demo",
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

@app.get("/api/health")
def health():
    return {"status":"ok","version":"1.0.0"}

@app.get("/api/market")
def market():
    df = make_demo_data()
    return {
        "symbol":"XAUUSD",
        "timeframe":"M15",
        "candles":[
            {
                "time":int(row.time.timestamp()),
                "open":round(float(row.open),2),
                "high":round(float(row.high),2),
                "low":round(float(row.low),2),
                "close":round(float(row.close),2)
            }
            for row in df.itertuples()
        ],
        "analysis":analyze_smc(df)
    }

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def home():
    return FileResponse("static/index.html")
                                                 
