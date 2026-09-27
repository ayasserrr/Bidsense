"""Converting money to the base currency without ever inventing a rate.

Two screens add up other people's figures - the dashboard's totals and the
compare screen's side-by-side grand totals - and both can be handed offers in
four currencies at once. The rule this module exists to enforce is the one the
whole application is built on: never quietly produce a number nobody can trace.

So every conversion carries the original amount and its currency alongside the
converted figure, names the rate it used and how old that rate is, and when
there is no rate it says so instead of substituting one. A currency with no row
in `exchange_rates` is not converted, is NOT dropped from the total in silence,
and is reported by name - a total that silently omitted the dollar offers would
be wrong in exactly the way this application catches in suppliers' documents.

Everything here is pure: it takes rows that have already been read and returns
values. The database read lives in `controllers.RatesController`, which is what
lets these rules be tested without a server, a network or a rate table.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

# Money is reported to two decimal places. The rate itself is NUMERIC(20,10)
# and is never rounded - rounding the rate rather than the result is how a
# total drifts away from the sum of its parts.
MONEY_EXPONENT = Decimal("0.01")


def to_decimal(value) -> Decimal | None:
    """A Decimal, or None for anything that is not a usable number.

    Never `float(...)`: asyncpg hands back NUMERIC as Decimal already, and
    routing it through a binary float would lose the exactness that made the
    column NUMERIC in the first place. A float that arrives anyway (a test, a
    JSON body) is converted through its string form for the same reason.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def quantize_money(value: Decimal | None) -> Decimal | None:
    """Round a converted figure to two decimal places for display."""
    if value is None:
        return None
    return value.quantize(MONEY_EXPONENT)


def _as_utc(moment: datetime | None) -> datetime | None:
    """Timestamps arrive tz-aware from the database; a hand-built one in a test
    may not, and subtracting a naive from an aware datetime raises."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


@dataclass(frozen=True)
class RateUsed:
    """The rate one converted figure was actually computed with.

    Returned with every converted amount rather than left implicit, because
    "4,287,500 EGP" means nothing on its own when the offer was written in
    dollars: the reader has to be able to see which rate produced it and how
    stale it is before they act on the number.
    """

    currency_code: str
    rate_to_base: Decimal
    # 'api' | 'manual', or None for the base currency converting to itself -
    # an identity, not a rate anybody set.
    source: str | None
    set_at: datetime | None
    rate_as_of: datetime | None
    # now - set_at. None for the identity rate, which has no age.
    age_seconds: int | None

    @property
    def is_identity(self) -> bool:
        return self.source is None


@dataclass(frozen=True)
class ConvertedAmount:
    """One amount, in both currencies, with the reason when only one of them
    could be filled in."""

    original_amount: Decimal | None
    original_currency: str | None
    base_currency: str
    converted_amount: Decimal | None
    rate: RateUsed | None
    # A sentence for the reader when `converted_amount` is None. Null when the
    # conversion succeeded, and also when there was no amount to convert.
    unconvertible_reason: str | None = None

    @property
    def is_converted(self) -> bool:
        return self.converted_amount is not None


@dataclass(frozen=True)
class CurrencyAmount:
    """One currency's share of a total, converted where it could be."""

    currency_code: str | None
    amount: Decimal
    offer_count: int
    converted_amount: Decimal | None
    rate: RateUsed | None
    unconvertible_reason: str | None = None


@dataclass(frozen=True)
class MoneyTotal:
    """A total that is honest about what it could not include.

    `converted_total` is the sum of the currencies that had a rate. It is NOT
    the whole figure whenever `unconvertible` is non-empty, and `is_complete`
    is the flag the UI must read before presenting it as one - which is why the
    per-currency breakdown is returned beside it rather than only on request.
    """

    base_currency: str
    converted_total: Decimal | None
    by_currency: list[CurrencyAmount] = field(default_factory=list)
    # The currencies whose amounts are in `by_currency` but NOT in
    # `converted_total`, named so the reader can go and set a rate.
    unconvertible: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """Whether `converted_total` accounts for every amount that went in.

        Read off `by_currency`, not off `unconvertible`: an amount whose
        currency was never recorded has no name to put in that list, and
        trusting the list alone would call the total complete while leaving
        that money out of it.
        """
        return all(row.converted_amount is not None for row in self.by_currency)


class RateBook:
    """The current rate table, read once and asked many times.

    Built from rows already loaded, so one dashboard request reads
    `exchange_rates` once and converts a page of offers against it rather than
    querying per offer. The table is a couple of dozen rows - it is always read
    whole.
    """

    def __init__(self, base_currency: str, rates: Iterable, *, now: datetime | None = None):
        self.base_currency = (base_currency or "").upper()
        self._now = _as_utc(now) or datetime.now(timezone.utc)
        self._rates: dict[str, RateUsed] = {}
        # Rates stored against a DIFFERENT base than the one configured today.
        # Kept out of `_rates` deliberately: converting through them would be
        # arithmetic on two unrelated numbers, so they are refused by name.
        self._wrong_base: dict[str, str] = {}

        for row in rates:
            code = (getattr(row, "currency_code", None) or "").upper()
            if not code:
                continue
            stored_base = (getattr(row, "base_currency_code", None) or "").upper()
            if stored_base != self.base_currency:
                self._wrong_base[code] = stored_base
                continue
            rate = to_decimal(getattr(row, "rate_to_base", None))
            if rate is None or rate <= 0:
                # The table has a CHECK for this; a row that got past it is a
                # broken row, not a licence to divide by zero.
                continue
            set_at = _as_utc(getattr(row, "set_at", None))
            self._rates[code] = RateUsed(
                currency_code=code,
                rate_to_base=rate,
                source=getattr(row, "source", None),
                set_at=set_at,
                rate_as_of=_as_utc(getattr(row, "rate_as_of", None)),
                age_seconds=(
                    max(int((self._now - set_at).total_seconds()), 0) if set_at else None
                ),
            )

    @property
    def currencies_on_file(self) -> list[str]:
        return sorted(self._rates)

    def rate_for(self, currency_code: str | None) -> RateUsed | None:
        """The rate for one currency, or None when there is not one to use."""
        rate, _reason = self._lookup(currency_code)
        return rate

    def _lookup(self, currency_code: str | None) -> tuple[RateUsed | None, str | None]:
        code = (currency_code or "").upper()
        if not code:
            return None, "This amount does not say which currency it is in."
        if code in self._rates:
            return self._rates[code], None
        if code == self.base_currency:
            # The base currency converts to itself. A stored row for it is
            # allowed (the table's CHECK pins it to 1) but is not required, and
            # 1:1 is an identity rather than a rate anyone had to fetch.
            return (
                RateUsed(
                    currency_code=code,
                    rate_to_base=Decimal(1),
                    source=None,
                    set_at=None,
                    rate_as_of=None,
                    age_seconds=None,
                ),
                None,
            )
        if code in self._wrong_base:
            return None, (
                f"The rate on file for {code} is quoted against "
                f"{self._wrong_base[code]}, not {self.base_currency}."
            )
        return None, f"No exchange rate on file for {code}."

    def convert(self, amount, currency_code: str | None) -> ConvertedAmount:
        """One amount, converted where a rate allows and reported as-is where
        it does not. The original is always returned."""
        original = to_decimal(amount)
        code = (currency_code or "").upper() or None
        if original is None:
            # Nothing to convert is not a failure to convert: an offer with no
            # grand total simply has no money on it, and calling that a missing
            # rate would send someone off to fix the rate table.
            return ConvertedAmount(
                original_amount=None,
                original_currency=code,
                base_currency=self.base_currency,
                converted_amount=None,
                rate=None,
                unconvertible_reason=None,
            )
        rate, reason = self._lookup(code)
        if rate is None:
            return ConvertedAmount(
                original_amount=original,
                original_currency=code,
                base_currency=self.base_currency,
                converted_amount=None,
                rate=None,
                unconvertible_reason=reason,
            )
        return ConvertedAmount(
            original_amount=original,
            original_currency=code,
            base_currency=self.base_currency,
            converted_amount=quantize_money(original * rate.rate_to_base),
            rate=rate,
            unconvertible_reason=None,
        )

    def total(self, groups: Iterable[tuple[str | None, object, int]]) -> MoneyTotal:
        """Add up amounts already grouped by currency.

        Takes `(currency_code, amount, count)` triples - the shape a GROUP BY
        returns - so a total over ten thousand offers is one query and one pass,
        not ten thousand conversions.

        A currency with no rate contributes its own line to `by_currency` and
        its name to `unconvertible`, and contributes nothing to
        `converted_total`. That is the whole point: the reader is told the total
        is partial rather than being handed a smaller number that looks whole.
        """
        by_currency: list[CurrencyAmount] = []
        unconvertible: list[str] = []
        running: Decimal | None = None

        for currency_code, amount, count in groups:
            value = to_decimal(amount)
            if value is None:
                continue
            converted = self.convert(value, currency_code)
            by_currency.append(
                CurrencyAmount(
                    currency_code=converted.original_currency,
                    amount=value,
                    offer_count=int(count or 0),
                    converted_amount=converted.converted_amount,
                    rate=converted.rate,
                    unconvertible_reason=converted.unconvertible_reason,
                )
            )
            if converted.converted_amount is None:
                # Named so somebody can act on it. An amount with no currency at
                # all has no name to report, and is left to `by_currency`.
                if converted.original_currency:
                    unconvertible.append(converted.original_currency)
                continue
            running = (
                converted.converted_amount
                if running is None
                else running + converted.converted_amount
            )

        by_currency.sort(key=lambda row: (row.currency_code is None, row.currency_code or ""))
        return MoneyTotal(
            base_currency=self.base_currency,
            converted_total=quantize_money(running),
            by_currency=by_currency,
            unconvertible=sorted(set(unconvertible)),
        )
