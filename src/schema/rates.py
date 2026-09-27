"""What the rates screen sends and receives, and the money shapes every other
response converts into.

Every response here reports where a rate came from, who put it there and how
old it is, because those are the three questions somebody asks before trusting
a converted total - and none of them can be answered from the number alone.

Every amount and every rate crosses the wire as a JSON **string** holding an
exact decimal ("4287500.00", "0.0206185567"). That is pydantic's own treatment
of `Decimal`, and it is the right one here: a grand total routed through a
binary float stops re-adding to the same number, which is the exact failure
this application exists to catch in other people's documents.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from helpers import money as money_helper
from models.enums import ExchangeRateSource


class ExchangeRateOut(BaseModel):
    """One currency's current rate."""

    currency_code: str
    base_currency_code: str
    # How many units of the base currency one unit of `currency_code` is worth.
    # Serialised as a string so the exact NUMERIC(20,10) survives JSON - a rate
    # rounded on the way out stops reproducing the totals computed with it.
    rate_to_base: Decimal
    source: ExchangeRateSource
    # The provider's own "as of". Null for a hand-typed rate, and different
    # from `set_at`: a refresh that ran a minute ago can be carrying
    # yesterday's published rate.
    rate_as_of: datetime | None = None
    set_at: datetime
    # Seconds since `set_at`. Computed server-side so every screen ages a rate
    # the same way.
    age_seconds: int
    set_by_user_id: int | None = None
    # Snapshot-free: joined from `users` at read time, so a renamed account
    # reads correctly and a deleted one simply has no name.
    set_by: str | None = None


class RatesResponse(BaseModel):
    """Every rate on file, plus what the server is configured to do about
    them."""

    base_currency: str
    rates: list[ExchangeRateOut] = Field(default_factory=list)
    # Currencies this application knows (the `currencies` table) that have no
    # rate yet. Listed so the screen can offer them rather than making somebody
    # guess which codes are accepted.
    currencies_without_a_rate: list[str] = Field(default_factory=list)
    # False on a firewalled server: the refresh button should say so rather
    # than failing when pressed.
    fetch_enabled: bool
    api_url: str
    fetched_at: datetime | None = None


class ManualRateRequest(BaseModel):
    """One rate, typed by hand. Any signed-in user may send this."""

    currency_code: str = Field(min_length=3, max_length=3)
    # Greater than zero, enforced here and again by a CHECK on the table.
    rate_to_base: Decimal = Field(gt=0)


class RateRefreshResponse(BaseModel):
    """The result of asking the provider for today's rates.

    `ok` is false for every kind of failure - unreachable, malformed, wrong
    base, switched off - and `message` is the sentence to show. The response
    still carries `rates`, unchanged, because a failed refresh changes nothing
    and the screen must keep showing what is on file rather than emptying
    itself. That is also why this is a 200 and not a 502: nothing is broken
    here, the provider simply had nothing to give.
    """

    ok: bool
    message: str
    # Currencies written by this refresh.
    updated: list[str] = Field(default_factory=list)
    # Currencies left alone because somebody had typed them in by hand. A
    # refresh does not silently overwrite a person's judgement; sending
    # `overwrite_manual=true` is the deliberate choice that does.
    kept_manual: list[str] = Field(default_factory=list)
    # Currencies the provider quoted that this application does not know, and
    # ones it knows that the provider did not quote.
    skipped: list[str] = Field(default_factory=list)
    rates: RatesResponse


# --- the money shapes every converted figure is returned in -----------------
# Built from `helpers.money`, which does the arithmetic, so the rules about a
# missing rate are enforced in one place and merely reported here.


class MoneyRate(BaseModel):
    """The rate one converted figure was computed with."""

    currency_code: str
    rate_to_base: Decimal
    # Null means the base currency converting to itself - an identity, not a
    # rate anybody fetched or typed.
    source: ExchangeRateSource | None = None
    set_at: datetime | None = None
    rate_as_of: datetime | None = None
    age_seconds: int | None = None

    @classmethod
    def of(cls, rate: money_helper.RateUsed | None) -> "MoneyRate | None":
        if rate is None:
            return None
        return cls(
            currency_code=rate.currency_code,
            rate_to_base=rate.rate_to_base,
            source=ExchangeRateSource(rate.source) if rate.source else None,
            set_at=rate.set_at,
            rate_as_of=rate.rate_as_of,
            age_seconds=rate.age_seconds,
        )


class ConvertedMoney(BaseModel):
    """One amount, in the currency the supplier wrote and in the base currency.

    `original_amount` and `original_currency` are ALWAYS filled in where there
    is an amount at all. `converted_amount` is null when no rate could be used,
    and `unconvertible_reason` then says why - the screen shows the original
    and the sentence, and never a substituted figure.
    """

    original_amount: Decimal | None = None
    original_currency: str | None = None
    base_currency: str
    converted_amount: Decimal | None = None
    rate: MoneyRate | None = None
    unconvertible_reason: str | None = None

    @classmethod
    def of(cls, converted: money_helper.ConvertedAmount) -> "ConvertedMoney":
        return cls(
            original_amount=converted.original_amount,
            original_currency=converted.original_currency,
            base_currency=converted.base_currency,
            converted_amount=converted.converted_amount,
            rate=MoneyRate.of(converted.rate),
            unconvertible_reason=converted.unconvertible_reason,
        )


class CurrencyTotal(BaseModel):
    """One currency's share of a total."""

    currency_code: str | None = None
    amount: Decimal
    offer_count: int
    converted_amount: Decimal | None = None
    rate: MoneyRate | None = None
    unconvertible_reason: str | None = None


class MoneyTotalOut(BaseModel):
    """A total that says what it could not include.

    `converted_total` is the sum of the currencies that had a rate. Read
    `is_complete` before presenting it as the whole figure: when it is false,
    the money in `unconvertible_currencies` is in `by_currency` and NOT in the
    total, which is the honest alternative to dropping those offers silently.
    """

    base_currency: str
    converted_total: Decimal | None = None
    is_complete: bool
    by_currency: list[CurrencyTotal] = Field(default_factory=list)
    unconvertible_currencies: list[str] = Field(default_factory=list)

    @classmethod
    def of(cls, total: money_helper.MoneyTotal) -> "MoneyTotalOut":
        return cls(
            base_currency=total.base_currency,
            converted_total=total.converted_total,
            is_complete=total.is_complete,
            by_currency=[
                CurrencyTotal(
                    currency_code=row.currency_code,
                    amount=row.amount,
                    offer_count=row.offer_count,
                    converted_amount=row.converted_amount,
                    rate=MoneyRate.of(row.rate),
                    unconvertible_reason=row.unconvertible_reason,
                )
                for row in total.by_currency
            ],
            unconvertible_currencies=total.unconvertible,
        )
