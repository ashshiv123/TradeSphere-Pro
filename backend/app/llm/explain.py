"""
LLM Explanation Layer (TradeSphere Pro - Stage 16).
Provider-agnostic explanation generator for stored signals.

Rules:
- Read-only: only explains stored Signal objects.
- NEVER influences decisions or orders.
- Failures/timeouts are non-blocking: fallback template JSON is provided and error is logged.
- Validated JSON structure:
    {
        "summary": "...",
        "supporting_factors": [...],
        "conflicting_factors": [...],
        "main_risks": [...]
    }
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.db.models_trading import Signal, SignalExplanation

logger = logging.getLogger(__name__)

# Default timeout in seconds for LLM API calls
LLM_TIMEOUT_SECONDS = 10.0


def _build_fallback_explanation(signal: Signal, error_note: Optional[str] = None) -> Dict[str, Any]:
    """Generates a structured template explanation when the LLM is unavailable or fails."""
    cs = signal.composite_score or 0.0
    conf = signal.confidence or 0.0
    direction = signal.direction or "HOLD"
    symbol = signal.symbol or "UNKNOWN"

    supp: List[str] = []
    conflicts: List[str] = []
    risks: List[str] = []

    if signal.contributions and isinstance(signal.contributions, dict):
        for field, item in signal.contributions.items():
            if not isinstance(item, dict):
                continue
            sc = item.get("score")
            wt = item.get("weight", 0)
            if sc is None:
                continue
            if direction == "LONG":
                if sc > 0:
                    supp.append(f"{field} bullish (score {sc:+.2f}, weight {wt}%)")
                elif sc < 0:
                    conflicts.append(f"{field} bearish (score {sc:+.2f}, weight {wt}%)")
            elif direction == "SHORT":
                if sc < 0:
                    supp.append(f"{field} bearish (score {sc:+.2f}, weight {wt}%)")
                elif sc > 0:
                    conflicts.append(f"{field} bullish (score {sc:+.2f}, weight {wt}%)")
            else:
                if abs(sc) >= 0.2:
                    supp.append(f"{field} score {sc:+.2f}")

    if not supp:
        supp = ["No dominant supporting factor identified."]
    if not conflicts:
        conflicts = ["No significant conflicting factor identified."]

    if direction == "HOLD":
        summary = (
            f"Hold recommendation for {symbol} at candle close. "
            f"Composite score is {cs:+.2f} with confidence {conf:.2f}. "
            f"Reason: {signal.hold_reason or 'neutral market conditions'}."
        )
        risks = ["Uncertain direction or insufficient signal strength."]
    else:
        summary = (
            f"{direction} signal triggered for {symbol} based on composite score of {cs:+.2f} "
            f"and confidence of {conf:.2f}. "
            f"Entry price is {signal.entry_price or 'market'} with stop loss at {signal.stop_loss}."
        )
        risks = [
            f"Regime factor is {signal.regime_factor or 1.0:.2f}.",
            f"Correlation factor with BTC is {signal.corr_factor or 1.0:.2f}.",
            f"Stop distance: {signal.sl_distance_atr or 1.5:.2f} ATR.",
        ]

    if error_note:
        risks.append(f"Note: Generated via fallback template ({error_note}).")

    return {
        "summary": summary,
        "supporting_factors": supp[:4],
        "conflicting_factors": conflicts[:4],
        "main_risks": risks[:4],
    }


def _clean_json_response(raw_text: str) -> Dict[str, Any]:
    """Extracts and validates JSON from LLM output."""
    raw = raw_text.strip()
    # Strip markdown code fences if present (e.g. ```json ... ```)
    if "```" in raw:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
        if match:
            raw = match.group(1).strip()

    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("LLM response did not contain a JSON dictionary.")

    required_keys = ["summary", "supporting_factors", "conflicting_factors", "main_risks"]
    for key in required_keys:
        if key not in data:
            raise ValueError(f"Missing required key '{key}' in LLM explanation JSON.")

    # Ensure list types
    for key in ["supporting_factors", "conflicting_factors", "main_risks"]:
        if not isinstance(data[key], list):
            data[key] = [str(data[key])]

    return data


def _call_provider(prompt: str) -> str:
    """Dispatches HTTP request to the configured LLM provider."""
    mock_mode = os.getenv("LLM_MOCK", "0").lower() in ("1", "true", "yes")
    if mock_mode:
        return json.dumps({
            "summary": "Mock explanation: Signal triggered based on momentum and trend metrics. Conditions align with scoring rules.",
            "supporting_factors": ["F1 Momentum is positive", "F2 EMA Trend is bullish"],
            "conflicting_factors": ["F3 RSI is slightly elevated"],
            "main_risks": ["BTC regime volatility", "Upcoming macro events"]
        })

    provider = os.getenv("LLM_PROVIDER", "").lower().strip()
    api_key = os.getenv("LLM_API_KEY", "").strip()

    if not provider:
        raise RuntimeError("LLM_PROVIDER not set in environment.")
    if not api_key:
        raise RuntimeError(f"LLM_API_KEY missing for provider '{provider}'.")

    model = os.getenv("LLM_MODEL", "").strip()

    if provider in ("openai", "open_ai"):
        model = model or "gpt-4o-mini"
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a quantitative crypto trading analyst. "
                        "Explain the trade signal strictly in valid JSON format. "
                        "Do NOT include financial advice or price predictions. "
                        "Keep response under 120 words total. "
                        "JSON keys required: 'summary' (string), 'supporting_factors' (list of strings), "
                        "'conflicting_factors' (list of strings), 'main_risks' (list of strings)."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
            "max_tokens": 300,
        }
        with httpx.Client(timeout=LLM_TIMEOUT_SECONDS) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    elif provider in ("anthropic", "claude"):
        model = model or "claude-3-haiku-20240307"
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": 300,
            "system": (
                "You are a quantitative crypto trading analyst. "
                "Output strictly a JSON object with keys: summary, supporting_factors, "
                "conflicting_factors, main_risks. No conversational text."
            ),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
        }
        with httpx.Client(timeout=LLM_TIMEOUT_SECONDS) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["content"][0]["text"]

    elif provider in ("gemini", "google"):
        model = model or "gemini-1.5-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": f"Output JSON only: {prompt}"}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 300,
                "responseMimeType": "application/json",
            },
        }
        with httpx.Client(timeout=LLM_TIMEOUT_SECONDS) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]

    else:
        raise RuntimeError(f"Unsupported LLM provider '{provider}'.")


def explain_signal(
    signal_id: int,
    session: Optional[Session] = None,
    force_refresh: bool = False,
) -> SignalExplanation:
    """
    Generates and stores an explanation for the given signal_id.
    - If explanation exists and force_refresh is False, returns existing explanation.
    - Catches all exceptions, records error string if failed, and persists fallback JSON.
    - Never raises to caller.
    """
    own_session = False
    if session is None:
        own_session = True
        session = SessionLocal()

    try:
        # Check if already explained
        existing = session.scalars(
            select(SignalExplanation).where(SignalExplanation.signal_id == signal_id)
        ).first()
        if existing and not force_refresh:
            return existing

        signal = session.scalars(select(Signal).where(Signal.id == signal_id)).first()
        if not signal:
            logger.warning("Cannot explain non-existent signal id=%s", signal_id)
            err_expl = SignalExplanation(
                signal_id=signal_id,
                error="Signal not found",
                text=_build_fallback_explanation(Signal(symbol="UNKNOWN", direction="HOLD"), "Signal not found"),
            )
            return err_expl

        # Build prompt
        prompt = (
            f"Explain this crypto futures trading signal:\n"
            f"Symbol: {signal.symbol}\n"
            f"Interval: {signal.interval}\n"
            f"Candle Close Time: {signal.ts}\n"
            f"Direction: {signal.direction}\n"
            f"Hold Reason: {signal.hold_reason or 'None'}\n"
            f"Composite Score: {signal.composite_score}\n"
            f"Confidence: {signal.confidence}\n"
            f"Regime Factor: {signal.regime_factor}\n"
            f"Correlation Factor: {signal.corr_factor}\n"
            f"Entry Price: {signal.entry_price}\n"
            f"Stop Loss: {signal.stop_loss}\n"
            f"Take Profit: {signal.take_profit}\n"
            f"Contributions by factor: {json.dumps(signal.contributions or {})}\n\n"
            f"Provide a brief, factual explanation in JSON format with keys: "
            f"'summary', 'supporting_factors', 'conflicting_factors', 'main_risks'."
        )

        provider_name = os.getenv("LLM_PROVIDER", "mock")
        model_name = os.getenv("LLM_MODEL", "default")
        error_msg: Optional[str] = None
        explanation_json: Dict[str, Any]

        try:
            raw_output = _call_provider(prompt)
            explanation_json = _clean_json_response(raw_output)
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {str(exc)}"
            logger.warning("LLM explanation failed for signal %s: %s", signal_id, error_msg)
            explanation_json = _build_fallback_explanation(signal, error_msg)

        if existing:
            existing.provider = provider_name
            existing.model = model_name
            existing.text = explanation_json
            existing.error = error_msg
            session.commit()
            return existing
        else:
            new_expl = SignalExplanation(
                signal_id=signal_id,
                provider=provider_name,
                model=model_name,
                text=explanation_json,
                error=error_msg,
            )
            session.add(new_expl)
            session.commit()
            return new_expl

    finally:
        if own_session:
            session.close()

