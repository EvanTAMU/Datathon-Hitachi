from typing import Dict, List
from database.hitl_feedback import HITLDatabase

class PromptEnhancementService:
    """
    Uses HITL feedback to dynamically enhance prompts
    """
    def __init__(self, db: HITLDatabase):
        self.db = db
    
    def get_enhancement_context(self) -> Dict:
        """
        Get context from learned patterns to enhance prompts
        """
        try:
            insights = self.db.get_correction_insights()
            
            enhancement_context = {
                'common_confusions': [],
                'emphasis_needed': [],
                'additional_examples': []
            }
            
            # Identify common confusions
            for correction in insights.get('common_corrections', []):
                if correction['count'] >= 5:
                    enhancement_context['common_confusions'].append({
                        'from': correction['from'],
                        'to': correction['to'],
                        'guidance': self._generate_confusion_guidance(correction)
                    })
            
            # Identify categories needing emphasis
            for class_name, stats in insights.get('accuracy_by_class', {}).items():
                accuracy = stats.get('accuracy', 100)  # Default to 100 if not present
                if accuracy < 80:  # Less than 80% accuracy
                    enhancement_context['emphasis_needed'].append({
                        'category': class_name,
                        'accuracy': accuracy,
                        'guidance': self._generate_emphasis_guidance(class_name, stats)
                    })
            
            return enhancement_context
        
        except Exception as e:
            print(f"  ⚠️ Error getting enhancement context: {e}")
            # Return empty context on error
            return {
                'common_confusions': [],
                'emphasis_needed': [],
                'additional_examples': []
            }
    
    def _generate_confusion_guidance(self, correction: Dict) -> str:
        """Generate guidance text for common confusions"""
        from_cat = correction['from']
        to_cat = correction['to']
        examples = correction.get('examples', [])
        
        guidance = f"\n**IMPORTANT DISTINCTION:** Documents are often misclassified as '{from_cat}' when they should be '{to_cat}'.\n"
        
        if examples:
            guidance += f"Common indicators for '{to_cat}':\n"
            for example in examples[:2]:
                if example and example.strip():
                    guidance += f"- {example.strip()}\n"
        
        return guidance
    
    def _generate_emphasis_guidance(self, category: str, stats: Dict) -> str:
        """Generate emphasis guidance for problematic categories"""
        # Use 'accuracy' key instead of 'current_accuracy'
        accuracy = stats.get('accuracy', 0)
        agreements = stats.get('agreements', 0)
        total = stats.get('total', 0)
        
        return f"\n**EXTRA ATTENTION NEEDED:** '{category}' classification has {accuracy:.1f}% accuracy ({agreements}/{total} correct). Be especially careful with this category.\n"
    
    def enhance_prompt(self, base_prompt: str, prompt_type: str = 'classification') -> str:
        """
        Enhance a prompt with learned context
        """
        try:
            context = self.get_enhancement_context()
            
            # If no enhancements needed, return original
            if not context['common_confusions'] and not context['emphasis_needed']:
                print("  ℹ️ No learned patterns to apply yet")
                return base_prompt
            
            enhancement = "\n\n--- 🧠 LEARNED FROM HUMAN FEEDBACK ---\n"
            
            # Add confusion warnings
            if context['common_confusions']:
                enhancement += "\n🎯 COMMON MISTAKES TO AVOID:\n"
                for confusion in context['common_confusions']:
                    enhancement += confusion['guidance']
            
            # Add emphasis areas
            if context['emphasis_needed']:
                enhancement += "\n⚠️ CATEGORIES REQUIRING EXTRA CARE:\n"
                for emphasis in context['emphasis_needed']:
                    enhancement += emphasis['guidance']
            
            enhancement += "\n--- END LEARNED CONTEXT ---\n\n"
            
            print(f"  ✓ Applied {len(context['common_confusions'])} confusion patterns and {len(context['emphasis_needed'])} emphasis areas")
            
            # Insert enhancement after the initial instruction but before examples
            if "**Response Format" in base_prompt:
                parts = base_prompt.split("**Response Format")
                return parts[0] + enhancement + "**Response Format" + parts[1]
            else:
                # Append to end if no clear insertion point
                return base_prompt + enhancement
        
        except Exception as e:
            print(f"  ⚠️ Error enhancing prompt: {e}")
            import traceback
            traceback.print_exc()
            # Return original prompt if enhancement fails
            return base_prompt