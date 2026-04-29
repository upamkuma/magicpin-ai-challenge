#!/usr/bin/env python3
"""
Multi-turn conversation handler for the Vera bot.
Demonstrates stateful conversation management with:
- Auto-reply detection and progressive backoff
- Intent transition detection (qualifying → action)
- Hostile/opt-out handling
- Off-topic routing
- Conversation state tracking
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict
from enum import Enum


class ConversationPhase(Enum):
    INITIATED = "initiated"          # Bot sent first message, no reply yet
    QUALIFYING = "qualifying"        # Back-and-forth, gathering info
    ACTION_MODE = "action_mode"      # Merchant committed, executing
    WAITING = "waiting"              # Backed off (auto-reply, etc.)
    ENDED = "ended"                  # Conversation closed


@dataclass
class Turn:
    role: str           # "bot" or "merchant"
    message: str
    timestamp: str
    is_auto_reply: bool = False


@dataclass
class ConversationState:
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str] = None
    phase: ConversationPhase = ConversationPhase.INITIATED
    turns: List[Turn] = field(default_factory=list)
    auto_reply_count: int = 0
    trigger_kind: str = ""
    original_topic: str = ""
    suppressed: bool = False

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    @property
    def merchant_turns(self) -> List[Turn]:
        return [t for t in self.turns if t.role == "merchant"]

    @property
    def last_bot_message(self) -> Optional[str]:
        for t in reversed(self.turns):
            if t.role == "bot":
                return t.message
        return None


# Detection patterns
AUTO_REPLY_PATTERNS = [
    "thank you for contacting",
    "our team will respond",
    "automated assistant",
    "we will get back to you",
    "your message has been received",
    "i am an automated",
    "auto-reply",
]

HOSTILE_PATTERNS = [
    "stop messaging", "not interested", "spam", "useless",
    "stop sending", "don't message", "unsubscribe",
    "leave me alone", "bothering", "block",
]

INTENT_COMMIT_PATTERNS = [
    "yes", "ok let", "let's do it", "go ahead", "sounds good",
    "please do", "yes please", "do it", "proceed", "confirm",
    "what's next", "whats next", "sure", "ok do it",
]

OFF_TOPIC_PATTERNS = [
    "gst", "tax", "filing", "income tax", "accounting",
    "legal", "lawyer", "insurance", "loan",
]


def detect_auto_reply(message: str) -> bool:
    """Check if a message looks like a WhatsApp Business auto-reply."""
    msg_lower = message.lower().strip()
    return any(p in msg_lower for p in AUTO_REPLY_PATTERNS)


def detect_hostile(message: str) -> bool:
    """Check if merchant is hostile or opting out."""
    msg_lower = message.lower().strip()
    return any(p in msg_lower for p in HOSTILE_PATTERNS)


def detect_intent_commit(message: str) -> bool:
    """Check if merchant is committing to action."""
    msg_lower = message.lower().strip()
    return any(p in msg_lower for p in INTENT_COMMIT_PATTERNS)


def detect_off_topic(message: str) -> bool:
    """Check if merchant is asking about something out of scope."""
    msg_lower = message.lower().strip()
    return any(p in msg_lower for p in OFF_TOPIC_PATTERNS)


def respond(state: ConversationState, merchant_message: str) -> dict:
    """
    Given the conversation so far + the merchant's latest message,
    produce the next bot reply.

    Returns dict with keys: action, body (optional), cta (optional),
    rationale, wait_seconds (optional).
    """
    # Record the merchant's turn
    is_auto = detect_auto_reply(merchant_message)
    state.turns.append(Turn(
        role="merchant",
        message=merchant_message,
        timestamp="",  # Would be filled by caller
        is_auto_reply=is_auto,
    ))

    # If conversation already ended, don't respond
    if state.phase == ConversationPhase.ENDED:
        return {
            "action": "end",
            "rationale": "Conversation already ended."
        }

    # ── AUTO-REPLY HANDLING ──
    if is_auto:
        state.auto_reply_count += 1

        if state.auto_reply_count >= 3:
            state.phase = ConversationPhase.ENDED
            return {
                "action": "end",
                "rationale": f"Auto-reply detected {state.auto_reply_count} times. "
                             f"No real engagement signal. Closing conversation."
            }

        if state.auto_reply_count >= 2:
            state.phase = ConversationPhase.WAITING
            return {
                "action": "wait",
                "wait_seconds": 86400,
                "rationale": "Same auto-reply twice in a row. Owner likely not at phone. "
                             "Waiting 24h before retry."
            }

        # First auto-reply: gentle nudge
        reply = ("Looks like an auto-reply — no worries! "
                 "When the owner sees this, just reply 'Yes' to continue. 😊")
        state.turns.append(Turn(role="bot", message=reply, timestamp=""))
        return {
            "action": "send",
            "body": reply,
            "cta": "binary_yes_no",
            "rationale": "Detected auto-reply (canned WhatsApp Business message). "
                         "One gentle nudge for the owner."
        }

    # Reset auto-reply counter on real message
    state.auto_reply_count = 0

    # ── HOSTILE / OPT-OUT ──
    if detect_hostile(merchant_message):
        state.phase = ConversationPhase.ENDED
        reply = ("Apologies for the bother — I won't message again. "
                 "If you ever need help, just send 'Hi Vera'. 🙏")
        state.turns.append(Turn(role="bot", message=reply, timestamp=""))
        return {
            "action": "send",
            "body": reply,
            "cta": "none",
            "rationale": "Merchant expressed frustration. Graceful exit with opt-back-in path. "
                         "Suppressing future triggers for this merchant."
        }

    # ── INTENT TRANSITION ──
    if detect_intent_commit(merchant_message):
        state.phase = ConversationPhase.ACTION_MODE
        reply = ("On it! Drafting everything now — will share in under 2 minutes. "
                 "You'll be able to review before anything goes live.")
        state.turns.append(Turn(role="bot", message=reply, timestamp=""))
        return {
            "action": "send",
            "body": reply,
            "cta": "none",
            "rationale": "Merchant explicitly committed ('yes' / 'let's do it'). "
                         "Switching from qualifying to action mode immediately."
        }

    # ── OFF-TOPIC ──
    if detect_off_topic(merchant_message):
        reply = ("That's outside what I can help with directly — "
                 "best to check with your CA or advisor for that. "
                 "Coming back to what we were discussing — "
                 "want me to go ahead with the draft?")
        state.turns.append(Turn(role="bot", message=reply, timestamp=""))
        return {
            "action": "send",
            "body": reply,
            "cta": "open_ended",
            "rationale": "Off-topic ask politely declined. "
                         "Redirecting back to original conversation thread."
        }

    # ── GENERAL ENGAGED REPLY ──
    state.phase = ConversationPhase.QUALIFYING

    # Check if merchant is asking a question
    if "?" in merchant_message:
        reply = ("Good question — let me check on that and get back to you "
                 "with specifics. Anything else you'd like me to look into?")
    else:
        reply = ("Got it. Working on this now — I'll have it ready for "
                 "your review shortly. Anything specific you'd like me to keep in mind?")

    state.turns.append(Turn(role="bot", message=reply, timestamp=""))
    return {
        "action": "send",
        "body": reply,
        "cta": "open_ended",
        "rationale": "Acknowledged merchant input. Advancing conversation "
                     "with open-ended follow-up to maintain engagement."
    }
