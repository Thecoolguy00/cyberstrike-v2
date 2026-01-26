import datetime
from app.utilities import dc_logger
from app.utilities.env_util import EnvironmentVariableRetriever 
from app.utilities.constants import Constants
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
import sys
from typing import List, Tuple, Union
from app.utilities.singletons_factory import DcSingleton

logger = dc_logger.LoggerAdap(
    dc_logger.get_logger(__name__), {"mom-generation": "v3"}
)

class MongoImplement(metaclass=DcSingleton):
    """Mongodb implementation class for Robust db.
    Args:
        MongoInterface (Class): Interface for all the Mongodb implementation.
    """

    def __init__(self, connection_string=None, db_name=None, max_pool=None, server_selection_timeout=None) -> None:
        """Constructor to create a connection with the robust db.
        """
        if connection_string is None:
            try:
                connection_string = EnvironmentVariableRetriever.get_env_variable("MONGO_URI")
            except Exception as e:
                logger.error(f"MONGO_URI not found in environment: {e}")
                raise
            mongo_config = Constants.fetch_constant("mongodb_config")
            db_name = mongo_config["db_name"]
            max_pool = mongo_config["max_pool"]
            server_selection_timeout = mongo_config["server_selection_timeout"]
        
        self.connection_string = connection_string
        self.db_name = db_name
        self.max_pool = int(max_pool) if isinstance(max_pool, str) else max_pool
        self.server_selection_timeout = int(server_selection_timeout) if isinstance(server_selection_timeout, str) else server_selection_timeout
        logger.info("Initializing connection pool for database connection, with {}".format(self.db_name))
        try:
            self.client = MongoClient(
                self.connection_string,
                maxPoolSize=self.max_pool,
                serverSelectionTimeoutMS=self.server_selection_timeout,
                uuidRepresentation="standard"
            )
            self.client.server_info()
            self.database = self.client[self.db_name]
            logger.info(f"Made {self.max_pool} max_connections with {self.db_name}")
        except (ConnectionFailure, ServerSelectionTimeoutError):
            logger.error(f"Could not Connect with databse={self.db_name}. Please check the connection string",exc_info=True)
            sys.exit(0)

    def insert_one(self,collection_name: str, data):
        """
        Function to insert one item in a collection.

        Args:
            collection_name (str): Name of the collection.
            data (dict): Data to be inserted.

        Returns:
            _id: ID of the inserted document.
        """
        session = self.client.start_session(causal_consistency=True)
        session.start_transaction()
        try:
            _id = self.database[collection_name].insert_one(data)
            session.commit_transaction()
            logger.info(f"Inserted data to {collection_name}")
            return _id.inserted_id.__str__()
        except Exception as exe:
            logger.error(f"Could not perform insertion on {collection_name} collection || {exe}",exc_info=True)
            session.abort_transaction()
            raise exe
        finally:
            session.end_session()

    def insert_many(self,collection_name: str, data_list):
        """
        Function to insert multiple items in a collection.

        Args:
            collection_name (str): Name of the collection.
            data_list (list): List of dictionaries containing data to be inserted.

        Returns:
            inserted_ids: List of IDs of the inserted documents.
        """
        session = self.client.start_session(causal_consistency=True)
        session.start_transaction()
        try:
            inserted_ids = self.database[collection_name].insert_many(
                data_list
            )
            session.commit_transaction()
            logger.info(f"Inserted {len(data_list)} items to {collection_name}")
            return inserted_ids.inserted_ids
        except Exception as exe:
            logger.error(f"Could not perform insertion on {collection_name} collection || {exe}",exc_info=True)
            session.abort_transaction()
            raise exe
        finally:
            session.end_session()


    def update_one(self, collection_name: str, query: dict, data: dict):
        """
        Function to update one item in a collection.

        Args:
            collection_name (str): Name of the collection.
            query (dict): Query to find the document to update.
            data (dict): Data to update in the document.
        """
        session = self.client.start_session(causal_consistency=True)
        session.start_transaction()
        try:
            self.database[collection_name].update_one(
                query, {"$set": data}
            )
            session.commit_transaction()
        except Exception as exe:
            logger.error(
                f"Error in Updating the collection name="
                f" {collection_name} || query ={query} || {exe}, starting rollback.",
                exc_info=True,
            )
            session.abort_transaction()
            raise exe
        finally:
            session.end_session()
    
    def update_many(self, collection_name: str, query: dict, data: dict):
        """
        Function to update one item in a collection.

        Args:
            collection_name (str): Name of the collection.
            query (dict): Query to find the document to update.
            data (dict): Data to update in the document.
        """
        session = self.client.start_session(causal_consistency=True)
        session.start_transaction()
        try:
            self.database[collection_name].update_many(
                query, {"$set": data}
            )
            session.commit_transaction()
        except Exception as exe:
            logger.error(
                f"Error in Updating the collection name="
                f" {collection_name} || query ={query} || {exe}, starting rollback.",
                exc_info=True,
            )
            session.abort_transaction()
            raise exe
        finally:
            session.end_session()   


    def read(self, collection_name: str,query: dict, sort: Union[List[Tuple], None] = None,col_names: Union[List[str], None] = None,max_count: int = None, skip_count: int = 0):
        """
        Function to read data from the database.

        Args:
            collection_name (str): Name of the collection.
            query (dict): Query to filter the documents.
            sort (Union[List[Tuple], None], optional): List of tuples to sort the
                documents. Defaults to None.
            col_names (Union[List[str], None], optional): List of column names to
                project. Defaults to None.
            max_count (int, optional): Maximum number of documents to return.
                Defaults to None.
            skip_count (int, optional): Number of documents to skip.
                Defaults to 0.

        Returns:
            list: List of documents matching the query.
        """
        data = []
        session = self.client.start_session(causal_consistency=True)
        session.start_transaction()
        try:
            cursor = self.database[collection_name].find(
                filter=query, projection=col_names, sort=sort
            )
            
            if skip_count:
                cursor = cursor.skip(skip_count)
                
            if max_count:
                cursor = cursor.limit(max_count)
                
            resp = cursor
            session.commit_transaction()
            for item in resp:
                data.append(item)
        except Exception as exe:
            logger.error(
                f"Error in executing the query = {query} for collection name ="
                f" {collection_name} || {exe}, starting rollback.",
                exc_info=True)
            session.abort_transaction()
            raise exe
        finally:
            session.end_session()
        return data


    def delete_one(self, collection_name, query):
        """
        Function to delete one item from a collection.

        Args:
            collection_name (str): Name of the collection.
            query (dict): Query to find the document to delete.
        """
        session = self.client.start_session(causal_consistency=True)
        session.start_transaction()
        try:
            self.database[collection_name].delete_one(query)
            session.commit_transaction()
            logger.info(f"Removed data from {collection_name} || query = {query}")
        except Exception as exe:
            logger.error(
                f"Could not perform deletion on {collection_name} collection || {exe}",
                exc_info=True)
            session.abort_transaction()
            raise exe
        finally:
            session.end_session()


    def delete_many(self, collection_name, query):
        """
        Function to delete multiple items from a collection.

        Args:
            collection_name (str): Name of the collection.
            query (dict): Query to find the documents to delete.
        """
        session = self.client.start_session(causal_consistency=True)
        session.start_transaction()
        try:
            result = self.database[collection_name].delete_many(query)
            session.commit_transaction()
            logger.info(
                f"Removed {result.deleted_count} documents from {collection_name} || query = {query}"
            )
        except Exception as exe:
            logger.error(
                f"Could not perform deletion on {collection_name} collection || {exe}",
                exc_info=True)
            session.abort_transaction()
            raise exe
        finally:
            session.end_session()

    def count(self, collection_name: str, query: dict) -> int:
        """
        Function to count documents in a collection matching the query.

        Args:
            collection_name (str): Name of the collection.
            query (dict): Query to filter the documents.

        Returns:
            int: Count of documents.
        """
        session = self.client.start_session(causal_consistency=True)
        session.start_transaction()
        try:
            count = self.database[collection_name].count_documents(query)
            session.commit_transaction()
            return count
        except Exception as exe:
            logger.error(f"Error counting documents in {collection_name} || {exe}", exc_info=True)
            session.abort_transaction()
            raise exe
        finally:
            session.end_session()

    def distinct(self, collection_name: str, field: str, query: dict = None) -> list:
        """
        Function to get distinct values of a field in a collection.

        Args:
            collection_name (str): Name of the collection.
            field (str): Field name to get distinct values from.
            query (dict, optional): Query to filter the documents. Defaults to None.

        Returns:
            list: List of distinct values.
        """
        if query is None:
            query = {}
        
        session = self.client.start_session(causal_consistency=True)
        session.start_transaction()
        try:
            distinct_values = self.database[collection_name].distinct(field, query)
            session.commit_transaction()
            logger.info(f"Retrieved distinct values for {field} in {collection_name}")
            return distinct_values
        except Exception as exe:
            logger.error(f"Error retrieving distinct values for {field} in {collection_name}: {exe}", exc_info=True)
            session.abort_transaction()
            raise exe
        finally:
            session.end_session()

    def aggregate(self, collection_name: str, pipeline: list) -> list:
        """
        Function to execute aggregation pipeline on a collection.

        Args:
            collection_name (str): Name of the collection.
            pipeline (list): MongoDB aggregation pipeline.

        Returns:
            list: List of aggregated documents.
        """
        session = self.client.start_session(causal_consistency=True)
        session.start_transaction()
        try:
            result = list(self.database[collection_name].aggregate(pipeline))
            session.commit_transaction()
            logger.info(f"Aggregation completed on {collection_name}")
            return result
        except Exception as exe:
            logger.error(f"Error in aggregation on {collection_name}: {exe}", exc_info=True)
            session.abort_transaction()
            raise exe
        finally:
            session.end_session()