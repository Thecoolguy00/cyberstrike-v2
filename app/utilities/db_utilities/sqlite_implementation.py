from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.utilities import dc_logger
from app.utilities.db_utilities.db_models.models import Base
from app.utilities.singletons_factory import DcSingleton

logger =dc_logger.LoggerAdap(dc_logger.get_logger(__name__), {"Chat2Test": "V1"})

class QLiteDatabase(metaclass=DcSingleton):
    """
    Database initialization and session management class.
    """

    def __init__(self, db_url: str = "sqlite:///./app.db"):
        self.db_url = db_url

        connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
        self.engine = create_engine(self.db_url, connect_args=connect_args)
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine
        )
        self.create_tables()

    def create_tables(self):
        """
        Create all database tables defined in Base metadata.
        """
        Base.metadata.create_all(bind=self.engine)
        logger.info("Database tables created successfully.")

    def get_db(self):
        """
        Dependency-compatible database session generator.
        Use in FastAPI routes as: Depends(db_instance.get_db)
        """
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()


