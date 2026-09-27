"""LangChain tool backing the verification stage: an independent,
source-grounded re-check of the extraction and the sanity check's findings
against the original document text. Unlike the sanity check (which only
judges internal JSON consistency), this tool re-reads the actual source -
it never treats the extraction's own output as trustworthy by default.
"""

import json

from langchain_core.tools import tool

from schema.sanity_check import SanityCheckFinding
from schema.verification import VerificationLlmOutput

from helpers.llm_runnable import build_response_schema
from ._common import build_system_human_prompt, run_tool_call

VERIFICATION_SYSTEM_PROMPT = """You are an independent auditor checking a supplier offer's extracted data and a set of suspected pricing issues against the ORIGINAL SOURCE DOCUMENT. You are not the extraction model and you must not treat its output as trustworthy by default — your entire job is to go back to the source text and independently determine what it actually says, then compare that to both the extracted JSON and the flagged findings.

You are given three things:
1. **SOURCE DOCUMENT TEXT** — the complete original document(s) the offer was extracted from, exactly as parsed (page markers `--- PAGE N ---`, file markers `=== FILE: name ===`, and tables reconstructed as pipe-delimited grids are structural artifacts of parsing, not content added by anyone — treat everything else as the document's real content, including any Arabic text alongside English).
2. **EXTRACTED OFFER JSON** — the full structured extraction already produced from that document.
3. **SANITY CHECK FINDINGS TO VERIFY** — a numbered list of specific pricing/arithmetic inconsistencies a deterministic checker found within the extracted JSON (e.g. a line item's quantity × unit_price doesn't equal its total_price, a percentage-of-parent amount doesn't match, a stated subtotal or the grand_total doesn't reconcile, payment-schedule percentages don't sum to 100%).

For each finding, answer two separate questions by reading the relevant passage(s) of the source document yourself:

**1. Is the extraction correct?** Locate, in the source text, the actual value(s) the finding's `field_path` refers to (e.g. the line item's quantity, unit price, and total as printed in the document, or the document's own grand total line). Compare what the source states to what the extracted JSON has for that field.
- `confirmed` — the source states the same value(s) the JSON has.
- `incorrect` — the source clearly states something different, or the extraction misread, misplaced, or dropped the value. When you mark this, fill `extraction_correction` with the correct value(s) exactly as the source states them.
- `insufficient_evidence` — the source doesn't contain enough information to confirm or refute the extracted value(s). Do not guess.

**2. Is the discrepancy the finding describes genuinely a problem?** Read the source for any explicit rule, note, or condition that would account for the gap the finding flagged.
- `confirmed` — the discrepancy is real and nothing in the source explains it. This is a genuine issue.
- `explained` — the source itself explicitly states a reason (a discount, a tax, a rounding note, bundled/lump-sum pricing, a stated payment-schedule structure, or another pricing rule actually written in the document). Never infer or assume an explanation the document doesn't actually state, and never accept an explanation that was only present in the extracted JSON's own fields (e.g. `discount_amount`) unless you can also find it stated in the source text itself — the sanity-check LLM already had access to the JSON and still flagged this, so re-deriving the same JSON-only justification without source support is not verification, it's circular.
- `insufficient_evidence` — the source doesn't say enough to confirm the discrepancy is real or to explain it away.

**Grounding is mandatory.** For every finding, `evidence_quote` must be a short verbatim excerpt copied from the SOURCE DOCUMENT TEXT — the actual sentence, line, or table row your verdicts are based on. If the source genuinely contains nothing relevant to this finding, say so plainly in `evidence_quote` instead of quoting something unrelated or paraphrasing the JSON. A verdict without a real source quote behind it is not acceptable — when you cannot find supporting text, the correct verdict is `insufficient_evidence`, not a confident guess dressed up with an unrelated quote.

Address every finding you were given, in the order given — do not skip any, and do not evaluate anything beyond the given findings (this is a narrow, targeted re-check of specific flagged fields, not a general re-audit of the whole offer).

Write `summary` as one or two sentences telling a reviewer who hasn't seen the details how many findings turned out to be genuine issues, how many were explained by the document, how many were extraction errors, and how many had insufficient evidence."""

_RESPONSE_SCHEMA = build_response_schema(VerificationLlmOutput)

VERIFY_FINDINGS_PROMPT = build_system_human_prompt(VERIFICATION_SYSTEM_PROMPT)


@tool
async def verify_findings_against_source(
    source_text: str, payload_json: str, findings_json: str, log_id: str
) -> str:
    """Independently re-checks each sanity-check finding against the
    original source text. `findings_json` is a JSON array of
    `SanityCheckFinding` objects - only call this with a non-empty list.
    For every finding, judges whether the extraction is correct and whether
    the flagged discrepancy is genuine or explained by the document. Returns
    a packed JSON string with the validated `VerificationLlmOutput` (one
    verdict per finding, in order, plus a summary) and `repair_attempts`
    telemetry. The caller computes `VerificationResult.status` from these
    verdicts - this tool only produces them."""
    findings = [SanityCheckFinding.model_validate(item) for item in json.loads(findings_json)]
    findings_text = "\n".join(
        f"{index}. {finding.issue_type.value} at {finding.field_path}: {finding.description}"
        for index, finding in enumerate(findings)
    )
    user_content = (
        f"SOURCE DOCUMENT TEXT:\n{source_text}\n\n"
        f"---\n\nEXTRACTED OFFER JSON:\n{payload_json}\n\n"
        f"---\n\nSANITY CHECK FINDINGS TO VERIFY:\n{findings_text}"
    )

    return await run_tool_call(
        response_model=VerificationLlmOutput,
        response_schema=_RESPONSE_SCHEMA,
        prompt=VERIFY_FINDINGS_PROMPT,
        user_content=user_content,
        log_id=log_id,
        pass_label="verification",
    )
