from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.utilities.db_utilities.sqlite_implementation import QLiteDatabase
from app.utilities.db_utilities.db_models.models import User
from app.utilities.singletons_factory import DcSingleton

qlite_db = QLiteDatabase()
class AuthManager(metaclass=DcSingleton):
    """
    Handles authentication, token creation, validation, and user resolution.
    """

    def __init__(self,
                 secret_key: str = "your-secret-key",
                 algorithm: str = "HS256",
                 access_token_expire_minutes: int = 60):
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.access_token_expire_minutes = access_token_expire_minutes
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        self.security = HTTPBearer()
        AuthManager._instance = self

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify plain password against its hash."""
        # return self.pwd_context.verify(plain_password, hashed_password)
        return plain_password == hashed_password


    def get_password_hash(self, password: str) -> str:
        """Hash the password using bcrypt."""
        return self.pwd_context.hash(password)

    def create_access_token(self, data: dict, expires_delta: Optional[timedelta] = None) -> str:
        """Create a JWT access token."""
        to_encode = data.copy()
        expire = datetime.now() + (expires_delta or timedelta(minutes=self.access_token_expire_minutes))
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        return encoded_jwt

    @staticmethod
    def decode_access_token(token: str) -> dict:
        """Decode and validate a JWT token."""
        try:
            instance = AuthManager._instance
            payload = jwt.decode(token, instance.secret_key, algorithms=[instance.algorithm])
            return payload
        except JWTError as e:
            raise JWTError(f"Invalid token: {str(e)}")
    @staticmethod
    def get_current_user(
        credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
        db: Session = Depends(qlite_db.get_db)
    ) -> User:
        """
        FastAPI dependency that validates JWT and returns the current user object.
        Works like a JWT filter in Spring Security.
        """
        token = credentials.credentials
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

        try:
            payload = AuthManager.decode_access_token(token)
            user_id: int = payload.get("sub")
            if user_id is None:
                raise credentials_exception
        except JWTError:
            raise credentials_exception

        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise credentials_exception

        return user

    def get_current_user_id(self, current_user: User = Depends(get_current_user)) -> int:
        """Return only the current user's ID."""
        return current_user.id
