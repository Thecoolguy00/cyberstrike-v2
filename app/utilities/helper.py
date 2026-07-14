from app.utilities import dc_logger
from app.utilities.singletons_factory import DcSingleton
from datetime import datetime, timezone
logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__))


class Helper(metaclass = DcSingleton):

    @staticmethod
    def utc_now() -> datetime:
        """Canonical UTC timestamp (datetime) — matches DB default format."""
        return datetime.now(timezone.utc)
    
    @staticmethod
    def utc_now_str() -> str:
        """Canonical UTC timestamp string — matches DB default format."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")