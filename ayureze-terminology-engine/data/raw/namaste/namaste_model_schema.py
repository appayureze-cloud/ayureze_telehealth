from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class NAMASTECode(BaseModel):
    namaste_code: str
    term_english: str
    term_original: str
    system: str  # Ayurveda / Siddha / Unani
    category: str
    tm2_code: Optional[str] = None
    tm2_display: Optional[str] = None
    icd_biomedicine_code: Optional[str] = None
    icd_biomedicine_display: Optional[str] = None
    confidence_score: Optional[float] = None
    mapping_status: str = "unmapped"  # unmapped / partial / complete
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
