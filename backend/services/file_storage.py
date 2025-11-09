import os
import shutil
import hashlib
from typing import Dict, Optional
from datetime import datetime, timedelta
from PIL import Image
import io
import json
from cryptography.fernet import Fernet
from pathlib import Path

class SecureFileStorage:
    """
    Secure file storage with encryption, retention policies, and access logging
    """
    def __init__(self, storage_dir: str, encryption_key: str = None):
        self.storage_dir = storage_dir
        self.thumbnail_dir = os.path.join(storage_dir, 'thumbnails')
        self.metadata_dir = os.path.join(storage_dir, 'metadata')
        
        # Create directories
        os.makedirs(self.storage_dir, exist_ok=True)
        os.makedirs(self.thumbnail_dir, exist_ok=True)
        os.makedirs(self.metadata_dir, exist_ok=True)
        
        # Initialize encryption
        if encryption_key:
            self.cipher = Fernet(encryption_key.encode())
            self.encryption_enabled = True
        else:
            # Generate a key for this session
            key = Fernet.generate_key()
            self.cipher = Fernet(key)
            self.encryption_enabled = False
            print("⚠️ Warning: Using session-only encryption key")
    
    def store_file(self, source_path: str, filename: str, classification: str, 
                   metadata: Dict) -> Dict:
        """
        Securely store a file with metadata and thumbnail
        """
        try:
            # Generate unique file ID
            file_hash = self._generate_file_hash(source_path)
            file_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file_hash[:8]}"
            
            # Determine file extension
            ext = filename.split('.')[-1].lower()
            stored_filename = f"{file_id}.{ext}"
            stored_path = os.path.join(self.storage_dir, stored_filename)
            
            # Copy or encrypt file
            if self.encryption_enabled and classification in ['Highly Sensitive', 'Confidential']:
                self._encrypt_file(source_path, stored_path)
            else:
                shutil.copy2(source_path, stored_path)
            
            # Create thumbnail if image or PDF
            thumbnail_path = self._create_thumbnail(source_path, file_id, ext)
            
            # Store metadata
            file_metadata = {
                'file_id': file_id,
                'original_filename': filename,
                'stored_filename': stored_filename,
                'stored_path': stored_path,
                'thumbnail_path': thumbnail_path,
                'classification': classification,
                'file_size': os.path.getsize(source_path),
                'file_type': ext,
                'upload_timestamp': datetime.now().isoformat(),
                'retention_until': (datetime.now() + timedelta(days=90)).isoformat(),
                'encrypted': self.encryption_enabled and classification in ['Highly Sensitive', 'Confidential'],
                'access_count': 0,
                'metadata': metadata
            }
            
            # Save metadata
            metadata_path = os.path.join(self.metadata_dir, f"{file_id}.json")
            with open(metadata_path, 'w') as f:
                json.dump(file_metadata, f, indent=2)
            
            return {
                'success': True,
                'file_id': file_id,
                'stored_path': stored_path,
                'thumbnail_path': thumbnail_path,
                'metadata': file_metadata
            }
        
        except Exception as e:
            print(f"Error storing file: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def retrieve_file(self, file_id: str) -> Optional[str]:
        """
        Retrieve a file by ID, decrypt if necessary
        """
        try:
            # Load metadata
            metadata = self._load_metadata(file_id)
            if not metadata:
                return None
            
            # Log access
            self._log_file_access(file_id, 'retrieve')
            
            stored_path = metadata['stored_path']
            
            # If encrypted, decrypt to temp file
            if metadata.get('encrypted'):
                temp_path = f"/tmp/decrypted_{file_id}.{metadata['file_type']}"
                self._decrypt_file(stored_path, temp_path)
                return temp_path
            
            return stored_path
        
        except Exception as e:
            print(f"Error retrieving file: {e}")
            return None
    
    def get_file_metadata(self, file_id: str) -> Optional[Dict]:
        """Get file metadata"""
        return self._load_metadata(file_id)
    
    def delete_file(self, file_id: str, reason: str = "manual") -> bool:
        """
        Securely delete a file and its metadata
        """
        try:
            metadata = self._load_metadata(file_id)
            if not metadata:
                return False
            
            # Log deletion
            self._log_file_access(file_id, 'delete', reason)
            
            # Securely delete file (overwrite before deletion for sensitive files)
            if metadata['classification'] in ['Highly Sensitive', 'Confidential']:
                self._secure_delete(metadata['stored_path'])
            else:
                os.remove(metadata['stored_path'])
            
            # Delete thumbnail
            if metadata.get('thumbnail_path') and os.path.exists(metadata['thumbnail_path']):
                os.remove(metadata['thumbnail_path'])
            
            # Delete metadata
            metadata_path = os.path.join(self.metadata_dir, f"{file_id}.json")
            os.remove(metadata_path)
            
            return True
        
        except Exception as e:
            print(f"Error deleting file: {e}")
            return False
    
    def cleanup_expired_files(self) -> Dict:
        """
        Clean up files past retention period
        """
        deleted_count = 0
        errors = []
        
        for metadata_file in os.listdir(self.metadata_dir):
            if not metadata_file.endswith('.json'):
                continue
            
            file_id = metadata_file.replace('.json', '')
            metadata = self._load_metadata(file_id)
            
            if metadata and metadata.get('retention_until'):
                retention_date = datetime.fromisoformat(metadata['retention_until'])
                if datetime.now() > retention_date:
                    if self.delete_file(file_id, reason="retention_policy"):
                        deleted_count += 1
                    else:
                        errors.append(file_id)
        
        return {
            'deleted_count': deleted_count,
            'errors': errors
        }
    
    def _generate_file_hash(self, file_path: str) -> str:
        """Generate SHA-256 hash of file"""
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    
    def _encrypt_file(self, source_path: str, dest_path: str):
        """Encrypt file using Fernet"""
        with open(source_path, 'rb') as f:
            data = f.read()
        
        encrypted_data = self.cipher.encrypt(data)
        
        with open(dest_path, 'wb') as f:
            f.write(encrypted_data)
    
    def _decrypt_file(self, source_path: str, dest_path: str):
        """Decrypt file using Fernet"""
        with open(source_path, 'rb') as f:
            encrypted_data = f.read()
        
        decrypted_data = self.cipher.decrypt(encrypted_data)
        
        with open(dest_path, 'wb') as f:
            f.write(decrypted_data)
    
    def _create_thumbnail(self, source_path: str, file_id: str, ext: str) -> Optional[str]:
        """Create thumbnail for preview"""
        try:
            if ext == 'pdf':
                import fitz
                doc = fitz.open(source_path)
                page = doc[0]
                pix = page.get_pixmap(matrix=fitz.Matrix(0.3, 0.3))
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            elif ext in ['png', 'jpg', 'jpeg']:
                img = Image.open(source_path)
            else:
                return None
            
            # Resize to thumbnail
            img.thumbnail((200, 200))
            thumbnail_path = os.path.join(self.thumbnail_dir, f"{file_id}_thumb.png")
            img.save(thumbnail_path, "PNG")
            
            return thumbnail_path
        
        except Exception as e:
            print(f"Could not create thumbnail: {e}")
            return None
    
    def _load_metadata(self, file_id: str) -> Optional[Dict]:
        """Load file metadata"""
        metadata_path = os.path.join(self.metadata_dir, f"{file_id}.json")
        if not os.path.exists(metadata_path):
            return None
        
        with open(metadata_path, 'r') as f:
            return json.load(f)
    
    def _log_file_access(self, file_id: str, action: str, details: str = ""):
        """Log file access for audit"""
        log_entry = {
            'file_id': file_id,
            'action': action,
            'details': details,
            'timestamp': datetime.now().isoformat()
        }
        
        log_file = os.path.join(self.storage_dir, 'access_log.jsonl')
        with open(log_file, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    
    def _secure_delete(self, file_path: str):
        """Securely delete sensitive files by overwriting"""
        if not os.path.exists(file_path):
            return
        
        file_size = os.path.getsize(file_path)
        
        # Overwrite with random data 3 times
        with open(file_path, 'wb') as f:
            for _ in range(3):
                f.write(os.urandom(file_size))
                f.seek(0)
        
        # Finally delete
        os.remove(file_path)