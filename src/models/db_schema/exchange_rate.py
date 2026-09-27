from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.enums import ExchangeRateSource

from .base import Base

EXCHANGE_RATE_SOURCE_VALUES = tuple(source.value for source in ExchangeRateSource)


class ExchangeRate(Base):
    """The current rate for one currency against the configured base currency.

    One row per currency, overwritten in place - there is no history here on
    purpose. A total converted last month and the same total converted today
    would otherwise disagree on a screen that lines them up side by side, and
    the client's question is "what is this worth", not "what was it worth when
    we read it".

    A currency with no row simply has no rate. That is the normal state of this
    table on a fresh install, and the reading code has to handle it anyway the
    moment one offer quotes a currency nobody has ever set: show the original
    figure, say that it could not be converted, and never substitute a number
    of its own.
    """

    __tablename__ = "exchange_rates"
    __table_args__ = (
        CheckConstraint(
            f"source IN {EXCHANGE_RATE_SOURCE_VALUES}", name="ck_exchange_rates_source"
        ),
        CheckConstraint("rate_to_base > 0", name="ck_exchange_rates_rate_positive"),
        # The base currency's own rate, if a row for it exists at all, can only
        # be 1.
        CheckConstraint(
            "currency_code <> base_currency_code OR rate_to_base = 1",
            name="ck_exchange_rates_base_is_one",
        ),
    )

    currency_code: Mapped[str] = mapped_column(
        Text, ForeignKey("currencies.code", ondelete="CASCADE"), primary_key=True
    )
    # Stored, not assumed. The base currency is configurable, and a rate
    # fetched against EGP is wrong the moment the base becomes USD - with the
    # base on the row, the reading code can refuse to convert instead of
    # quietly reporting a number that means nothing.
    base_currency_code: Mapped[str] = mapped_column(
        Text, ForeignKey("currencies.code"), nullable=False
    )
    # Numeric, never a float. Money run through a binary float stops adding up,
    # and re-adding other people's arithmetic is what this application is for.
    rate_to_base: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)

    # The provider's own "as of", which is a different fact from `set_at`: a
    # refresh that ran a minute ago can still be carrying yesterday's published
    # rate. NULL when a person typed the rate.
    rate_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # When this row was last written. Every response that converts money
    # reports the age measured from here, so nobody has to guess whether the
    # figure they are reading is a week old.
    set_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    # Who typed it. NULL for an API refresh - and also for a manual rate whose
    # author's account has since been deleted, which is why nothing constrains
    # 'manual' to a non-null user.
    set_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
