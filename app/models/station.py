from sqlalchemy import ARRAY, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuditMixin, Base, UUIDPkMixin

# Not part of the supplied schema — added because the UI reads/writes a
# dealership profile (name, brand, GSTIN, address, mobiles, logo,
# audit_contact_email) across Landing/Login/Layout/Offers/Credit Bills, and
# audit_contact_email is actively edited from the Fuel Entry audit modal. In
# practice a single row — enforced at the service layer, not the schema.


class Station(Base, UUIDPkMixin, AuditMixin):
    __tablename__ = "Stations"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[str | None] = mapped_column(Text)
    dealer_type: Mapped[str | None] = mapped_column(Text)
    sap_no: Mapped[str | None] = mapped_column(Text)
    gstin: Mapped[str | None] = mapped_column(Text)
    dealer_name: Mapped[str | None] = mapped_column(Text)
    address_lines: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    location: Mapped[str | None] = mapped_column(Text)
    mobiles: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    email: Mapped[str | None] = mapped_column(Text)
    logo_url: Mapped[str | None] = mapped_column(Text)
    photo_url: Mapped[str | None] = mapped_column(Text)
    audit_contact_email: Mapped[str | None] = mapped_column(Text)
