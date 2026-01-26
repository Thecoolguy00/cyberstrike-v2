import re
import sys
from inspect import getframeinfo, stack
from psycopg2 import pool
from psycopg2.extras import execute_values
from psycopg2 import DatabaseError, DataError
from psycopg2 import Error
from app.utilities import dc_logger
from app.utilities.singletons_factory import DcSingleton

logger = dc_logger.LoggerAdap(dc_logger.get_logger(__name__), {"analysis-engine": "v3"})

class DbUtil(metaclass=DcSingleton):
    
    def __init__(self,dbname,dbuser,dbhost,dbpassword,dbport,min_pool_size,max_pool_size) -> None:
        self.dbname = dbname
        self.user = dbuser
        self.password = dbpassword
        self.host = dbhost
        self.port = dbport
        self.min_pool_size = min_pool_size
        self.max_pool_size = max_pool_size
        try:
            self.postgres_pool = pool.ThreadedConnectionPool(
                self.min_pool_size, self.max_pool_size,
                user=self.user,
                password=self.password,
                host=self.host,
                port=self.port,
                database=self.dbname)
            if self.postgres_pool:
                logger.info(f'Made {self.max_pool_size} connections successfully with USER={self.user} || DBNAME= {self.dbname}')
        except (Error, DatabaseError) as exe:
            logger.error(f'Error while connecting to PostgreSQL: {exe}',exc_info=True)
    
    def insert_bulk_data(self, table_name, col_names, data,return_parameter=None):
        """
        Insert bulk data into the given table
        :param table_name: name of the table
        :param data: list of tuples containing data to be inserted
        :return: True if data insertion is successful else False
        """
        rows = []
        try:
            con = self.postgres_pool.getconn()
            cur = con.cursor()
            try:
                if return_parameter is None:
                    sql_insert_generic = "INSERT INTO {} ({}) VALUES %s".format(table_name, col_names)
                    logger.info(sql_insert_generic)
                    logger.info(
                        "Inserting {} entries into {} table with no return parameter".format(len(data), table_name))
                    execute_values(cur, sql_insert_generic, data, template=None, page_size=len(data))
                    con.commit()
                else:
                    return_parameter_string = ""
                    for item in return_parameter:
                        return_parameter_string += item + ","
                    return_parameter_string = return_parameter_string[:-1]
                    sql_insert_return = "INSERT INTO {} ({}) VALUES  %s returning {}".format(table_name, col_names,
                                                                                             return_parameter_string)
                    logger.info(sql_insert_return)
                    logger.info(
                        "Inserting {} entries into {} table with {} return parameter".format(len(data), table_name,
                                                                                             return_parameter))
                    execute_values(cur, sql_insert_return, data, template=None, page_size=len(data))
                    con.commit()
                    for row in cur.fetchall():
                        for item in row:
                            rows.append(item)
            except DataError as e:
                logger.error(e,exc_info=True)
                con.rollback()
                pass
        except DatabaseError as e:
            logger.error(e,exc_info=True)
            pass
        finally:
            if con:
                con.close()
                self.postgres_pool.putconn(con)
        return rows
    
    def execute_query(self, sql, data, is_write=False, is_return=True):
        """This function is used to execute sql queries but don't use to insert multiple vales in db as insertion
        operation is slow so use next method """
        rows = []
        col_names = None
        con = None
        try:
            con = self.postgres_pool.getconn()
            cur = con.cursor()
            cur.execute(sql, data)
            if cur.description:
                col_names = [desc[0] for desc in cur.description]
            if is_write:
                con.commit()
            if is_return:
                while True:
                    row = cur.fetchone()
                    if row is None:
                        break
                    rows.append(row)
        except DatabaseError as e:
            if con:
                con.rollback()
            logger.error(e,exc_info=True)
            sys.exit(1)
        finally:
            if con:
                con.close()
                self.postgres_pool.putconn(con)
        return rows, col_names
    
    def __del__(self):
        """
        Close all the connections in the connection pool
        """
        if self.postgres_pool:
            self.postgres_pool.closeall()
            logger.info(f"PostgreSQL connection pool closed successfully for DB_NAME={self.dbname} || DB_USER= {self.user}")