"""DraftingPort: the ONLY seam a generative model is reachable through.

One method, and it returns a ``str``. Not a message, not a decision, not a number: the raw text
a model produced, which the domain then validates against a schema and a closed fact set
(:mod:`..domain.drafting`) and discards on any failure. Typing it as a string rather than as an
``OutreachMessage`` is the point. If the port returned a domain object, the model would be
constructing a domain object, and "the model never produces a consequential value" would be a
convention rather than a type.

Two properties hold for every implementation of this port:

* it is called ONLY after the eligibility engine has answered ``eligible``. No draft exists for
  a contact that may not be made, so a refused contact costs no tokens and leaks no facts to a
  model; and
* whatever it returns is untrusted. There is no implementation whose output is taken on faith,
  including the offline one.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import DraftRequest


class DraftingUnavailableError(RuntimeError):
    """Raised when no drafter is configured or reachable.

    The service treats it as a discarded draft: the deterministic template body is prepared for
    a human instead, and nothing is delivered automatically.
    """


@runtime_checkable
class DraftingPort(Protocol):
    def draft(self, request: DraftRequest) -> str:
        """Return raw candidate text (expected to be a JSON object with a ``body`` string)."""
        ...
