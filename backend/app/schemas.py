from typing import Dict, List, Optional

from pydantic import BaseModel


class RegisterIn(BaseModel):
    fullName: str
    studentId: str
    email: str
    password: str
    program: str
    yearLevel: str


class LoginIn(BaseModel):
    email: str
    password: str


class ResetRequestIn(BaseModel):
    email: str


class ResetConfirmIn(BaseModel):
    email: str
    newPassword: str


class ChangePasswordIn(BaseModel):
    currentPassword: str
    newPassword: str


class ProfileIn(BaseModel):
    program: str
    yearLevel: str


class AccountIn(BaseModel):
    role: str
    fullName: str
    email: str
    password: str


class AccountUpdateIn(BaseModel):
    role: str
    fullName: str
    email: str
    password: Optional[str] = ""


class TermIn(BaseModel):
    trimester: str
    academicYear: str


class ScholarshipIn(BaseModel):
    key: str
    status: str
    benefit: str
    deadline: str
    deadlineAt: Optional[str] = None
    eligibility: List[str]


class ScholarshipsIn(BaseModel):
    scholarships: List[ScholarshipIn]


class DocumentIn(BaseModel):
    name: str
    path: str
    sizeBytes: Optional[int] = None
    mimeType: Optional[str] = None


class ApplicationIn(BaseModel):
    id: str
    termId: Optional[str] = None
    program: str
    yearLevel: str
    scholarshipType: str
    documents: Dict[str, DocumentIn]
    gwa: Optional[float] = None
    lowestGrade: Optional[float] = None
    hasFailingGrade: bool = False
    hasIncompleteGrade: bool = False
    hasDroppedGrade: bool = False


class StatusIn(BaseModel):
    status: str
    remarks: Optional[str] = ""
    discountPercent: Optional[float] = None


class DocumentReviewIn(BaseModel):
    review: str
    reason: Optional[str] = ""


class AllowResubmissionIn(BaseModel):
    reason: str


class DiscountIn(BaseModel):
    discountPercent: Optional[float] = None


class ReopenIn(BaseModel):
    reason: str


class AppealIn(BaseModel):
    reason: str


class AppealResponseIn(BaseModel):
    decision: str
    response: Optional[str] = ""


class DutyIn(BaseModel):
    hours: int
    completed: bool = False


class UploadUrlIn(BaseModel):
    path: str
    applicationId: str
    requirementKey: str
    fileName: str
    contentType: str
    sizeBytes: int


class PathsIn(BaseModel):
    paths: List[str]
