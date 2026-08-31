import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Integer, Numeric, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditMixin, Base, UUIDPkMixin


class LubricantProduct(Base, UUIDPkMixin, AuditMixin):
    __tablename__ = "Lubricant_Products"
    __table_args__ = (CheckConstraint("packaging IN ('packet', 'cane')", name="ck_lubricant_products_packaging"),)

    name: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'Pcs'"))
    packaging: Mapped[str] = mapped_column(Text, nullable=False)
    # Numeric, not Integer — Pump 2's nozzle-dispensed oil decrements this in
    # fractional litres (see FuelEntryService), even though most products
    # here are whole-unit packets/cans.
    stock: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, server_default=text("0"))

    price_history: Mapped[list["LubricantPriceHistory"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", order_by="LubricantPriceHistory.effective_from"
    )
    purchase_history: Mapped[list["LubricantPurchaseHistory"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", order_by="LubricantPurchaseHistory.date"
    )


class LubricantPriceHistory(Base, UUIDPkMixin):
    """Sale rate in force on any date = latest row with effective_from <= that date."""

    __tablename__ = "Lubricant_Price_History"
    __table_args__ = (
        UniqueConstraint("product_id", "effective_from", name="uq_lubricant_price_history"),
        Index("idx_lubricant_price_history_product", "product_id", "effective_from"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Lubricant_Products.id", ondelete="CASCADE"), nullable=False
    )
    rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)

    product: Mapped["LubricantProduct"] = relationship(back_populates="price_history")


class LubricantPurchaseHistory(Base, UUIDPkMixin):
    """Every restock — acquisition cost, separate from the sale rate above."""

    __tablename__ = "Lubricant_Purchase_History"
    __table_args__ = (Index("idx_lubricant_purchase_history_product", "product_id", "date"),)

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Lubricant_Products.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    product: Mapped["LubricantProduct"] = relationship(back_populates="purchase_history")
