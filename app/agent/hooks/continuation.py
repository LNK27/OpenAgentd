"""ContinuationHook — drives the ``/continue`` agent run.

When a user invokes the ``/continue`` command, the agent loop runs against
the existing DB history with no new user turn appended.  Two jobs need
doing in that run, both one-shot on the very first model call:

1. **Inject a continuation directive** into the message list as an
   ephemeral ``HumanMessage`` (never persisted, never seen by the
   frontend).  Empirically OpenAI Chat Completions, when given a
   trailing-assistant message in plain prose, restarts rather than
   continues — see ``manual/try_providers/try_continue_probe.py``.  A
   short explicit instruction routed through the standard
   user→assistant alternation pattern fixes that.

2. **Stamp the first assistant response** with
   ``extra["is_continuation"] = True`` so the frontend can render it tight
   against the prior assistant bubble.  The API response layer uses this same
   flag to omit reasoning content from client-facing history while keeping the
   provider request shape unchanged for prompt-cache compatibility.

Both behaviours are one-shot per run.  Within a single ``/continue``
turn the model may emit several assistant messages (content → tool
call → reaction); only the first one is a continuation of the prior
turn.  ``_directive_fired`` and ``_stamp_fired`` ensure each side of
the hook runs exactly once.

The ``is_continuation`` flag rides on ``AssistantMessage.extra`` and is
persisted verbatim by :class:`SQLiteCheckpointer.sync` via the existing
``extra=msg.extra`` pass-through — no changes to the persistence layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.agent.hooks.base import BaseAgentHook
from app.agent.schemas.chat import AssistantMessage, HumanMessage

if TYPE_CHECKING:
    from app.agent.state import AgentState, ModelRequest, RunContext


# Phrasing notes:
# * "your previous response" anchors the model to the trailing assistant turn.
# * "was interrupted" gives the model a reason for the truncation so it does
#   not infer "the user changed their mind" and restart.
# * "Continue from exactly where it stopped" is the action.
# * "Do not restart, apologise, or add a preamble" pre-empts the three
#   failure modes observed in the empirical probe.
# * "produce the next tokens that would have come after the partial text"
#   reframes the task as completion, not response generation.
CONTINUATION_DIRECTIVE = (
    "Your previous response was interrupted before it could complete. "
    "Continue from exactly where it stopped — produce the next tokens "
    "that would have come after the partial text. Do not restart your "
    "answer, do not apologise, do not add a preamble, do not summarise "
    "what you already said. Just continue."
)


class ContinuationHook(BaseAgentHook):
    """Drive the ``/continue`` agent run — directive + stamp, one-shot.

    Attached to a single ``/continue``-triggered agent run.  Both
    behaviours fire exactly once per run.
    """

    def __init__(self) -> None:
        self._directive_fired: bool = False
        self._stamp_fired: bool = False

    async def before_model(
        self,
        ctx: "RunContext",
        state: "AgentState",
        request: "ModelRequest",
    ) -> "ModelRequest | None":
        if self._directive_fired:
            return None
        self._directive_fired = True
        directive_msg = HumanMessage(content=CONTINUATION_DIRECTIVE)
        return request.override(messages=request.messages + (directive_msg,))

    async def after_model(
        self,
        ctx: "RunContext",
        state: "AgentState",
        response: AssistantMessage,
    ) -> None:
        if self._stamp_fired:
            return
        # Merge into existing extra (the agent loop sets extra["usage"]
        # before this hook runs — preserve it).
        #
        # TODO(frontend): the flag is currently set but no UI keys off it.
        # Per the design discussion (Option 3 — tight stack), the message
        # renderer should suppress the avatar/header and tighten the top
        # margin when the previous block is from the same assistant.
        if response.extra is None:
            response.extra = {"is_continuation": True}
        else:
            response.extra["is_continuation"] = True
        self._stamp_fired = True
