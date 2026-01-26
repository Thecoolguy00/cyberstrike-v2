import os
from app.utilities import dc_logger
from app.utilities.singletons_factory import DcSingleton
from app.utilities.dc_exception import MissingEnvironmentVariableException
logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__), {"chat2tes": "V1"})

class EnvironmentVariableRetriever(metaclass = DcSingleton):
    
    @classmethod
    def get_env_variable(cls,variable_name):
        """
        Retrieves the value of an environment variable.

        Args:
            variable_name (str): The name of the environment variable.

        Returns:
            str: The value of the environment variable, or None if not found.
        """
        # First, check if the variable exists in os.environ
        try:
            if variable_name in os.environ:
                return os.environ.get(variable_name)
            else:
                raise MissingEnvironmentVariableException(variable_name)
        except Exception as e:
            logger.error("Error retrieving environment variable '%s': %s", variable_name, e)
            raise