"""SQLAlchemy models for catalog products, snapshots, and scrape runs."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all persistence models."""


class ProductRecord(Base):
    """The durable identity and current descriptive fields of a product."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str | None] = mapped_column(String(255))
    product_url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_product_url: Mapped[str] = mapped_column(
        Text,
        unique=True,
        index=True,
        nullable=False,
    )
    image_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    snapshots: Mapped[list[ProductSnapshot]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )


class ScrapeRun(Base):
    """Metadata and outcome for one catalog scraping execution."""

    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    products_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    products_valid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    products_invalid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)

    snapshots: Mapped[list[ProductSnapshot]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class ProductSnapshot(Base):
    """A product's observed dynamic fields during a specific scrape run."""

    __tablename__ = "product_snapshots"
    __table_args__ = (
        UniqueConstraint("product_id", "run_id", name="uq_product_snapshots_product_run"),
        Index("ix_product_snapshots_run_id", "run_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2, asdecimal=True), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    availability: Mapped[str] = mapped_column(String(64), nullable=False)
    rating: Mapped[float | None] = mapped_column(nullable=True)
    description: Mapped[str | None] = mapped_column(Text)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("scrape_runs.id", ondelete="CASCADE"),
        nullable=False,
    )

    product: Mapped[ProductRecord] = relationship(back_populates="snapshots")
    run: Mapped[ScrapeRun] = relationship(back_populates="snapshots")
