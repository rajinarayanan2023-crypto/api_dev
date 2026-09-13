from decimal import Decimal

from pydantic import BaseModel


class DashboardSummaryOut(BaseModel):
    petrol_litres: Decimal
    diesel_litres: Decimal
    oil_machine_litres: Decimal
    oil_packet_units: Decimal
    oil_packet_amount: Decimal
    oil_cane_units: Decimal
    oil_cane_amount: Decimal
    commission_earned: Decimal
    total_expenses: Decimal
    profit: Decimal
    rate_status: str
