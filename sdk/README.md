# PromptMatrix Python SDK

The official Python SDK for [PromptMatrix](https://promptmatrix.github.io) — live prompt management for AI applications.

## Install

```bash
pip install promptmatrix-sdk

# For async support
pip install "promptmatrix-sdk[async]"
```

## Quick Start

```python
from promptmatrix import PromptMatrix

pm = PromptMatrix(api_key="pm_live_xxxxxxxxxxxxx")

# Drop-in replacement for your hardcoded string:
# Before: SYSTEM = "You are a helpful assistant..."
# After:
SYSTEM = pm.serve("assistant.system")

# With variables (use {{variable_name}} in the prompt)
subject = pm.serve("email.subject", variables={"product": "PromptMatrix"})

# With fallback (returned if API is unreachable)
system = pm.serve("assistant.system", fallback="You are a helpful assistant.")
```

## Async

```python
import asyncio
from promptmatrix import PromptMatrix

pm = PromptMatrix(api_key="pm_live_xxxxxxxxxxxxx")

async def main():
    system = await pm.aserve("assistant.system")

asyncio.run(main())
```

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `api_key` | required | Your API key (from the Dashboard → API Keys) |
| `base_url` | `http://localhost:8000` | Your PromptMatrix backend URL (local or remote self-hosted) |
| `ttl` | `30` | In-process cache TTL in seconds. Set to `0` to disable. |
| `timeout` | `4` | HTTP request timeout in seconds |
| `strict` | `False` | If `True`, raises `PromptMatrixError` instead of returning fallback |

## Cache Invalidation

```python
# Invalidate all cached prompts (e.g. after receiving a webhook)
pm.invalidate()

# Invalidate a specific key
pm.invalidate("assistant.system")
```

## Zero Dependencies

The SDK core uses Python stdlib only (`urllib`, `threading`, `json`).  
The async variant requires `anyio>=4.0`.

## License

MIT
