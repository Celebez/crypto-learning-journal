#!/usr/bin/env python3
"""
One-time backfill: add price_change_pct to existing VERIFIED entries.
Computes from stored actual_price and market_context.price (the prediction entry price).
"""
import json
from pathlib import Path
from datetime import datetime, timezone

REG = Path.home() / ".hermes/skills/trading/crypto_portfolio_monitor_learning/data/prediction_registry.json"

with open(REG) as f:
    p = json.load(f)

preds = p.get("predictions", [])
backfilled = 0
skipped = 0
errored = 0

for x in preds:
    if x.get("status") != "VERIFIED":
        continue
    v = x.get("verification", {})
    if "price_change_pct" in v and v["price_change_pct"] is not None:
        skipped += 1
        continue
    pred_price = x.get("market_context", {}).get("price", 0)
    actual_price = v.get("actual_price", 0)
    if pred_price > 0 and actual_price > 0:
        pct = round((actual_price - pred_price) / pred_price * 100, 4)
        v["price_change_pct"] = pct
        backfilled += 1
    else:
        errored += 1

p["last_updated"] = datetime.now(timezone.utc).isoformat()
with open(REG, "w") as f:
    json.dump(p, f, indent=2, default=str)

print(f"Backfilled: {backfilled}")
print(f"Already had pct: {skipped}")
print(f"Could not compute (missing prices): {errored}")
print(f"Registry updated_at: {p['last_updated']}")
