from enum import Enum

class SupportedLlms(Enum):
    LLAMA3_GROQ_70B_VERSATILE = "llama-3.3-70b-versatile"
    MOONSHOT_KIMI_K2_INSTRUCT_0905 = "moonshot_kimi_k2_instruct_0905"
    GPT_OSS_120B = "gpt-oss-120b"
    GEMINI_2_5_FLASH = "gemini_2_5_flash"
    GEMINI_2_5_FLASH_LITE = "gemini_2_5_flash_lite"
    GEMINI_2_5_PRO = "gemini_2_5_pro"
    GPT_4O = "gpt_4o"
    GPT_4O_MINI = "gpt_4o_mini"
    O1_PREVIEW = "o1_preview"
    O1_MINI = "o1_mini"

class ChatState(Enum):
    TESTING = "testing"
    TEST_CASE = "test_case"
    FINAL_REPORT = "final_report"

class ChatType(Enum):
    QUICK_SESSION = "quick_session"
    TEST_CASE_DISCOVERY = "test_case_discovery"
    GENERAL_CHAT = "general_chat"

class NotificationStatus(Enum):
    UNREAD = "unread"
    READ = "read"