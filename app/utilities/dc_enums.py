from enum import Enum

class SupportedLlms(Enum):
    GPT_OSS_120B = "gpt-oss-120b"
    DEEPSEEK_V4_FLASH_OPENROUTER = "deepseek_v4_flash_openrouter"
    DEEPSEEK_V4_PRO_OPENROUTER = "deepseek_v4_pro_openrouter"
    TENCENT_HY3_PREVIEW_OPENROUTER = "tencent_hy3_preview_openrouter"
