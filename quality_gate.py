#!/usr/bin/env python3
"""
Quality Gate Module for Vera Bot

This module implements a pre-send validation layer that evaluates
every outbound message against quality, relevance, and compliance
criteria before delivery. Messages that fail validation are silently
dropped to protect user experience and merchant reputation.

Scoring dimensions:
    - Relevance  (0-3): Is the message grounded in actual context?
    - Timing     (0-2): Is this the right moment to engage?
    - Personalization (0-2): Does it feel tailored to the recipient?
    - Clarity    (0-2): Is there a single, clear ask?
    - Trust      (0-1): Are claims backed by data or sources?

Messages scoring below 7/10 are blocked.
"""

import re
from typing import Dict, List, Optional, Tuple


# ── Blocklist: low-value filler phrases ──

FILLER_PHRASES = [
    "hey there", "check this out", "don't miss this", "don't miss out",
    "exciting news", "big announcement", "amazing deal", "great opportunity",
    "click here", "act now", "limited time", "you won't believe",
    "hi there", "hello there", "good morning", "good evening",
]

# ── Blocklist: manufactured scarcity ──

SCARCITY_PHRASES = [
    "only today", "last chance", "hurry up", "running out",
    "expires soon", "don't wait", "urgent offer", "final call",
    "now or never", "once in a lifetime", "while supplies last",
    "!!!",
]

# ── Blocklist: regex patterns that indicate promotional spam ──

PROMOTIONAL_PATTERNS = [
    r"https?://",
    r"www\.",
    r"₹\d+\s*off",
    r"\bfree\b.*\bfree\b",
    r"guaranteed",
    r"100% safe",
    r"completely cure",
    r"miracle",
    r"best in city",
    r"#1\b",
    r"number one",
]

# ── Per-category restricted vocabulary ──

RESTRICTED_VOCAB = {
    "dentists": ["guaranteed", "100% safe", "completely cure", "miracle",
                 "best in city", "doctor approved", "pain-free guaranteed"],
    "salons": ["medical", "treatment", "cure", "diagnosis", "prescription"],
    "restaurants": ["medical", "treatment", "cure", "clinical", "prescription"],
    "gyms": ["guaranteed results", "lose weight fast", "miracle", "cure",
             "medical advice", "prescription"],
    "pharmacies": ["discount drug", "cheap medicine", "no prescription needed",
                   "self-medicate", "miracle cure"],
}

# ── Expected tone per category ──

EXPECTED_TONE = {
    "dentists": {"tone": "peer_clinical", "desc": "professional, health-focused, calm"},
    "salons": {"tone": "lifestyle", "desc": "lifestyle, grooming, light offers"},
    "restaurants": {"tone": "casual_warm", "desc": "food timing, cravings-driven"},
    "gyms": {"tone": "motivational", "desc": "motivation, consistency-focused"},
    "pharmacies": {"tone": "responsible", "desc": "essential, compliance-aware"},
}


# ══════════════════════════════════════════
# Scoring Functions
# ══════════════════════════════════════════

def _eval_relevance(body: str, trigger: dict, merchant: dict, category: dict) -> Tuple[int, str]:
    """How well is the message grounded in real context data? (0-3)"""
    score = 0
    notes = []

    kind = trigger.get("kind", "")
    payload = trigger.get("payload", {})

    if kind and kind != "placeholder":
        score += 1
        notes.append("trigger-grounded")

    identity = merchant.get("identity", {})
    owner = identity.get("owner_first_name", "")
    biz_name = identity.get("name", "")
    if owner and owner.lower() in body.lower():
        score += 1
        notes.append("addresses-owner")
    elif biz_name and biz_name.lower() in body.lower():
        score += 1
        notes.append("references-business")

    perf = merchant.get("performance", {})
    data_vals = [str(perf.get("views", "")), str(perf.get("calls", "")),
                 str(perf.get("ctr", ""))]
    if any(v in body and v and v != "0" for v in data_vals):
        score += 1
        notes.append("cites-metrics")
    elif payload and not payload.get("placeholder"):
        score += 1
        notes.append("payload-driven")

    return min(score, 3), ", ".join(notes) if notes else "weak-context"


def _eval_timing(trigger: dict) -> Tuple[int, str]:
    """Is this an appropriate moment to reach out? (0-2)"""
    urgency = trigger.get("urgency", 0)
    kind = trigger.get("kind", "")

    if urgency >= 4:
        return 2, "high-urgency"
    elif urgency >= 2:
        return 1, "moderate-urgency"
    elif kind in ("curious_ask_due", "dormant_with_vera", "milestone_reached"):
        return 1, "cadence-appropriate"
    else:
        return 0, "low-urgency"


def _eval_personalization(body: str, merchant: dict, customer: Optional[dict]) -> Tuple[int, str]:
    """Does the message feel individually crafted? (0-2)"""
    score = 0
    notes = []

    identity = merchant.get("identity", {})
    owner = identity.get("owner_first_name", "")
    locality = identity.get("locality", "")

    if owner and owner in body:
        score += 1
        notes.append("owner-name")

    if customer:
        cname = customer.get("identity", {}).get("name", "")
        lang = customer.get("identity", {}).get("language_pref", "")
        if cname and cname in body:
            score += 1
            notes.append("customer-name")
        elif "hi" in lang and any(w in body.lower() for w in ["apke", "aapki", "namaste", "yahan", "hai"]):
            score += 1
            notes.append("language-match")
    elif locality and locality.lower() in body.lower():
        score += 1
        notes.append("locality-ref")

    return min(score, 2), ", ".join(notes) if notes else "impersonal"


def _eval_clarity(body: str, cta: str) -> Tuple[int, str]:
    """Is the message concise with a single clear ask? (0-2)"""
    score = 0
    notes = []

    if 50 < len(body) < 500:
        score += 1
        notes.append("good-length")
    elif len(body) <= 50:
        notes.append("too-short")
    else:
        notes.append("too-long")

    if cta and cta != "none":
        ask_count = sum(1 for p in ["want me to", "reply", "want to", "shall i", "should i"]
                        if p in body.lower())
        if ask_count <= 2:
            score += 1
            notes.append("single-cta")
        else:
            notes.append("multi-cta")
    else:
        score += 1
        notes.append("cta-not-needed")

    return min(score, 2), ", ".join(notes) if notes else "unclear"


def _eval_trust(body: str, rationale: str, category: dict) -> Tuple[int, str]:
    """Are the claims backed by evidence or credible sources? (0-1)"""
    cat_slug = category.get("slug", "")

    cited = any(s in body for s in ["JIDA", "DCI", "IDA", "source", "study", "trial", "research"])
    has_numbers = any(c.isdigit() for c in body)

    restricted = RESTRICTED_VOCAB.get(cat_slug, [])
    bad_words = [w for w in restricted if w.lower() in body.lower()]
    if bad_words:
        return 0, f"restricted-term: {bad_words[0]}"

    if cited or has_numbers or rationale:
        return 1, "evidence-backed"
    return 0, "unsubstantiated"


# ══════════════════════════════════════════
# Main Validation Function
# ══════════════════════════════════════════

def evaluate_message(
    body: str,
    cta: str,
    rationale: str,
    trigger: dict,
    merchant: dict,
    category: dict,
    customer: Optional[dict] = None,
    recent_messages: Optional[List[str]] = None,
) -> Dict:
    """
    Run a candidate message through quality validation.

    Each message is checked against hard-rejection rules first,
    then scored on 5 dimensions. If total < 7, the message is blocked.

    Args:
        body: The composed message text
        cta: Call-to-action type (e.g. 'open_ended', 'binary_yes_no')
        rationale: Why this message was composed
        trigger: Trigger context dict
        merchant: Merchant context dict
        category: Category context dict
        customer: Optional customer context dict
        recent_messages: List of recently sent bodies (for dedup)

    Returns:
        dict with keys: allow, score, reason, violations, scores
    """
    violations = []
    body_lower = body.lower().strip()

    # ── Empty body check ──
    if not body or len(body.strip()) < 10:
        return {
            "allow": False, "score": 0,
            "reason": "Empty or near-empty message body",
            "violations": ["empty_body"]
        }

    # ── Filler phrase detection ──
    for phrase in FILLER_PHRASES:
        if phrase in body_lower and len(body) < 100:
            violations.append(f"generic_content: '{phrase}'")

    # ── Manufactured scarcity ──
    for phrase in SCARCITY_PHRASES:
        if phrase in body_lower:
            violations.append(f"fake_urgency: '{phrase}'")

    # ── Promotional spam patterns ──
    for pat in PROMOTIONAL_PATTERNS:
        if re.search(pat, body, re.IGNORECASE):
            violations.append(f"spam_pattern: '{pat}'")

    # ── URL presence (WhatsApp Business API rejects these) ──
    if re.search(r"https?://|www\.", body):
        return {
            "allow": False, "score": 0,
            "reason": "URLs in body — WhatsApp Business API would reject",
            "violations": ["url_in_body"]
        }

    # ── Multiple call-to-action detection ──
    ask_phrases = ["want me to", "shall i", "should i", "would you like",
                   "can i", "do you want"]
    ask_count = sum(1 for p in ask_phrases if p in body_lower)
    if ask_count > 2:
        violations.append(f"multiple_ctas: {ask_count} detected")

    # ── Near-duplicate detection ──
    if recent_messages:
        for prev in recent_messages:
            if prev and body:
                common = len(set(body_lower.split()) & set(prev.lower().split()))
                total_words = max(len(set(body_lower.split())), 1)
                if common / total_words > 0.8:
                    violations.append("duplicate_message")
                    break

    # ── Category restricted vocabulary ──
    cat_slug = category.get("slug", "")
    restricted = RESTRICTED_VOCAB.get(cat_slug, [])
    for term in restricted:
        if term.lower() in body_lower:
            violations.append(f"category_taboo: '{term}'")

    # ── Context grounding requirement ──
    trigger_kind = trigger.get("kind", "")
    if not trigger_kind or trigger_kind == "placeholder":
        owner_name = merchant.get("identity", {}).get("owner_first_name", "")
        if owner_name not in body:
            violations.append("no_context_grounding")

    # If any hard-rejection rule triggered, block immediately
    if violations:
        return {
            "allow": False, "score": 0,
            "reason": f"Hard rejection: {violations[0]}",
            "violations": violations
        }

    # ── Multi-dimensional scoring ──
    s_rel, r_rel = _eval_relevance(body, trigger, merchant, category)
    s_tim, r_tim = _eval_timing(trigger)
    s_per, r_per = _eval_personalization(body, merchant, customer)
    s_cla, r_cla = _eval_clarity(body, cta)
    s_tru, r_tru = _eval_trust(body, rationale, category)

    total = s_rel + s_tim + s_per + s_cla + s_tru
    dimension_scores = {
        "relevance": (s_rel, r_rel),
        "timing": (s_tim, r_tim),
        "personalization": (s_per, r_per),
        "clarity": (s_cla, r_cla),
        "trustworthiness": (s_tru, r_tru),
    }

    # ── Category tone validation ──
    tone_ok = True
    if cat_slug == "dentists" and any(w in body_lower for w in ["deal", "discount", "sale", "cheap"]):
        violations.append("tone_mismatch: sales language in clinical context")
        tone_ok = False
    elif cat_slug == "pharmacies" and any(w in body_lower for w in ["fun", "party", "celebrate"]):
        violations.append("tone_mismatch: casual language in pharmacy context")
        tone_ok = False

    if not tone_ok:
        total = max(total - 2, 0)

    # ── Final decision ──
    allow = total >= 7

    if allow:
        reason = f"Approved (score {total}/10). Grounded in {trigger_kind} trigger with {r_rel}."
    else:
        weakest = min(dimension_scores.items(), key=lambda x: x[1][0])[0]
        reason = f"Blocked (score {total}/10 < threshold 7). Weakest dimension: {weakest}."

    return {
        "allow": allow,
        "score": total,
        "reason": reason,
        "violations": violations,
        "scores": dimension_scores,
    }
