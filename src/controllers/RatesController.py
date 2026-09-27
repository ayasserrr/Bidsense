"""The exchange rate table: reading it, editing one row, and refreshing it.

The rates are a small, shared, boring table - one row per currency, no history -
and almost all of the care here is about what must NOT happen. A refresh must
never block a page, must never empty the table when the provider is down, and
must never quietly replace a rate somebody typed in by hand. A missing rate
must stay missing rather than becoming a plausible-looking guess.

The provider is configurable and needs no key by default
(`https://open.er-api.com/v6/latest/{base}`). Note the direction: that service
publishes "one BASE buys N of this currency", and what this application stores
is the opposite - how many units of the base ONE unit of the foreign currency
is worth, because that is the multiplier a total is converted with. Getting
that the wrong way round is the one arithmetic mistake in this file that would
look entirely reasonable on screen.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from helpers.money import RateBook, to_decimal
from models.db_schema import Currency, ExchangeRate, User
from models.enums import ExchangeRateSource
from schema.rates import ExchangeRateOut, ManualRateRequest, RateRefreshResponse, RatesResponse

from .BaseController import BaseController

logger = logging.getLogger(__name__)


class UnknownCurrencyError(ValueError):
    """A currency code this application does not carry.

    `exchange_rates.currency_code` is a foreign key to `currencies`, so an
    unknown code would fail as an integrity error deep in a flush. Caught here
    it becomes a sentence naming the code.
    """

    def __init__(self, currency_code: str):
        self.currency_code = currency_code
        super().__init__(f"{currency_code} is not a currency this application knows.")


class BaseRateMustBeOneError(ValueError):
    """The base currency is worth exactly one of itself.

    A CHECK on the table says the same thing. Caught here it is a sentence
    instead of a constraint violation.
    """

    def __init__(self, currency_code: str):
        self.currency_code = currency_code
        super().__init__(
            f"{currency_code} is the base currency, so its rate can only be 1."
        )


class RateFetchError(RuntimeError):
    """The provider could not be read. Carries the sentence to show."""


class RatesController(BaseController):

    def __init__(self, db: AsyncSession, *, transport: httpx.AsyncBaseTransport | None = None):
        super().__init__()
        self.db = db
        # Tests hand in an httpx.MockTransport; production uses the network.
        # There is no other way into this class's HTTP call, which is what
        # keeps the test suite off a public service it does not own.
        self._transport = transport

    @property
    def base_currency(self) -> str:
        return (self.app_settings.BASE_CURRENCY or "").upper()

    # --- reading -----------------------------------------------------------

    async def load_rates(self) -> list[ExchangeRate]:
        """Every rate on file. The table is read whole, always - it is a couple
        of dozen rows and every aggregate needs all of them."""
        result = await self.db.execute(select(ExchangeRate).order_by(ExchangeRate.currency_code))
        return list(result.scalars().all())

    async def rate_book(self, *, now: datetime | None = None) -> RateBook:
        """The rate table as the conversion helper wants it.

        Every aggregate in the application goes through this: one read per
        request, then conversions in memory. Converting per offer would be the
        N+1 that makes the dashboard the slowest page in the app.
        """
        return RateBook(self.base_currency, await self.load_rates(), now=now)

    async def list_rates(self, *, now: datetime | None = None) -> RatesResponse:
        rows = await self.load_rates()
        known = set(
            (await self.db.execute(select(Currency.code))).scalars().all()
        )
        # One join for the editors' names rather than one query per row.
        editor_ids = {row.set_by_user_id for row in rows if row.set_by_user_id is not None}
        names: dict[int, str] = {}
        if editor_ids:
            result = await self.db.execute(
                select(User.id, User.display_name).where(User.id.in_(editor_ids))
            )
            names = {user_id: display_name for user_id, display_name in result.all()}

        moment = now or datetime.now(timezone.utc)
        rates = [self._to_out(row, names, moment) for row in rows]
        return RatesResponse(
            base_currency=self.base_currency,
            rates=rates,
            currencies_without_a_rate=sorted(known - {row.currency_code for row in rows}),
            fetch_enabled=bool(self.app_settings.EXCHANGE_RATES_FETCH_ENABLED),
            api_url=self._api_url(),
            fetched_at=max(
                (row.set_at for row in rows if row.source == ExchangeRateSource.API.value),
                default=None,
            ),
        )

    @staticmethod
    def _to_out(row: ExchangeRate, names: dict[int, str], now: datetime) -> ExchangeRateOut:
        set_at = row.set_at
        if set_at is not None and set_at.tzinfo is None:
            set_at = set_at.replace(tzinfo=timezone.utc)
        return ExchangeRateOut(
            currency_code=row.currency_code,
            base_currency_code=row.base_currency_code,
            rate_to_base=row.rate_to_base,
            source=ExchangeRateSource(row.source),
            rate_as_of=row.rate_as_of,
            set_at=set_at,
            age_seconds=max(int((now - set_at).total_seconds()), 0) if set_at else 0,
            set_by_user_id=row.set_by_user_id,
            set_by=names.get(row.set_by_user_id) if row.set_by_user_id else None,
        )

    # --- editing one rate by hand ------------------------------------------

    async def set_manual_rate(self, request: ManualRateRequest, *, user: User) -> ExchangeRate:
        """Type one rate in. Any signed-in user may, and their name goes on it.

        Not admin-only, by decision: the people who read these totals are the
        people who know what the bank actually charged this week, and making
        them raise a ticket to correct a stale rate is how a wrong number stays
        on the dashboard for a month. The editor is recorded instead, so a rate
        nobody recognises can always be traced to whoever set it.
        """
        code = request.currency_code.upper()
        known = await self.db.get(Currency, code)
        if known is None:
            raise UnknownCurrencyError(code)

        rate = to_decimal(request.rate_to_base)
        if code == self.base_currency and rate != Decimal(1):
            raise BaseRateMustBeOneError(code)

        row = await self.db.get(ExchangeRate, code)
        if row is None:
            row = ExchangeRate(currency_code=code)
            self.db.add(row)
        row.base_currency_code = self.base_currency
        row.rate_to_base = rate
        row.source = ExchangeRateSource.MANUAL.value
        # The provider's "as of" belongs to the provider's number, not to this
        # one. Clearing it is what stops a hand-typed rate inheriting the
        # authority of the fetch it replaced.
        row.rate_as_of = None
        row.set_at = datetime.now(timezone.utc)
        row.set_by_user_id = user.id
        await self.db.commit()
        return row

    # --- refreshing from the provider --------------------------------------

    def _api_url(self) -> str:
        template = self.app_settings.EXCHANGE_RATES_API_URL or ""
        return template.replace("{base}", self.base_currency)

    async def refresh(self, *, overwrite_manual: bool = False) -> RateRefreshResponse:
        """Ask the provider for today's rates and write what comes back.

        Never raises for a provider problem. A refresh that fails leaves every
        existing rate exactly as it was and returns `ok=false` with the sentence
        to show - the screen keeps rendering the rates already on file, which is
        the whole reason this feature stores them instead of fetching them on
        the way past.
        """
        if not self.app_settings.EXCHANGE_RATES_FETCH_ENABLED:
            return await self._refresh_failed(
                "Fetching exchange rates is switched off on this server. The rates already "
                "on file are unchanged, and any of them can still be set by hand."
            )

        try:
            payload = await self._fetch()
        except RateFetchError as exc:
            logger.warning("exchange rate refresh failed: %s", exc)
            return await self._refresh_failed(str(exc))

        quoted, as_of = payload
        known = set((await self.db.execute(select(Currency.code))).scalars().all())
        existing = {row.currency_code: row for row in await self.load_rates()}

        updated: list[str] = []
        kept_manual: list[str] = []
        skipped: list[str] = []
        now = datetime.now(timezone.utc)

        for code in sorted(known):
            rate = quoted.get(code)
            if rate is None:
                # The provider does not publish this one. Silence, not a zero -
                # and definitely not a deletion of a rate somebody set.
                skipped.append(code)
                continue
            row = existing.get(code)
            if row is not None and row.source == ExchangeRateSource.MANUAL.value and not overwrite_manual:
                kept_manual.append(code)
                continue
            if row is None:
                row = ExchangeRate(currency_code=code)
                self.db.add(row)
            row.base_currency_code = self.base_currency
            row.rate_to_base = rate
            row.source = ExchangeRateSource.API.value
            row.rate_as_of = as_of
            row.set_at = now
            # The provider set it, not a person - and a rate that used to be
            # manual stops carrying its old editor's name once it is overwritten.
            row.set_by_user_id = None
            updated.append(code)

        await self.db.commit()
        return RateRefreshResponse(
            ok=True,
            message=self._refresh_sentence(updated, kept_manual, skipped),
            updated=updated,
            kept_manual=kept_manual,
            skipped=skipped,
            rates=await self.list_rates(),
        )

    def _refresh_sentence(
        self, updated: list[str], kept_manual: list[str], skipped: list[str]
    ) -> str:
        parts = [
            f"Updated {len(updated)} rate{'' if len(updated) == 1 else 's'} against "
            f"{self.base_currency}."
        ]
        if kept_manual:
            parts.append(
                f"Kept the hand-set rate for {', '.join(kept_manual)} - refresh with "
                "'overwrite_manual' to replace those too."
            )
        if skipped:
            parts.append(f"The provider does not publish {', '.join(skipped)}.")
        return " ".join(parts)

    async def _refresh_failed(self, message: str) -> RateRefreshResponse:
        """A failure carries the untouched table with it, so one call is enough
        to both report the problem and redraw the screen."""
        return RateRefreshResponse(
            ok=False, message=message, rates=await self.list_rates()
        )

    async def _fetch(self) -> tuple[dict[str, Decimal], datetime | None]:
        """One request to the provider, parsed into `{code: rate_to_base}`.

        Raises `RateFetchError` with a sentence a reviewer can read for every
        way this goes wrong - unreachable, not JSON, the wrong shape, or quoted
        against a different base than this deployment converts to. Converting
        through someone else's base would produce numbers that are wrong by a
        factor nobody would spot.
        """
        url = self._api_url()
        timeout = httpx.Timeout(self.app_settings.EXCHANGE_RATES_TIMEOUT_SECONDS)
        try:
            async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as http:
                response = await http.get(url)
        except httpx.HTTPError as exc:
            raise RateFetchError(
                f"The exchange rate service at {url} could not be reached ({exc.__class__.__name__}). "
                "The rates already on file are unchanged."
            ) from exc

        if response.status_code >= 400:
            raise RateFetchError(
                f"The exchange rate service at {url} answered {response.status_code}. "
                "The rates already on file are unchanged."
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise RateFetchError(
                f"The exchange rate service at {url} did not return JSON. "
                "The rates already on file are unchanged."
            ) from exc

        if not isinstance(body, dict):
            raise RateFetchError(
                f"The exchange rate service at {url} returned something that is not a rate "
                "list. The rates already on file are unchanged."
            )

        quoted = body.get("rates")
        if not isinstance(quoted, dict) or not quoted:
            raise RateFetchError(
                f"The exchange rate service at {url} returned no rates. "
                "The rates already on file are unchanged."
            )

        reported_base = str(body.get("base_code") or body.get("base") or "").upper()
        if reported_base and reported_base != self.base_currency:
            raise RateFetchError(
                f"The exchange rate service quoted rates against {reported_base}, not "
                f"{self.base_currency}. Nothing was changed - converting through the wrong "
                "base would be worse than having no rate at all."
            )

        rates: dict[str, Decimal] = {}
        for code, value in quoted.items():
            per_base = to_decimal(value)
            if per_base is None or per_base <= 0:
                # A zero or a null would divide by zero below, and a negative
                # rate is not a rate. Dropping the entry leaves that currency
                # with whatever it had, which is the honest outcome.
                continue
            try:
                # The provider says "one BASE buys `per_base` of this currency".
                # What is stored is the inverse - what one unit of this currency
                # is worth in the base - because that is the multiplier a total
                # is converted with.
                rates[str(code).upper()] = Decimal(1) / per_base
            except (InvalidOperation, ZeroDivisionError):
                continue

        if not rates:
            raise RateFetchError(
                f"The exchange rate service at {url} returned no usable rates. "
                "The rates already on file are unchanged."
            )
        return rates, _provider_as_of(body)


def _provider_as_of(body: dict) -> datetime | None:
    """The provider's own publication time, where it gives one.

    Recorded separately from `set_at` because they answer different questions:
    `set_at` is when this deployment last wrote the row, and this is how fresh
    the number in it was when it did.
    """
    unix = body.get("time_last_update_unix")
    if isinstance(unix, (int, float)) and unix > 0:
        return datetime.fromtimestamp(float(unix), tz=timezone.utc)
    return None
