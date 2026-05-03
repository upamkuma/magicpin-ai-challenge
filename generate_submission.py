#!/usr/bin/env python3
"""Generate submission.jsonl by composing messages for all 30 test pairs."""

import json, sys, os
from pathlib import Path

# Add project root to path so we can import bot modules
sys.path.insert(0, str(Path(__file__).parent))

# Import the compose function from bot
from bot import compose

EXPANDED = Path(__file__).parent / "dataset" / "expanded"

def load_json(path):
    with open(path) as f:
        return json.load(f)

def main():
    # Load test pairs
    pairs = load_json(EXPANDED / "test_pairs.json")["pairs"]

    # Load all data
    categories = {}
    for f in (EXPANDED / "categories").glob("*.json"):
        d = load_json(f)
        categories[d.get("slug", f.stem)] = d

    merchants = {}
    for f in (EXPANDED / "merchants").glob("*.json"):
        d = load_json(f)
        merchants[d.get("merchant_id", f.stem)] = d

    customers = {}
    for f in (EXPANDED / "customers").glob("*.json"):
        d = load_json(f)
        customers[d.get("customer_id", f.stem)] = d

    triggers = {}
    for f in (EXPANDED / "triggers").glob("*.json"):
        d = load_json(f)
        triggers[d.get("id", f.stem)] = d

    print(f"Loaded: {len(categories)} categories, {len(merchants)} merchants, "
          f"{len(customers)} customers, {len(triggers)} triggers")

    results = []
    for pair in pairs:
        tid = pair["test_id"]
        trig_id = pair["trigger_id"]
        mid = pair["merchant_id"]
        cid = pair.get("customer_id")

        trigger = triggers.get(trig_id, {})
        merchant = merchants.get(mid, {})
        customer = customers.get(cid) if cid else None
        cat_slug = merchant.get("category_slug", "")
        category = categories.get(cat_slug, {})

        conv_id = f"conv_{mid}_{trig_id}"
        kind = trigger.get("kind", "spike")
        mapped_kind = kind
        if kind == "perf_spike": mapped_kind = "spike"
        elif kind == "perf_dip": mapped_kind = "dip"
        elif kind == "recall_due": mapped_kind = "recall"
        elif kind == "dormant_with_vera": mapped_kind = "inactivity"
        elif kind == "festival_upcoming": mapped_kind = "festival"

        res = compose(category, merchant, mapped_kind)
        actions = res.get("actions", [])
        action = actions[0] if actions else None

        if action:
            entry = {
                "test_id": tid,
                "trigger_id": trig_id,
                "merchant_id": mid,
                "customer_id": cid,
                "body": action.get("message", ""),
                "cta": action.get("cta", ""),
                "send_as": action.get("send_as", ""),
                "suppression_key": action.get("suppression_key", ""),
                "rationale": action.get("rationale", ""),
            }
        else:
            # Fallback — compose a minimal valid message
            owner = merchant.get("identity", {}).get("owner_first_name", "")
            mname = merchant.get("identity", {}).get("name", "Merchant")
            kind = trigger.get("kind", "")
            entry = {
                "test_id": tid,
                "trigger_id": trig_id,
                "merchant_id": mid,
                "customer_id": cid,
                "body": f"{owner or mname}, just checking in — anything I can help with today?",
                "cta": "open_ended",
                "send_as": "vera",
                "suppression_key": trigger.get("suppression_key", f"{kind}:{mid}"),
                "rationale": f"Fallback engagement for {kind} trigger.",
            }

        results.append(entry)
        status = "✅" if action else "⚠️ fallback"
        print(f"  {tid}: {status} — {entry['body'][:60]}...")

    # Write submission.jsonl
    out = Path(__file__).parent / "submission.jsonl"
    with open(out, "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\n✅ Wrote {len(results)} entries to {out}")

if __name__ == "__main__":
    main()
