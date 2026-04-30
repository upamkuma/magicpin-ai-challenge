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

@app.get("/")
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
async def tick(body: TickBody):
    actions = []
    
    triggers_to_process = body.available_triggers
    # If no explicit triggers provided but merchant_id is present, find all triggers for this merchant
    if not triggers_to_process and body.merchant_id:
        triggers_to_process = [
            k[1] for k, v in contexts.items() 
            if k[0] == "trigger" and v.get("payload", {}).get("merchant_id") == body.merchant_id
        ]
        
    for trg_id in triggers_to_process:
        trg_data = contexts.get(("trigger", trg_id), {}).get("payload")
        if not trg_data:
            continue
        sk = trg_data.get("suppression_key", "")
        if sk in suppressed:
            continue
        mid = trg_data.get("merchant_id")
        cid = trg_data.get("customer_id")
        merchant = contexts.get(("merchant", mid), {}).get("payload") if mid else None
        if not merchant:
            continue
        cat_slug = merchant.get("category_slug", "")
        category = contexts.get(("category", cat_slug), {}).get("payload")
        if not category:
            continue
        customer = contexts.get(("customer", cid), {}).get("payload") if cid else None
        conv_id = f"conv_{mid}_{trg_id}"
        if conv_id in ended_convos:
            continue
        action = compose_message(category, merchant, trg_data, customer, trg_id, conv_id)
        if action:
            # ── Quality gate: block low-quality messages ──
            verdict = evaluate_message(
                body=action.get("body", ""),
                cta=action.get("cta", ""),
                rationale=action.get("rationale", ""),
                trigger=trg_data,
                merchant=merchant,
                category=category,
                customer=customer,
            )
            if not verdict["allow"]:
                # Message blocked — silence is better than spam
                continue
            # Attach quality score to the action for transparency
            action["quality_score"] = verdict["score"]
            action["quality_reason"] = verdict["reason"]
            suppressed.add(sk)
            actions.append(action)
    return {"actions": actions}

@app.post("/v1/reply")
async def reply(body: ReplyBody):
    if body.conversation_id in ended_convos:
        return {"action": "end", "rationale": "Conversation already ended."}
    conv = conversations.setdefault(body.conversation_id, [])
    conv.append({"from": body.from_role, "msg": body.message, "turn": body.turn_number})
    msg_lower = body.message.lower().strip()

    # Auto-reply detection
    auto_patterns = ["thank you for contacting", "our team will respond", "automated assistant",
                     "we will get back to you", "your message has been received"]
    is_auto = any(p in msg_lower for p in auto_patterns)
    auto_count = sum(1 for t in conv if t["from"] == "merchant" and
                     any(p in t["msg"].lower() for p in auto_patterns))

    if is_auto:
        if auto_count >= 3:
            ended_convos.add(body.conversation_id)
            return {"action": "end", "rationale": "Auto-reply detected 3+ times. No real engagement. Closing."}
        if auto_count >= 2:
            return {"action": "wait", "wait_seconds": 86400,
                    "rationale": "Same auto-reply twice. Owner likely away. Waiting 24h."}
        return {"action": "send",
                "body": "Looks like an auto-reply — no worries! When the owner sees this, just reply 'Yes' to continue. 😊",
                "cta": "binary_yes_no",
                "rationale": "Detected auto-reply. One gentle nudge for the owner."}

    # Hostile / opt-out detection
    hostile_words = ["stop messaging", "not interested", "spam", "useless", "stop sending",
                     "don't message", "unsubscribe", "leave me alone", "bothering"]
    if any(w in msg_lower for w in hostile_words):
        ended_convos.add(body.conversation_id)
        return {"action": "send",
                "body": "Apologies for the bother — I won't message again. If you ever need help, just send 'Hi Vera'. 🙏",
                "cta": "none",
                "rationale": "Merchant expressed frustration. Graceful exit with opt-back-in path."}

    # Intent transition — merchant says yes/go/do it
    intent_words = ["yes", "ok let", "let's do it", "go ahead", "sounds good", "please do",
                    "yes please", "do it", "proceed", "confirm", "what's next", "whats next"]
    if any(w in msg_lower for w in intent_words):
        merchant = contexts.get(("merchant", body.merchant_id), {}).get("payload", {})
        name = merchant.get("identity", {}).get("owner_first_name", "")
        return {"action": "send",
                "body": f"On it{', ' + name if name else ''}! Drafting everything now — will share in under 2 minutes. You'll be able to review before anything goes live.",
                "cta": "none",
                "rationale": "Merchant committed. Switching to action mode immediately — no more qualifying."}

    # Off-topic detection
    off_topic = ["gst", "tax", "filing", "income tax", "accounting", "legal", "lawyer"]
    if any(w in msg_lower for w in off_topic):
        return {"action": "send",
                "body": "That's outside what I can help with directly — best to check with your CA or advisor for that. Coming back to what we were discussing — want me to go ahead with the draft?",
                "cta": "open_ended",
                "rationale": "Off-topic ask politely declined. Redirecting to original conversation thread."}

    # General engaged reply
    merchant = contexts.get(("merchant", body.merchant_id), {}).get("payload", {})
    name = merchant.get("identity", {}).get("owner_first_name", "")
    return {"action": "send",
            "body": f"Got it{', ' + name if name else ''}. Working on this now — I'll have it ready for your review shortly. Anything specific you'd like me to keep in mind?",
            "cta": "open_ended",
            "rationale": "Acknowledged merchant input and advancing conversation with open-ended follow-up."}


# ─── Composer Logic ───

def compose_message(category, merchant, trigger, customer, trg_id, conv_id):
    """Compose a context-aware message based on trigger kind."""
    kind = trigger.get("kind", "")
    identity = merchant.get("identity", {})
    mname = identity.get("name", "Merchant")
    owner = identity.get("owner_first_name", "")
    cat_slug = category.get("slug", "")
    payload = trigger.get("payload", {})
    scope = trigger.get("scope", "merchant")
    perf = merchant.get("performance", {})
    offers = [o for o in merchant.get("offers", []) if o.get("status") == "active"]
    signals = merchant.get("signals", [])
    cust_agg = merchant.get("customer_aggregate", {})
    voice = category.get("voice", {})
    digest = category.get("digest", [])
    is_customer = customer is not None and scope == "customer"
    send_as = "merchant_on_behalf" if is_customer else "vera"

    # Resolve digest items
    def get_digest_item(item_id):
        for d in digest:
            if d.get("id") == item_id:
                return d
        return None

    # ── Enrich placeholder payloads with sensible defaults from context ──
    if payload.get("placeholder"):
        delta_7d = perf.get("delta_7d", {})
        if kind == "perf_dip":
            worst = "views" if abs(delta_7d.get("views_pct", 0)) >= abs(delta_7d.get("calls_pct", 0)) else "calls"
            payload = {"metric": worst, "delta_pct": delta_7d.get(f"{worst}_pct", -0.15)}
        elif kind == "perf_spike":
            best = "views" if delta_7d.get("views_pct", 0) >= delta_7d.get("calls_pct", 0) else "calls"
            payload = {"metric": best, "delta_pct": abs(delta_7d.get(f"{best}_pct", 0.10)), "likely_driver": "recent activity"}
        elif kind == "milestone_reached":
            v = perf.get("views", 0)
            milestone = ((v // 500) + 1) * 500 if v else 1000
            payload = {"metric": "profile views", "value_now": v, "milestone_value": milestone}
        elif kind == "dormant_with_vera":
            payload = {"days_since_last_merchant_message": 14}
        elif kind == "festival_upcoming":
            payload = {"festival": "Independence Day", "days_until": 108}
        elif kind == "competitor_opened":
            payload = {"competitor_name": "a nearby business", "distance_km": 1.5, "their_offer": ""}
        elif kind == "recall_due":
            payload = {"service_due": "follow-up session", "available_slots": [{"label": "next Monday"}, {"label": "next Wednesday"}]}
        elif kind == "customer_lapsed_soft":
            payload = {"days_since_last_visit": 90}
        elif kind == "appointment_tomorrow":
            payload = {"appointment_time": "10:00 AM", "service": "appointment"}
        elif kind == "chronic_refill_due":
            payload = {"molecule_list": ["prescribed medication"], "stock_runs_out_iso": "2026-05-05"}
        elif kind == "trial_followup":
            payload = {"next_session_options": [{"label": "next Monday morning"}]}
        elif kind == "review_theme_emerged":
            themes = merchant.get("review_themes", [])
            if themes:
                t = themes[0]
                payload = {"theme": t.get("theme", "service quality"), "occurrences_30d": t.get("occurrences_30d", 3), "common_quote": ""}
            else:
                payload = {"theme": "service quality", "occurrences_30d": 3, "common_quote": ""}
        elif kind == "renewal_due":
            sub = merchant.get("subscription", {})
            payload = {"days_remaining": sub.get("days_remaining", 30), "plan": sub.get("plan", "Pro")}
        elif kind == "curious_ask_due":
            payload = {}
        elif kind == "research_digest":
            if digest:
                payload = {"top_item_id": digest[0].get("id", "")}
            else:
                payload = {}

    body, cta, rationale = "", "open_ended", ""

    if kind == "research_digest":
        item = get_digest_item(payload.get("top_item_id", ""))
        if item:
            src = item.get("source", "")
            title = item.get("title", "")
            trial_n = item.get("trial_n", "")
            seg = item.get("patient_segment", "").replace("_", " ")
            cohort = ""
            if "high_risk_adult_cohort" in signals and seg:
                cohort = f" relevant to your {seg} patients"
            elif seg:
                cohort = f" focused on {seg}"
            body = (f"{'Dr. ' + owner if cat_slug == 'dentists' and owner else owner or mname}, "
                    f"{src.split(',')[0] if src else 'Latest research'} just dropped. "
                    f"Key finding{cohort} — {title}"
                    f"{f' ({trial_n:,}-patient trial)' if trial_n else ''}. "
                    f"Worth a 2-min read. Want me to pull the abstract + draft a patient-ed WhatsApp you can share? "
                    f"— {src}")
            rationale = f"Research digest with source citation and merchant-specific anchor. {src}"
        else:
            return None

    elif kind == "regulation_change":
        item = get_digest_item(payload.get("top_item_id", ""))
        deadline = payload.get("deadline_iso", "")[:10]
        if item:
            body = (f"{'Dr. ' + owner if cat_slug == 'dentists' and owner else owner or mname}, "
                    f"heads-up: {item['title']}. "
                    f"Deadline: {deadline}. {item.get('summary', '')} "
                    f"Want me to draft a compliance checklist you can share with your team?")
            cta = "open_ended"
            rationale = f"Compliance alert with deadline. Urgency {trigger.get('urgency')}. Source: {item.get('source', '')}"
        else:
            return None

    elif kind == "recall_due" and is_customer:
        cname = customer.get("identity", {}).get("name", "")
        lang = customer.get("identity", {}).get("language_pref", "english")
        slots = payload.get("available_slots", [])
        slot_text = " ya ".join(s.get("label", "") for s in slots[:2]) if "hi" in lang else " or ".join(s.get("label", "") for s in slots[:2])
        offer_text = offers[0]["title"] if offers else "regular cleaning"
        svc = payload.get("service_due", "checkup").replace("_", " ")
        body = (f"Hi {cname}, {mname} here 🦷 "
                f"Your {svc} is coming up. "
                f"{'Apke liye' if 'hi' in lang else 'We have'} slots ready: {slot_text}. "
                f"{offer_text} + complimentary fluoride. "
                f"Reply 1 or 2 to book, or tell us a time that works.")
        cta = "multi_choice_slot"
        rationale = f"Recall reminder for {cname}. Language: {lang}. Using merchant's active offer."

    elif kind == "perf_dip":
        metric = payload.get("metric", "views")
        delta = payload.get("delta_pct", 0)
        pct = abs(int(delta * 100))
        body = (f"{owner or mname}, your {metric} dropped {pct}% this week. "
                f"This is worth looking at — "
                f"{'peers in your area average ' + str(category.get('peer_stats', {}).get('avg_ctr', '')) + ' CTR. ' if metric == 'ctr' else ''}"
                f"Want me to run a quick diagnostic and suggest 2-3 specific actions?")
        rationale = f"Performance dip alert: {metric} down {pct}%. Offering actionable next steps."

    elif kind == "renewal_due":
        days = payload.get("days_remaining", 0)
        plan = payload.get("plan", "Pro")
        body = (f"{owner or mname}, your {plan} subscription renews in {days} days. "
                f"Your profile has been driving {perf.get('views', 0):,} views and {perf.get('calls', 0)} calls this month. "
                f"Want me to show a quick before/after comparison of your metrics?")
        cta = "open_ended"
        rationale = f"Renewal reminder grounded in performance data. {days} days remaining."

    elif kind == "festival_upcoming":
        fest = payload.get("festival", "")
        days = payload.get("days_until", 0)
        if days > 30:
            body = (f"{owner or mname}, {fest} is {days} days away — early, but smart planners book inventory and staff now. "
                    f"Want me to set a reminder for 30 days out to draft your {fest} campaign?")
        else:
            body = (f"{owner or mname}, {fest} is {days} days away. "
                    f"{'Perfect time to plan festive offers. ' if cat_slug in ('salons', 'restaurants') else ''}"
                    f"Want me to draft a {fest} special post for your Google profile?")
        rationale = f"Festival prep prompt — {fest} in {days} days. Category: {cat_slug}."

    elif kind == "wedding_package_followup" and is_customer:
        cname = customer.get("identity", {}).get("name", "")
        days_to = payload.get("days_to_wedding", 0)
        body = (f"Hi {cname} 💍 {owner or ''} from {mname} here. "
                f"{days_to} days to your wedding — perfect window to start your skin-prep program. "
                f"Want me to block your preferred slot for the first session next week?")
        cta = "binary_yes_no"
        rationale = f"Bridal followup. {days_to} days to wedding. Skin-prep window open."

    elif kind == "curious_ask_due":
        body = (f"Hi {owner or mname}! Quick check — what service has been most asked-for this week? "
                f"I'll turn the answer into a Google post + a WhatsApp reply you can use when customers ask pricing. Takes 5 min.")
        rationale = "Curious-ask cadence. Low-stakes question with reciprocity offer."

    elif kind == "winback_eligible":
        days_exp = payload.get("days_since_expiry", 0)
        dip = abs(int(payload.get("perf_dip_pct", 0) * 100))
        body = (f"{owner or mname}, it's been {days_exp} days since your subscription paused. "
                f"Your profile views have dipped {dip}% since then. "
                f"Want to see a 30-second summary of what reactivating would look like for your numbers?")
        rationale = f"Winback message. {days_exp} days since expiry, {dip}% dip."

    elif kind == "ipl_match_today":
        match = payload.get("match", "")
        venue = payload.get("venue", "")
        is_weeknight = payload.get("is_weeknight", True)
        offer_title = offers[0]["title"] if offers else ""
        if not is_weeknight:
            body = (f"Quick heads-up {owner or mname} — {match} at {venue} tonight. "
                    f"Saturday IPL matches usually shift -12% restaurant covers (people watch at home). "
                    f"{'Push your ' + offer_title + ' as a delivery-only Saturday special. ' if offer_title else ''}"
                    f"Want me to draft a delivery push for Swiggy + an Insta story? Live in 10 min.")
        else:
            body = (f"{owner or mname}, {match} tonight at {venue}. "
                    f"Match nights typically boost delivery orders. "
                    f"{'Your ' + offer_title + ' could work perfectly as a match-night combo. ' if offer_title else ''}"
                    f"Want me to draft a quick match-night promo?")
        rationale = f"IPL trigger. {'Weekend' if not is_weeknight else 'Weeknight'} strategy. Contrarian if weekend."

    elif kind == "review_theme_emerged":
        theme = payload.get("theme", "").replace("_", " ")
        count = payload.get("occurrences_30d", 0)
        quote = payload.get("common_quote", "")
        quote_part = ' — one said: "' + quote + '"' if quote else ''
        body = (f"{owner or mname}, noticed {count} recent reviews mention \"{theme}\""
                f"{quote_part}. "
                f"Want me to draft a response template + suggest an operational fix?")
        rationale = f"Review pattern alert: {theme} x{count}. Proactive reputation management."

    elif kind == "milestone_reached":
        metric = payload.get("metric", "").replace("_", " ")
        val = payload.get("value_now", 0)
        milestone = payload.get("milestone_value", 0)
        body = (f"{'Dr. ' + owner if cat_slug == 'dentists' and owner else owner or mname}, "
                f"you're at {val} {metric} — just {milestone - val} away from {milestone}! "
                f"Want me to draft a thank-you post + a push to get those last few?")
        rationale = f"Milestone proximity: {val}/{milestone} {metric}. Social proof opportunity."

    elif kind == "active_planning_intent":
        topic = payload.get("intent_topic", "").replace("_", " ")
        body = (f"{owner or mname}, I've drafted a starter plan for the {topic}. "
                f"It includes pricing tiers and a suggested rollout. "
                f"Want me to share it now so you can review and tweak?")
        cta = "binary_yes_no"
        rationale = f"Active planning continuation for {topic}. Delivering drafted artifact."

    elif kind == "seasonal_perf_dip":
        delta = abs(int(payload.get("delta_pct", 0) * 100))
        note = payload.get("season_note", "seasonal")
        members = cust_agg.get("total_active_members", "")
        body = (f"{owner or mname}, your views are down {delta}% this week — but this is the normal "
                f"{note.replace('_', ' ')} lull (every metro gym sees -25 to -35% in this window). "
                f"Action: skip ad spend now, save it for Sept-Oct when conversion is 2x. "
                f"{'Focus retention on your ' + str(members) + ' members. ' if members else ''}"
                f"Want me to draft a summer attendance challenge to keep them through the dip?")
        rationale = f"Seasonal dip reframe. -{delta}% is expected. Save spend, focus retention."

    elif kind == "customer_lapsed_hard" and is_customer:
        cname = customer.get("identity", {}).get("name", "")
        days = payload.get("days_since_last_visit", 0)
        focus = payload.get("previous_focus", "").replace("_", " ")
        offer_text = offers[0]["title"] if offers else "a free trial class"
        body = (f"Hi {cname} 👋 {owner or ''} from {mname} here. It's been about {days // 7} weeks — "
                f"happens to most members at some point, no judgment. "
                f"{'We have new classes that fit ' + focus + ' goals well. ' if focus else ''}"
                f"Want me to hold a free trial spot for you? Reply YES — no commitment, no auto-charge.")
        cta = "binary_yes_no"
        rationale = f"Lapsed customer winback. {days} days. No-shame, low-friction."

    elif kind == "supply_alert":
        mol = payload.get("molecule", "")
        batches = payload.get("affected_batches", [])
        mfr = payload.get("manufacturer", "")
        chronic = cust_agg.get("chronic_rx_count", 0)
        body = (f"{owner or mname}, urgent: voluntary recall on {len(batches)} {mol} batch{'es' if len(batches) > 1 else ''} "
                f"({', '.join(batches)}) by {mfr} — sub-potency, no safety risk, but customers should be informed. "
                f"{'Your chronic-Rx list has ' + str(chronic) + ' patients who may be affected. ' if chronic else ''}"
                f"Want me to draft their WhatsApp note + the replacement-pickup workflow?")
        cta = "open_ended"
        rationale = f"Supply/compliance alert. Batch recall for {mol}. Urgent."

    elif kind == "chronic_refill_due" and is_customer:
        cname = customer.get("identity", {}).get("name", "")
        lang = customer.get("identity", {}).get("language_pref", "english")
        mols = payload.get("molecule_list", [])
        runout = payload.get("stock_runs_out_iso", "")[:10]
        senior = customer.get("identity", {}).get("senior_citizen", False)
        sr_offer = [o for o in offers if "senior" in o.get("title", "").lower()]
        del_offer = [o for o in offers if "deliver" in o.get("title", "").lower()]
        if "hi" in lang:
            body = (f"Namaste — {mname} yahan. {cname} ji ki {len(mols)} monthly medicines "
                    f"({', '.join(mols)}) {runout} ko khatam hongi. "
                    f"Same dose, same brand pack ready hai. "
                    f"{'Senior discount 15% applied. ' if sr_offer or senior else ''}"
                    f"{'Free home delivery to saved address. ' if del_offer else ''}"
                    f"Reply CONFIRM to dispatch, or call if any change in dosage.")
        else:
            body = (f"Hello — {mname} here. {cname}'s monthly medicines "
                    f"({', '.join(mols)}) run out on {runout}. "
                    f"Same dose, same brand ready. "
                    f"{'Senior 15% discount applied. ' if sr_offer or senior else ''}"
                    f"{'Free home delivery. ' if del_offer else ''}"
                    f"Reply CONFIRM to dispatch.")
        cta = "binary_confirm"
        rationale = f"Chronic refill reminder. {len(mols)} molecules. {'Hindi' if 'hi' in lang else 'English'} voice."

    elif kind == "category_seasonal":
        trends = payload.get("trends", [])
        trend_text = ", ".join(t.replace("_", " ") for t in trends[:3])
        body = (f"{owner or mname}, summer demand shifts are here: {trend_text}. "
                f"Want me to suggest shelf adjustments and a quick seasonal Google post?")
        rationale = f"Seasonal demand shift alert with actionable shelf recommendation."

    elif kind == "gbp_unverified":
        uplift = int(payload.get("estimated_uplift_pct", 0) * 100)
        body = (f"{owner or mname}, your Google Business Profile isn't verified yet — "
                f"verified profiles typically see {uplift}% more visibility. "
                f"It's a one-time setup (postcard or phone call, 5 min). "
                f"Want me to walk you through it right now?")
        rationale = f"GBP verification nudge. {uplift}% uplift potential. Low-effort CTA."

    elif kind == "cde_opportunity":
        item = get_digest_item(payload.get("digest_item_id", ""))
        if item:
            body = (f"{'Dr. ' + owner if cat_slug == 'dentists' and owner else owner or mname}, "
                    f"upcoming CDE: \"{item.get('title', '')}\" — "
                    f"{item.get('summary', '')} "
                    f"{'Free for IDA members. ' if 'free' in str(payload.get('fee', '')).lower() else ''}"
                    f"{str(payload.get('credits', '')) + ' CDE credits. ' if payload.get('credits') else ''}"
                    f"Want me to add it to your calendar?")
            rationale = f"CDE opportunity with credits. Low-friction calendar add."
        else:
            return None

    elif kind == "competitor_opened":
        comp = payload.get("competitor_name", "")
        dist = payload.get("distance_km", 0)
        their_offer = payload.get("their_offer", "")
        body = (f"{'Dr. ' + owner if cat_slug == 'dentists' and owner else owner or mname}, "
                f"a new competitor ({comp}) opened {dist}km away"
                f"{', offering ' + their_offer if their_offer else ''}. "
                f"Your CTR is {perf.get('ctr', '?')} vs peer median {category.get('peer_stats', {}).get('avg_ctr', '?')}. "
                f"Want me to audit your listing and suggest quick differentiation moves?")
        rationale = f"Competitor alert. {comp} at {dist}km. Defensive positioning."

    elif kind == "perf_spike":
        metric = payload.get("metric", "views")
        delta = int(payload.get("delta_pct", 0) * 100)
        driver = payload.get("likely_driver", "").replace("_", " ")
        body = (f"Nice uptick {owner or mname} — your {metric} jumped {delta}% this week"
                f"{', likely driven by your ' + driver if driver else ''}. "
                f"Want me to double down on what's working?")
        rationale = f"Performance spike acknowledgment. {metric} +{delta}%. Capitalize on momentum."

    elif kind == "dormant_with_vera":
        days = payload.get("days_since_last_merchant_message", 0)
        body = (f"Hi {owner or mname} — it's been {days} days since we last connected. "
                f"Your profile is still active with {perf.get('views', 0):,} views this month. "
                f"Quick question: what's been your biggest challenge this month? "
                f"I might have something useful.")
        rationale = f"Re-engagement after {days}d dormancy. Open-ended question to restart."

    elif kind == "trial_followup" and is_customer:
        cname = customer.get("identity", {}).get("name", "")
        sessions = payload.get("next_session_options", [])
        slot_text = sessions[0].get("label", "next week") if sessions else "next week"
        body = (f"Hi {cname} 👋 {owner or ''} from {mname} here. "
                f"Hope the trial session went well! "
                f"Next session available: {slot_text}. "
                f"Want me to reserve the spot? Reply YES to confirm.")
        cta = "binary_yes_no"
        rationale = f"Trial followup for {cname}. Single slot offered for simplicity."

    elif kind == "appointment_tomorrow" and is_customer:
        cname = customer.get("identity", {}).get("name", "")
        lang = customer.get("identity", {}).get("language_pref", "english")
        appt_time = payload.get("appointment_time", "")
        appt_service = payload.get("service", payload.get("metric_or_topic", "appointment")).replace("_", " ")
        if "hi" in lang:
            body = (f"Hi {cname}, {mname} ki taraf se reminder 📋 "
                    f"Aapki kal ki appointment confirmed hai"
                    f"{' — ' + appt_time if appt_time else ''}. "
                    f"Kuch change karna ho toh reply karein, warna hum aapka wait karenge!")
        else:
            body = (f"Hi {cname}, quick reminder from {mname} 📋 "
                    f"Your appointment tomorrow is confirmed"
                    f"{' at ' + appt_time if appt_time else ''}. "
                    f"Reply if you need to reschedule, otherwise we'll see you there!")
        cta = "open_ended"
        rationale = f"Appointment reminder for {cname}. Language: {lang}. Friendly confirmation tone."

    elif kind == "customer_lapsed_soft" and is_customer:
        cname = customer.get("identity", {}).get("name", "")
        lang = customer.get("identity", {}).get("language_pref", "english")
        days_since = payload.get("days_since_last_visit", 90)
        offer_text = offers[0]["title"] if offers else ""
        if "hi" in lang:
            body = (f"Hi {cname}, {mname} se 👋 Kaafi time ho gaya aapko dekhe — "
                    f"miss kar rahe hain! "
                    f"{'Aapke liye special: ' + offer_text + '. ' if offer_text else ''}"
                    f"Kab aana chahenge? Reply karein, hum slot fix kar dete hain.")
        else:
            body = (f"Hi {cname} 👋 It's been a while since your last visit to {mname}. "
                    f"We'd love to see you back! "
                    f"{'Special for you: ' + offer_text + '. ' if offer_text else ''}"
                    f"When works for you? Reply and we'll hold a slot.")
        cta = "open_ended"
        rationale = f"Lapsed-soft winback for {cname}. {days_since} days since last visit. Warm, no-pressure tone."

    elif kind in ("customer_lapsed_soft", "appointment_tomorrow"):
        # Merchant-scoped versions of customer triggers — skip gracefully
        return None

    else:
        return None

    if not body:
        return None

    return {
        "conversation_id": conv_id,
        "merchant_id": trigger.get("merchant_id"),
        "customer_id": trigger.get("customer_id"),
        "send_as": send_as,
        "trigger_id": trg_id,
        "template_name": f"vera_{kind}_v1",
        "template_params": [owner or mname, body[:80]],
        "body": body,
        "cta": cta,
        "suppression_key": trigger.get("suppression_key", ""),
        "rationale": rationale
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
