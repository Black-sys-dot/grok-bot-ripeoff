"""Security and Credential Sanitizer for Grok Bot.

Ensures no API keys, bearer tokens, or secrets leak into:
1. LLM context / chat history
2. Frontend API responses
3. Activity logs or stdout
4. Remote requests
"""

from __future__ import annotations

import re

# Patterns matching popular tokens and credentials
CREDENTIAL_PATTERNS = [
    # OpenAI / OpenRouter: sk-...
    re.compile(r"\b(sk-[a-zA-Z0-9_\-]{20,})\b"),
    # Hugging Face: hf_...
    re.compile(r"\b(hf_[a-zA-Z0-9_\-]{20,})\b"),
    # Notion: ntn_...
    re.compile(r"\b(ntn_[a-zA-Z0-9_\-]{20,})\b"),
    # GitHub: ghp_..., gho_..., glpat-...
    re.compile(r"\b((?:ghp|gho|ghu|ghs|ghr|glpat)-[a-zA-Z0-9_\-]{20,})\b"),
    # Bearer tokens in headers or strings
    re.compile(r"(Bearer\s+)[a-zA-Z0-9_\-\.]{16,}", re.IGNORECASE),
    # Common key/secret assignments: password="...", api_key="..."
    re.compile(r"((?:api[_-]?key|secret|password|auth_token)\s*[:=]\s*['\"])[^'\"\s]{8,}(['\"])", re.IGNORECASE),
]


def sanitize_sensitive_data(val: str) -> str:
    """Scrub known secret and token patterns from text."""
    if not isinstance(val, str) or not val:
        return val

    redacted = val
    # Redact specific prefixes
    redacted = re.sub(r"\b(sk-[a-zA-Z0-9_\-]{6})[a-zA-Z0-9_\-]{14,}\b", r"\1[REDACTED]", redacted)
    redacted = re.sub(r"\b(hf_[a-zA-Z0-9_\-]{6})[a-zA-Z0-9_\-]{14,}\b", r"\1[REDACTED]", redacted)
    redacted = re.sub(r"\b(ntn_[a-zA-Z0-9_\-]{6})[a-zA-Z0-9_\-]{14,}\b", r"\1[REDACTED]", redacted)
    redacted = re.sub(r"\b((?:ghp|gho|ghu|ghs|ghr|glpat)-[a-zA-Z0-9_\-]{6})[a-zA-Z0-9_\-]{14,}\b", r"\1[REDACTED]", redacted)
    
    # Redact Bearer tokens
    redacted = re.sub(r"(Bearer\s+)[a-zA-Z0-9_\-\.]{16,}", r"\1[REDACTED_TOKEN]", redacted, flags=re.IGNORECASE)

    # Redact explicit key assignments
    redacted = re.sub(
        r"((?:api[_-]?key|secret|password|auth_token)\s*[:=]\s*['\"])[^'\"\s]{8,}(['\"])",
        r"\1[REDACTED]\2",
        redacted,
        flags=re.IGNORECASE,
    )

    return redacted
