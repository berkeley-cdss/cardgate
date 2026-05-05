from pydantic import BaseModel, Field
from typing import Optional


class Person(BaseModel):
    """
    Standardized data model for a person, regardless of source (HR, SIS).
    """

    id: str = Field(..., description="The Student ID (SID) or Employee ID (EID)")
    first_name: str
    last_name: str
    middle_initial: str = ""
    email: Optional[str] = None
    role: str = Field(
        ...,
        description="Role type: Faculty, Staff, Postdoc, PhD, MA, BA, Course-enrolled, Course-staff",
    )
    card_key_number: Optional[str] = None
