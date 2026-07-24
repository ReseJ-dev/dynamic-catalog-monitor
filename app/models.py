"""Application-level models for catalog data and comparison results."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

ComparableValue = str | int | float | bool | Decimal | datetime | None


class Product(BaseModel):
    """A normalized and validated product collected from the catalog."""

    model_config = ConfigDict(str_strip_whitespace=True)

    product_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    category: str | None = None
    price: Decimal = Field(ge=0)
    currency: str = Field(min_length=1)
    availability: str = Field(min_length=1)
    rating: float | None = Field(default=None, ge=0.0, le=5.0)
    description: str | None = None
    image_url: HttpUrl | None = None
    product_url: HttpUrl
    scraped_at: datetime

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        """Normalize a textual currency code to uppercase."""

        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("scraped_at")
    @classmethod
    def require_timezone_aware_datetime(cls, value: datetime) -> datetime:
        """Reject timestamps without a usable UTC offset."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("scraped_at must be timezone-aware")
        return value


class RawProduct(BaseModel):
    """Unmodified values extracted by the scraper before normalization."""

    product_id: str | None = None
    title: str | None = None
    category: str | None = None
    price: str | None = None
    currency: str | None = None
    availability: str | None = None
    rating: str | None = None
    description: str | None = None
    image_url: str | None = None
    product_url: str | None = None
    scraped_at: datetime


class InvalidRecord(BaseModel):
    """A raw product that could not be converted into a valid product."""

    raw_product: RawProduct
    errors: list[str] = Field(default_factory=list)


class FieldChange(BaseModel):
    """A changed non-specialized field for an existing product."""

    product_id: str
    field_name: str
    old_value: ComparableValue
    new_value: ComparableValue


class PriceChange(BaseModel):
    """A price change for an existing product."""

    product_id: str
    old_price: Decimal = Field(ge=0)
    new_price: Decimal = Field(ge=0)
    difference: Decimal | None = None
    percentage_change: Decimal | None = None


class AvailabilityChange(BaseModel):
    """An availability change for an existing product."""

    product_id: str
    old_availability: str
    new_availability: str


class ComparisonResult(BaseModel):
    """Products and field-level changes between two catalog snapshots."""

    added_products: list[Product] = Field(default_factory=list)
    removed_products: list[Product] = Field(default_factory=list)
    field_changes: list[FieldChange] = Field(default_factory=list)
    price_changes: list[PriceChange] = Field(default_factory=list)
    availability_changes: list[AvailabilityChange] = Field(default_factory=list)


class RunSummary(BaseModel):
    """Counts and errors produced by a catalog monitoring run."""

    total_scraped: int = Field(default=0, ge=0)
    valid_products: int = Field(default=0, ge=0)
    invalid_records: int = Field(default=0, ge=0)
    duplicates_removed: int = Field(default=0, ge=0)
    added_products: int = Field(default=0, ge=0)
    removed_products: int = Field(default=0, ge=0)
    changed_products: int = Field(default=0, ge=0)
    errors: list[str] = Field(default_factory=list)
