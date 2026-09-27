"""Shared network-failure classification."""

from __future__ import annotations

import http.client
import urllib.error

# Transport failures a fetch may raise; anything else is a bug and should propagate.
NETWORK_ERRORS = (urllib.error.URLError, http.client.HTTPException, ConnectionError, TimeoutError)
