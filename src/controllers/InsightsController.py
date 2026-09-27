"""The read-models behind the dashboard and the compare screen.

Both screens ask the same kind of question - "how do these offers stand?" - of
different numbers of offers, and both are read-only. They live together because
they share the rules that make the answers agree: what counts as a live offer,
what counts as in review, what counts as a gap, and how money in four
currencies is added up.

Two things this deliberately does NOT do:

* It does not call `PersistController.get_full_offer`. That reads roughly ten
  tables for one offer, which is the right shape for the detail page and
  exactly the wrong one here - three offers on the compare screen would be
  thirty queries for a dozen fields. Every query below is narrow, and none of
  them is per-offer: a comparison of twelve offers costs the same number of
  round trips as a comparison of two.
* It does not rank, score or recommend. The compare screen returns facts in the
  supplier's own words, with a normalised reading beside them where a
  mechanical rule exists, and leaves the judgement to the reader.

Every list and count here applies `visibility_filter`, so two people in
different departments reading the same dashboard correctly see different
totals. `offer_events` carries no owner of its own, so the activity timeline
hand-joins `offers` and scopes on that - there is no relationship() anywhere in
this codebase and this is no exception.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from helpers.commercial_terms import normalize_incoterm
from helpers.completeness_checklist import CHECKLIST
from helpers.completeness_gaps import GAP_VERDICTS, effective_verdict_column
from helpers.money import RateBook, to_decimal
from helpers.visibility import visibility_filter
from models.db_schema import (
    CompletenessRequirement,
    Offer,
    OfferCompletenessResult,
    OfferEvent,
    OfferItem,
    OfferPaymentSchedule,
    OfferVerifiedFinding,
    PipelineJob,
    Supplier,
    User,
)
from models.enums import (
    CompletenessVerdict,
    FindingVerdict,
    JobKind,
    JobStatus,
    SanityCheckStatus,
    VerificationStatus,
)
from schema.compare import (
    CompareGroupTotalOut,
    CompareOfferOut,
    ComparePaymentMilestoneOut,
    CompareResponse,
    CompareTermOut,
    CompareTermsOut,
    UnconvertibleCurrencyOut,
)
from schema.dashboard import (
    ActivityEventOut,
    AttentionOfferOut,
    AverageReadTimeOut,
    CompareReadyRfqOut,
    DashboardMoneyOut,
    DashboardResponse,
    NeedsAttentionOut,
    OffersInReviewOut,
    ReadingNowOut,
    TermsToChaseOut,
)
from schema.rates import ConvertedMoney, MoneyRate, MoneyTotalOut

from .BaseController import BaseController

logger = logging.getLogger(__name__)

# More columns than this is a spreadsheet, not a comparison - and the per-id
# visibility check is one query each, so the cap is what keeps that honest.
MAX_COMPARE_OFFERS = 12

# The fallback denominator for "N of 10", used only when the checklist table
# has not been seeded yet. The live count is read from the database so an
# admin's edit to the checklist shows up rather than silently disagreeing.
SEEDED_MANDATORY_TERMS = sum(1 for entry in CHECKLIST if entry.is_mandatory)

# Which checklist row backs which cell of the compare table.
_TERM_CODES = {
    "delivery_term": "COM_DELIVERY_TERM",
    "delivery_lead_time": "COM_DELIVERY_LEAD_TIME",
    "payment_terms": "COM_PAYMENT_TERMS",
    "warranty": "COM_WARRANTY",
    "validity": "COM_VALIDITY",
}


def is_in_review():
    """The offers-list rule, in SQL: verification says a human is needed, or
    verification never ran and the sanity check flagged it.

    One rule, so the dashboard KPI and the list badge can never disagree about
    which offers are waiting on somebody.
    """
    return or_(
        Offer.verification_status == VerificationStatus.NEEDS_HUMAN_REVIEW.value,
        and_(
            Offer.verification_status.is_(None),
            Offer.sanity_check_status == SanityCheckStatus.NEEDS_REVIEW.value,
        ),
    )


def live_offer_clauses() -> list:
    """What "an offer in the working list" means, in one place.

    Read to the end (`persisted_at`), the newest version of its chain, and not
    archived. Archived is not deleted and not superseded - it is retired, and
    it stays readable and comparable while being out of every count.
    """
    return [
        Offer.persisted_at.is_not(None),
        Offer.is_active_latest.is_(True),
        Offer.archived_at.is_(None),
    ]


def _scope(query, user: User, owner_column, department_column):
    clause = visibility_filter(
        user=user, owner_id_column=owner_column, department_column=department_column
    )
    return query if clause is None else query.where(clause)


def _confirmed_findings_subquery():
    """Confirmed findings per offer. `confirmed` is the verdict that survived
    verification against the source - `explained` and `insufficient_evidence`
    are not things to chase."""
    return (
        select(
            OfferVerifiedFinding.offer_id.label("offer_id"),
            func.count().label("confirmed"),
        )
        .where(OfferVerifiedFinding.finding_verdict == FindingVerdict.CONFIRMED.value)
        .group_by(OfferVerifiedFinding.offer_id)
        .subquery()
    )


def _completeness_subquery():
    """Mandatory gaps and the mandatory total, per offer.

    Uses `effective_verdict_column` and `GAP_VERDICTS` from
    helpers.completeness_gaps rather than restating them: the badge on the
    offers list, the offer header and these two screens have to be counting the
    same thing, and a fourth copy of the rule is a fourth chance to drift.
    """
    gap = case(
        (
            OfferCompletenessResult.was_mandatory.is_(True)
            & effective_verdict_column().in_(GAP_VERDICTS),
            1,
        ),
        else_=0,
    )
    mandatory = case((OfferCompletenessResult.was_mandatory.is_(True), 1), else_=0)
    return (
        select(
            OfferCompletenessResult.offer_id.label("offer_id"),
            func.coalesce(func.sum(gap), 0).label("gaps"),
            func.coalesce(func.sum(mandatory), 0).label("mandatory"),
        )
        .group_by(OfferCompletenessResult.offer_id)
        .subquery()
    )


class InsightsController(BaseController):

    def __init__(self, db: AsyncSession):
        super().__init__()
        self.db = db

    # --- the dashboard ------------------------------------------------------

    async def dashboard(
        self,
        *,
        user: User,
        rate_book: RateBook,
        stale_days: int,
        read_time_sample: int,
        attention_limit: int,
        activity_limit: int,
        now: datetime | None = None,
    ) -> DashboardResponse:
        """Every figure the dashboard screen shows, in nine bounded queries.

        None of them is per-offer. The counts, the money and the attention rows
        are three passes over `offers` with two grouped joins, and the rest are
        single aggregates - so the landing screen does not get slower as the
        installation fills up.
        """
        moment = now or datetime.now(timezone.utc)
        counts = await self._offer_counts(user=user, stale_days=stale_days, now=moment)
        mandatory_total = await self._mandatory_terms_total()
        money = await self._money_totals(user=user, rate_book=rate_book)
        attention = await self._attention_offers(
            user=user, rate_book=rate_book, limit=attention_limit, mandatory_total=mandatory_total, now=moment
        )
        compare_ready = await self._compare_ready_rfqs(user=user, limit=attention_limit)
        average = await self._average_read_time(user=user, sample=read_time_sample)
        reading = await self._reading_now(user=user)
        activity = await self._activity(user=user, limit=activity_limit)

        return DashboardResponse(
            generated_at=moment,
            base_currency=rate_book.base_currency,
            offers_in_review=OffersInReviewOut(
                count=counts["in_review"],
                waiting_longer_than_stale_days=counts["stale"],
                stale_days=stale_days,
                added_last_7_days=counts["added_last_7_days"],
                live_offers=counts["live"],
            ),
            terms_to_chase=TermsToChaseOut(
                mandatory_gaps=counts["gaps"],
                offers_with_gaps=counts["offers_with_gaps"],
                mandatory_terms_per_offer=mandatory_total,
                offers_checked=counts["offers_checked"],
                offers_never_checked=max(counts["live"] - counts["offers_checked"], 0),
            ),
            average_read_time=average,
            reading_now=reading,
            money=DashboardMoneyOut(
                live_offers=money[0],
                awaiting_review=money[1],
                offers_without_a_total=counts["without_total"],
            ),
            needs_attention=NeedsAttentionOut(
                offers=attention,
                compare_ready=compare_ready,
                offers_total=counts["offers_needing_attention"],
            ),
            activity=activity,
        )

    async def _offer_counts(self, *, user: User, stale_days: int, now: datetime) -> dict[str, int]:
        """Every whole-population count on the screen, in one query.

        Separate queries would be separate snapshots: with a run finishing
        between two of them, "7 offers in review, 2 of them over three days
        old" could report a 2 that is not part of the 7.
        """
        findings = _confirmed_findings_subquery()
        completeness = _completeness_subquery()
        confirmed = func.coalesce(findings.c.confirmed, 0)
        gaps = func.coalesce(completeness.c.gaps, 0)

        # Measured from when the read finished, not from when the files were
        # uploaded: the clock a reviewer is being judged against starts when the
        # offer reached their desk. Offers that predate `persisted_at` being
        # set fall back to created_at rather than being excluded.
        waiting_since = func.coalesce(Offer.persisted_at, Offer.created_at)
        stale_cutoff = now - timedelta(days=stale_days)
        week_ago = now - timedelta(days=7)

        query = (
            select(
                func.count().label("live"),
                _sum_case(is_in_review()).label("in_review"),
                _sum_case(and_(is_in_review(), waiting_since < stale_cutoff)).label("stale"),
                _sum_case(Offer.created_at >= week_ago).label("added_last_7_days"),
                _sum_case(Offer.grand_total.is_(None)).label("without_total"),
                func.coalesce(func.sum(gaps), 0).label("gaps"),
                _sum_case(gaps > 0).label("offers_with_gaps"),
                _sum_case(completeness.c.offer_id.is_not(None)).label("offers_checked"),
                _sum_case(or_(gaps > 0, confirmed > 0)).label("offers_needing_attention"),
            )
            .select_from(Offer)
            .outerjoin(findings, findings.c.offer_id == Offer.id)
            .outerjoin(completeness, completeness.c.offer_id == Offer.id)
            .where(*live_offer_clauses())
        )
        query = _scope(query, user, Offer.created_by_user_id, Offer.created_by_department)
        row = (await self.db.execute(query)).one()
        return {key: int(value or 0) for key, value in row._mapping.items()}

    async def _mandatory_terms_total(self) -> int:
        """The denominator of "N of 10", read from the live checklist.

        The client will revise the list - that is why it is a table and not an
        enum - and a hard-coded 10 would keep saying 10 after he does.
        """
        total = (
            await self.db.execute(
                select(func.count())
                .select_from(CompletenessRequirement)
                .where(
                    CompletenessRequirement.is_mandatory.is_(True),
                    CompletenessRequirement.is_active.is_(True),
                )
            )
        ).scalar_one()
        return int(total or 0) or SEEDED_MANDATORY_TERMS

    async def _money_totals(
        self, *, user: User, rate_book: RateBook
    ) -> tuple[MoneyTotalOut, MoneyTotalOut]:
        """The value of the live offers, and of the subset still in review.

        Grouped in SQL and converted in Python, so a hundred thousand offers is
        one query and a handful of multiplications. Both totals come out of the
        same GROUP BY for the same reason the counts share a query: two reads
        would be two moments.
        """
        in_review_amount = case((is_in_review(), Offer.grand_total), else_=None)
        query = (
            select(
                Offer.grand_total_currency,
                func.sum(Offer.grand_total),
                func.count(),
                func.sum(in_review_amount),
                _sum_case(is_in_review()),
            )
            .where(*live_offer_clauses(), Offer.grand_total.is_not(None))
            .group_by(Offer.grand_total_currency)
        )
        query = _scope(query, user, Offer.created_by_user_id, Offer.created_by_department)
        rows = (await self.db.execute(query)).all()

        live_groups = [(currency, total, int(count or 0)) for currency, total, count, _, _ in rows]
        # A currency where nothing is in review contributes no line at all -
        # `sum(... ) FILTER` style zeroes would put "0 USD" on the screen as if
        # a dollar offer were waiting.
        review_groups = [
            (currency, review_total, int(review_count or 0))
            for currency, _, _, review_total, review_count in rows
            if int(review_count or 0) > 0
        ]
        return (
            MoneyTotalOut.of(rate_book.total(live_groups)),
            MoneyTotalOut.of(rate_book.total(review_groups)),
        )

    async def _attention_offers(
        self,
        *,
        user: User,
        rate_book: RateBook,
        limit: int,
        mandatory_total: int,
        now: datetime,
    ) -> list[AttentionOfferOut]:
        """The offers with something to chase, worst first, capped.

        Ordered in SQL rather than fetched and sorted here: the point of the
        cap is that the database returns `limit` rows, not that the application
        throws most of them away.
        """
        findings = _confirmed_findings_subquery()
        completeness = _completeness_subquery()
        confirmed = func.coalesce(findings.c.confirmed, 0)
        gaps = func.coalesce(completeness.c.gaps, 0)

        query = (
            select(
                Offer,
                Supplier.supplier_name,
                confirmed.label("confirmed"),
                completeness.c.gaps,
                completeness.c.mandatory,
            )
            .select_from(Offer)
            .outerjoin(Supplier, Offer.supplier_id == Supplier.supplier_id)
            .outerjoin(findings, findings.c.offer_id == Offer.id)
            .outerjoin(completeness, completeness.c.offer_id == Offer.id)
            .where(*live_offer_clauses(), or_(confirmed > 0, gaps > 0))
            .order_by(confirmed.desc(), gaps.desc(), Offer.created_at.desc())
            .limit(limit)
        )
        query = _scope(query, user, Offer.created_by_user_id, Offer.created_by_department)
        rows = (await self.db.execute(query)).all()

        return [
            AttentionOfferOut(
                offer_id=offer.id,
                offer_ref=offer.offer_ref,
                supplier_name=supplier_name,
                rfq_number=offer.rfq_number,
                project_name=offer.project_name_entered or offer.project_name_original,
                project_name_entered=offer.project_name_entered,
                project_name_original=offer.project_name_original,
                confirmed_findings=int(confirmed_count or 0),
                # None, not 0: an offer nobody has checked has no gap count, and
                # drawing it as a clean "0 of 10" is the false reassurance this
                # application exists to remove.
                mandatory_gaps=None if row_gaps is None else int(row_gaps),
                mandatory_terms_total=int(row_mandatory) if row_mandatory else mandatory_total,
                sanity_check_status=_enum_or_none(SanityCheckStatus, offer.sanity_check_status),
                verification_status=_enum_or_none(VerificationStatus, offer.verification_status),
                grand_total=ConvertedMoney.of(
                    rate_book.convert(offer.grand_total, offer.grand_total_currency)
                ),
                waiting_days=_whole_days_since(offer.persisted_at or offer.created_at, now),
                created_at=offer.created_at,
                persisted_at=offer.persisted_at,
            )
            for offer, supplier_name, confirmed_count, row_gaps, row_mandatory in rows
        ]

    async def _compare_ready_rfqs(self, *, user: User, limit: int) -> list[CompareReadyRfqOut]:
        """RFQs with more than one offer read against them.

        The entry point to the compare screen, and the only thing this can
        honestly say: nothing in the database records whether anybody has
        actually compared them, so the row says "these can be compared", not
        "nothing compared yet".
        """
        query = (
            select(
                Offer.rfq_number,
                func.count().label("offer_count"),
                func.array_agg(Offer.id).label("offer_ids"),
                func.array_agg(func.coalesce(Supplier.supplier_name, "")).label("suppliers"),
                func.max(Offer.created_at).label("latest_created_at"),
            )
            .select_from(Offer)
            .outerjoin(Supplier, Offer.supplier_id == Supplier.supplier_id)
            .where(*live_offer_clauses(), Offer.rfq_number.is_not(None), Offer.rfq_number != "")
            .group_by(Offer.rfq_number)
            .having(func.count() > 1)
            .order_by(func.max(Offer.created_at).desc())
            .limit(limit)
        )
        query = _scope(query, user, Offer.created_by_user_id, Offer.created_by_department)
        rows = (await self.db.execute(query)).all()
        return [
            CompareReadyRfqOut(
                rfq_number=rfq_number,
                offer_count=int(offer_count or 0),
                offer_ids=sorted(offer_ids or []),
                supplier_names=sorted({name for name in (suppliers or []) if name}),
                latest_created_at=latest,
            )
            for rfq_number, offer_count, offer_ids, suppliers, latest in rows
        ]

    async def _average_read_time(self, *, user: User, sample: int) -> AverageReadTimeOut:
        """How long a read takes here, over the most recent finished runs.

        `started_at` to `finished_at`, never `created_at` to `finished_at`: with
        a real queue in front of the runner, the second measures how long the
        backlog was as much as how fast the read is, and the number on the
        screen would grow every time somebody uploaded five offers at once.

        Only successful `offer_pipeline` runs count. A failed run stops
        somewhere in the middle and a cancelled one stops when a person said so;
        averaging those in would make the estimate better the more often the
        pipeline broke.
        """
        recent = (
            select(
                PipelineJob.started_at,
                PipelineJob.finished_at,
            )
            .where(
                PipelineJob.kind == JobKind.OFFER_PIPELINE.value,
                PipelineJob.status == JobStatus.SUCCEEDED.value,
                PipelineJob.started_at.is_not(None),
                PipelineJob.finished_at.is_not(None),
            )
            .order_by(PipelineJob.finished_at.desc())
            .limit(sample)
        )
        recent = _scope(
            recent, user, PipelineJob.created_by_user_id, PipelineJob.created_by_department
        ).subquery()

        seconds = func.extract("epoch", recent.c.finished_at - recent.c.started_at)
        row = (
            await self.db.execute(select(func.avg(seconds), func.count()).select_from(recent))
        ).one()
        average, size = row
        return AverageReadTimeOut(
            seconds=float(average) if average is not None else None,
            sample_size=int(size or 0),
            sample_requested=sample,
        )

    async def _reading_now(self, *, user: User) -> ReadingNowOut:
        """How many reads are running and how many are waiting, for this caller.

        Counts only. The panel's progress bar, stage line, ETA and controls come
        from the queue endpoint, which owns the queue - two sources for the same
        panel is two sources that can disagree.
        """
        query = (
            select(PipelineJob.status, func.count())
            .where(PipelineJob.status.in_([JobStatus.RUNNING.value, JobStatus.QUEUED.value]))
            .group_by(PipelineJob.status)
        )
        query = _scope(
            query, user, PipelineJob.created_by_user_id, PipelineJob.created_by_department
        )
        counts = {status: int(count or 0) for status, count in (await self.db.execute(query)).all()}
        return ReadingNowOut(
            running=counts.get(JobStatus.RUNNING.value, 0),
            waiting=counts.get(JobStatus.QUEUED.value, 0),
        )

    async def _activity(self, *, user: User, limit: int) -> list[ActivityEventOut]:
        """The newest events across every offer the caller may see.

        `offer_events` carries no owner columns on purpose: an event is visible
        exactly when its offer is. So this hand-joins `offers` and applies the
        same `visibility_filter` as every other list - copying the department
        onto the event row would be a second copy of the policy, free to drift
        from the first.

        Not restricted to live offers: an archived or superseded offer's history
        is still this department's history, and cutting it out would make the
        timeline stop halfway through a story.
        """
        query = (
            select(OfferEvent, Offer.offer_ref)
            .select_from(OfferEvent)
            .join(Offer, Offer.id == OfferEvent.offer_id)
            .order_by(OfferEvent.created_at.desc(), OfferEvent.event_id.desc())
            .limit(limit)
        )
        query = _scope(query, user, Offer.created_by_user_id, Offer.created_by_department)
        rows = (await self.db.execute(query)).all()
        return [
            ActivityEventOut(
                event_id=event.event_id,
                offer_id=event.offer_id,
                offer_ref=offer_ref,
                kind=event.kind,
                detail=event.detail,
                payload=event.payload,
                actor_user_id=event.actor_user_id,
                actor_display_name=event.actor_display_name or "",
                # A NULL actor is the system itself - the design's "Bidsense".
                # Read off the id, not off the empty name: a person whose
                # account was deleted keeps their snapshotted name and must not
                # become the system.
                is_system=event.actor_user_id is None and not event.actor_display_name,
                created_at=event.created_at,
            )
            for event, offer_ref in rows
        ]

    # --- the compare screen -------------------------------------------------

    async def compare(
        self,
        offer_ids: list[int],
        *,
        user: User,
        rate_book: RateBook,
        now: datetime | None = None,
    ) -> CompareResponse:
        """The offers on one RFQ, side by side. Six queries, whatever the count.

        The caller has already proved it may see each id (the route resolves
        `ensure_offer_visible` per id); the offers query carries
        `visibility_filter` as well, so a change to one guard cannot silently
        widen the other.
        """
        moment = now or datetime.now(timezone.utc)
        offers = await self._compare_offers(offer_ids, user=user)
        found = {offer.id for offer, _ in offers}
        ordered = [offer_id for offer_id in offer_ids if offer_id in found]

        findings = await self._confirmed_counts(ordered)
        results = await self._completeness_results(ordered)
        items = await self._item_counts(ordered)
        schedules = await self._payment_schedules(ordered)
        group_totals = await self._group_totals(ordered)
        mandatory_total = await self._mandatory_terms_total()

        by_id = {offer.id: (offer, supplier_name) for offer, supplier_name in offers}
        columns = [
            self._compare_column(
                *by_id[offer_id],
                rate_book=rate_book,
                confirmed=findings.get(offer_id, 0),
                results=results.get(offer_id, {}),
                item_count=items.get(offer_id, 0),
                schedule=schedules.get(offer_id, []),
                groups=group_totals.get(offer_id, []),
                mandatory_total=mandatory_total,
            )
            for offer_id in ordered
        ]
        return self._compare_response(columns, rate_book=rate_book, now=moment)

    async def _compare_offers(
        self, offer_ids: list[int], *, user: User
    ) -> list[tuple[Offer, str | None]]:
        query = (
            select(Offer, Supplier.supplier_name)
            .outerjoin(Supplier, Offer.supplier_id == Supplier.supplier_id)
            .where(Offer.id.in_(offer_ids))
        )
        query = _scope(query, user, Offer.created_by_user_id, Offer.created_by_department)
        return list((await self.db.execute(query)).all())

    async def _confirmed_counts(self, offer_ids: list[int]) -> dict[int, int]:
        if not offer_ids:
            return {}
        rows = (
            await self.db.execute(
                select(OfferVerifiedFinding.offer_id, func.count())
                .where(
                    OfferVerifiedFinding.offer_id.in_(offer_ids),
                    OfferVerifiedFinding.finding_verdict == FindingVerdict.CONFIRMED.value,
                )
                .group_by(OfferVerifiedFinding.offer_id)
            )
        ).all()
        return {offer_id: int(count or 0) for offer_id, count in rows}

    async def _completeness_results(
        self, offer_ids: list[int]
    ) -> dict[int, dict[str, OfferCompletenessResult]]:
        """Every checklist result for these offers, keyed by offer and code.

        One query for the whole table rather than one per column: twelve offers
        is at most a few hundred rows, and the alternative is twelve round trips
        for the same thing.
        """
        if not offer_ids:
            return {}
        rows = (
            await self.db.execute(
                select(OfferCompletenessResult).where(
                    OfferCompletenessResult.offer_id.in_(offer_ids)
                )
            )
        ).scalars().all()
        by_offer: dict[int, dict[str, OfferCompletenessResult]] = {}
        for row in rows:
            by_offer.setdefault(row.offer_id, {})[row.requirement_code] = row
        return by_offer

    async def _item_counts(self, offer_ids: list[int]) -> dict[int, int]:
        if not offer_ids:
            return {}
        rows = (
            await self.db.execute(
                select(OfferItem.offer_id, func.count())
                .where(OfferItem.offer_id.in_(offer_ids))
                .group_by(OfferItem.offer_id)
            )
        ).all()
        return {offer_id: int(count or 0) for offer_id, count in rows}

    async def _payment_schedules(
        self, offer_ids: list[int]
    ) -> dict[int, list[OfferPaymentSchedule]]:
        if not offer_ids:
            return {}
        rows = (
            await self.db.execute(
                select(OfferPaymentSchedule)
                .where(OfferPaymentSchedule.offer_id.in_(offer_ids))
                .order_by(OfferPaymentSchedule.offer_id, OfferPaymentSchedule.sequence_no)
            )
        ).scalars().all()
        by_offer: dict[int, list[OfferPaymentSchedule]] = {}
        for row in rows:
            by_offer.setdefault(row.offer_id, []).append(row)
        return by_offer

    async def _group_totals(self, offer_ids: list[int]) -> dict[int, list[OfferItem]]:
        """Each offer's top-level items that carry their own stated subtotal.

        Only relevant to offers with no single `grand_total` (a "Base offer"
        and an "Alternative offer" each independently totaled) - fetched for
        every offer regardless, same shape as `_item_counts`, since building
        the column doesn't yet know which offers will need it.
        """
        if not offer_ids:
            return {}
        rows = (
            await self.db.execute(
                select(OfferItem)
                .where(
                    OfferItem.offer_id.in_(offer_ids),
                    OfferItem.parent_item_id.is_(None),
                    OfferItem.stated_subtotal_amount.is_not(None),
                )
                .order_by(OfferItem.offer_id, OfferItem.sort_order)
            )
        ).scalars().all()
        by_offer: dict[int, list[OfferItem]] = {}
        for row in rows:
            by_offer.setdefault(row.offer_id, []).append(row)
        return by_offer

    def _compare_column(
        self,
        offer: Offer,
        supplier_name: str | None,
        *,
        rate_book: RateBook,
        confirmed: int,
        results: dict[str, OfferCompletenessResult],
        item_count: int,
        schedule: list[OfferPaymentSchedule],
        groups: list[OfferItem],
        mandatory_total: int,
    ) -> CompareOfferOut:
        mandatory_rows = [row for row in results.values() if row.was_mandatory]
        checked = bool(results)
        return CompareOfferOut(
            offer_id=offer.id,
            offer_ref=offer.offer_ref,
            supplier_name=supplier_name,
            rfq_number=offer.rfq_number,
            project_name_entered=offer.project_name_entered,
            project_name_original=offer.project_name_original,
            is_active_latest=bool(offer.is_active_latest),
            archived=offer.archived_at is not None,
            created_at=offer.created_at,
            persisted_at=offer.persisted_at,
            grand_total=ConvertedMoney.of(
                rate_book.convert(offer.grand_total, offer.grand_total_currency)
            ),
            group_totals=(
                [
                    CompareGroupTotalOut(
                        label=group.item_group_label or group.description,
                        total=ConvertedMoney.of(
                            rate_book.convert(
                                group.stated_subtotal_amount, group.stated_subtotal_currency
                            )
                        ),
                    )
                    for group in groups
                ]
                if offer.grand_total is None
                else []
            ),
            confirmed_findings=confirmed,
            sanity_check_status=_enum_or_none(SanityCheckStatus, offer.sanity_check_status),
            verification_status=_enum_or_none(VerificationStatus, offer.verification_status),
            mandatory_gaps=(
                sum(
                    1
                    for row in mandatory_rows
                    if row.effective_verdict in GAP_VERDICTS
                )
                if checked
                else None
            ),
            mandatory_terms_total=len(mandatory_rows) if mandatory_rows else mandatory_total,
            completeness_checked=checked,
            item_count=item_count,
            terms=self._compare_terms(offer, results, schedule),
            payment_schedule=[
                ComparePaymentMilestoneOut(
                    sequence_no=row.sequence_no,
                    trigger_event=row.trigger_event,
                    percentage=to_decimal(row.percentage),
                    description=row.description_original,
                )
                for row in schedule
            ],
        )

    @staticmethod
    def _compare_terms(
        offer: Offer,
        results: dict[str, OfferCompletenessResult],
        schedule: list[OfferPaymentSchedule],
    ) -> CompareTermsOut:
        """The six term rows, each as written and as read.

        The offer's own extracted field is preferred for `stated` because it is
        the supplier's wording verbatim; the checker's value fills in where
        extraction left the field empty but the check found the term elsewhere
        in the documents.
        """
        delivery = results.get(_TERM_CODES["delivery_term"])
        delivery_text = offer.incoterm or _result_value(delivery)
        incoterm_code = normalize_incoterm(delivery_text) or normalize_incoterm(
            offer.delivery_terms_original
        )

        payment = results.get(_TERM_CODES["payment_terms"])
        # "30 / 60 / 10" - the design's comparable form of a payment schedule,
        # built from the extracted milestones and returned BESIDE the
        # supplier's sentence, never instead of it.
        milestones = " / ".join(
            _percentage_text(row.percentage) for row in schedule if row.percentage is not None
        )

        return CompareTermsOut(
            incoterm=_term(
                stated=offer.incoterm or delivery_text,
                normalized=incoterm_code,
                normalized_from="incoterm" if incoterm_code else None,
                result=delivery,
            ),
            delivery_terms=_term(
                stated=offer.delivery_terms_original,
                # Free text with no mechanical rule behind it - returned exactly
                # as the supplier wrote it, and compared by eye.
                normalized=None,
                normalized_from=None,
                result=delivery,
            ),
            delivery_lead_time=_term(
                stated=_result_value(results.get(_TERM_CODES["delivery_lead_time"])),
                normalized=_result_normalized(results.get(_TERM_CODES["delivery_lead_time"])),
                normalized_from=(
                    "completeness_check"
                    if _result_normalized(results.get(_TERM_CODES["delivery_lead_time"]))
                    else None
                ),
                result=results.get(_TERM_CODES["delivery_lead_time"]),
            ),
            payment_terms=_term(
                stated=offer.payment_terms_original or _result_value(payment),
                normalized=milestones or None,
                normalized_from="payment_schedule" if milestones else None,
                result=payment,
            ),
            warranty=_term(
                stated=offer.warranty_terms_original
                or _result_value(results.get(_TERM_CODES["warranty"])),
                normalized=_result_normalized(results.get(_TERM_CODES["warranty"])),
                normalized_from=(
                    "completeness_check"
                    if _result_normalized(results.get(_TERM_CODES["warranty"]))
                    else None
                ),
                result=results.get(_TERM_CODES["warranty"]),
            ),
            validity=_term(
                stated=offer.validity_terms_original
                or _result_value(results.get(_TERM_CODES["validity"])),
                normalized=_result_normalized(results.get(_TERM_CODES["validity"])),
                normalized_from=(
                    "completeness_check"
                    if _result_normalized(results.get(_TERM_CODES["validity"]))
                    else None
                ),
                result=results.get(_TERM_CODES["validity"]),
            ),
        )

    @staticmethod
    def _compare_response(
        columns: list[CompareOfferOut], *, rate_book: RateBook, now: datetime
    ) -> CompareResponse:
        """Assemble the comparison and say out loud what it cannot claim."""
        rfq_numbers = sorted({column.rfq_number for column in columns if column.rfq_number})
        missing_rfq = any(not column.rfq_number for column in columns)
        same_rfq = len(rfq_numbers) == 1 and not missing_rfq

        currencies = sorted(
            {
                column.grand_total.original_currency
                for column in columns
                if column.grand_total.original_currency
            }
        )
        rate_dependent = len(currencies) > 1

        rates_used: dict[str, MoneyRate] = {}
        unconvertible: dict[str, str] = {}
        for column in columns:
            money = column.grand_total
            # Only rates somebody fetched or typed. The base currency's own
            # 1:1 is an identity, and listing it under "the rates this
            # comparison depends on" would invite a reader to go and check it.
            if money.rate is not None and money.rate.source is not None:
                rates_used[money.rate.currency_code] = money.rate
            elif money.original_currency and money.unconvertible_reason:
                unconvertible[money.original_currency] = money.unconvertible_reason

        notes: list[str] = []
        if not same_rfq and len(columns) > 1:
            notes.append(
                "These offers are not all filed against the same RFQ, so they may not be "
                "answering the same scope."
            )
        if rate_dependent:
            oldest = max(
                (rate.age_seconds or 0 for rate in rates_used.values()),
                default=0,
            )
            notes.append(
                f"These offers are quoted in {len(currencies)} currencies. The converted "
                f"totals depend on the rates on file, the oldest of which was set "
                f"{max(oldest // 86400, 0)} day(s) ago."
            )
        for code, reason in sorted(unconvertible.items()):
            notes.append(f"{reason} That offer's total is shown only in {code}.")
        superseded = [column.offer_ref or str(column.offer_id) for column in columns if not column.is_active_latest]
        if superseded:
            notes.append(
                f"{', '.join(superseded)} is not the newest version of its offer - a later "
                "version has been uploaded."
            )
        archived = [column.offer_ref or str(column.offer_id) for column in columns if column.archived]
        if archived:
            notes.append(f"{', '.join(archived)} has been archived.")
        unchecked = [
            column.offer_ref or str(column.offer_id)
            for column in columns
            if not column.completeness_checked
        ]
        if unchecked:
            notes.append(
                f"The completeness check has never run for {', '.join(unchecked)}, so its "
                "missing-terms cell is blank rather than zero."
            )

        return CompareResponse(
            generated_at=now,
            base_currency=rate_book.base_currency,
            offers=columns,
            rfq_numbers=rfq_numbers,
            same_rfq=same_rfq,
            currencies=currencies,
            rate_dependent=rate_dependent,
            rates_used=[rates_used[code] for code in sorted(rates_used)],
            unconvertible_currencies=[
                UnconvertibleCurrencyOut(currency_code=code, reason=reason)
                for code, reason in sorted(unconvertible.items())
            ],
            notes=notes,
        )


# --- small shared pieces -----------------------------------------------------


def _sum_case(condition):
    """`SUM(CASE WHEN ... THEN 1 ELSE 0 END)` - a counted condition.

    Written this way rather than as `COUNT(*) FILTER (WHERE ...)` to match
    helpers/completeness_gaps, which does the same thing for the same reason:
    one readable shape for every conditional count in the codebase.
    """
    return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)


def _enum_or_none(enum_type, value):
    """A stored status as its enum, or None for a status no longer in the enum.

    A check constraint keeps these columns honest, but a value retired from the
    enum while rows still hold it would otherwise raise on the way out - and a
    dashboard that 500s because of one old row is worse than one missing badge.
    """
    if value is None:
        return None
    try:
        return enum_type(value)
    except ValueError:
        logger.warning("unknown %s value on an offer: %r", enum_type.__name__, value)
        return None


def _whole_days_since(moment: datetime | None, now: datetime) -> int | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max((now - moment).days, 0)


def _result_value(result: OfferCompletenessResult | None) -> str | None:
    """The reviewer's corrected value where there is one, otherwise the
    checker's - the same override-wins rule the completeness section uses."""
    return result.effective_value if result is not None else None


def _result_normalized(result: OfferCompletenessResult | None) -> str | None:
    return result.normalized_value if result is not None else None


def _term(
    *,
    stated: str | None,
    normalized: str | None,
    normalized_from: str | None,
    result: OfferCompletenessResult | None,
) -> CompareTermOut:
    return CompareTermOut(
        stated=stated or None,
        normalized=normalized,
        normalized_from=normalized_from,
        verdict=(
            _enum_or_none(CompletenessVerdict, result.effective_verdict)
            if result is not None
            else None
        ),
        is_overridden=bool(result.is_overridden) if result is not None else False,
    )


def _percentage_text(percentage) -> str:
    """"30", not "30.00" - the design's "30 / 60 / 10"."""
    value = to_decimal(percentage)
    if value is None:
        return ""
    normalized = value.normalize()
    return f"{normalized:f}"
