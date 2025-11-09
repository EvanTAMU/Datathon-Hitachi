import json
import os
import re
from typing import Dict, List

class PromptLibrary:
    def __init__(self, config_path: str = None, db=None):
        if config_path is None:
            # Default path relative to this file
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(base_dir, "config", "prompt_library.json")
        
        with open(config_path, 'r') as f:
            self.prompts = json.load(f)
        
        # Initialize enhancement service if database provided
        self.db = db
        if db:
            from services.prompt_enhancement import PromptEnhancementService
            self.enhancer = PromptEnhancementService(db)
        else:
            self.enhancer = None
    
    def perform_initial_scan(self, doc_info: Dict) -> Dict:
        """
        Perform quick initial scan to determine document characteristics
        This helps choose the right specialized prompt
        """
        scan_result = {
            'contains_numbers': False,
            'has_ssn_pattern': False,
            'has_credit_card_pattern': False,
            'is_internal': False,
            'has_confidential_markers': False,
            'has_violent_indicators': False,
            'is_marketing': False,
            'has_technical_content': False,
            'word_count': 0,
            'image_count': doc_info.get('total_images', 0)
        }
        
        # Combine all text from document
        all_text = ""
        for page in doc_info.get('pages_content', []):
            if page.get('text'):
                all_text += page['text'] + " "
        
        all_text_lower = all_text.lower()
        scan_result['word_count'] = len(all_text.split())
        
        # Check for numeric patterns (potential PII)
        if re.search(r'\d{3}-\d{2}-\d{4}', all_text):  # SSN pattern
            scan_result['has_ssn_pattern'] = True
            scan_result['contains_numbers'] = True
        
        if re.search(r'\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}', all_text):  # Credit card
            scan_result['has_credit_card_pattern'] = True
            scan_result['contains_numbers'] = True
        
        if re.search(r'\d{9,}', all_text):  # Account numbers (9+ digits)
            scan_result['contains_numbers'] = True
        
        # Check for internal/confidential markers
        internal_keywords = [
            'internal only', 'confidential', 'proprietary', 'do not distribute',
            'internal memo', 'company confidential', 'restricted', 'for internal use'
        ]
        for keyword in internal_keywords:
            if keyword in all_text_lower:
                scan_result['is_internal'] = True
                scan_result['has_confidential_markers'] = True
                break
        
        # Check for marketing indicators
        marketing_keywords = [
            'brochure', 'marketing', 'promotional', 'advertisement', 'sale',
            'visit our website', 'contact us', 'learn more', 'special offer'
        ]
        marketing_count = sum(1 for kw in marketing_keywords if kw in all_text_lower)
        if marketing_count >= 2:
            scan_result['is_marketing'] = True
        
        # Check for violent/unsafe indicators (for safety routing)
        violent_keywords = [
            'weapon', 'gun', 'rifle', 'military', 'combat', 'battlefield',
            'violence', 'assault', 'attack', 'warfare'
        ]
        violent_count = sum(1 for kw in violent_keywords if kw in all_text_lower)
        if violent_count >= 2:
            scan_result['has_violent_indicators'] = True
        
        # Check for technical/schematic content
        technical_keywords = [
            'specification', 'schematic', 'blueprint', 'technical drawing',
            'patent', 'design document', 'engineering'
        ]
        for keyword in technical_keywords:
            if keyword in all_text_lower:
                scan_result['has_technical_content'] = True
                break
        
        return scan_result
    
    def get_dynamic_prompt_tree(self, initial_scan_result: Dict = None) -> str:
        """
        Generate dynamic prompt based on initial document scan
        WITH HITL-learned enhancements
        """
        # Get base prompt based on scan
        base_prompt = self._get_base_prompt_for_scan(initial_scan_result)
        
        # Enhance with learned patterns from HITL feedback
        if self.enhancer:
            print(" Enhancing prompt with learned patterns...")
            base_prompt = self.enhancer.enhance_prompt(base_prompt, 'classification')
        
        return base_prompt
    
    def _get_base_prompt_for_scan(self, initial_scan_result: Dict = None) -> str:
        """Get base prompt based on scan results"""
        if not initial_scan_result:
            return self.get_classification_prompt()
        
        # Decision tree logic
        # Priority 1: SSN or Credit Card detected → PII-focused
        if initial_scan_result.get('has_ssn_pattern') or initial_scan_result.get('has_credit_card_pattern'):
            print(" Dynamic Prompt: Using PII-focused prompt (SSN/CC detected)")
            return self._get_pii_focused_prompt()
        
        # Priority 2: Numbers detected → Broader PII check
        if initial_scan_result.get('contains_numbers'):
            print(" Dynamic Prompt: Using PII-focused prompt (numbers detected)")
            return self._get_pii_focused_prompt()
        
        # Priority 3: Internal/Confidential markers → Confidential-focused
        if initial_scan_result.get('is_internal') or initial_scan_result.get('has_confidential_markers'):
            print(" Dynamic Prompt: Using Confidential-focused prompt")
            return self._get_confidential_focused_prompt()
        
        # Priority 4: Technical content → Technical classification
        if initial_scan_result.get('has_technical_content'):
            print(" Dynamic Prompt: Using Technical/Proprietary-focused prompt")
            return self._get_technical_focused_prompt()
        
        # Priority 5: Marketing indicators → Public-focused
        if initial_scan_result.get('is_marketing'):
            print(" Dynamic Prompt: Using Public/Marketing-focused prompt")
            return self._get_public_focused_prompt()
        
        # Priority 6: Violent indicators → Safety-aware classification
        if initial_scan_result.get('has_violent_indicators'):
            print(" Dynamic Prompt: Using Safety-aware classification prompt")
            return self._get_safety_aware_prompt()
        
        # Default: Use standard classification prompt
        print(" Dynamic Prompt: Using standard classification prompt")
        return self.get_classification_prompt()
    
    def _get_pii_focused_prompt(self) -> str:
        """Specialized prompt for documents with potential PII"""
        base = """
You are a PII detection expert analyzing a document that may contain Personal Identifiable Information.

**PRIMARY OBJECTIVE:** Identify and classify based on PII presence.

**PII Detection Checklist:**
1. **Social Security Numbers (SSN):** Format XXX-XX-XXXX or 9 consecutive digits
2. **Credit Card Numbers:** 16 digits, may have spaces or dashes
3. **Bank Account Numbers:** 8-17 digits
4. **Driver's License Numbers:** Various formats
5. **Dates of Birth:** Any DOB in context of a person
6. **Medical Record Numbers:** Any healthcare identifiers
7. **Passport Numbers:** Various formats
8. **Personal Addresses:** Full residential addresses
9. **Phone Numbers:** With personal context

**Classification Decision:**
- **IF ANY of the above PII is found** → "Highly Sensitive"
- **IF only names/addresses without SSN/financial data** → "Confidential"
- **IF no PII at all** → Evaluate as normal document

**CRITICAL:** Even ONE instance of SSN, credit card, or account number makes the entire document "Highly Sensitive"

**Response Format (JSON):**
{
    "classification": "Highly Sensitive" | "Confidential" | "Public",
    "confidence": 0.95,
    "primary_reason": "Found Social Security Number on page X",
    "detailed_reasoning": "Document contains PII including SSN which classifies it as Highly Sensitive",
    "evidence": [{
        "page": 1,
        "location": "Middle section",
        "finding": "SSN: XXX-XX-XXXX detected",
        "category_trigger": "Highly Sensitive - PII (SSN)"
    }],
    "pii_detected": {
        "ssn": true,
        "credit_card": false,
        "account_numbers": false,
        "names": true,
        "addresses": true,
        "other": []
    },
    "recommendations": ["Redact all PII", "Restrict access"],
    "requires_human_review": false,
    "review_reason": ""
}

Analyze and respond ONLY with JSON:
"""
        return self._apply_learned_enhancements(base, "PII")
    
    def _get_confidential_focused_prompt(self) -> str:
        """Specialized prompt for internal/confidential documents"""
        base = """
You are analyzing a document that appears to be INTERNAL or CONFIDENTIAL.

**Classification Logic:**

**Highly Sensitive**: Contains PII, proprietary tech, classified info, trade secrets
**Confidential**: Internal memos, business strategy, customer lists, operational docs
**Public**: Only if meant for external distribution despite labels

Analyze and respond with JSON format showing classification, evidence, and reasoning.
"""
        return self._apply_learned_enhancements(base, "Confidential")
    
    def _get_technical_focused_prompt(self) -> str:
        """Specialized prompt for technical documents"""
        return """
You are analyzing a TECHNICAL document for proprietary content.

**Highly Sensitive**: Defense specs, proprietary formulas, trade secrets, patent-pending
**Confidential**: Internal technical docs, SOPs, non-proprietary engineering
**Public**: Published papers, customer specs, open-source docs

Respond with JSON classification.
"""
    
    def _get_public_focused_prompt(self) -> str:
        """Specialized prompt for public documents"""
        return """
You are verifying a PUBLIC/MARKETING document.

**Confirm Public IF**: Marketing material, public contact info, no confidential markers
**Reclassify Confidential IF**: Draft restrictions, internal pricing, customer analytics
**Reclassify Highly Sensitive IF**: Any PII found

Respond with JSON classification.
"""
    
    def _get_safety_aware_prompt(self) -> str:
        """Specialized prompt for military/defense content"""
        return """
You are analyzing MILITARY/WEAPONS/DEFENSE content.

**Highly Sensitive**: Classified specs, active weapons systems, restricted tech
**Confidential**: Internal defense docs, non-classified equipment info
**Public**: Declassified historical docs, published military history

Note: Safety is evaluated separately. Focus on SENSITIVITY.

Respond with JSON classification.
"""
    
    def _apply_learned_enhancements(self, base_prompt: str, category: str) -> str:
        """Apply learned enhancements from HITL feedback"""
        if not self.db:
            return base_prompt
        
        try:
            patterns = self.db.get_learned_patterns()
            
            # Filter patterns relevant to this category
            relevant_patterns = [p for p in patterns if p['from_classification'] == category and p['frequency'] >= 3]
            
            if relevant_patterns:
                enhancement = "\n\n--- LEARNED FROM HUMAN CORRECTIONS ---\n"
                for pattern in relevant_patterns[:3]:  # Top 3 patterns
                    enhancement += f"COMMON MISTAKE: Documents are often incorrectly classified as '{pattern['from_classification']}' when they should be '{pattern['to_classification']}'\n"
                    enhancement += f"   Occurred {pattern['frequency']} times. Context: {pattern['context'][:150]}...\n\n"
                enhancement += "--- END LEARNED PATTERNS ---\n\n"
                
                return base_prompt + enhancement
        except Exception as e:
            print(f"Warning: Could not apply learned enhancements: {e}")
        
        return base_prompt
    
    def get_classification_prompt(self, page_content: str = None) -> str:
        """Standard classification prompt with enhancements"""
        base_prompt = """
You are an expert document classifier for regulatory compliance. Analyze the provided document and classify it into ONE of these categories based on SENSITIVITY LEVEL:

**Categories (Choose ONE):**

1. **Highly Sensitive**: Documents containing:
   - Personal Identifiable Information (PII): Social Security Numbers (format: XXX-XX-XXXX), credit card numbers, bank account numbers, date of birth, criminal history
   - Proprietary technical schematics or defense designs
   - Military equipment specifications or classified information
   - Medical records with patient identifiers

2. **Confidential**: Documents containing:
   - Internal business communications (memos, strategy documents)
   - Non-public operational information
   - Customer lists with contact details (names, addresses, phone numbers)
   - Internal financial reports not meant for public distribution
   - Employee information (but NOT SSN or sensitive PII)

3. **Public**: Documents that are:
   - Marketing materials and brochures
   - Press releases
   - Product catalogs meant for public distribution
   - Generic promotional images

**IMPORTANT CLASSIFICATION RULES:**
- If document contains SSN, credit cards, or account numbers → ALWAYS "Highly Sensitive"
- If document says "Internal Only", "Confidential", or contains business strategy → "Confidential"
- If document is clearly for public marketing/distribution → "Public"
- Choose the HIGHEST sensitivity level if multiple apply
- DO NOT classify as "Unsafe" - that is handled separately

**Response Format (MUST be valid JSON):**
{
    "classification": "Highly Sensitive" | "Confidential" | "Public",
    "confidence": 0.95,
    "primary_reason": "Brief one-sentence explanation",
    "detailed_reasoning": "Detailed explanation of why this classification was chosen",
    "evidence": [
        {
            "page": 1,
            "location": "Top of page",
            "finding": "Found Social Security Number 123-45-6789",
            "category_trigger": "Highly Sensitive - PII (SSN)"
        }
    ],
    "pii_detected": {
        "ssn": false,
        "credit_card": false,
        "account_numbers": false,
        "names": false,
        "addresses": false,
        "other": []
    },
    "recommendations": ["Redact SSN before distribution"],
    "requires_human_review": false,
    "review_reason": ""
}

**Examples:**

Example 1 - Marketing Brochure:
- Content: "Welcome to our exciting new product! Visit www.example.com"
- Classification: "Public"
- Reasoning: "This is clearly marketing material meant for public distribution"

Example 2 - Employment Application with SSN:
- Content: "Name: John Smith, SSN: 123-45-6789"
- Classification: "Highly Sensitive"
- Reasoning: "Contains Social Security Number which is PII"

Example 3 - Internal Memo:
- Content: "INTERNAL ONLY - Q4 Strategy Discussion"
- Classification: "Confidential"
- Reasoning: "Marked as internal only, contains business strategy"

Now analyze the document and respond ONLY with the JSON format above:
"""
        
        # Enhance with learned patterns
        if self.enhancer:
            base_prompt = self.enhancer.enhance_prompt(base_prompt, 'classification')
        
        return base_prompt
    
    def _get_pii_focused_prompt(self) -> str:
        """Specialized prompt for documents with potential PII"""
        base = """
You are a PII detection expert analyzing a document that may contain Personal Identifiable Information.

**PRIMARY OBJECTIVE:** Identify and classify based on PII presence.

**PII Detection Checklist:**
1. **Social Security Numbers (SSN):** Format XXX-XX-XXXX or 9 consecutive digits
2. **Credit Card Numbers:** 16 digits, may have spaces or dashes
3. **Bank Account Numbers:** 8-17 digits
4. **Driver's License Numbers:** Various formats
5. **Dates of Birth:** Any DOB in context of a person
6. **Medical Record Numbers:** Any healthcare identifiers
7. **Passport Numbers:** Various formats
8. **Personal Addresses:** Full residential addresses
9. **Phone Numbers:** With personal context

**Classification Decision:**
- **IF ANY of the above PII is found** → "Highly Sensitive"
- **IF only names/addresses without SSN/financial data** → "Confidential"
- **IF no PII at all** → Evaluate as normal document

**CRITICAL:** Even ONE instance of SSN, credit card, or account number makes the entire document "Highly Sensitive"

**Response Format (JSON):**
{
    "classification": "Highly Sensitive" | "Confidential" | "Public",
    "confidence": 0.95,
    "primary_reason": "Found Social Security Number on page X",
    "detailed_reasoning": "Document contains PII including SSN which classifies it as Highly Sensitive",
    "evidence": [{
        "page": 1,
        "location": "Middle section",
        "finding": "SSN: XXX-XX-XXXX detected",
        "category_trigger": "Highly Sensitive - PII (SSN)"
    }],
    "pii_detected": {
        "ssn": true,
        "credit_card": false,
        "account_numbers": false,
        "names": true,
        "addresses": true,
        "other": []
    },
    "recommendations": ["Redact all PII", "Restrict access"],
    "requires_human_review": false,
    "review_reason": ""
}

**SCAN CAREFULLY:** Check every page, every number sequence, every form field.
Analyze the document now and respond ONLY with JSON:
"""
        return self._apply_learned_enhancements(base, "Highly Sensitive")
    
    def _get_confidential_focused_prompt(self) -> str:
        """Specialized prompt for internal/confidential documents"""
        base = """
You are analyzing a document that appears to be INTERNAL or CONFIDENTIAL.

**PRIMARY OBJECTIVE:** Determine the appropriate confidentiality level.

**Classification Logic:**

**Highly Sensitive** (Choose if):
- Contains PII (SSN, credit cards, account numbers)
- Contains proprietary technical designs or trade secrets
- Contains classified government information
- Contains executive compensation details
- Contains unreleased financial data

**Confidential** (Choose if):
- Marked "Internal Only" or "Confidential"
- Contains business strategy or planning documents
- Contains customer lists (names/addresses only, no SSN)
- Contains employee information (no SSN)
- Contains draft documents not meant for public release
- Contains meeting minutes or internal communications
- Contains operational procedures

**Public** (Only if):
- Clearly meant for external distribution despite "internal" label
- Already published information

**Response Format (JSON):**
{
    "classification": "Highly Sensitive" | "Confidential" | "Public",
    "confidence": 0.90,
    "primary_reason": "Document marked as Internal Only",
    "detailed_reasoning": "Internal business document with strategic planning info",
    "evidence": [{
        "page": 1,
        "location": "Header",
        "finding": "CONFIDENTIAL - INTERNAL USE ONLY",
        "category_trigger": "Confidential"
    }],
    "pii_detected": {
        "ssn": false,
        "credit_card": false,
        "account_numbers": false,
        "names": true,
        "addresses": false,
        "other": []
    },
    "recommendations": ["Restrict distribution"],
    "requires_human_review": false,
    "review_reason": ""
}

Analyze and respond ONLY with JSON:
"""
        return self._apply_learned_enhancements(base, "Confidential")
    
    def _get_technical_focused_prompt(self) -> str:
        """Specialized prompt for technical documents"""
        base = """
You are analyzing a TECHNICAL document for proprietary content.

**Highly Sensitive**: Defense specs, proprietary formulas, trade secrets, patent-pending
**Confidential**: Internal technical docs, SOPs, non-proprietary engineering
**Public**: Published papers, customer specs, open-source docs

Respond with JSON classification including evidence and reasoning.
"""
        return self._apply_learned_enhancements(base, "Technical")
    
    def _get_public_focused_prompt(self) -> str:
        """Specialized prompt for public documents"""
        base = """
You are verifying a PUBLIC/MARKETING document.

**Confirm Public IF**: Marketing material, public contact info, no confidential markers
**Reclassify Confidential IF**: Draft restrictions, internal pricing
**Reclassify Highly Sensitive IF**: Any PII found

Respond with JSON classification.
"""
        return self._apply_learned_enhancements(base, "Public")
    
    def _get_safety_aware_prompt(self) -> str:
        """Specialized prompt for military/defense content"""
        return """
You are analyzing MILITARY/WEAPONS/DEFENSE content for SENSITIVITY (not safety).

**Highly Sensitive**: Classified specs, active weapons systems, restricted tech
**Confidential**: Internal defense docs, non-classified equipment info
**Public**: Declassified docs, published military history

Note: Safety is evaluated separately. Focus on SENSITIVITY level.

Respond with JSON classification.
"""
    
    def _apply_learned_enhancements(self, base_prompt: str, category: str) -> str:
        """Apply learned enhancements from HITL feedback"""
        if not self.db:
            return base_prompt
        
        try:
            patterns = self.db.get_learned_patterns()
            
            # Filter patterns relevant to this category
            relevant_patterns = [
                p for p in patterns 
                if (p['from_classification'] == category or p['to_classification'] == category) 
                and p['frequency'] >= 3
            ]
            
            if relevant_patterns:
                enhancement = "\n\n--- LEARNED FROM HUMAN CORRECTIONS ---\n"
                enhancement += "The following patterns have been identified from expert feedback:\n\n"
                
                for pattern in relevant_patterns[:3]:  # Top 3 patterns
                    enhancement += f"COMMON MISTAKE #{pattern['frequency']}:\n"
                    enhancement += f"   '{pattern['from_classification']}' is often confused with '{pattern['to_classification']}'\n"
                    
                    if pattern.get('context'):
                        contexts = pattern['context'].split(' | ')
                        if contexts:
                            enhancement += f"   Expert feedback: {contexts[0][:150]}\n"
                    
                    enhancement += f"   → Be extra careful distinguishing these categories!\n\n"
                
                enhancement += "--- END LEARNED PATTERNS ---\n\n"
                
                print(f"  Applied {len(relevant_patterns)} learned patterns to prompt")
                return base_prompt + enhancement
        except Exception as e:
            print(f"  Could not apply learned enhancements: {e}")
        
        return base_prompt
    
    def get_safety_check_prompt(self) -> str:
        """Dedicated safety check prompt"""
        return """
You are a content safety expert analyzing this document for harmful content that would make it UNSAFE.

**CRITICAL INSTRUCTION:** Be VERY STRICT in identifying unsafe content. When in doubt about violence, explicit content, or child safety, mark as UNSAFE.

**Analyze for these specific safety violations:**

1. **Child Safety (CRITICAL):**
   - ANY content that could harm children
   - Content inappropriate for minors
   - Violent imagery involving children
   - Any exploitative content

2. **Graphic Violence:**
   - Images or descriptions of violence
   - Blood, gore, weapons being used
   - Battlefield scenes, combat imagery
   - Dead or injured people or animals
   - ANY imagery that shows harm being done

3. **Hate Speech:**
   - Discriminatory language
   - Slurs or derogatory terms
   - Content promoting hatred

4. **Sexually Explicit Content:**
   - Nudity or sexual imagery
   - Sexual exploitation
   - Adult content

5. **Dangerous Content:**
   - Instructions for making weapons
   - Guides for illegal activities
   - Self-harm content

6. **Other Harmful Content:**
   - Cyberbullying content
   - Malware or hacking tutorials
   - Dangerous misinformation

**IMPORTANT RULES:**
- Military equipment images (tanks, jets, weapons) → MARK AS UNSAFE
- ANY violent imagery → MARK AS UNSAFE  
- Disturbing or graphic content → MARK AS UNSAFE
- Business documents with PII → SAFE (just sensitive)
- Internal memos → SAFE (just confidential)
- Marketing materials → SAFE

**Response Format (MUST be valid JSON):**

If SAFE:
{
    "is_safe": true,
    "child_safe": true,
    "violations": [],
    "confidence": 0.95,
    "requires_immediate_review": false
}

If UNSAFE:
{
    "is_safe": false,
    "child_safe": false,
    "violations": [{
        "type": "Graphic Violence",
        "severity": "high",
        "location": "Page 1, main image",
        "description": "Image shows weapons or violent scene"
    }],
    "confidence": 0.90,
    "requires_immediate_review": true
}

**TEST YOUR DECISION:**
- Would this be appropriate on a children's website? → If NO, mark UNSAFE
- Does this show violence, weapons, or harm? → If YES, mark UNSAFE
- Is this disturbing or graphic? → If YES, mark UNSAFE

Analyze the document. Be STRICT. Respond ONLY with JSON:
"""
    
    def get_dual_verification_prompt(self, first_result: Dict) -> str:
        """Second LLM verification prompt"""
        return f"""
You are a secondary reviewer verifying a document classification.

**Previous Classification:** {first_result.get('classification')}
**Previous Confidence:** {first_result.get('confidence')}

**Your Task:**
1. Independently analyze the document
2. Determine if you agree with the classification
3. Focus on these key questions:
   - Does it contain PII (SSN, credit cards, account numbers)? → Highly Sensitive
   - Is it marked "Internal" or "Confidential"? → Confidential  
   - Is it public marketing material? → Public

**Previous Analysis:**
{json.dumps(first_result, indent=2)}

**Response Format (MUST be valid JSON):**
{{
    "agreement": true,
    "your_classification": "Highly Sensitive" | "Confidential" | "Public",
    "confidence": 0.95,
    "discrepancies": [],
    "additional_evidence": [],
    "recommendation": "CONFIRM",
    "reasoning": "I agree because..."
}}

If you DISAGREE:
{{
    "agreement": false,
    "your_classification": "Different classification",
    "confidence": 0.90,
    "discrepancies": ["Primary missed SSN on page 2"],
    "additional_evidence": [
        {{
            "page": 2,
            "finding": "Found SSN: XXX-XX-XXXX",
            "category_trigger": "Highly Sensitive"
        }}
    ],
    "recommendation": "OVERRIDE",
    "reasoning": "I found evidence of PII that was missed"
}}

Analyze and respond ONLY with JSON:
"""