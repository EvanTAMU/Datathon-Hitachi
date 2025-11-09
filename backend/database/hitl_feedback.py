import json
import os
from datetime import datetime
from typing import List, Dict, Optional
import sqlite3

class HITLDatabase:
    """
    Enhanced database for HITL feedback with persistent review tracking
    """
    def __init__(self, db_path: str = "hitl_feedback.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize the database with required tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create feedback table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT NOT NULL,
                original_classification TEXT NOT NULL,
                corrected_classification TEXT,
                reviewer_name TEXT,
                reviewer_comments TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                confidence_score REAL,
                evidence TEXT,
                is_agreement BOOLEAN DEFAULT 0
            )
        ''')
        
        # Create audit trail table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS audit_trail (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_name TEXT NOT NULL,
                classification TEXT NOT NULL,
                confidence REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                user_id TEXT,
                action TEXT,
                details TEXT,
                reviewed BOOLEAN DEFAULT 0,
                review_timestamp DATETIME
            )
        ''')
        
        # Create review status tracking table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS review_status (
                document_id INTEGER PRIMARY KEY,
                reviewed BOOLEAN DEFAULT 0,
                review_timestamp DATETIME,
                reviewer_name TEXT,
                FOREIGN KEY (document_id) REFERENCES audit_trail(id)
            )
        ''')
        
        # Create learned patterns table for improving prompts
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS learned_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_type TEXT NOT NULL,
                from_classification TEXT,
                to_classification TEXT,
                frequency INTEGER DEFAULT 1,
                keywords TEXT,
                context TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_seen DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def save_feedback(self, feedback: Dict) -> int:
        """Save HITL feedback and mark document as reviewed"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Determine if this is an agreement or correction
        is_agreement = feedback.get('original_classification') == feedback.get('corrected_classification')
        
        cursor.execute('''
            INSERT INTO feedback 
            (document_id, original_classification, corrected_classification, 
             reviewer_name, reviewer_comments, confidence_score, evidence, is_agreement)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            feedback.get('document_id'),
            feedback.get('original_classification'),
            feedback.get('corrected_classification'),
            feedback.get('reviewer_name'),
            feedback.get('reviewer_comments'),
            feedback.get('confidence_score'),
            json.dumps(feedback.get('evidence', [])),
            is_agreement
        ))
        
        feedback_id = cursor.lastrowid
        
        # Mark document as reviewed
        cursor.execute('''
            INSERT OR REPLACE INTO review_status 
            (document_id, reviewed, review_timestamp, reviewer_name)
            VALUES (?, 1, CURRENT_TIMESTAMP, ?)
        ''', (int(feedback.get('document_id')), feedback.get('reviewer_name')))
        
        # Update audit trail
        cursor.execute('''
            UPDATE audit_trail 
            SET reviewed = 1, review_timestamp = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (int(feedback.get('document_id')),))
        
        # If this is a correction, learn from it
        if not is_agreement:
            self._record_learned_pattern(
                cursor,
                feedback.get('original_classification'),
                feedback.get('corrected_classification'),
                feedback.get('reviewer_comments', '')
            )
        
        conn.commit()
        conn.close()
        
        return feedback_id
    
    def _record_learned_pattern(self, cursor, from_class: str, to_class: str, comments: str):
        """Record a learned pattern from corrections"""
        # Check if this pattern already exists
        cursor.execute('''
            SELECT id, frequency FROM learned_patterns
            WHERE from_classification = ? AND to_classification = ?
        ''', (from_class, to_class))
        
        existing = cursor.fetchone()
        
        if existing:
            # Increment frequency
            cursor.execute('''
                UPDATE learned_patterns
                SET frequency = frequency + 1,
                    last_seen = CURRENT_TIMESTAMP,
                    context = context || ' | ' || ?
                WHERE id = ?
            ''', (comments[:200], existing[0]))
        else:
            # Create new pattern
            cursor.execute('''
                INSERT INTO learned_patterns
                (pattern_type, from_classification, to_classification, frequency, context)
                VALUES ('misclassification', ?, ?, 1, ?)
            ''', (from_class, to_class, comments[:200]))
    
    def is_document_reviewed(self, document_id: int) -> bool:
        """Check if a document has been reviewed"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT reviewed FROM review_status WHERE document_id = ?
        ''', (document_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        return result and result[0] == 1
    
    def get_unreviewed_documents(self, limit: int = 100) -> List[Dict]:
        """Get documents that haven't been reviewed yet"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT a.* FROM audit_trail a
            LEFT JOIN review_status r ON a.id = r.document_id
            WHERE (r.reviewed IS NULL OR r.reviewed = 0)
            AND a.classification IS NOT NULL
            ORDER BY a.timestamp DESC
            LIMIT ?
        ''', (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_learned_patterns(self) -> List[Dict]:
        """Get all learned patterns from corrections"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM learned_patterns
            ORDER BY frequency DESC, last_seen DESC
        ''')
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_correction_insights(self) -> Dict:
        """Get insights from corrections for prompt improvement"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Most common corrections
        cursor.execute('''
            SELECT from_classification, to_classification, frequency, context
            FROM learned_patterns
            WHERE frequency >= 3
            ORDER BY frequency DESC
            LIMIT 10
        ''')
        
        common_corrections = []
        for row in cursor.fetchall():
            common_corrections.append({
                'from': row[0],
                'to': row[1],
                'count': row[2],
                'examples': row[3].split(' | ')[:3]
            })
        
        # Agreement rate by classification
        cursor.execute('''
            SELECT original_classification, 
                   SUM(CASE WHEN is_agreement = 1 THEN 1 ELSE 0 END) as agreements,
                   COUNT(*) as total
            FROM feedback
            GROUP BY original_classification
        ''')
        
        accuracy_by_class = {}
        for row in cursor.fetchall():
            accuracy_by_class[row[0]] = {
                'agreements': row[1],
                'total': row[2],
                'accuracy': (row[1] / row[2] * 100) if row[2] > 0 else 0
            }
        
        conn.close()
        
        return {
            'common_corrections': common_corrections,
            'accuracy_by_class': accuracy_by_class
        }
    
    def save_audit_log(self, log_entry: Dict) -> int:
        """Save audit trail entry"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO audit_trail 
            (document_name, classification, confidence, user_id, action, details)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            log_entry.get('document_name'),
            log_entry.get('classification'),
            log_entry.get('confidence'),
            log_entry.get('user_id', 'system'),
            log_entry.get('action', 'classification'),
            json.dumps(log_entry.get('details', {}))
        ))
        
        audit_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return audit_id
    
    def get_audit_trail(self, limit: int = 100, include_reviewed: bool = True) -> List[Dict]:
        """Retrieve audit trail entries"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if include_reviewed:
            cursor.execute('''
                SELECT * FROM audit_trail 
                ORDER BY timestamp DESC 
                LIMIT ?
            ''', (limit,))
        else:
            cursor.execute('''
                SELECT * FROM audit_trail 
                WHERE reviewed = 0
                ORDER BY timestamp DESC 
                LIMIT ?
            ''', (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_feedback_history(self, document_id: str = None, limit: int = 100) -> List[Dict]:
        """Retrieve feedback history"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if document_id:
            cursor.execute('''
                SELECT * FROM feedback 
                WHERE document_id = ?
                ORDER BY timestamp DESC 
                LIMIT ?
            ''', (document_id, limit))
        else:
            cursor.execute('''
                SELECT * FROM feedback 
                ORDER BY timestamp DESC 
                LIMIT ?
            ''', (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_classification_stats(self) -> Dict:
        """Get statistics about classifications"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Count by classification
        cursor.execute('''
            SELECT classification, COUNT(*) as count 
            FROM audit_trail 
            GROUP BY classification
        ''')
        
        classification_counts = dict(cursor.fetchall())
        
        # Average confidence by classification
        cursor.execute('''
            SELECT classification, AVG(confidence) as avg_confidence 
            FROM audit_trail 
            WHERE confidence IS NOT NULL
            GROUP BY classification
        ''')
        
        avg_confidence = dict(cursor.fetchall())
        
        # Total documents processed
        cursor.execute('SELECT COUNT(*) FROM audit_trail')
        total_docs = cursor.fetchone()[0]
        
        # Review statistics
        cursor.execute('SELECT COUNT(*) FROM audit_trail WHERE reviewed = 1')
        reviewed_docs = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            'total_documents': total_docs,
            'reviewed_documents': reviewed_docs,
            'pending_review': total_docs - reviewed_docs,
            'classification_counts': classification_counts,
            'average_confidence': avg_confidence
        }