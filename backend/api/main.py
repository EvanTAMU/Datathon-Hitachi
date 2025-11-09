from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from typing import List
import uvicorn
import os
import sys
import uuid
from datetime import datetime
from cryptography.fernet import Fernet

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.classification import ClassificationService
from database.hitl_feedback import HITLDatabase
from services.file_storage import SecureFileStorage
from config.settings import Settings

settings = Settings()

app = FastAPI(title="Regulatory Document Classifier")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database
hitl_db = HITLDatabase(settings.DATABASE_PATH)

# Initialize secure storage
encryption_key = os.getenv("ENCRYPTION_KEY")
if not encryption_key:
    # Generate a session key and warn
    encryption_key = Fernet.generate_key().decode()
    print("⚠️ WARNING: Using temporary encryption key. Set ENCRYPTION_KEY in .env for production!")

file_storage = SecureFileStorage(
    storage_dir=settings.STORAGE_DIR,
    encryption_key=encryption_key
)

# Initialize classifier with database for HITL learning
classifier = ClassificationService(
    settings.GEMINI_API_KEY, 
    enable_dual_verification=settings.ENABLE_DUAL_VERIFICATION,
    db=hitl_db
)

# Store for batch processing status
batch_jobs = {}

# Ensure directories exist
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.STORAGE_DIR, exist_ok=True)

@app.get("/")
async def root():
    return {
        "message": "Regulatory Document Classifier API",
        "version": "1.0.0",
        "security": {
            "encryption_enabled": True,
            "retention_days": 90,
            "audit_logging": True
        },
        "endpoints": {
            "classify_single": "/api/classify/single",
            "classify_batch": "/api/classify/batch",
            "batch_status": "/api/batch/{job_id}/status",
            "feedback": "/api/feedback",
            "audit_trail": "/api/audit-trail",
            "review_unreviewed": "/api/review/unreviewed",
            "feedback_insights": "/api/feedback/insights",
            "file_view": "/api/files/view/{file_id}",
            "file_reclassify": "/api/files/reclassify/{file_id}",
            "file_delete": "/api/files/{file_id}",
            "stats": "/api/stats"
        }
    }

@app.post("/api/classify/single")
async def classify_single_document(file: UploadFile = File(...)):
    """
    Classify a single document with secure storage
    """
    file_extension = file.filename.split(".")[-1].lower()
    if file_extension not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid file type. Allowed: {settings.ALLOWED_EXTENSIONS}"
        )
    
    # Save uploaded file temporarily
    temp_path = os.path.join(settings.UPLOAD_DIR, f"{uuid.uuid4()}_{file.filename}")
    
    try:
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        # Classify
        result = await classifier.classify_document(temp_path, file_extension)
        
        # Store file securely AFTER classification
        storage_result = file_storage.store_file(
            source_path=temp_path,
            filename=file.filename,
            classification=result.get('classification', 'Unknown'),
            metadata={
                'classification_result': result,
                'original_size': os.path.getsize(temp_path)
            }
        )
        
        if storage_result['success']:
            result['file_id'] = storage_result['file_id']
            result['stored'] = True
            result['encrypted'] = storage_result['metadata'].get('encrypted', False)
        
        # Save to audit trail with file_id
        audit_id = hitl_db.save_audit_log({
            'document_name': file.filename,
            'classification': result.get('classification'),
            'confidence': result.get('confidence'),
            'action': 'classification',
            'details': {**result, 'file_id': storage_result.get('file_id')}
        })
        
        result['filename'] = file.filename
        result['audit_id'] = audit_id
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        # Clean up temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)

@app.post("/api/classify/batch")
async def classify_batch(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...)
):
    """
    Classify multiple documents in batch
    """
    job_id = str(uuid.uuid4())
    batch_jobs[job_id] = {
        "status": "processing",
        "total": len(files),
        "completed": 0,
        "results": [],
        "started_at": datetime.now().isoformat()
    }
    
    background_tasks.add_task(process_batch, job_id, files)
    
    return {
        "job_id": job_id, 
        "status": "started",
        "total_files": len(files)
    }

async def process_batch(job_id: str, files: List[UploadFile]):
    """
    Background task for batch processing with secure storage
    """
    for idx, file in enumerate(files):
        file_extension = file.filename.split(".")[-1].lower()
        
        if file_extension not in settings.ALLOWED_EXTENSIONS:
            batch_jobs[job_id]["results"].append({
                "filename": file.filename,
                "error": "Invalid file type"
            })
            batch_jobs[job_id]["completed"] = idx + 1
            continue
        
        file_path = os.path.join(settings.UPLOAD_DIR, f"{uuid.uuid4()}_{file.filename}")
        
        try:
            with open(file_path, "wb") as f:
                content = await file.read()
                f.write(content)
            
            result = await classifier.classify_document(file_path, file_extension)
            
            # Store file securely
            storage_result = file_storage.store_file(
                source_path=file_path,
                filename=file.filename,
                classification=result.get('classification', 'Unknown'),
                metadata={'batch_job': job_id}
            )
            
            if storage_result['success']:
                result['file_id'] = storage_result['file_id']
                result['stored'] = True
            
            batch_jobs[job_id]["results"].append({
                "filename": file.filename,
                "result": result
            })
            
            # Save to audit trail
            hitl_db.save_audit_log({
                'document_name': file.filename,
                'classification': result.get('classification'),
                'confidence': result.get('confidence'),
                'action': 'batch_classification',
                'details': {'job_id': job_id, 'file_id': storage_result.get('file_id')}
            })
            
        except Exception as e:
            batch_jobs[job_id]["results"].append({
                "filename": file.filename,
                "error": str(e)
            })
        
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)
        
        batch_jobs[job_id]["completed"] = idx + 1
    
    batch_jobs[job_id]["status"] = "completed"
    batch_jobs[job_id]["completed_at"] = datetime.now().isoformat()

@app.get("/api/batch/{job_id}/status")
async def get_batch_status(job_id: str):
    """Get status of batch job"""
    job = batch_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@app.get("/api/files/thumbnail/{file_id}")
async def get_thumbnail(file_id: str):
    """Get file thumbnail for preview"""
    metadata = file_storage.get_file_metadata(file_id)
    if not metadata or not metadata.get('thumbnail_path'):
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    
    if not os.path.exists(metadata['thumbnail_path']):
        raise HTTPException(status_code=404, detail="Thumbnail file missing")
    
    return FileResponse(metadata['thumbnail_path'], media_type='image/png')

@app.get("/api/files/view/{file_id}")
async def view_file(file_id: str):
    """View/download file (with access logging)"""
    file_path = file_storage.retrieve_file(file_id)
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    metadata = file_storage.get_file_metadata(file_id)
    return FileResponse(
        file_path, 
        filename=metadata['original_filename'],
        media_type='application/octet-stream'
    )

@app.post("/api/files/reclassify/{file_id}")
async def reclassify_file(file_id: str):
    """Re-classify an existing file"""
    file_path = file_storage.retrieve_file(file_id)
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    try:
        metadata = file_storage.get_file_metadata(file_id)
        file_extension = metadata['file_type']
        
        # Re-classify
        result = await classifier.classify_document(file_path, file_extension)
        
        # Update stored metadata
        metadata['classification'] = result.get('classification')
        metadata['last_reclassified'] = datetime.now().isoformat()
        metadata['classification_history'] = metadata.get('classification_history', [])
        metadata['classification_history'].append({
            'classification': result.get('classification'),
            'confidence': result.get('confidence'),
            'timestamp': datetime.now().isoformat()
        })
        
        # Save updated metadata
        metadata_path = os.path.join(file_storage.metadata_dir, f"{file_id}.json")
        import json
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        # Log re-classification
        hitl_db.save_audit_log({
            'document_name': metadata['original_filename'],
            'classification': result.get('classification'),
            'confidence': result.get('confidence'),
            'action': 're-classification',
            'details': result
        })
        
        result['file_id'] = file_id
        return result
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/files/{file_id}")
async def delete_file(file_id: str, reason: str = "user_request"):
    """Securely delete a file"""
    success = file_storage.delete_file(file_id, reason)
    if success:
        return {"status": "success", "message": "File securely deleted"}
    else:
        raise HTTPException(status_code=404, detail="File not found or deletion failed")

@app.post("/api/files/cleanup")
async def cleanup_expired_files():
    """Run retention policy cleanup"""
    result = file_storage.cleanup_expired_files()
    return {
        "status": "success",
        "deleted_count": result['deleted_count'],
        "errors": result['errors'],
        "message": f"Deleted {result['deleted_count']} expired files"
    }

@app.post("/api/feedback")
async def submit_feedback(feedback: dict):
    """Submit HITL feedback"""
    try:
        feedback_id = hitl_db.save_feedback(feedback)
        return {
            "status": "success",
            "feedback_id": feedback_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/audit-trail")
async def get_audit_trail(limit: int = 100):
    """Get audit trail"""
    try:
        trail = hitl_db.get_audit_trail(limit)
        return {
            "status": "success",
            "count": len(trail),
            "data": trail
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/review/unreviewed")
async def get_unreviewed_documents(limit: int = 100):
    """Get only unreviewed documents for HITL queue"""
    try:
        unreviewed = hitl_db.get_unreviewed_documents(limit)
        return {
            "status": "success",
            "count": len(unreviewed),
            "data": unreviewed
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/feedback/insights")
async def get_feedback_insights():
    """Get insights from HITL feedback for prompt improvement"""
    try:
        insights = hitl_db.get_correction_insights()
        learned_patterns = hitl_db.get_learned_patterns()
        
        return {
            "status": "success",
            "insights": insights,
            "learned_patterns": learned_patterns
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stats")
async def get_statistics():
    """Get classification statistics"""
    try:
        stats = hitl_db.get_classification_stats()
        return {
            "status": "success",
            "data": stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "storage": {
            "encryption_enabled": True,
            "retention_days": 90
        }
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)