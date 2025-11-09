import sys
import os
# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from typing import Dict, List, Any
from services.gemini_service import GeminiService
from services.preprocessing import PreprocessingService
from utils.prompt_library import PromptLibrary
import asyncio
import json
import re

class ClassificationService:
    def __init__(self, api_key: str, enable_dual_verification: bool = True, db = None):
        self.gemini_primary = GeminiService(api_key, "gemini-2.5-flash")
        self.gemini_secondary = GeminiService(api_key, "gemini-2.5-flash") if enable_dual_verification else None
        self.prompt_library = PromptLibrary(db=db) # Pass Database
        self.enable_dual_verification = enable_dual_verification

    
    async def classify_document(self, file_path: str, file_type: str) -> Dict:
        """
        Main classification workflow
        """
        try:
            # Step 1: Preprocessing
            print("Step 1: Preprocessing document...")
            doc_info = PreprocessingService.extract_document_info(file_path, file_type)
            
            if not doc_info["is_legible"]:
                return {
                    "status": "error",
                    "message": "Document is not legible",
                    "pre_check": doc_info
                }
            
            # Step 2: Safety Check (parallel with classification)
            print("Step 2: Running safety check...")
            safety_result = await self._safety_check(doc_info)
            
            # Step 3: Primary Classification
            print("Step 3: Running primary classification...")
            primary_result = await self._primary_classification(doc_info)
            
            # Step 4: Dual Verification (if enabled)
            if self.enable_dual_verification and primary_result.get("confidence", 0) < 0.9:
                print("Step 4: Running secondary verification...")
                secondary_result = await self._secondary_verification(doc_info, primary_result)
                final_result = self._reconcile_classifications(primary_result, secondary_result)
            else:
                print("Step 4: Skipping dual verification (high confidence or disabled)...")
                final_result = primary_result
            
            # Step 5: Combine results
            print("Step 5: Combining results...")
            return {
                "status": "success",
                "pre_check": {
                    "total_pages": doc_info["total_pages"],
                    "total_images": doc_info["total_images"],
                    "is_legible": doc_info["is_legible"]
                },
                "classification": final_result.get("classification", "Unknown"),
                "confidence": final_result.get("confidence", 0.0),
                "reasoning": final_result.get("detailed_reasoning", "No reasoning provided"),
                "evidence": final_result.get("evidence", []),
                "pii_detected": final_result.get("pii_detected", {}),
                "safety_assessment": safety_result,
                "requires_human_review": final_result.get("requires_human_review", False),
                "review_reason": final_result.get("review_reason", ""),
                "dual_verification_used": self.enable_dual_verification
            }
        
        except Exception as e:
            print(f"❌ Error in classify_document: {str(e)}")
            import traceback
            traceback.print_exc()
            return {
                "status": "error",
                "message": str(e),
                "classification": "Error",
                "confidence": 0.0,
                "reasoning": f"Classification failed: {str(e)}",
                "evidence": [],
                "pii_detected": {},
                "safety_assessment": {"is_safe": True, "child_safe": True, "violations": []},
                "requires_human_review": True,
                "review_reason": "Classification error occurred"
            }
    
    async def _primary_classification(self, doc_info: Dict) -> Dict:
        """
        Primary classification using first LLM
        """
        try:
            # Prepare content for Gemini
            content = []
            for page in doc_info["pages_content"]:
                if page["text"] and page["text"].strip():
                    content.append(f"[Page {page['page_number']}]\n{page['text']}")
                if page["image"]:
                    content.append(page["image"])
            
            print(f"  Prepared {len(content)} content items for classification")
            
            prompt = self.prompt_library.get_classification_prompt()
            result = await self.gemini_primary.classify_document(content, prompt)
            
            print(f"  Gemini API response success: {result.get('success')}")
            
            if result["success"]:
                classification = result["classification"]
                
                # Validate required fields
                if not isinstance(classification, dict):
                    print(f"  Warning: Expected dict, got {type(classification)}")
                    classification = self._parse_response_text(result.get("raw_response", ""))
                
                # Ensure all required fields exist
                classification = self._ensure_required_fields(classification)
                
                return classification
            else:
                error_msg = result.get('error', 'Unknown error')
                print(f"  ❌ Classification API error: {error_msg}")
                raise Exception(f"Classification failed: {error_msg}")
                
        except Exception as e:
            print(f"  ❌ Exception in _primary_classification: {str(e)}")
            import traceback
            traceback.print_exc()
            raise
    
    
    async def _safety_check(self, doc_info: Dict) -> Dict:
        """
        Safety assessment - separate from classification
        """
        try:
            content = []
            for page in doc_info["pages_content"]:
                if page["text"] and page["text"].strip():
                    content.append(page["text"])
                if page["image"]:
                    content.append(page["image"])
            
            prompt = self.prompt_library.get_safety_check_prompt()
            result = await self.gemini_primary.safety_check(prompt, content)
            
            if result["success"]:
                safety_data = result["classification"]
                
                # Ensure proper structure
                return {
                    "is_safe": safety_data.get("is_safe", True),
                    "child_safe": safety_data.get("child_safe", True),
                    "violations": safety_data.get("violations", []),
                    "confidence": safety_data.get("confidence", 0.95)
                }
            else:
                # Default to safe if check fails
                return {
                    "is_safe": True, 
                    "child_safe": True, 
                    "violations": [], 
                    "confidence": 0.5
                }
        except Exception as e:
            print(f"  ⚠️ Safety check failed: {str(e)}")
            # Default to safe if check fails
            return {
                "is_safe": True, 
                "child_safe": True, 
                "violations": [], 
                "confidence": 0.5
            }

    async def _secondary_verification(self, doc_info: Dict, primary_result: Dict) -> Dict:
        """
        Secondary verification using second LLM
        """
        try:
            content = []
            for page in doc_info["pages_content"]:
                if page["text"] and page["text"].strip():
                    content.append(page["text"])
                if page["image"]:
                    content.append(page["image"])
            
            prompt = self.prompt_library.get_dual_verification_prompt(primary_result)
            result = await self.gemini_secondary.classify_document(content, prompt)
            
            if result["success"]:
                return result["classification"]
            else:
                return primary_result
        except Exception as e:
            print(f"  ⚠️ Secondary verification failed: {str(e)}")
            return primary_result
    
    def _reconcile_classifications(self, primary: Dict, secondary: Dict) -> Dict:
        """
        Reconcile two classification results
        """
        if secondary.get("agreement", False):
            return primary
        
        if secondary.get("recommendation") == "OVERRIDE":
            return {
                **secondary,
                "classification": secondary["your_classification"],
                "note": "Secondary verification overrode primary classification"
            }
        
        # If disagreement, flag for human review
        return {
            **primary,
            "requires_human_review": True,
            "review_reason": f"Disagreement between classifiers. Primary: {primary.get('classification')}, Secondary: {secondary.get('your_classification')}",
            "secondary_opinion": secondary
        }
    
    def _parse_response_text(self, text: str) -> Dict:
        """
        Parse JSON from response text, handling markdown code blocks
        """
        try:
            # Try direct JSON parse first
            return json.loads(text)
        except:
            # Try to extract JSON from markdown code blocks
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group(1))
                except:
                    pass
            
            # Try to find any JSON object in the text
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group(0))
                except:
                    pass
            
            # If all else fails, return a default structure
            print(f"  ⚠️ Could not parse JSON from response: {text[:200]}")
            return self._create_default_classification()
    
    def _ensure_required_fields(self, classification: Dict) -> Dict:
        """
        Ensure all required fields exist in the classification result
        """
        defaults = {
            "classification": "Unknown",
            "confidence": 0.5,
            "primary_reason": "Classification completed",
            "detailed_reasoning": "Document analyzed",
            "evidence": [],
            "pii_detected": {
                "ssn": False,
                "credit_card": False,
                "account_numbers": False,
                "names": False,
                "addresses": False,
                "other": []
            },
            "safety_assessment": {
                "is_safe": True,
                "child_safe": True,
                "issues": []
            },
            "recommendations": [],
            "requires_human_review": False,
            "review_reason": ""
        }
        
        # Merge defaults with actual classification
        result = {**defaults, **classification}
        
        # Ensure evidence is a list
        if not isinstance(result["evidence"], list):
            result["evidence"] = []
        
        # Ensure pii_detected is a dict
        if not isinstance(result["pii_detected"], dict):
            result["pii_detected"] = defaults["pii_detected"]
        
        return result
    
    def _create_default_classification(self) -> Dict:
        """
        Create a default classification result
        """
        return {
            "classification": "Public",
            "confidence": 0.5,
            "primary_reason": "Unable to parse detailed classification",
            "detailed_reasoning": "The document was analyzed but the response format was unexpected. Defaulting to Public classification for safety.",
            "evidence": [{
                "page": 1,
                "location": "Full document",
                "finding": "Unable to extract specific evidence",
                "category_trigger": "Default"
            }],
            "pii_detected": {
                "ssn": False,
                "credit_card": False,
                "account_numbers": False,
                "names": False,
                "addresses": False,
                "other": []
            },
            "safety_assessment": {
                "is_safe": True,
                "child_safe": True,
                "issues": []
            },
            "recommendations": ["Manual review recommended due to parsing issues"],
            "requires_human_review": True,
            "review_reason": "Unable to parse detailed classification response"
        }