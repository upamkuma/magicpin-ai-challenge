#!/usr/bin/env python3
"""Load all expanded dataset into the running bot."""

import json
import os
import urllib.request
from pathlib import Path

BOT = os.environ.get("BOT_URL", "http://localhost:8080")
EXPANDED = Path(__file__).parent / "dataset" / "expanded"

def post(path, data):
    req = urllib.request.Request(
        BOT + path,
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    resp = urllib.request.urlopen(req, timeout=10)
    return json.loads(resp.read())

def main():
    # Push categories
    cat_dir = EXPANDED / "categories"
    cat_count = 0
    for f in cat_dir.glob("*.json"):
        data = json.load(open(f))
        slug = data.get("slug", f.stem)
        post("/v1/context", {"scope": "category", "context_id": slug, "version": 3, "payload": data, "delivered_at": "2026-04-26T09:45:00Z"})
        cat_count += 1
    print(f"Pushed {cat_count} categories")

    # Push merchants
    m_dir = EXPANDED / "merchants"
    m_count = 0
    for f in m_dir.glob("*.json"):
        data = json.load(open(f))
        mid = data.get("merchant_id", f.stem)
        post("/v1/context", {"scope": "merchant", "context_id": mid, "version": 3, "payload": data, "delivered_at": "2026-04-26T09:45:30Z"})
        m_count += 1
    print(f"Pushed {m_count} merchants")

    # Push customers
    c_dir = EXPANDED / "customers"
    c_count = 0
    for f in c_dir.glob("*.json"):
        data = json.load(open(f))
        cid = data.get("customer_id", f.stem)
        post("/v1/context", {"scope": "customer", "context_id": cid, "version": 3, "payload": data, "delivered_at": "2026-04-26T09:46:00Z"})
        c_count += 1
    print(f"Pushed {c_count} customers")

    # Push triggers
    t_dir = EXPANDED / "triggers"
    t_count = 0
    for f in t_dir.glob("*.json"):
        data = json.load(open(f))
        tid = data.get("id", f.stem)
        post("/v1/context", {"scope": "trigger", "context_id": tid, "version": 3, "payload": data, "delivered_at": "2026-04-26T10:30:00Z"})
        t_count += 1
    print(f"Pushed {t_count} triggers")

    # Verify
    req = urllib.request.Request(BOT + "/v1/healthz")
    resp = urllib.request.urlopen(req, timeout=5)
    health = json.loads(resp.read())
    print(f"\nBot status: {health}")

if __name__ == "__main__":
    main()
