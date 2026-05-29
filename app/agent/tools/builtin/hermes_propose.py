"""hermes_propose tool -- request proposal-only write intents from Hermes."""

from __future__ import annotations

import json
from typing import Annotated

from pydantic import Field

from app.agent.tools.registry import Tool
from app.services.hermes import (
    HermesConnectionError,
    HermesProposal,
    HermesProposalRequest,
    HermesSchemaError,
    HermesTimeoutError,
    HermesUnavailableError,
    propose_write_intents,
)


async def _hermes_propose(
    task: Annotated[
        str,
        Field(description="The memory or drafting task Hermes should analyze."),
    ],
    context: Annotated[
        str,
        Field(
            description=(
                "Optional context string for Hermes. It will be clamped by the "
                "Hermes adapter before transport."
            )
        ),
    ] = "",
    target_folder: Annotated[
        str | None,
        Field(description="Optional target vault folder hint for new-note proposals."),
    ] = None,
    max_intents: Annotated[
        int,
        Field(description="Maximum write intents to request, clamped to 1..20."),
    ] = 5,
) -> str:
    """Ask Hermes for structured vault write-intent proposals without writing.

    Use this to draft candidate second-brain notes. The returned intents are
    proposals only; to persist a note, call vault_write explicitly with one
    accepted intent.
    """
    try:
        proposal = await propose_write_intents(
            HermesProposalRequest(
                task=task,
                context=context,
                target_folder=target_folder,
                max_intents=max_intents,
            )
        )
    except HermesUnavailableError as exc:
        return f"Hermes connector unavailable: {exc}"
    except HermesTimeoutError as exc:
        return f"Hermes connector timed out: {exc}"
    except HermesConnectionError as exc:
        return f"Hermes connector connection failed: {exc}"
    except HermesSchemaError as exc:
        return f"Hermes connector schema error: {exc}"

    return _format_proposal(proposal)


def _format_proposal(proposal: HermesProposal) -> str:
    payload = {
        "summary": proposal.summary,
        "warnings": proposal.warnings,
        "model_info": proposal.model_info,
        "valid_intents": [
            {
                "vault_write_params": intent.as_vault_write_params(),
                "body_truncated": intent.body_truncated,
                "warnings": intent.warnings,
            }
            for intent in proposal.valid_intents
        ],
        "conflicts": [
            {
                "vault_write_params": intent.as_vault_write_params(),
                "warning": intent.warning,
                "body_truncated": intent.body_truncated,
                "warnings": intent.warnings,
            }
            for intent in proposal.conflicts
        ],
        "invalid_intents": [
            {
                "folder": intent.folder,
                "slug": intent.slug,
                "title": intent.title,
                "invalid_reason": intent.invalid_reason,
            }
            for intent in proposal.invalid_intents
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


hermes_propose = Tool(
    _hermes_propose,
    name="hermes_propose",
    description=(
        "Ask the Hermes sidecar for structured vault write-intent proposals. "
        "This tool never writes to the Obsidian vault; use vault_write "
        "separately for accepted new-note intents."
    ),
)
