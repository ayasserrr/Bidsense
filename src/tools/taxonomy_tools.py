"""The LLM fallback for categorising line items.

Most rows never reach it: an exact alias hit or a fuzzy one resolves them
first, and only what survives both is batched into a single call. That ordering
is the point - a 36-row bill of quantities should cost one gateway request to
categorise, not 36.
"""

import json

from langchain_core.tools import tool

from helpers.llm_runnable import build_response_schema
from schema.taxonomy import TaxonomyResolutionResult

from ._common import build_system_human_prompt, run_tool_call

TAXONOMY_SYSTEM_PROMPT = """You are sorting the line items of a supplier offer into a fixed engineering taxonomy. You are given the list of allowed categories and a numbered list of item descriptions. For each item, say which category it belongs to.

The categories are two levels: ten disciplines (Electrical, HVAC, Plumbing, Fire Fighting Systems, Light Current Systems, Automation, Civil Works, Architecture, Training, Certification) and the equipment types under each of them. Always prefer the most specific category that clearly fits. If an item plainly belongs to a discipline but to none of its equipment types - a general "electrical works" line, say - use the discipline's own code.

Return `node_code: null` when the description genuinely does not say what the item is: a bare "as per attached specification", a lump-sum line, a discount row, a freight charge. An unresolved item is visibly unresolved and a reviewer can fix it in seconds; a confidently wrong one silently corrupts the report that reads from it. Null is the better answer whenever you are not sure.

Set `confidence` honestly between 0.0 and 1.0. Anything below 0.6 is discarded by the caller, so an uncertain guess costs nothing - but an overconfident wrong one does.

Judge only from the words in front of you. Do not infer a discipline from the supplier's name or from what the rest of the offer is about: a UPS supplier really does sometimes quote a concrete plinth, and that line is Civil Works."""

_RESPONSE_SCHEMA = build_response_schema(TaxonomyResolutionResult)
RESOLVE_PROMPT = build_system_human_prompt(TAXONOMY_SYSTEM_PROMPT)


@tool
async def resolve_item_categories(items_json: str, categories_json: str, log_id: str) -> str:
    """Assigns a taxonomy node to each item that alias matching could not place.

    `items_json` is a JSON array of `{ref, description, equipment_type, model}`;
    `categories_json` a JSON array of `{code, label, discipline}`. Returns a
    packed JSON string with a validated `TaxonomyResolutionResult` and
    `repair_attempts` telemetry.
    """
    items = json.loads(items_json)
    categories = json.loads(categories_json)

    categories_text = "\n".join(
        f"- {entry['code']}: {entry['discipline']} > {entry['label']}"
        if entry.get("discipline")
        else f"- {entry['code']}: {entry['label']} (discipline)"
        for entry in categories
    )
    items_text = "\n".join(
        "- "
        + entry["ref"]
        + ": "
        + entry["description"]
        + (f" | equipment type: {entry['equipment_type']}" if entry.get("equipment_type") else "")
        + (f" | model: {entry['model']}" if entry.get("model") else "")
        for entry in items
    )
    user_content = (
        "ALLOWED CATEGORIES:\n" + categories_text + "\n\n---\n\nITEMS TO CATEGORISE:\n" + items_text
    )

    return await run_tool_call(
        response_model=TaxonomyResolutionResult,
        response_schema=_RESPONSE_SCHEMA,
        prompt=RESOLVE_PROMPT,
        user_content=user_content,
        log_id=log_id,
        pass_label="taxonomy_resolve",
        # A compact list of short descriptions, not a document - the helper
        # model is the right size for this.
        use_helper_model=True,
    )
