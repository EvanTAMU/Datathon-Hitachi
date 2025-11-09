import os
from dotenv import load_dotenv
from datetime import timedelta

load_dotenv()

class Settings:
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    
    # File storage settings
    UPLOAD_DIR = "uploads/temp"
    STORAGE_DIR = "uploads/storage"  # Permanent storage
        
    # Security settings
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}
    ENABLE_DUAL_VERIFICATION = True
    
    # Data retention policy
    RETENTION_DAYS = 90  # Keep files for 90 days
    AUTO_DELETE_ENABLED = True
    
    # Privacy settings
    ENCRYPT_STORED_FILES = True
    LOG_FILE_ACCESS = True
    REDACT_PII_IN_LOGS = True
    
    # Database
    DATABASE_PATH = "hitl_feedback.db"

settings = Settings()