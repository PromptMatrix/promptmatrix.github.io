"""
PromptMatrix Python SDK
=======================
Drop-in replacement for hardcoded prompt strings.

Usage:
  pip install promptmatrix-sdk

  from promptmatrix import PromptMatrix
  pm = PromptMatrix(api_key="pm_live_xxx")  # defaults to http://localhost:8000
  # For a remote server: PromptMatrix(api_key="pm_live_xxx", base_url="https://your-server.com")

  # Sync
  system_prompt = pm.serve("assistant.system")

  # Async
  system_prompt = await pm.aserve("assistant.system")

  # With variables
  system_prompt = pm.serve("email.subject", variables={"product": "PromptMatrix"})

The SDK caches responses in-process with a configurable TTL.
If the API is unreachable, it returns the fallback value (or raises, if strict=True).
"""

__version__ = "0.1.0"
__all__ = ["PromptMatrix", "PromptMatrixError"]

from .client import PromptMatrix, PromptMatrixError
