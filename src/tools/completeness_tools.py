"""The LLM half of the completeness checker.

One call per excerpt of the offer, run concurrently. Each call sees the whole
checklist and one slice of the source, and says only what THAT slice states;
`CompletenessController` reconciles the slices afterwards. Splitting it this way
is what makes the client's hardest requirement structural rather than hopeful -
a requirement is only ever reported missing after every slice of every file has
been asked about it, because "missing" is what is left when no slice found it.
"""

import json

from langchain_core.tools import tool

from helpers.llm_runnable import build_response_schema
from schema.completeness import CompletenessScanResult

from ._common import build_system_human_prompt, run_tool_call

COMPLETENESS_SYSTEM_PROMPT = """You are auditing a supplier's offer for COMPLETENESS. You are not summarising the offer and you are not extracting all of its data - you are answering one question about each item on a fixed checklist: does this offer actually state it?

You will be given a checklist and an excerpt of the offer's source text. The excerpt may be one part of a longer document, and the offer may be split across several files (a commercial quotation, a technical datasheet, a bill of quantities). Judge ONLY what is in the excerpt in front of you. If the excerpt says nothing about a requirement, leave that requirement out of your answer entirely - another excerpt may state it, and the parts are reconciled afterwards. Do NOT report a requirement as missing merely because this particular excerpt is silent about it.

For each requirement the excerpt DOES address, return one finding with:

- `requirement_code`: copy it exactly from the checklist. Never invent a code.
- `verdict`:
  - `present` - the excerpt states it clearly enough for a reviewer to act on.
  - `unclear` - the excerpt touches the subject but does not pin it down (e.g. "delivery as agreed", "warranty as per manufacturer" with no duration).
  - `not_applicable` - the requirement plainly does not apply to this kind of offer. A UPS quotation has nothing to say about Plumbing, and reporting that as a gap is wrong.
  - `missing` - the excerpt is about this subject and still fails to state it. Use this sparingly; silence is usually `not_applicable` or simply an omitted finding.
- `extracted_value`: the answer in as few words as possible - "CIF Alexandria", "30 days", "24 months from commissioning", "50% advance / 50% before shipment". Null unless the verdict is `present`.
- `evidence_quote`: the sentence or table row that states it, copied VERBATIM - character for character, same spacing, same language, no tidying, no translation, no ellipsis. This quote is looked up in the source text mechanically to determine which file and page it came from. A paraphrased quote cannot be found and the finding loses its source. Null when you found nothing.
- `reasoning`: one short sentence a reviewer can check.

RULES THAT MATTER, in the client's own terms:

1. **Delivery Term.** CIF, DDP, Ex-Works and Ex-Factory are the terms normally seen, but ANY Incoterms 2020 term counts as present - EXW, FCA, CPT, CIP, DAP, DPU, DDP, FAS, FOB, CFR, CIF. Do NOT report a gap just because the offer used a term that is not one of the common four. Report a gap only when no delivery term is stated at all.

2. **Delivery Term is not Delivery Lead Time.** "CIF Alexandria" says where and on whose account, not when. "8 weeks from PO" says when, not on what terms. They are two separate checklist rows and an offer very often states one and not the other. A per-row "Availability"/"Delivery time" column in a pricing table IS a lead time - but only when it says how long or by when. "Ex-stock", "Based on the available stock" and "Subject to prior sale" say where the goods are and commit to no date; they are NOT a lead time.

3. **Currency must be NAMED.** A code ("USD", "EGP") or a word ("Dollars", "Egyptian Pounds") is present. A bare currency symbol is NOT - it does not distinguish US, Canadian or Australian dollars. An offer that only ever prints a symbol has genuinely left the currency open; mark it `unclear`.

4. **VAT silence is a real gap.** Prices printed with nothing said about tax is one of the most commonly missed terms and exactly what this check exists to catch. Do not assume prices exclude VAT because that is usual - if the offer does not say, it is missing.

5. **The ten technical disciplines are scope questions.** `present` means this offer contains scope belonging to that discipline - a priced line item, a technical section, a named system. Use the line items as your main evidence. `not_applicable` means this offer's subject has nothing to do with that discipline. Only use `missing` when the offer is clearly about that discipline and still fails to describe it. An offer that explicitly EXCLUDES a discipline ("our offer doesn't include any civil work", "electrical works by others") does NOT cover it: answer `not_applicable` and quote the exclusion sentence. Never read an exclusion as `present` on a discipline row - a reviewer who sees "Civil Works: stated" concludes the supplier is doing the foundations when the offer says in writing that they are not.

6. **Installation, Spare Parts, Maintenance and Training** are answered by an explicit inclusion, an explicit exclusion, or a priced line. An offer that says "installation excluded" has ANSWERED the question - that is `present` with the value "excluded", not a gap. A gap is when the offer never mentions it at all. This rule applies ONLY to those four checklist rows (COM_INSTALLATION, COM_SPARE_PARTS, COM_MAINTENANCE, TECH_TRAINING) and never to the other nine discipline rows, which are governed by rule 5 above.

7. **`not_applicable` is never an answer for a commercial term.** Every offer has a price, a currency, a delivery, a validity. If a commercial requirement (the COM_ rows) is not stated, that is `missing` - a gap the reviewer has to chase - not "does not apply". Reserve `not_applicable` for the technical disciplines.

8. **Quote what the document says, never what you expect it to say.** If you cannot find a verbatim quote, do not produce a finding for that requirement."""


def build_scan_schema(requirement_codes: list[str]) -> dict:
    """The response schema with the allowed requirement codes baked in.

    The checklist lives in a table an admin can edit, so the set of valid codes
    is only known at runtime - hence building the schema here rather than at
    import time. Constraining `requirement_code` to an enum lets guided decoding
    rule out an invented code before it is ever emitted; the controller still
    drops unknown codes afterwards, because the schema is guidance and the
    reconciliation is the guarantee.
    """
    schema = build_response_schema(CompletenessScanResult)
    finding = schema.get("$defs", {}).get("CompletenessScanFinding")
    if finding:
        properties = finding.get("properties", {})
        if requirement_codes and "requirement_code" in properties:
            properties["requirement_code"]["enum"] = list(requirement_codes)
        # Force every finding field required too, which `build_response_schema`
        # deliberately does NOT do for nested objects. The reason it holds back
        # there is a 36-row bill of quantities, where forcing each item's
        # twenty-odd fields multiplies output length and risks truncation. This
        # list is at most one entry per checklist row, and the fields being
        # skipped would be exactly the ones that carry the answer - the quote
        # and the value. Cheap here, load-bearing here.
        if properties:
            finding["required"] = list(properties.keys())
    return schema


@tool
async def scan_excerpt_for_requirements(
    excerpt: str, checklist_json: str, log_id: str, pass_label: str
) -> str:
    """Judges one excerpt of an offer against the completeness checklist.

    `checklist_json` is a JSON array of `{code, group, label, description}`.
    Returns a packed JSON string with a validated `CompletenessScanResult` and
    `repair_attempts` telemetry. Call once per excerpt; the caller reconciles.
    """
    checklist = json.loads(checklist_json)
    checklist_text = "\n".join(
        f"- {entry['code']} [{entry['group']}] {entry['label']}: {entry['description']}"
        for entry in checklist
    )
    user_content = (
        "CHECKLIST:\n"
        + checklist_text
        + "\n\n---\n\nOFFER SOURCE TEXT (one excerpt - other parts of this offer exist "
        "and are checked separately):\n"
        + excerpt
    )

    return await run_tool_call(
        response_model=CompletenessScanResult,
        response_schema=build_scan_schema([entry["code"] for entry in checklist]),
        prompt=build_system_human_prompt(COMPLETENESS_SYSTEM_PROMPT),
        user_content=user_content,
        log_id=log_id,
        pass_label=pass_label,
        # Reads a document excerpt, so it needs the primary model's context
        # window and its stronger reading - not the helper.
        use_helper_model=False,
    )
