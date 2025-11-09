import google.generativeai as genai
from typing import List, Dict, Any
import json
from PIL import Image
import io
import re

class GeminiService:
    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash"):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)
        self.safety_settings = [
            {
                "category": "HARM_CATEGORY_HARASSMENT",
                "threshold": "BLOCK_NONE"
            },
            {
                "category": "HARM_CATEGORY_HATE_SPEECH",
                "threshold": "BLOCK_NONE"
            },
            {
                "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "threshold": "BLOCK_NONE"
            },
            {
                "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                "threshold": "BLOCK_NONE"
            }
        ]
    
    async def classify_document(self, content: List[Any], prompt: str) -> Dict:
        """
        Classify document using Gemini API
        content: List of text strings and/or PIL Images
        """
        try:
            print(f"    Sending request to Gemini API...")
            print(f"    Content items: {len(content)}")
            
            response = self.model.generate_content(
                [prompt] + content,
                safety_settings=self.safety_settings,
                generation_config={
                    "temperature": 0.1,
                    "top_p": 0.95,
                    "top_k": 40,
                    "max_output_tokens": 8192,
                }
            )
            
            print(f"    ✓ Received response from Gemini")
            
            # Get the text response
            response_text = response.text
            print(f"    Response length: {len(response_text)} characters")
            
            # Try to parse JSON from the response
            result = self._parse_json_response(response_text)
            
            return {
                "success": True,
                "classification": result,
                "raw_response": response_text
            }
            
        except Exception as e:
            error_message = str(e)
            print(f"    ❌ Gemini API Error: {error_message}")
            
            # Check for specific error types
            if "API key" in error_message:
                error_message = "Invalid API key. Please check your GEMINI_API_KEY in .env file"
            elif "quota" in error_message.lower():
                error_message = "API quota exceeded. Please check your Gemini API usage limits"
            elif "blocked" in error_message.lower():
                error_message = "Content was blocked by safety filters"
            
            return {
                "success": False,
                "error": error_message,
                "classification": self._create_error_classification(error_message)
            }
    
    async def safety_check(self, prompt: str, content: List[Any]) -> Dict:
        """
        Dedicated safety check for content
        """
        safety_prompt = prompt
        
        return await self.classify_document(content, safety_prompt)
    
    def _parse_json_response(self, response_text: str) -> Dict:
        """
        Parse JSON from response, handling markdown code blocks and other formats
        """
        # Try direct JSON parse
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            pass
        
        # Try to extract JSON from markdown code blocks
        json_patterns = [
            r'```json\s*(\{.*?\})\s*```',  # ```json {...} ```
            r'```\s*(\{.*?\})\s*```',       # ``` {...} ```
            r'(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})'  # Any JSON object
        ]
        
        for pattern in json_patterns:
            matches = re.findall(pattern, response_text, re.DOTALL)
            for match in matches:
                try:
                    return json.loads(match)
                except json.JSONDecodeError:
                    continue
        
        # If we can't parse JSON, create a basic structure from the text
        print(f"    ⚠️ Could not parse JSON, creating structured response from text")
        return self._create_fallback_classification(response_text)
    
    def _create_fallback_classification(self, response_text: str) -> Dict:
        """
        Create a classification structure from plain text response
        """
        # Try to extract classification from text
        classification = "Public"  # Default
        if any(word in response_text.lower() for word in ["highly sensitive", "ssn", "social security", "classified"]):
            classification = "Highly Sensitive"
        elif any(word in response_text.lower() for word in ["confidential", "internal", "private"]):
            classification = "Confidential"
        elif any(word in response_text.lower() for word in ["unsafe", "inappropriate", "explicit"]):
            classification = "Unsafe"
        
        return {
            "classification": classification,
            "confidence": 0.6,
            "primary_reason": "Parsed from text response",
            "detailed_reasoning": response_text[:500],  # First 500 chars
            "evidence": [{
                "page": 1,
                "location": "Document analysis",
                "finding": "Classification based on text analysis",
                "category_trigger": classification
            }],
            "pii_detected": {
                "ssn": "ssn" in response_text.lower() or "social security" in response_text.lower(),
                "credit_card": "credit card" in response_text.lower(),
                "account_numbers": "account" in response_text.lower(),
                "names": False,
                "addresses": False,
                "other": []
            },
            "safety_assessment": {
                "is_safe": "unsafe" not in response_text.lower(),
                "child_safe": "unsafe" not in response_text.lower(),
                "issues": []
            },
            "recommendations": [],
            "requires_human_review": True,
            "review_reason": "Response format was not standard JSON"
        }
    
    def _create_error_classification(self, error_message: str) -> Dict:
        """
        Create a classification result for error cases
        """
        return {
            "classification": "Error",
            "confidence": 0.0,
            "primary_reason": "API Error",
            "detailed_reasoning": f"Classification failed due to error: {error_message}",
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
            "recommendations": ["Retry classification", "Check API configuration"],
            "requires_human_review": True,
            "review_reason": f"API Error: {error_message}"
        }