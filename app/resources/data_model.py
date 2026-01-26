from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List
from datetime import datetime
from typing import Any, Optional, Union
from app.utilities.dc_enums import ChatType, NotificationStatus


class JiraTestCaseID(BaseModel):
    test_case_unique_id: str
    project_id: int
class UpdateTestCaseRequest(BaseModel):
    chat_id: str
    project_id: str
    test_case_id: str
    test_case_unique_id: str
    # comments can be a JSON object or plain string
    comments: Union[dict, str]


class UserBase(BaseModel):
    username: Optional[str] = None


class UserCreate(UserBase):
    email: EmailStr
    password: str = Field(..., min_length=6)  # min length in characters

    # @validator('password')
    # def validate_password(cls, v):
    #     # Check the actual UTF-8 encoded byte length
    #     if len(v.encode('utf-8')) > 72:  # bcrypt has a 72-byte limit
    #         raise ValueError('password cannot be longer than 72 bytes when UTF-8 encoded')
    #     return v


class UserOut(BaseModel):
    id: int
    email: str
    name: Optional[str] = None
    username: Optional[str] = None
    jira_email: Optional[str] = None
    jira_api_token: Optional[str] = None
    jira_api_url: Optional[str] = None
    created_at: datetime

    model_config = {
        # This is the new way in Pydantic V2 to enable ORM mode
        "from_attributes": True
    }

    
class UserUpdate(BaseModel):
    name: Optional[str] = None
    jira_email: Optional[str] = None
    jira_api_token: Optional[str] = None
    jira_api_url : Optional[str] = None



class UserLogin(BaseModel):
    email: EmailStr
    password: str


class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None
    status: str = "active"
    jira_project_id: Optional[str] = None


class ProjectCreate(ProjectBase):
    pass


class ProjectOut(ProjectBase):
    id: int
    user_id: int
    created_at: datetime

    model_config = {
        "from_attributes": True
    }


class ChatBase(BaseModel):
    title: Optional[str] = None
    project_id: int


class ChatCreate(ChatBase):
    chat_type: ChatType

class ChatOut(ChatBase):
    id: int
    user_id: int
    project_id: int
    created_at: datetime
    chat_type: ChatType
    model_config = {
        "from_attributes": True
    }


class MessageBase(BaseModel):
    content: Optional[str] = None
    file_type: Optional[str] = None
    file_name: Optional[str] = None
    file_url: Optional[str] = None
    invoke_type: Optional[str] = None
    test_case: Optional[List[dict]] = None  # For test case approval responses


class MessageCreate(MessageBase):
    pass


class MessageOut(MessageBase):
    id: int
    chat_id: int
    sender: str
    timestamp: datetime
    model_config= {"from_attributes": True}

class ChatBotResponse(BaseModel):
    type: str  # 'ai_response' or 'user_interrupt'
    response: str


class ExecuteTestCasesRequest(BaseModel):
    """Request model for test case execution"""
    test_context: str
    generated_test_cases: dict
    session_id: Optional[str] = None


class ExecuteTestCasesFromMongoRequest(BaseModel):
    """Request model for executing test cases from MongoDB"""
    project_id: str
    chat_id: str
    test_case_ids: List[str]

class TestCase(BaseModel):
    project_id: str
    chat_id: str
    status: str
    created_at: str
    updated_at: str
    test_case_id: str
    title: str
    module_feature: str
    priority: str
    preconditions: str
    test_steps: list[str]
    test_data: str
    expected_result: str
    actual_result: str = ""  
    error_log: str | None = None 
    test_case_unique_id: str

class TestCaseExecutionResult(BaseModel):
    """Result for a single test case execution"""
    test_case_unique_id: str  # MongoDB _id as string for mapping
    test_case_id: str  # MongoDB _id as string
    test_case: dict  # Original test case
    status: str  # 'passed', 'failed', 'error'
    actual_result: Optional[str] = None
    error_log: Optional[str] = None
    executed_at: Optional[datetime] = None


class ExecuteTestCasesResponse(BaseModel):
    """Response model for test case execution"""
    type: str
    response: str
    test_results: Optional[List[TestCaseExecutionResult]] = None
    message: Optional[str] = None
    message: str

class NotificationOut(BaseModel):
    """Response model for notifications"""
    id: int
    user_id: int
    chat_id: Optional[int] = None
    project_id: Optional[int] = None
    message: str
    status: NotificationStatus
    created_at: datetime
    
    model_config = {
        "from_attributes": True
    }

class TestCaseListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    test_cases: List[dict]


class DeleteTestCasesRequest(BaseModel):
    """Request model for soft deleting test cases"""
    test_case_unique_ids: List[str]  # List of MongoDB ObjectId strings

class ExportTestCasesRequest(BaseModel):
    """Request model for exporting test cases"""
    test_case_unique_ids: List[str]  # List of MongoDB ObjectId strings


# ==================== REPORTS API SCHEMAS ====================

# ---- Filter Options Response (API #1) ----
class ProjectFilterOption(BaseModel):
    """Project option for filter dropdown"""
    project_id: int
    project_name: str
    session_count: int


class SessionFilterOption(BaseModel):
    """Session option for filter dropdown"""
    session_id: str
    session_name: str
    project_id: int
    session_type: str
    created_at: datetime
    test_case_count: int


class FilterOptionsResponse(BaseModel):
    """Response for GET /reports/filter-options"""
    projects: List[ProjectFilterOption]
    sessions: List[SessionFilterOption]
    priorities: List[str]
    modules: List[str]
    statuses: List[str]


# ---- Get Reports Request & Response (API #2) ----
class ReportFilters(BaseModel):
    """Filters for report generation"""
    project_ids: Optional[List[int]] = None
    session_ids: Optional[List[str]] = None
    test_case_status: Optional[List[str]] = None  # ["Pass", "Fail", "New"]
    priority: Optional[List[str]] = None
    modules: Optional[List[str]] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    page: int = 1
    page_size: int = 10


class GetReportsRequest(BaseModel):
    """Request body for POST /reports/get-reports"""
    filters: ReportFilters


class KPISummary(BaseModel):
    """KPI metrics summary"""
    total_test_cases: int
    total_passed: int
    total_failed: int
    total_new: int
    overall_pass_rate: float
    date_range: dict  # {"from": datetime, "to": datetime}


class TestCaseMetrics(BaseModel):
    """Test case metrics for a session"""
    total_test_cases: int
    test_cases_passed: int
    test_cases_failed: int
    test_cases_new: int
    pass_rate_percentage: float
    modules_covered: List[str]
    module_count: int


class SessionReport(BaseModel):
    """Report data for a single session"""
    session_id: str
    session_name: str
    project_id: int
    project_name: str
    session_type: str
    created_at: datetime
    test_case_metrics: TestCaseMetrics


class PaginationInfo(BaseModel):
    """Pagination metadata"""
    current_page: int
    total_pages: int
    total_records: int
    page_size: int
    has_next: bool
    has_prev: bool


class GetReportsResponse(BaseModel):
    """Response for POST /reports/get-reports"""
    kpi_summary: KPISummary
    reports: List[SessionReport]
    pagination: PaginationInfo


# ---- Session Test Cases Request & Response (API #3) ----
class SessionInfo(BaseModel):
    """Information about a session"""
    session_id: str
    session_name: str
    project_name: str
    created_at: datetime
    total_test_cases: int


class TestCaseDetail(BaseModel):
    """Detailed test case information"""
    test_case_id: str
    test_case_unique_id: str
    title: str
    module: str
    priority: str
    status: str
    steps: List[str]
    expected_result: str
    actual_result: Optional[str] = None
    execution_time_seconds: Optional[int] = None
    trace_available: bool
    trace_url: str
    created_at: datetime


class SessionTestCasesResponse(BaseModel):
    """Response for GET /reports/sessions/{session_id}/test-cases"""
    session_info: SessionInfo
    test_cases: List[TestCaseDetail]
    pagination: PaginationInfo


# ---- Export Request & Response (API #4) ----
class ExportReportRequest(BaseModel):
    """Request body for POST /reports/export"""
    export_format: str  # "csv" (currently only CSV)
    filters: ReportFilters
    export_type: str  # "summary" or "detailed"


class ExportReportResponse(BaseModel):
    """Response for export - returns file stream, but this is the metadata"""
    message: str
    export_format: str
    export_type: str
    total_records: int