"""
PromptMatrix SDK — Core Client
"""

import time
import threading
import urllib.request
import urllib.error
import json
from typing import Optional, Dict, Any


class PromptMatrixError(Exception):
    """Raised when the API returns an error and strict=True."""
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class _CacheEntry:
    __slots__ = ("value", "expires_at")

    def __init__(self, value: str, ttl: float):
        self.value = value
        self.expires_at = time.monotonic() + ttl


class PromptMatrix:
    """
    Sync + async client for the PromptMatrix serve API.

    Parameters
    ----------
    api_key : str
        Your PromptMatrix API key (e.g. ``pm_live_xxxxxxxxxxxxx``).
    base_url : str
        Base URL of your PromptMatrix backend.
        Defaults to ``http://localhost:8000`` (local self-hosted instance).
        For a remote/team server, pass your server's URL explicitly.
    ttl : float
        In-process cache TTL in seconds. Default: 30.
        Set to 0 to disable caching.
    timeout : float
        HTTP request timeout in seconds. Default: 4.
    strict : bool
        If True, raises ``PromptMatrixError`` when the API is unreachable.
        If False (default), returns the fallback value instead.

    Example
    -------
    >>> pm = PromptMatrix(api_key="pm_live_xxx")
    >>> system_prompt = pm.serve("assistant.system")
    >>> # With variables
    >>> subject = pm.serve("email.subject", variables={"product": "PromptMatrix"})
    """

    DEFAULT_BASE_URL = "http://localhost:8000"

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        ttl: float = 30.0,
        timeout: float = 4.0,
        strict: bool = False,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.ttl = ttl
        self.timeout = timeout
        self.strict = strict

        self._cache: Dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────

    def serve(
        self,
        key: str,
        variables: Optional[Dict[str, Any]] = None,
        fallback: str = "",
    ) -> str:
        """
        Fetch the live version of a prompt by key.

        This is the drop-in replacement for your hardcoded string:

            # Before
            SYSTEM = "You are a helpful assistant..."

            # After
            SYSTEM = pm.serve("assistant.system", fallback="You are a helpful assistant...")

        Parameters
        ----------
        key : str
            The prompt key (e.g. ``"assistant.system"``).
        variables : dict, optional
            Key-value pairs to interpolate into the prompt text.
            Inside the prompt, use ``{{variable_name}}``.
        fallback : str
            Value to return if the API is unreachable and ``strict=False``.

        Returns
        -------
        str
            The live prompt content.
        """
        cache_key = self._cache_key(key, variables)

        # Cache hit
        with self._lock:
            entry = self._cache.get(cache_key)
            if entry and time.monotonic() < entry.expires_at:
                return entry.value

        # Fetch
        try:
            content = self._fetch(key, variables)
        except PromptMatrixError:
            if self.strict:
                raise
            return fallback

        # Cache store
        if self.ttl > 0:
            with self._lock:
                self._cache[cache_key] = _CacheEntry(content, self.ttl)

        return content

    async def aserve(
        self,
        key: str,
        variables: Optional[Dict[str, Any]] = None,
        fallback: str = "",
    ) -> str:
        """
        Async version of ``serve()``. Uses ``anyio.to_thread.run_sync``
        so it works in both asyncio and trio without extra dependencies.

        Example
        -------
        >>> system_prompt = await pm.aserve("assistant.system")
        """
        import anyio

        return await anyio.to_thread.run_sync(
            lambda: self.serve(key, variables=variables, fallback=fallback)
        )

    def invalidate(self, key: Optional[str] = None):
        """
        Invalidate cache entries.

        Call after a prompt is approved to force a fresh fetch
        without waiting for TTL expiry.

        Parameters
        ----------
        key : str, optional
            If given, invalidates only entries for this key.
            If None, clears the entire in-process cache.
        """
        with self._lock:
            if key is None:
                self._cache.clear()
            else:
                self._cache = {
                    k: v for k, v in self._cache.items()
                    if not k.startswith(key)
                }

    # ── Internal ──────────────────────────────────────────────────────────

    def _cache_key(self, key: str, variables: Optional[Dict]) -> str:
        if variables:
            var_str = "&".join(f"{k}={v}" for k, v in sorted(variables.items()))
            return f"{key}?{var_str}"
        return key

    def _fetch(self, key: str, variables: Optional[Dict]) -> str:
        url = f"{self.base_url}/pm/serve/{key}"
        if variables:
            params = "&".join(f"{k}={v}" for k, v in variables.items())
            url = f"{url}?{params}"

        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "User-Agent": f"promptmatrix-sdk/0.1.0",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode())
                content = body.get("content") or body.get("text") or body.get("prompt", "")
                if not content and isinstance(body, str):
                    content = body
                return content
        except urllib.error.HTTPError as e:
            raise PromptMatrixError(
                f"PromptMatrix API error {e.code} for key '{key}'",
                status_code=e.code,
            )
        except (urllib.error.URLError, OSError) as e:
            raise PromptMatrixError(f"PromptMatrix unreachable: {e}")
