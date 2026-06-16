from pydantic import BaseModel, Field
from typing import Optional


class Person(BaseModel):
    """
    Standardized data model for a person, regardless of source (HR, SIS).
    """

    id: str = Field(..., description="The Student ID (SID) or Employee ID (EID)")
    uid: Optional[str] = Field(None, description="The CalNet UID (Campus UID)")
    first_name: str
    last_name: str
    middle_initial: str = ""
    email: Optional[str] = None
    role: str = Field(
        ...,
        description="Role type: Faculty, Staff, Postdoc, PhD, MA, BA, Course-enrolled, Course-staff",
    )
    department: str = ""
    seos_number: Optional[str] = None  # 7-digit high frequency (seos)
    lowprox_number: Optional[str] = None   # 6-digit low frequency (lowprox)
