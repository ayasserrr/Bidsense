from enum import Enum


class PriceBasis(str, Enum):
    FIXED = "fixed"
    PERCENTAGE_OF_PARENT = "percentage_of_parent"
    INCLUDED_NO_CHARGE = "included_no_charge"
    TBD = "tbd"


class EntityType(str, Enum):
    ITEM = "item"
    OFFER = "offer"


class EntryType(str, Enum):
    INCLUDE = "include"
    EXCLUDE = "exclude"


# Not exhaustive of every real-world procurement category - a reasonable
# starting controlled vocabulary for offer_items.item_category. Extending it
# only requires a new migration updating the CHECK constraint, not a schema
# rewrite, so treat this list as safe to grow later rather than as final.
class ItemCategory(str, Enum):
    EQUIPMENT = "equipment"
    ACCESSORY = "accessory"
    SPARE_PART = "spare_part"
    INSTALLATION = "installation"
    SERVICE = "service"
    WARRANTY = "warranty"
    TRAINING = "training"
    SOFTWARE = "software"
    CIVIL_WORKS = "civil_works"
    TRANSPORTATION = "transportation"
    OTHER = "other"


# The fixed ISO-4217 set the extraction prompts require currency_primary,
# grand_total_currency, price_currency, and stated_subtotal_currency to be
# mapped into - matches the currencies table's seed data one-to-one.
class CurrencyCode(str, Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    EGP = "EGP"
    SAR = "SAR"
    AED = "AED"
    QAR = "QAR"
    KWD = "KWD"
    BHD = "BHD"
    OMR = "OMR"
    JOD = "JOD"
    LYD = "LYD"
    IQD = "IQD"
    LBP = "LBP"
    CHF = "CHF"
    JPY = "JPY"
    CNY = "CNY"
    INR = "INR"
    TRY = "TRY"
    CAD = "CAD"
    AUD = "AUD"
    ZAR = "ZAR"
    SEK = "SEK"
    NOK = "NOK"
    DKK = "DKK"
    KRW = "KRW"
    SGD = "SGD"
