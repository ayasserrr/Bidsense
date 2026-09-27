from enum import Enum


class ExchangeRateSource(str, Enum):
    """Where the rate on file came from.

    Two values, and the difference is not cosmetic: `manual` is somebody's
    judgement, carries their name on the row, and must never be silently
    overwritten by the next refresh without that being a deliberate choice.
    `api` is whatever the configured provider last published.

    There is no `default` or `assumed` value on purpose. A currency with no row
    has no rate, and the only honest thing to do with it is to show the
    original figure and say so - inventing a rate would turn an unconvertible
    total into a wrong one, which is the failure this application exists to
    catch in other people's documents.
    """

    API = "api"
    MANUAL = "manual"
