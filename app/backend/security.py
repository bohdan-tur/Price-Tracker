from jose import JWTError,jwt
from passlib.context import CryptContext
from datetime import datetime,timedelta,UTC
from app.backend.config import settings


crypt_context = CryptContext(schemes=["argon2"], deprecated="auto")
def hash_password(password:str):
       return crypt_context.hash(password)



def verify_password(plain_password:str,hashed_password:str):
    return crypt_context.verify(plain_password,hashed_password)




def _create_token(
    data: dict,
    secret_key: str,
    expires_delta: timedelta,
    token_type: str
):
    data_to_encode = data.copy()

    expires = datetime.now(UTC) + expires_delta

    data_to_encode.update({
        "exp": expires,
        "type": token_type
    })

    return jwt.encode(
        data_to_encode,
        secret_key,
        algorithm=settings.ALGORITHM
    )


def create_access_token(data: dict):
    return _create_token(
        data=data,
        secret_key=settings.ACCESS_TOKEN_SECRET_KEY,
        expires_delta=timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRES_MINUTES
        ),
        token_type="access"
    )


def create_refresh_token(data: dict):
    return _create_token(
        data=data,
        secret_key=settings.REFRESH_TOKEN_SECRET_KEY,
        expires_delta=timedelta(
            days=settings.REFRESH_TOKEN_EXPIRES_DAYS
        ),
        token_type="refresh"
    )



def verify_token(token:str,secret_key:str,expected_type:str):
    try:
        payload = jwt.decode(token,
                             secret_key,
                             algorithms=[settings.ALGORITHM]
                             )
        if payload["type"] != expected_type:
            raise JWTError("Invalid token type")

        return payload
    except JWTError:
        raise JWTError("Invalid token")



def verify_access_token(token:str):
    return verify_token(token,settings.ACCESS_TOKEN_SECRET_KEY,"access")



def verify_refresh_token(token:str):
    return verify_token(token,settings.REFRESH_TOKEN_SECRET_KEY,"refresh")







