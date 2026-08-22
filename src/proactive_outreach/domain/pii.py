"""The PII pattern set this vertical redacts with, sourced from the shared `pii-kit`.

Row selection and ORDER are per-vertical (the commons deliberately does not bake them in): here
the national-ID rows run first and the universal email/phone rows last. A vertical with a
bare-digit account catch-all would order that last so it does not subsume a national id.

The three markets are the ones the catalog row scopes this system to. They are also the markets
whose quiet hours the shipped policy configures, and the two lists are meant to stay in step: a
market this service will contact people in is a market whose identifiers it must be able to
mask. Serving a fourth market means adding both rows, not one.

Personal data reaches this service in exactly one field, the source system's free-text
``detail``. Everything else the domain carries is a pseudonymous ``subject_id`` and a closed set
of already-minimised facts, so redaction has a small, named surface rather than being a
best-effort sweep over an open structure.
"""

from __future__ import annotations

from pii_kit import UNIVERSAL_PATTERNS, Pattern, national_patterns_for

# The jurisdictions this deployment serves (override per client). Obviously synthetic data only.
JURISDICTIONS: tuple[str, ...] = ("SG", "AU", "JP")

PII_PATTERNS: tuple[Pattern, ...] = (
    *national_patterns_for(JURISDICTIONS),
    *UNIVERSAL_PATTERNS,
)
