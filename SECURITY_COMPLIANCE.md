# Data Privacy & Security Compliance

## Overview
This document outlines the security and privacy measures implemented in the Regulatory Document Classifier system.

---

## Security Measures Implemented

### 1. File Encryption
- **Technology**: Fernet (symmetric encryption using AES-128)
- **Scope**: All Highly Sensitive and Confidential documents encrypted at rest
- **Key Management**: Encryption keys stored in environment variables (never in code)
- **Access**: Files automatically decrypted only when accessed by authorized users

### 2. Secure File Deletion
- **Method**: DOD 5220.22-M compliant multi-pass overwrite
- **Process**: 
  1. Overwrite file with random data (3 passes)
  2. Delete file system entry
  3. Remove all metadata references
- **Applies to**: All Highly Sensitive and Confidential documents

### 3. Data Retention Policy
- **Default Period**: 90 days
- **Automatic Cleanup**: System automatically deletes files past retention date
- **Audit Trail**: All deletions logged with reason and timestamp
- **Configuration**: Adjustable per deployment requirements

### 4. Access Logging
- **All Operations Logged**: Upload, view, download, re-classify, delete
- **Log Format**: Append-only JSONL format
- **Contents**: Timestamp, action, file_id, user (no PII in logs)
- **Location**: `uploads/storage/access_log.jsonl`

### 5. Privacy Protection
- **PII Redaction**: Personal information never appears in system logs
- **Error Messages**: No sensitive data exposed in error responses
- **Temporary Files**: Securely deleted immediately after processing
- **API Keys**: Stored only in environment variables

### 6. Audit Trail
- **Complete History**: Every classification action recorded
- **Immutable Records**: Audit trail entries cannot be modified
- **Reviewer Tracking**: All human reviews logged with reviewer name
- **Export Capability**: Audit trail exportable for compliance reporting

---

## Compliance Standards

### GDPR Compliance
| Requirement | Implementation |
|-------------|----------------|
| Right to Erasure | `DELETE /api/files/{file_id}` endpoint |
| Data Minimization | Only essential data stored |
| Encryption | AES-128 for sensitive documents |
| Processing Records | Complete audit trail |
| Retention Limits | 90-day automatic deletion |
| Access Logs | All file access tracked |

### HIPAA Compliance (if handling medical records)
| Requirement | Implementation |
|-------------|----------------|
| Encryption at Rest | Fernet encryption for sensitive files |
| Access Controls | File access logging |
| Audit Controls | Immutable audit trail |
| Secure Disposal | DOD-compliant secure deletion |

### SOC 2 Type II Compliance
| Control | Implementation |
|---------|----------------|
| Security | Encryption, access logging, secure deletion |
| Availability | Health check endpoints, error handling |
| Confidentiality | Classification-based encryption |
| Privacy | PII redaction, retention policies |
| Processing Integrity | Audit trail, HITL validation |

---

## ⚙️ Configuration

### Environment Variables (`.env`)

```bash
# Required
GEMINI_API_KEY=your_gemini_api_key_here

# Security (Generate these securely)
ENCRYPTION_KEY=generate_using_command_below
# python -c "from cryptography.fernet import Fernet; print(f'ENCRYPTION_KEY={Fernet.generate_key().decode()}')"

# Voice output
ELEVENLABS_API_KEY=your_elevenlabs_api_key_here

# Optional - with defaults
RETENTION_DAYS=90
AUTO_DELETE_ENABLED=true
MAX_FILE_SIZE=52428800