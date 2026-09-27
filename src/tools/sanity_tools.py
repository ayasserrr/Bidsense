"""LangChain tools backing the sanity-check stage.

`check_offer_arithmetic` is deliberately not an LLM call - a thin `@tool`
wrapper around the deterministic arithmetic checker in
`helpers.sanity_check_guard`. `judge_sanity_check_flags` is the LLM-backed
second half: given the flags the arithmetic check found, it judges each one
as genuine or explainable. `controllers.SanityCheckController` invokes both
in that fixed order - not an agent's runtime choice.
"""

import json

from langchain_core.tools import tool

from helpers.sanity_check_guard import find_sanity_flags
from schema.offer import OfferExtractionPayload
from schema.sanity_check import SanityCheckResult

from helpers.llm_runnable import build_response_schema
from ._common import build_system_human_prompt, run_tool_call

SANITY_CHECK_SYSTEM_PROMPT = """You are reviewing a structured extraction of a supplier offer for pricing/arithmetic consistency. You are given the full extracted JSON and a list of automated flags produced by a deterministic numeric checker - each flag identifies a specific field where the numbers don't reconcile: a line item's quantity x unit_price (net of any discount_amount) doesn't equal its total_price, a percentage-of-parent item's total_price doesn't match its own percentage_value applied to its parent's total_price, an item's stated_subtotal_amount doesn't match the sum of that item plus its accessories' total_price, the offer's grand_total doesn't match the sum of its top-level items, or a group of payment_schedules percentages doesn't sum to 100%.

Your job is to review each flagged item and decide, using only the context already present in the JSON (descriptions, discount_amount, price_basis, currency, item hierarchy, extra_attributes, general_notes_original), whether it is:

1. **A genuine pricing inconsistency worth flagging for human review** - the numbers plainly don't add up and nothing in the data explains *why the gap is not a problem*, or
2. **Explainable and not a real issue** - the mismatch is only rounding at the level of a single currency unit, or a field elsewhere in the same JSON gives an actual *reason* the numbers legitimately differ (a discount, a tax note, an explicit statement that this item's price is special).

**A note that merely restates or acknowledges the same gap is not an explanation - it is confirmation the issue is real, and must be kept, not dismissed.** Extraction sometimes writes a `general_notes_original` sentence like "the stated quantity and unit price do not reconcile with the total price as printed in the source" - that sentence is extraction flagging the *same* arithmetic problem you were just given as a flag, sourced from the document itself. It gives no discount, no special pricing rule, no reason the numbers should differ - it only confirms the source document itself prints inconsistent figures. Dismissing a flag on the basis of a note like this would hide a genuine source-document inconsistency from the reviewer who most needs to see it. Only dismiss when the note (or another field) states an actual causal reason for the gap - not merely that the gap exists or was already noticed.

You do not have the original source document - only this JSON and the flags. Your review is strictly about whether the JSON is *internally* arithmetically consistent, using only what's already in the JSON to judge explainability. Do not invent a justification that isn't visible in the data just to dismiss a flag - if you cannot point to a specific field that gives an actual reason for the gap, treat it as a genuine issue. Equally, do not flag something the data itself already explains just to be thorough - dismissing a truly explainable flag is the correct, complete answer for that flag.

Do not evaluate anything not covered by the given flags - this is a narrow review of exactly what was flagged, not a general audit of the whole offer, and not a re-check of anything the flags don't mention.

For each flag, decide keep (genuine issue) or dismiss (explainable). For every flag you keep, add one entry to `findings` with:
- `issue_type`: copy the flag's own type.
- `severity`: "critical" if the mismatch is large enough to materially change the offer's price (e.g. more than a few percent of the item's or offer's value), "warning" otherwise (a smaller gap still worth a human glance but unlikely to change the bottom line).
- `field_path`: copy the flag's own field path.
- `description`: one clear sentence explaining what's wrong, in your own words - not just a copy of the automated flag's description.

Set `status` to "needs_review" if you kept at least one finding, or "passed" if you dismissed every flag as explainable. Write `summary` as one or two sentences giving a reviewer who hasn't seen the details an overall sense of this offer's pricing consistency - mention how many flags were reviewed and how many were kept, in plain language."""

_RESPONSE_SCHEMA = build_response_schema(SanityCheckResult)

JUDGE_PROMPT = build_system_human_prompt(SANITY_CHECK_SYSTEM_PROMPT)


@tool
def check_offer_arithmetic(payload_json: str) -> str:
    """Checks an extracted offer's internal pricing arithmetic: quantity x
    unit_price vs total_price, percentage-of-parent pricing, stated
    subtotals, and grand_total vs the sum of top-level items. `payload_json`
    is an `OfferExtractionPayload` as JSON. Returns a JSON array of flags
    (`flag_type`, `field_path`, `description`); empty means nothing flagged.
    Pure function, no LLM call."""
    payload = OfferExtractionPayload.model_validate_json(payload_json)
    flags = find_sanity_flags(payload)
    return json.dumps(
        [
            {
                "flag_type": flag.flag_type.value,
                "field_path": flag.field_path,
                "description": flag.description,
            }
            for flag in flags
        ]
    )


@tool
async def judge_sanity_check_flags(payload_json: str, flags_json: str, log_id: str) -> str:
    """Reviews the flags from `check_offer_arithmetic` and decides, per
    flag, whether it's a genuine pricing inconsistency or explainable from
    context already in the JSON. `flags_json` is the array
    `check_offer_arithmetic` returned - only call this with a non-empty
    list. Returns a packed JSON string with the validated `SanityCheckResult`
    and `repair_attempts` telemetry."""
    flags = json.loads(flags_json)
    flags_text = "\n".join(
        f"- {flag['flag_type']} at {flag['field_path']}: {flag['description']}" for flag in flags
    )
    user_content = f"EXTRACTED OFFER JSON:\n{payload_json}\n\n---\n\nAUTOMATED FLAGS:\n{flags_text}"

    return await run_tool_call(
        response_model=SanityCheckResult,
        response_schema=_RESPONSE_SCHEMA,
        prompt=JUDGE_PROMPT,
        user_content=user_content,
        log_id=log_id,
        pass_label="sanity_check",
        # A compact JSON payload plus a list of flags - no document to read,
        # so this does not need the primary model's context window.
        use_helper_model=True,
    )
