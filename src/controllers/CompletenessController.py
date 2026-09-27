import asyncio
import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from helpers.commercial_terms import (
    SCOPE_SUBJECTS,
    currency_is_named,
    derive_scope_answer,
    normalize_incoterm,
    normalize_vat_status,
    states_lead_time,
)
from helpers.completeness_checklist import CHECKLIST
from helpers.extraction_merge import chunk_pages
from helpers.offer_events import (
    record_completeness_override_cleared,
    record_completeness_overridden,
)
from helpers.source_index import SourceIndex
from helpers.source_text import build_indexed_page_text, get_offer_documents, get_ordered_pages
from models.db_schema import (
    CompletenessEvidence,
    CompletenessRequirement,
    Document,
    IncludedFeature,
    InclusionExclusion,
    Offer,
    OfferCompletenessResult,
    OfferItem,
    User,
)
from models.enums import CompletenessVerdict, EntityType, RequirementGroup, ScopeAnswer
from schema.completeness import CompletenessScanResult
from tools import scan_excerpt_for_requirements
from tools._common import unpack_result

from .BaseController import BaseController

logger = logging.getLogger(__name__)

# (excerpts_completed, excerpts_total)
ScanProgressCallback = Callable[[int, int], Awaitable[None]]

# Which answer wins when two excerpts of the same offer disagree. A chunk that
# found the term beats one that did not, and "the subject came up but was not
# pinned down" beats "this does not apply" - because it demonstrably does.
_VERDICT_RANK: dict[str, int] = {
    CompletenessVerdict.PRESENT.value: 4,
    CompletenessVerdict.UNCLEAR.value: 3,
    CompletenessVerdict.NOT_APPLICABLE.value: 2,
    CompletenessVerdict.MISSING.value: 1,
}

# Which checklist row each scope question answers.
_SCOPE_REQUIREMENTS: dict[str, str] = {
    "installation": "COM_INSTALLATION",
    "spare_parts": "COM_SPARE_PARTS",
    "maintenance": "COM_MAINTENANCE",
    "training": "TECH_TRAINING",
}

# An offer refusing a discipline, in the words offers actually use. Reading one
# of these as coverage is the most commercially dangerous mistake this checker
# can make: a reviewer who sees "Civil Works: stated" concludes the supplier is
# pouring the plinths, when the offer expressly says they are not.
_EXCLUSION_WORDING = re.compile(
    r"\bdo(?:es)?\s?n[o'’]?t\s+(?:include|cover)\b"
    r"|\bnot\s+include[d]?\b"
    r"|\bexclude[sd]?\b|\bexcluding\b|\bexclusive\s+of\b|\bexclusion[s]?\b"
    r"|\bout\s+of\s+(?:our\s+)?scope\b"
    r"|\bnot\s+(?:in|within|part\s+of)\s+(?:our\s+)?scope\b"
    r"|\bby\s+(?:others|client|customer|owner)\b",
    re.I,
)

# ...but the exclusion has to govern the whole claim before it can cancel a
# discipline. Offers routinely state scope and then carve one sub-item out of
# it - "HVAC supply and installation included; ductwork insulation not
# included" - and reading that as a refusal of HVAC loses coverage the offer
# plainly gives. Two things disqualify a match:
#   - an inclusion stated BEFORE it, because what follows is being carved out of
#     that scope rather than refusing it;
#   - an exclusion whose object is money rather than work. "Prices are exclusive
#     of VAT" is a tax statement and says nothing about any discipline, but it
#     reads to the regex exactly like one.
# What it deliberately does NOT do is decide whether the excluded thing belongs
# to the discipline being judged; that needs the discipline's own vocabulary,
# so "Supply of all light current systems; cabling containment not included"
# still reads as a refusal. Under-reporting coverage is the safe direction here:
# a priced line item in the discipline overturns it through
# `_apply_discipline_evidence`, which runs after this.
_INCLUSION_WORDING = re.compile(
    r"\binclude[sd]?\b|\bincluding\b|\binclusive\b|\bcovered\b|\bprovided\b"
    r"|\b(?:in|within)\s+(?:our\s+)?scope\b",
    re.I,
)
_MONEY_OBJECT = re.compile(
    r"^\W*(?:the\s+|any\s+|all\s+)?(?:vat|tax|taxes|duties|customs|prices?|charges)\b",
    re.I,
)


def _exclusion_governs(claim: str) -> bool:
    """Whether anything in `claim` refuses the claim as a whole."""
    for match in _EXCLUSION_WORDING.finditer(claim):
        if _INCLUSION_WORDING.search(claim[: match.start()]):
            continue
        if _MONEY_OBJECT.match(claim[match.end() :]):
            continue
        return True
    return False


class OfferHasNoSourceTextError(Exception):
    def __init__(self, offer_id: int):
        self.offer_id = offer_id
        super().__init__(f"Offer {offer_id} has no parsed source text to check")


@dataclass
class _Finding:
    """One reconciled answer, before it becomes a database row."""

    verdict: str
    extracted_value: str | None = None
    normalized_value: str | None = None
    evidence_quote: str | None = None
    reasoning: str | None = None
    source_document_id: uuid.UUID | None = None
    source_filename: str | None = None
    source_page_number: int | None = None


@dataclass
class _OfferFacts:
    """What the saved offer says, in the shape the deterministic readers expect.

    Read from the database rather than from the in-memory extraction payload,
    deliberately: a check run inside the pipeline and a check re-run three days
    later then judge exactly the same facts - the ones that were actually saved.
    """

    incoterm: str | None = None
    delivery_terms_original: str | None = None
    payment_terms_original: str | None = None
    validity_terms_original: str | None = None
    warranty_terms_original: str | None = None
    tax_treatment_original: str | None = None
    price_currency_original: str | None = None
    currency_primary: str | None = None
    grand_total: float | None = None
    lead_times: list[str] = field(default_factory=list)
    items: list = field(default_factory=list)
    included_features: list = field(default_factory=list)
    inclusions_exclusions: list = field(default_factory=list)


class CompletenessController(BaseController):
    """Answers the client's real question: what does this offer NOT say?

    The shape of the work is what makes the hardest requirement - "search every
    file before declaring anything missing" - structural rather than something
    the model has to remember. Every excerpt of every file is asked about every
    requirement, concurrently; a requirement is reported missing only because no
    excerpt found it. Nothing is asked to prove a negative.

    Runs strictly AFTER persist, never as part of it. A failure here therefore
    costs a re-run of a check, not an offer.
    """

    def __init__(self, db: AsyncSession):
        super().__init__()
        self.db = db

    # --- checklist ---------------------------------------------------------

    async def seed_requirements(self) -> int:
        """Writes any checklist row that is not in the table yet.

        Insert-only on purpose. An admin's edit to a label, description or
        mandatory flag lives in the database and must survive a restart, so
        this never updates an existing row - it only fills in what a new
        deployment is missing.
        """
        existing = set(
            (await self.db.execute(select(CompletenessRequirement.code))).scalars().all()
        )
        added = 0
        for entry in CHECKLIST:
            if entry.code in existing:
                continue
            self.db.add(
                CompletenessRequirement(
                    code=entry.code,
                    requirement_group=entry.group.value,
                    label=entry.label,
                    description=entry.description,
                    is_mandatory=entry.is_mandatory,
                    is_active=True,
                    sort_order=entry.sort_order,
                )
            )
            added += 1
        if added:
            await self.db.commit()
        return added

    async def get_active_requirements(self) -> list[CompletenessRequirement]:
        result = await self.db.execute(
            select(CompletenessRequirement)
            .where(CompletenessRequirement.is_active.is_(True))
            .order_by(CompletenessRequirement.sort_order, CompletenessRequirement.code)
        )
        return list(result.scalars().all())

    # --- the check itself --------------------------------------------------

    async def check_offer(
        self,
        offer_id: int,
        on_progress: ScanProgressCallback | None = None,
    ) -> list[OfferCompletenessResult]:
        """The whole check: read every excerpt, then judge what it found against
        the saved offer.

        The shape for a caller with nothing else to do while it runs - a
        re-check from the offer page. A pipeline run calls the two halves
        separately (`pipeline/prescan.py`), because only the second half has to
        wait for anything.
        """
        scans = await self.scan_offer(offer_id, on_progress=on_progress)
        return await self.reconcile_and_save(offer_id, scans)

    async def scan_offer(
        self,
        offer_id: int,
        on_progress: ScanProgressCallback | None = None,
    ) -> list[CompletenessScanResult]:
        """Ask the model about every excerpt of every file.

        The half that needs nothing but parsed pages - which exist the moment
        the parse stage ends. Nothing extraction, persist or taxonomy produces
        is read here, which is exactly why this can run beside them instead of
        after them.

        What comes back is plain schema objects and nothing bound to this
        session. That is what lets the answers outlive it: the scan runs in its
        own session, closed well before the reconciliation reads them.
        """
        requirements = await self.get_active_requirements()
        if not requirements:
            logger.warning("completeness offer_id=%s skipped - no active requirements", offer_id)
            return []

        documents = await get_offer_documents(self.db, offer_id)
        filenames = {doc["document_id"]: doc["filename"] for doc in documents}
        pages = await self._offer_pages(documents)
        if not pages:
            raise OfferHasNoSourceTextError(offer_id)

        chunks = chunk_pages(
            pages,
            max_pages=self.app_settings.EXTRACTION_MAX_PAGES_PER_CHUNK,
            overlap=self.app_settings.EXTRACTION_CHUNK_PAGE_OVERLAP,
        )
        checklist_json = json.dumps(
            [
                {
                    "code": requirement.code,
                    "group": requirement.requirement_group,
                    "label": requirement.label,
                    "description": requirement.description,
                }
                for requirement in requirements
            ]
        )

        return await self._scan_chunks(
            offer_id=offer_id,
            chunks=chunks,
            filenames=filenames,
            checklist_json=checklist_json,
            on_progress=on_progress,
        )

    async def reconcile_and_save(
        self, offer_id: int, scans: list[CompletenessScanResult]
    ) -> list[OfferCompletenessResult]:
        """Turn the excerpts' answers into one verdict per requirement, judged
        against what was actually saved.

        The half that has to wait, and why the stage is where it is in the
        graph: `_load_offer_facts` reads the offer and its items, so it needs
        persist, and `_apply_discipline_evidence` reads the taxonomy node each
        item resolved to, so it needs taxonomy.

        Re-reads the requirements and the pages rather than being handed them by
        the scan. They are ORM rows, the scan ran in a session that is closed by
        now, and a detached row read here would raise long after the thing that
        actually caused it.
        """
        requirements = await self.get_active_requirements()
        if not requirements:
            return []

        documents = await get_offer_documents(self.db, offer_id)
        filenames = {doc["document_id"]: doc["filename"] for doc in documents}
        # One index over the WHOLE offer - every file, every page. Quotes are
        # located in this, not in the excerpt they came from, so a quote is
        # attributed to its real file even though the model only ever saw a
        # slice.
        index = build_indexed_page_text(await self._offer_pages(documents), filenames)

        valid_codes = {requirement.code for requirement in requirements}
        findings = self._reconcile(scans, valid_codes)

        facts = await self._load_offer_facts(offer_id)
        self._apply_deterministic_answers(findings, facts)
        # Ordering matters here. An exclusion sentence is struck down as
        # evidence of coverage BEFORE the line items get their say, so that a
        # priced item in that discipline - the one thing that really does prove
        # coverage - can still overturn it in `_apply_discipline_evidence`.
        self._settle_discipline_exclusions(findings, requirements)
        await self._apply_discipline_evidence(offer_id, findings, valid_codes)
        self._deny_not_applicable_on_mandatory(findings, requirements)
        self._fill_unanswered(findings, requirements, source_text_read=bool(scans))
        self._attribute_sources(findings, index, filenames)

        return await self._save(offer_id, findings, requirements)

    async def _offer_pages(self, documents: list[dict]) -> list:
        pages = []
        for document in documents:
            pages.extend(await get_ordered_pages(self.db, document["document_id"]))
        return pages

    async def _scan_chunks(
        self,
        *,
        offer_id: int,
        chunks: list,
        filenames: dict,
        checklist_json: str,
        on_progress: ScanProgressCallback | None,
    ) -> list[CompletenessScanResult]:
        """One model call per excerpt, all in flight together.

        Bounded by LLM_MAX_CONCURRENT_REQUESTS inside the transport, which every
        stage shares - so a fifteen-chunk offer cannot flood the gateway, and a
        three-chunk one finishes in roughly the time of its slowest chunk.
        """
        total = len(chunks)
        completed = 0
        lock = asyncio.Lock()

        async def scan(position: int, chunk) -> CompletenessScanResult | None:
            nonlocal completed
            excerpt = build_indexed_page_text(chunk, filenames).text
            try:
                raw = await scan_excerpt_for_requirements.ainvoke(
                    {
                        "excerpt": excerpt,
                        "checklist_json": checklist_json,
                        "log_id": str(offer_id),
                        "pass_label": f"completeness_{position + 1}of{total}",
                    }
                )
                result, _telemetry = unpack_result(raw, CompletenessScanResult)
            except Exception as exc:
                # One excerpt failing must not lose the other fourteen. It is
                # recorded and skipped: the cost is that anything only stated in
                # THIS excerpt may be reported as a gap, which is the safe
                # direction to fail - a false "missing" gets questioned, a false
                # "present" does not.
                logger.warning(
                    "completeness offer_id=%s excerpt=%s/%s failed: %s",
                    offer_id, position + 1, total, exc,
                )
                result = None
            if on_progress is not None:
                async with lock:
                    completed += 1
                    await on_progress(completed, total)
            return result

        tasks = [asyncio.create_task(scan(position, chunk)) for position, chunk in enumerate(chunks)]
        try:
            results = await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        return [result for result in results if result is not None]

    @staticmethod
    def _reconcile(
        scans: list[CompletenessScanResult], valid_codes: set[str]
    ) -> dict[str, _Finding]:
        """Merges the excerpts' answers into one answer per requirement.

        Unknown codes are dropped rather than trusted - the schema constrains
        them but the reconciliation is what guarantees it, and an unknown code
        would otherwise violate the unique constraint or create a phantom row.
        """
        best: dict[str, _Finding] = {}
        for scan in scans:
            for finding in scan.findings:
                code = (finding.requirement_code or "").strip()
                if code not in valid_codes:
                    continue
                verdict = finding.verdict.value
                candidate = _Finding(
                    verdict=verdict,
                    extracted_value=(finding.extracted_value or "").strip() or None,
                    evidence_quote=(finding.evidence_quote or "").strip() or None,
                    reasoning=(finding.reasoning or "").strip() or None,
                )
                current = best.get(code)
                if current is None:
                    best[code] = candidate
                    continue
                new_rank = _VERDICT_RANK.get(verdict, 0)
                old_rank = _VERDICT_RANK.get(current.verdict, 0)
                if new_rank > old_rank:
                    best[code] = candidate
                elif new_rank == old_rank and not current.evidence_quote and candidate.evidence_quote:
                    # Same verdict, but this one can prove it.
                    best[code] = candidate
        return best

    async def _load_offer_facts(self, offer_id: int) -> _OfferFacts:
        offer = await self.db.get(Offer, offer_id)
        if offer is None:
            return _OfferFacts()

        items = list(
            (
                await self.db.execute(
                    select(OfferItem).where(OfferItem.offer_id == offer_id).order_by(OfferItem.sort_order)
                )
            )
            .scalars()
            .all()
        )
        # `included_features` and `inclusions_exclusions` are polymorphic on
        # (entity_type, entity_id) rather than carrying an offer_id: an entry
        # belongs either to the offer or to one of its items. Both matter here -
        # "installation included" is as often written against a single line as
        # against the whole offer - so item-level rows are fetched by item id.
        item_ids = [item.item_id for item in items]
        feature_scope = [
            (IncludedFeature.entity_type == EntityType.OFFER.value)
            & (IncludedFeature.entity_id == offer_id)
        ]
        if item_ids:
            feature_scope.append(
                (IncludedFeature.entity_type == EntityType.ITEM.value)
                & (IncludedFeature.entity_id.in_(item_ids))
            )
        features = list(
            (await self.db.execute(select(IncludedFeature).where(or_(*feature_scope))))
            .scalars()
            .all()
        )
        # Read at item level as well as offer level, exactly like the features
        # above. "Installation excluded" is as often written against a single
        # line as against the whole offer, and a rule that only ever looked at
        # the offer-level list left those sentences to the model alone.
        entry_scope = [
            (InclusionExclusion.entity_type == EntityType.OFFER.value)
            & (InclusionExclusion.entity_id == offer_id)
        ]
        if item_ids:
            entry_scope.append(
                (InclusionExclusion.entity_type == EntityType.ITEM.value)
                & (InclusionExclusion.entity_id.in_(item_ids))
            )
        entries = list(
            (await self.db.execute(select(InclusionExclusion).where(or_(*entry_scope))))
            .scalars()
            .all()
        )

        return _OfferFacts(
            incoterm=offer.incoterm,
            delivery_terms_original=offer.delivery_terms_original,
            payment_terms_original=offer.payment_terms_original,
            validity_terms_original=offer.validity_terms_original,
            warranty_terms_original=offer.warranty_terms_original,
            tax_treatment_original=offer.tax_treatment_original,
            price_currency_original=offer.price_currency_original,
            currency_primary=offer.currency_primary,
            grand_total=float(offer.grand_total) if offer.grand_total is not None else None,
            # A per-row "Availability"/"Delivery time" column IS a lead time, and
            # is often the only place one appears - there is no offer-level field
            # for it.
            lead_times=[
                item.availability_original_text
                for item in items
                if (item.availability_original_text or "").strip()
            ],
            items=items,
            included_features=features,
            inclusions_exclusions=entries,
        )

    @staticmethod
    def _apply_deterministic_answers(
        findings: dict[str, _Finding], facts: _OfferFacts
    ) -> None:
        """Overrules the model where a rule can settle it.

        Only ever upgrades a verdict to `present`, with one deliberate
        exception: a currency the offer never actually named is downgraded,
        because accepting a bare symbol is the specific mistake the client
        called out.

        `settles_unclear` is the difference between a rule and a field. A rule
        that READ the text - this string is Incoterm CIF, this wording means VAT
        exclusive - may overrule the model's `unclear`, because it has actually
        decided the question. A saved field that merely holds some text may not:
        extraction files "warranty as per manufacturer" in `warranty_terms` just
        as readily as "24 months from commissioning", and the first one is
        exactly what `unclear` is for. Treating any non-empty field as an answer
        made the Warranty Duration row unflaggable.
        """

        def upgrade(
            code: str,
            value: str | None,
            normalized: str | None,
            why: str,
            *,
            settles_unclear: bool = False,
        ) -> None:
            if not value:
                return
            current = findings.get(code)
            if current is not None and current.verdict == CompletenessVerdict.PRESENT.value:
                # Keep the model's quote - it is real evidence from the source -
                # but let the normalised reading stand.
                current.normalized_value = current.normalized_value or normalized
                current.extracted_value = current.extracted_value or value
                return
            if (
                current is not None
                and current.verdict == CompletenessVerdict.UNCLEAR.value
                and not settles_unclear
            ):
                # The model read the sentence and judged it too vague to act on.
                # A field holding that same vague sentence is not a second
                # opinion - keep the value, keep the verdict.
                current.extracted_value = current.extracted_value or value
                current.normalized_value = current.normalized_value or normalized
                return
            findings[code] = _Finding(
                verdict=CompletenessVerdict.PRESENT.value,
                extracted_value=value,
                normalized_value=normalized,
                evidence_quote=current.evidence_quote if current else None,
                reasoning=why,
            )

        # Both fields are tried, not just the first. `incoterm` is extraction's
        # mapped reading and `delivery_terms_original` the sentence it came
        # from; when the mapped value is something unrecognised, the sentence
        # itself may still name the term plainly.
        for delivery_text in (facts.incoterm, facts.delivery_terms_original):
            incoterm = normalize_incoterm(delivery_text)
            if incoterm:
                upgrade(
                    "COM_DELIVERY_TERM",
                    (delivery_text or "").strip(),
                    incoterm,
                    "Recognised as Incoterms 2020 term " + incoterm + " in the saved offer.",
                    settles_unclear=True,
                )
                break

        upgrade(
            "COM_PAYMENT_TERMS",
            (facts.payment_terms_original or "").strip(),
            None,
            "Stated in the saved offer's payment terms.",
        )
        upgrade(
            "COM_VALIDITY",
            (facts.validity_terms_original or "").strip(),
            None,
            "Stated in the saved offer's validity terms.",
        )
        upgrade(
            "COM_WARRANTY",
            (facts.warranty_terms_original or "").strip(),
            None,
            "Stated in the saved offer's warranty terms.",
        )

        vat_status = normalize_vat_status(facts.tax_treatment_original)
        if vat_status:
            upgrade(
                "COM_VAT_STATUS",
                (facts.tax_treatment_original or "").strip(),
                vat_status,
                "Tax treatment read as " + vat_status + ".",
                settles_unclear=True,
            )

        # Only the availability entries that actually say WHEN. The column is
        # just as often a stock condition ("Ex-stock", "Based on the available
        # stock"), which says where the goods are and commits to no date.
        stated_lead_times = [text for text in facts.lead_times if states_lead_time(text)]
        if stated_lead_times:
            upgrade(
                "COM_DELIVERY_LEAD_TIME",
                "; ".join(dict.fromkeys(stated_lead_times))[:500],
                None,
                "Taken from the per-item availability/lead-time column.",
            )

        for subject in SCOPE_SUBJECTS:
            answer = derive_scope_answer(facts, subject)
            if answer is ScopeAnswer.UNSPECIFIED:
                continue
            upgrade(
                _SCOPE_REQUIREMENTS[subject],
                answer.value,
                answer.value,
                "Answered by the offer's own items and inclusion/exclusion list.",
                # A categorised line item or an explicit inclusion/exclusion
                # entry is a definite statement, not a vague one.
                settles_unclear=True,
            )

        CompletenessController._settle_currency(findings, facts)

    @staticmethod
    def _settle_currency(findings: dict[str, _Finding], facts: _OfferFacts) -> None:
        """The client's rule: a currency counts only when NAMED."""
        code = "COM_CURRENCY"
        named = currency_is_named(facts.price_currency_original, facts.currency_primary)
        current = findings.get(code)
        if named:
            findings[code] = _Finding(
                verdict=CompletenessVerdict.PRESENT.value,
                extracted_value=(facts.price_currency_original or "").strip(),
                normalized_value=facts.currency_primary,
                evidence_quote=current.evidence_quote if current else None,
                reasoning="Currency is named in the offer.",
            )
            return
        if current is None or current.verdict != CompletenessVerdict.PRESENT.value:
            return
        # The model called it present. Accept that only if what it quoted names
        # a currency rather than printing a symbol.
        claimed = current.extracted_value or ""
        if sum(1 for char in claimed if char.isalpha()) >= 3:
            return
        current.verdict = CompletenessVerdict.UNCLEAR.value
        current.reasoning = (
            "The offer prices are shown with a currency symbol but no named currency "
            "(a code such as USD/EGP, or the currency spelled out), so which currency "
            "is meant is not established."
        )

    async def _apply_discipline_evidence(
        self, offer_id: int, findings: dict[str, _Finding], valid_codes: set[str]
    ) -> None:
        """A priced line item in a discipline is the strongest possible evidence
        that the offer covers it - stronger than any sentence about it.

        This is why the taxonomy roots share their codes with the ten technical
        requirements: the bill of quantities answers the technical half of the
        checklist directly.
        """
        rows = (
            await self.db.execute(
                select(OfferItem.taxonomy_node_id, OfferItem.description)
                .where(OfferItem.offer_id == offer_id)
                .where(OfferItem.taxonomy_node_id.is_not(None))
            )
        ).all()
        if not rows:
            return

        from models.db_schema import TaxonomyNode

        node_ids = {row[0] for row in rows}
        nodes = {
            node.node_id: node
            for node in (
                await self.db.execute(select(TaxonomyNode).where(TaxonomyNode.node_id.in_(node_ids)))
            )
            .scalars()
            .all()
        }
        # Walk each resolved node up to its discipline root.
        roots: dict[str, list[str]] = {}
        for node_id, description in rows:
            node = nodes.get(node_id)
            while node is not None and node.parent_node_id is not None:
                parent = nodes.get(node.parent_node_id)
                if parent is None:
                    parent = await self.db.get(TaxonomyNode, node.parent_node_id)
                    if parent is not None:
                        nodes[parent.node_id] = parent
                node = parent
            if node is None or node.code not in valid_codes:
                continue
            roots.setdefault(node.code, []).append(description)

        for code, descriptions in roots.items():
            existing = findings.get(code)
            if existing is not None and existing.verdict == CompletenessVerdict.PRESENT.value:
                continue
            sample = "; ".join(descriptions[:3])
            findings[code] = _Finding(
                verdict=CompletenessVerdict.PRESENT.value,
                extracted_value=f"{len(descriptions)} item(s) in this discipline",
                normalized_value=None,
                evidence_quote=existing.evidence_quote if existing else None,
                reasoning=f"Priced line items belong to this discipline: {sample}"[:800],
            )

    @staticmethod
    def _settle_discipline_exclusions(
        findings: dict[str, _Finding], requirements: list[CompletenessRequirement]
    ) -> None:
        """An exclusion is not coverage - for the ten discipline rows.

        The four scope terms (Installation, Spare Parts, Maintenance, Training)
        ask "did the supplier answer this?", and there "excluded" is a perfectly
        good answer. The ten discipline rows ask a different question - "does
        this offer CONTAIN scope belonging to that discipline?" - and there an
        explicit exclusion is evidence of the opposite. The scan model
        generalises the first rule onto the second and reports Civil Works as
        `present` on the strength of "our offer doesn't include any civil work";
        nothing downstream could correct it, because `present` outranks every
        other verdict.

        The exclusion sentence is kept as the reasoning, so the reviewer still
        sees what the supplier actually said.
        """
        technical = {
            requirement.code
            for requirement in requirements
            if requirement.requirement_group == RequirementGroup.TECHNICAL.value
        }
        for code in technical:
            finding = findings.get(code)
            if finding is None or finding.verdict != CompletenessVerdict.PRESENT.value:
                continue
            claim = " ".join(filter(None, (finding.extracted_value, finding.evidence_quote)))
            if not claim or not _exclusion_governs(claim):
                continue
            finding.verdict = CompletenessVerdict.NOT_APPLICABLE.value
            quote = finding.evidence_quote or finding.extracted_value or ""
            finding.reasoning = (
                "The offer explicitly excludes this discipline, so it is not covered: " + quote
            )[:800]

    @staticmethod
    def _deny_not_applicable_on_mandatory(
        findings: dict[str, _Finding], requirements: list[CompletenessRequirement]
    ) -> None:
        """A required term cannot be "not applicable" to an offer.

        Every offer has a price, a currency, a delivery and a validity - that is
        why these ten rows are mandatory in the first place. The model is
        nevertheless free to answer `not_applicable` for anything, and because
        that verdict outranks `missing` when excerpts disagree, one excerpt
        saying "does not apply" was enough to turn a genuine gap into a grey
        N/A badge that is counted as no gap at all and flagged nowhere.
        """
        for requirement in requirements:
            if not requirement.is_mandatory:
                continue
            finding = findings.get(requirement.code)
            if finding is None or finding.verdict != CompletenessVerdict.NOT_APPLICABLE.value:
                continue
            finding.verdict = CompletenessVerdict.MISSING.value
            previous = f" (the check had read it as not applicable: {finding.reasoning})" if finding.reasoning else ""
            finding.reasoning = (
                "This term is required of every offer, so 'not applicable' is not an answer to "
                "it - the offer does not state it." + previous
            )[:800]

    @staticmethod
    def _fill_unanswered(
        findings: dict[str, _Finding],
        requirements: list[CompletenessRequirement],
        *,
        source_text_read: bool = True,
    ) -> None:
        """What to say about a requirement no excerpt addressed.

        The default follows the requirement's own mandatory flag, which is the
        same field the report flags on. A required term nobody stated is
        genuinely MISSING - that is the whole product. An optional one is
        NOT_APPLICABLE: a UPS quotation is not incomplete for having nothing to
        say about Plumbing, and ten false alarms would bury the real gaps. Keying
        this on the group instead meant an admin who marked a discipline
        mandatory got a row that defaulted to N/A and could never flag.

        `source_text_read` is not cosmetic. "Every file and page was checked" is
        a claim about work that was done; when no excerpt could be read at all,
        saying it anyway tells the reviewer the document was searched when it
        was not.
        """
        for requirement in requirements:
            if requirement.code in findings:
                continue
            if not requirement.is_mandatory:
                findings[requirement.code] = _Finding(
                    verdict=CompletenessVerdict.NOT_APPLICABLE.value,
                    reasoning="No scope belonging to this discipline appears anywhere in the offer.",
                )
            else:
                findings[requirement.code] = _Finding(
                    verdict=CompletenessVerdict.MISSING.value,
                    reasoning=(
                        "Not stated anywhere in the offer - every file and page was checked."
                        if source_text_read
                        else "Not stated in what could be read of this offer - none of its text "
                        "could be checked, so treat this as unverified rather than confirmed."
                    ),
                )

    @staticmethod
    def _attribute_sources(
        findings: dict[str, _Finding], index: SourceIndex, filenames: dict
    ) -> None:
        """Turns each quote into a real file and page, or into nothing.

        A quote that cannot be found in the source is dropped along with its
        attribution rather than being shown next to a guessed filename. The
        verdict survives - the model may well have read something real and
        paraphrased it - but the claim to a source does not.
        """
        for finding in findings.values():
            if not finding.evidence_quote:
                continue
            segment = index.locate(finding.evidence_quote)
            if segment is None:
                finding.evidence_quote = None
                continue
            finding.source_document_id = segment.document_id
            finding.source_filename = filenames.get(segment.document_id)
            finding.source_page_number = segment.page_number

    async def _save(
        self,
        offer_id: int,
        findings: dict[str, _Finding],
        requirements: list[CompletenessRequirement],
    ) -> list[OfferCompletenessResult]:
        """Upserts one row per requirement, leaving reviewer overrides alone.

        Deliberately not delete-and-reinsert. Re-running the check is the
        expected thing to do when a late technical file arrives, and wiping the
        rows would take every override - and its attached evidence - with it.
        """
        existing = {
            row.requirement_code: row
            for row in (
                await self.db.execute(
                    select(OfferCompletenessResult).where(
                        OfferCompletenessResult.offer_id == offer_id
                    )
                )
            )
            .scalars()
            .all()
        }
        now = datetime.now(timezone.utc)
        saved: list[OfferCompletenessResult] = []

        for requirement in requirements:
            finding = findings.get(requirement.code)
            if finding is None:
                continue
            row = existing.pop(requirement.code, None)
            if row is None:
                row = OfferCompletenessResult(offer_id=offer_id, requirement_code=requirement.code)
                self.db.add(row)

            row.requirement_label = requirement.label
            row.requirement_group = requirement.requirement_group
            row.was_mandatory = requirement.is_mandatory
            row.sort_order = requirement.sort_order
            row.verdict = finding.verdict
            row.extracted_value = finding.extracted_value
            row.normalized_value = finding.normalized_value
            row.evidence_quote = finding.evidence_quote
            row.source_document_id = finding.source_document_id
            row.source_filename = finding.source_filename
            row.source_page_number = finding.source_page_number
            row.reasoning = finding.reasoning
            row.checked_at = now
            saved.append(row)

        # Anything left in `existing` belongs to a requirement that has since
        # been deactivated. An overridden one is kept - a reviewer's correction
        # and its evidence outlive a checklist edit.
        for row in existing.values():
            if row.is_overridden:
                continue
            await self.db.delete(row)

        await self.db.commit()
        for row in saved:
            await self.db.refresh(row)
        logger.info(
            "completeness offer_id=%s wrote %s results (%s gaps)",
            offer_id,
            len(saved),
            sum(
                1
                for row in saved
                if row.effective_verdict
                in (CompletenessVerdict.MISSING.value, CompletenessVerdict.UNCLEAR.value)
                and row.was_mandatory
            ),
        )
        return saved

    # --- reading and overriding -------------------------------------------

    async def get_results(self, offer_id: int) -> list[OfferCompletenessResult]:
        result = await self.db.execute(
            select(OfferCompletenessResult)
            .where(OfferCompletenessResult.offer_id == offer_id)
            .order_by(OfferCompletenessResult.sort_order, OfferCompletenessResult.requirement_code)
        )
        return list(result.scalars().all())

    async def get_evidence(self, offer_id: int) -> list[CompletenessEvidence]:
        result = await self.db.execute(
            select(CompletenessEvidence)
            .where(CompletenessEvidence.offer_id == offer_id)
            .order_by(CompletenessEvidence.uploaded_at.desc())
        )
        return list(result.scalars().all())

    async def get_result(self, offer_id: int, requirement_code: str) -> OfferCompletenessResult | None:
        result = await self.db.execute(
            select(OfferCompletenessResult)
            .where(OfferCompletenessResult.offer_id == offer_id)
            .where(OfferCompletenessResult.requirement_code == requirement_code)
        )
        return result.scalar_one_or_none()

    async def get_evidence_file(
        self, offer_id: int, evidence_id: uuid.UUID
    ) -> CompletenessEvidence | None:
        result = await self.db.execute(
            select(CompletenessEvidence)
            .where(CompletenessEvidence.offer_id == offer_id)
            .where(CompletenessEvidence.evidence_id == evidence_id)
        )
        return result.scalar_one_or_none()

    async def apply_override(
        self,
        *,
        result: OfferCompletenessResult,
        verdict: str,
        value: str | None,
        note: str | None,
        evidence: CompletenessEvidence,
        user: User,
    ) -> OfferCompletenessResult:
        result.is_overridden = True
        result.override_verdict = verdict
        result.override_value = (value or "").strip() or None
        result.override_note = (note or "").strip() or None
        result.override_evidence_id = evidence.evidence_id
        result.overridden_by_user_id = user.id
        result.overridden_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(result)
        # "Yara Kamal corrected 'Warranty period' with an email". Recorded
        # after the commit, on its own transaction: a log line is not worth
        # losing a correction a reviewer had to go and get evidence for.
        await record_completeness_overridden(
            offer_id=result.offer_id,
            actor=user,
            requirement_label=result.requirement_label,
            requirement_code=result.requirement_code,
            verdict=verdict,
            evidence_filename=evidence.original_filename,
            evidence_kind=evidence.evidence_kind,
        )
        return result

    async def clear_override(
        self, result: OfferCompletenessResult, user: User | None = None
    ) -> OfferCompletenessResult:
        """Removes a correction, leaving the machine verdict showing again.

        The evidence file itself is kept. It was attached to this offer as a
        record of what was asked and answered, and deleting it because somebody
        changed their mind about one verdict would lose that.

        `user` is who is undoing it, for the activity log. Taking a correction
        away changes what the offer reports just as much as making one did, so
        it earns its own line rather than leaving the earlier "corrected ..."
        entry standing as though it were still true.
        """
        result.is_overridden = False
        result.override_verdict = None
        result.override_value = None
        result.override_note = None
        result.override_evidence_id = None
        result.overridden_by_user_id = None
        result.overridden_at = None
        await self.db.commit()
        await self.db.refresh(result)
        await record_completeness_override_cleared(
            offer_id=result.offer_id,
            actor=user,
            requirement_label=result.requirement_label,
            requirement_code=result.requirement_code,
        )
        return result

    async def document_filenames(self, offer_id: int) -> dict[uuid.UUID, str]:
        rows = (
            await self.db.execute(
                select(Document.document_id, Document.original_filename).where(
                    Document.offer_id == offer_id
                )
            )
        ).all()
        return {row[0]: row[1] for row in rows}
