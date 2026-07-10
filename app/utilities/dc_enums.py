from enum import Enum

class SupportedLlms(Enum):
    OPENROUTER_DEEPSEEK_V4_PRO = "openrouter_deepseek_v4_flash"
    OPENROUTER_DEEPSEEK_V4_FLASH = "openrouter_deepseek_v4_pro"
    OPENROUTER_TENCENT_HY3_PREVIEW = "openrouter_tencent_hy3_preview"
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
    MISTRAL_LARGE="mistral_large"
    MISTRAL_MEDIUM="mistral_medium"
