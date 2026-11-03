"""Compatibility wrapper for LLM explanations."""
from app.llm.explain import explain_signal, _call_provider as _call_llm

__all__ = ["explain_signal", "_call_llm"]
