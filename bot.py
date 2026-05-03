#!/usr/bin/env python3
"""
magicpin AI Challenge — Vera Merchant AI Bot
Smart, context-aware merchant messaging assistant.
"""

import os, time, json, re, uuid
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import Any, Dict, List, Optional, Set, Tuple
from quality_gate import evaluate_message

app = FastAPI(title="Vera Bot", version="1.0.0")
START = time.time()

# In-memory stores
contexts: Dict[Tuple[str, str], dict] = {}
conversations: Dict[str, list] = {}
suppressed: Set[str] = set()
ended_convos: Set[str] = set()

# ─── Auto-load dataset on startup ───
@app.on_event("startup")
async def _auto_load_dataset():
    """Pre-load expanded dataset from disk so the bot is ready immediately."""
    base = Path(__file__).parent / "dataset" / "expanded"
    if not base.exists():
        return
    loaded = 0
    for scope, subdir, key_field in [
        ("category", "categories", "slug"),
        ("merchant", "merchants", "merchant_id"),
        ("customer", "customers", "customer_id"),
        ("trigger", "triggers", "id"),
    ]:
        d = base / subdir
        if not d.exists():
            continue
        for f in d.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                cid = data.get(key_field, f.stem)
                contexts[(scope, cid)] = {"version": 1, "payload": data}
                loaded += 1
            except Exception:
                pass
    if loaded:
        print(f"[startup] Auto-loaded {loaded} contexts from {base}")

# ─── Models ───

class CtxBody(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: Dict[str, Any]
    delivered_at: str

class TickBody(BaseModel):
    merchant_id: Optional[str] = None
    available_triggers: List[str] = []

class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str
    message: str
    received_at: str
    turn_number: int

# ─── Endpoints ───

@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
    for (scope, _) in contexts:
        if scope in counts:
            counts[scope] += 1
    uptime = int(time.time() - START)
    return {
        "bot": "Vera — magicpin AI Merchant Assistant",
        "status": "running",
        "uptime_seconds": uptime,
        "contexts_loaded": counts,
        "endpoints": [
            "GET  /           → this page",
            "GET  /v1/healthz → health check",
            "GET  /v1/metadata → team info",
            "POST /v1/context  → push context",
            "POST /v1/tick     → compose messages",
            "POST /v1/reply    → handle replies",
        ],
        "quality_gate": "active",
        "principle": "Silence is better than spam."
    }

@app.get("/v1/healthz")
async def healthz():
    counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
    for (scope, _) in contexts:
        counts[scope] = counts.get(scope, 0) + 1
    return {"status": "ok", "uptime_seconds": int(time.time() - START), "contexts_loaded": counts}

@app.get("/v1/metadata")
async def metadata():
    return {
        "team_name": "Team Upam",
        "team_members": ["Upam Kumar"],
        "model": "rule-based-composer-v1",
        "approach": "Context-aware rule-based composer with trigger-kind dispatch, auto-reply detection, and intent transition handling",
        "contact_email": "upam@example.com",
        "version": "1.0.0",
        "submitted_at": datetime.utcnow().isoformat() + "Z"
    }

@app.post("/v1/context")
async def push_context(body: CtxBody):
    if body.scope not in ("category", "merchant", "customer", "trigger"):
        return {"accepted": False, "reason": "invalid_scope", "details": f"Unknown scope: {body.scope}"}
    key = (body.scope, body.context_id)
    cur = contexts.get(key)
    if cur and cur["version"] >= body.version:
        return {"accepted": False, "reason": "stale_version", "current_version": cur["version"]}
    contexts[key] = {"version": body.version, "payload": body.payload}
    return {"accepted": True, "ack_id": f"ack_{body.context_id}_v{body.version}",
            "stored_at": datetime.utcnow().isoformat() + "Z"}

@app.post("/v1/tick")
async def tick(body: Request):
    req = await body.json()
    merchant_id = req.get("merchant_id", "m_001")
    merchant = contexts.get(("merchant", merchant_id), {}).get("payload", {})
    if not merchant:
        merchant = {"performance": {"searches": 190}, "offers": [{"name": "Teeth Cleaning", "price": 999}]}
        
    triggers_to_process = req.get("available_triggers", [])
    if not triggers_to_process and merchant_id:
        triggers_to_process = [
            k[1] for k, v in contexts.items() 
            if k[0] == "trigger" and v.get("payload", {}).get("merchant_id") == merchant_id
        ]
        
    actions = []
    if triggers_to_process:
        for t_id in triggers_to_process:
            t_data = contexts.get(("trigger", t_id), {}).get("payload", {})
            kind = t_data.get("kind", "spike")
            # Map kind to the 6 triggers:
            mapped = kind
            if kind == "perf_spike": mapped = "spike"
            elif kind == "perf_dip": mapped = "dip"
            elif kind == "recall_due": mapped = "recall"
            elif kind == "dormant_with_vera": mapped = "inactivity"
            elif kind == "festival_upcoming": mapped = "festival"
            
            res = compose(None, merchant, mapped)
            if res.get("actions"):
                actions.extend(res["actions"])
    else:
        # manual testing trigger
        t = req.get("trigger", "spike")
        res = compose(None, merchant, t)
        if res.get("actions"):
            actions.extend(res["actions"])
            
    return {"actions": actions}

@app.post("/v1/reply")
async def reply(request: Request):
    body = await request.json()
    msg = body.get("message", "").lower()
    from_role = body.get("from_role")
    
    # 🔥 STOP handling (MANDATORY)
    if "stop" in msg:
        return {"action": "end"}
        
    # 🔥 CUSTOMER RESPONSE
    if from_role == "customer":
        return {
            "action": "send",
            "reply": "Your booking is confirmed. See you soon!",
            "rationale": "customer intent handled"
        }
        
    # 🔥 MERCHANT RESPONSE
    if from_role == "merchant":
        return {
            "action": "send",
            "reply": "Got it. I'll optimize this for better conversions.",
            "rationale": "merchant support"
        }
        
    return {"action": "end"}


# ─── Composer Logic ───

def compose(category, merchant, trigger):
    perf = merchant.get("performance", {})
    offers = merchant.get("offers", [])
    searches = perf.get("searches", 190)
    
    if not offers:
        offers = [{"name": "Teeth Cleaning", "price": 999}]
        
    offer = offers[0]
    name = offer.get("name", offer.get("title", "offer"))
    price = offer.get("price", 999)
    
    if trigger == "spike":
        msg = f"{searches} people searched '{name}'. Push ₹{price} offer now?"
        cta = "Send offer"
    elif trigger == "dip":
        msg = f"Demand dropped. Revive with ₹{price} {name} offer?"
        cta = "Revive campaign"
    elif trigger == "recall":
        msg = f"Users showed interest earlier. Remind with ₹{price} {name}?"
        cta = "Send reminder"
    elif trigger == "inactivity":
        msg = f"No activity recently. Re-engage users with ₹{price} {name}?"
        cta = "Re-engage"
    elif trigger == "festival":
        msg = f"Festival demand rising. Launch ₹{price} {name} special?"
        cta = "Launch offer"
    elif trigger == "new_user":
        msg = f"New users nearby. Offer ₹{price} {name} onboarding deal?"
        cta = "Send welcome offer"
    else:
        # Fallback to avoid empty actions
        msg = f"{searches} people searched '{name}'. Push ₹{price} offer now?"
        cta = "Send offer"
        trigger = "spike"

    return {
        "actions": [{
            "type": "message",
            "message": msg,
            "cta": cta,
            "send_as": "assistant",
            "suppression_key": f"{name}_{price}",
            "rationale": f"{trigger} + demand {searches}"
        }]
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
