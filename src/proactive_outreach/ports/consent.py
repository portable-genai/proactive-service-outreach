"""ConsentPort: the boundary onto the catalog's consent and preference store (Mkt6).

**This repo builds no consent store.** The store lives inside the marketing compliance and
brand governance system, which already models consent as a rule with its own engine and its own
citations, and is already this system's mandatory dependency. Here there is a port, three
adapters, and the wire types re-exported from ``consent-preference-kit`` so the domain depends
on a versioned client rather than on another service's internal module or on a hand-rolled HTTP
call. A second store would be a second answer to a legal question about a person, which is the
one thing a bank cannot have.

The port's contract is narrow and deliberately fail-closed:

* :meth:`ConsentPort.decide` returns a decision or RAISES
  :class:`ConsentUnavailableError`. It never returns ``None`` and never returns a
  locally-invented allow. The service treats the raise as an unknown consent state, which the
  eligibility engine denies on.
* :meth:`ConsentPort.record_send` is not optional bookkeeping. A frequency cap counts recorded
  sends and nothing else, so a consumer that decides but never records passes every cap
  forever. It is called after the message actually goes out, quoting the decision id that
  permitted it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from consent_preference_kit import (
    CHANNELS,
    OUTCOME_ALLOWED,
    OUTCOME_DENIED,
    ConsentDecision,
    ConsentQuery,
    SendRecord,
)
from consent_preference_kit import (
    Citation as ConsentCitation,
)


class ConsentUnavailableError(RuntimeError):
    """Raised when no consent decision could be obtained at all.

    Distinct from a decision that says "denied": that is an answer, and it is recorded as one.
    This is the absence of an answer, and the eligibility engine reads it as
    ``consent_unknown``, which denies.
    """


@runtime_checkable
class ConsentPort(Protocol):
    def decide(self, query: ConsentQuery) -> ConsentDecision:
        """Ask whether this subject may be contacted, at the query's explicit ``as_of``."""
        ...

    def record_send(self, send: SendRecord) -> str:
        """Record one contact so the store's frequency caps count it. Returns the send id."""
        ...


__all__ = [
    "CHANNELS",
    "OUTCOME_ALLOWED",
    "OUTCOME_DENIED",
    "ConsentCitation",
    "ConsentDecision",
    "ConsentPort",
    "ConsentQuery",
    "ConsentUnavailableError",
    "SendRecord",
]
