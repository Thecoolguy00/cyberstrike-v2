"""Prompt fetcher utility.

Singleton class to load configured prompts from MongoDB and cache them in memory.
Only the prompt name and prompt text are stored (mapping prompt_name -> prompt_text).

It reads the mapping of prompts and versions from `constants.yaml` under the key
`prompts_cofig` (keeps tolerant lookup for `prompts_config` too).
"""
from typing import Dict, Any

from app.utilities import dc_logger
from app.utilities.constants import Constants
from app.utilities.singletons_factory import DcSingleton
from app.utilities.db_utilities.mongo_implementation import MongoImplement
from app.utilities.dc_exception import MissingPromptException

mcp_config_path = Constants.fetch_constant("mcp_server_config")["playwright_config"]


logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__), {"PromptFetcher": "v1"})

# Collection name for prompts (from constants)
MONGO_PROMPT_COLLECTION = Constants.fetch_constant("mongodb_config")["prompts_collection"]


class PromptFetcher(metaclass=DcSingleton):
    """Singleton responsible for loading and caching prompts from MongoDB.
    """

    def __init__(self):
        self._client = MongoImplement()
        self.prompts: Dict[str, str] = {}
        logger.info("PromptFetcher initialized")
        # try initial load, but don't raise on failure
        try:
            self.refresh()
        except Exception:
            logger.exception("Initial prompt cache load failed")

    def get_prompt_version(self, name: str, version: int) -> str | None:
        """Fetch prompt text for `name` with specific `version` from MongoDB.
        
        Args:
            name: The prompt name
            version: The version number to fetch
            
        Returns:
            The prompt text if found, None otherwise.
        """
        try:
            query = {"prompt_name": name, "version": version }
            docs = self._client.read(MONGO_PROMPT_COLLECTION, query)
            if not docs:
                logger.warning("No document found for prompt %s version %s", name, version)
                return None
            doc = docs[0]
            prompt_text = doc.get("prompt") or doc.get("text") or ""
            if prompt_text:
                return prompt_text
            else:
                logger.warning("Prompt document for %s version %s has empty text", name, version)
                return None
        except Exception as e:
            logger.exception("Error fetching prompt %s version %s: %s", name, version, e)
            return None
        
        
    def _load_prompts_config(self) -> Dict[str, int]:
        """Read prompts mapping from constants. Support both keys to be safe.

        Returns mapping prompt_name -> version (int).
        """
        cfg = {}
        # tolerate the typo in constants.yaml: prompts_cofig
        try:
            cfg = Constants.fetch_constant("prompts_config")
        except Exception:
            try:
                cfg = Constants.fetch_constant("prompts_config")
            except Exception:
                logger.exception("Failed to read prompts configuration from constants")
                cfg = {}

        out: Dict[str, int] = {}
        for k, v in (cfg or {}).items():
            try:
                out[k] = int(v)
            except Exception:
                logger.warning("Invalid version for prompt %s: %s", k, v)
        return out

    def refresh(self) -> Dict[str, str]:
        """Reload prompts from MongoDB according to constants configuration.

        Returns the cache mapping prompt_name -> prompt_text.
        """
        prompts_cfg = self._load_prompts_config()
        logger.info("Refreshing prompts cache for keys: %s", list(prompts_cfg.keys()))

        new_cache: Dict[str, str] = {}
        for name, version in prompts_cfg.items():
            try:
                # Query accepts either `version` or `version_no` fields in DB
                query = {"prompt_name": name, "$or": [{"version": version}, {"version_no": version}]}
                docs = self._client.read(MONGO_PROMPT_COLLECTION, query)
                if not docs:
                    logger.warning("No document found for prompt %s version %s", name, version)
                    continue
                doc = docs[0]
                prompt_text = doc.get("prompt") or doc.get("text") or ""
                if prompt_text:
                    new_cache[name] = prompt_text
                    logger.info("Loaded prompt %s (version=%s)", name, version)
                else:
                    raise MissingPromptException(name, version)
                    # logger.warning("Prompt document for %s has empty text", name)
            except Exception as e:
                    raise MissingPromptException(name, version)
                

        self.prompts = new_cache
        logger.info("Prompts cache populated with %d entries", len(self.prompts))
        return self.prompts


    def get_prompt(self, name: str) -> str | None:
        """Return the prompt text for `name`, or None if not found."""
        return self.prompts.get(name)


    def get_all(self) -> Dict[str, str]:
        """Return a shallow copy of the prompts cache."""
        return dict(self.prompts)


