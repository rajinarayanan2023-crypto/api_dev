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

    purchase_history: Mapped[list["LubricantPurchaseHistory"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", order_by="LubricantPurchaseHistory.date"
    )


# The app no longer reads or writes this table (the "Revise Price" feature
# it backed was removed as a purely display-only concern isolated to the
# Lubricants page — Pump 2's oil pricing has always been driven entirely by
# LubricantPurchaseHistory's cost, a separate table). The model stays
# registered here, with no relationship back from LubricantProduct, so that
# an `alembic revision --autogenerate` run against this metadata doesn't
# propose dropping the still-existing Lubricant_Price_History table/rows.
class LubricantPriceHistory(Base, UUIDPkMixin, AuditMixin):
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
    previous_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))


class LubricantPurchaseHistory(Base, UUIDPkMixin, AuditMixin):
    """Every restock — acquisition cost, separate from the sale rate above.

    Gained AuditMixin for the same reason as LubricantPriceHistory above —
    an acquisition cost worth reconciling later is worth knowing who entered
    it and when.
    """

    __tablename__ = "Lubricant_Purchase_History"
    __table_args__ = (Index("idx_lubricant_purchase_history_product", "product_id", "date"),)

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Lubricant_Products.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    product: Mapped["LubricantProduct"] = relationship(back_populates="purchase_history")
