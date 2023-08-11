import logging
import re
import subprocess
import sys
from urllib.request import Request
from fastapi import FastAPI, HTTPException, Depends,Form, UploadFile,File,Header
from starlette.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from passlib.context import CryptContext
from pymongo import MongoClient
from jose import jwt, JWTError
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
import redis.asyncio as redis
from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter

# Load environment variables from .env file
load_dotenv()

# Configure the logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    filename="app.log",
)

# Create a logger for the application
logger = logging.getLogger("app")

app = FastAPI()

# MongoDB configuration
mongo_uri = os.getenv("MONGO_URI")
mongo_client = MongoClient(mongo_uri)
database = mongo_client[os.getenv("DATABASE_NAME")]
users_collection = database[os.getenv("USERS_COLLECTION")]

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 Password Bearer for token management
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Function to verify user credentials using MongoDB
def verify_user(username: str, password: str):
    user = users_collection.find_one({"username": username})
    if user and pwd_context.verify(password, user["hashed_password"]):
        return True
    return False

# Function to create access token (JWT) with expiration time
def create_access_token(data: dict, expires_delta: timedelta = None):
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)  # Default expiration time is 15 minutes

    data["exp"] = expire
    encoded_jwt = jwt.encode(data, os.getenv("SECRET_KEY"), algorithm="HS256")
    return encoded_jwt

# Function to decode JWT token
def decode_token(token: str):
    try:
        payload = jwt.decode(token, os.getenv("SECRET_KEY"), algorithms=["HS256"])
        return payload
    except JWTError:
        logger.error("Invalid credentials - JWT decoding failed.")
        raise HTTPException(status_code=401, detail="Invalid credentials")

def is_valid_password(password):
    if len(password) < 8:
        return False

    if not any(char.isupper() for char in password):
        return False

    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False

    if not any(char.isdigit() for char in password):
        return False

    return True

@app.middleware("http")
async def catch_exceptions(request: Request, call_next):
    try:
        response = await call_next(request)
        return response
    except HTTPException as http_exc:
        if http_exc.status_code == 500:
            logger.critical(f"500 Internal Server Error: {http_exc}")
            
        raise HTTPException(status_code=401, detail="Invalid credentials")
    except Exception as exc:
        logger.exception(f"Unhandled Exception: {exc}")
        
        raise HTTPException(status_code=401, detail="Invalid credentials")
@app.on_event("startup")
async def startup():
    global redis_client
    logger.info("APP STARTED SUCCESSFULLY")
    redis_client = redis.from_url("redis://localhost", encoding="utf-8", decode_responses=True)
    await FastAPILimiter.init(redis_client)

@app.on_event("shutdown")
async def shutdown():
    await FastAPILimiter.close()

# Signup route to register a new user
@app.post("/signup/")
async def signup_user(form_data: OAuth2PasswordRequestForm = Depends()):
    username = form_data.username
    password = form_data.password

    if not is_valid_password(password):
        raise HTTPException(status_code=400, detail="Invalid password. Password must be at least 8 characters long and contain at least one capital letter, special symbol, and number.")

    if users_collection.find_one({"username": username}):
        logger.warning("User already exists - Signup request rejected.")
        raise HTTPException(status_code=400, detail="User already exists")

    hashed_password = pwd_context.hash(password)
    users_collection.insert_one({"username": username, "hashed_password": hashed_password})

    logger.info(f"User registered successfully - Username: {username}")
    return {"message": "User registered successfully"}

# Login route to authenticate user and provide access token (JWT)
@app.post("/login/", dependencies=[Depends(RateLimiter(times=1, seconds=4))])
async def login_user(form_data: OAuth2PasswordRequestForm = Depends()):
    username = form_data.username
    password = form_data.password

    if not verify_user(username, password):
        logger.warning(f"Invalid credentials - Username: {username}")
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = create_access_token(data={"sub": username}, expires_delta=timedelta(hours=30))  # Set token expiration to 1 hour

    # Store the token in Redis with the expiration time
    await redis_client.setex(username,60*30, access_token)
    

    logger.info(f"User logged in successfully - Username: {username}")

    return {"access_token": access_token, "token_type": "bearer"}

# Protected route - requires a valid JWT token to access
@app.get("/protected/")
async def protected_route(token: str = Depends(oauth2_scheme)):
    user_data = decode_token(token)
   
    # Check if the token exists and is not expired in Redis
    cached_token = await redis_client.get(user_data["sub"])
    
    
 
    if not cached_token or cached_token != token:  # Compare raw token without decoding
        logger.warning(f"Invalid or expired token - Username: {user_data['sub']}")
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    logger.info(f"Access granted to protected route - Username: {user_data['sub']}")
    return {"message": "This is a protected route", "user": user_data["sub"]}

UPLOAD_DIR = "UserData"
@app.post("/upload-avatar/", dependencies=[Depends(RateLimiter(times=1, seconds=10))])
async def upload_avatar(
    token: str = Depends(oauth2_scheme),
    avatar: UploadFile = File(...),
):
    user_data = decode_token(token)
    cached_token = await redis_client.get(user_data["sub"])

    if not cached_token or cached_token != token:
        logger.warning(f"Invalid or expired token - Username: {user_data['sub']}")
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Check if the user exists in the database
    if not users_collection.find_one({"username": user_data["sub"]}):
        raise HTTPException(status_code=404, detail="User not found in the database")

    # Check if the uploaded file is an image
    allowed_extensions = ["jpg", "jpeg", "png", "gif"]
    file_extension = avatar.filename.split(".")[-1].lower()
    if file_extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Invalid file format. Only JPG, JPEG, PNG, and GIF files are allowed.")

    # Create a directory for the user's avatars if it doesn't exist
    user_avatar_dir = os.path.join(UPLOAD_DIR, user_data["sub"])
    if not os.path.exists(user_avatar_dir):
        os.makedirs(user_avatar_dir)

    # Remove existing avatar if it exists
    existing_avatar = users_collection.find_one({"username": user_data["sub"]}, {"avatar": 1})
    if existing_avatar and "avatar" in existing_avatar:
        existing_avatar_path = os.path.join(user_avatar_dir, os.path.basename(existing_avatar["avatar"]))
        if os.path.exists(existing_avatar_path):
            os.remove(existing_avatar_path)

    avatar.filename = f"{user_data['sub']}.{file_extension}"
    # Save the uploaded file to the user's avatar directory
    file_path = os.path.join(user_avatar_dir, avatar.filename)
    with open(file_path, "wb") as f:
        f.write(avatar.file.read())

    # Update the user's avatar URL in the database
    avatar_url = f"/{UPLOAD_DIR}/{user_data['sub']}/{avatar.filename}"
    users_collection.update_one({"username": user_data['sub']}, {"$set": {"avatar": avatar_url}})

    return {"message": "Avatar uploaded successfully"}

#Get the avatar for the username
@app.get("/get-avatar/")
async def get_avatar(token: str = Depends(oauth2_scheme)):
    

    

    user_data = decode_token(token)
    cached_token = await redis_client.get(user_data["sub"])
    if not cached_token or cached_token != token:
        logger.warning(f"Invalid or expired token - Username: {user_data['sub']}")
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Retrieve avatar URL from the database
    user = users_collection.find_one({"username": user_data["sub"]})
    
    if user and "avatar" in user:
        avatar_path = user["avatar"]
        
        # Ensure avatar path is a string
        if isinstance(avatar_path, str):
            return FileResponse(f"./{avatar_path}")  # Return the avatar image

    raise HTTPException(status_code=404, detail="Avatar not found for the user")
