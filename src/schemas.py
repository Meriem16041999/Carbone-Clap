from typing import Optional, List
from pydantic import BaseModel

class RideRow(BaseModel):
    cheque_or_course: Optional[str] = None
    date_time_start: Optional[str] = None
    date_time_end: Optional[str] = None
    pickup_address: Optional[str] = None
    destination_address: Optional[str] = None
    passenger: Optional[str] = None
    reported_km: Optional[float] = None

    km_computed: Optional[float] = None  # ✅ AJOUT ICI

class RidesExtraction(BaseModel):
    rows: List[RideRow] = []
