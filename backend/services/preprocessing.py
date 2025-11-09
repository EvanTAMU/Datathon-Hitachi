import fitz  # PyMuPDF
from PIL import Image
import io
from typing import Dict, List, Tuple
import cv2
import numpy as np

class PreprocessingService:
    
    @staticmethod
    def extract_document_info(file_path: str, file_type: str) -> Dict:
        """
        Extract basic information from document
        """
        if file_type == "pdf":
            return PreprocessingService._process_pdf(file_path)
        elif file_type in ["png", "jpg", "jpeg"]:
            return PreprocessingService._process_image(file_path)
        else:
            raise ValueError(f"Unsupported file type: {file_type}")
    
    @staticmethod
    def _process_pdf(file_path: str) -> Dict:
        """
        Process PDF and extract metadata
        """
        doc = fitz.open(file_path)
        pages_content = []
        images = []
        image_count = 0
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            
            # Extract text
            text = page.get_text()
            
            # Check legibility (text density)
            legibility_score = PreprocessingService._calculate_legibility(text, page)
            
            # Extract images from page
            page_images = page.get_images()
            image_count += len(page_images)
            
            # Convert page to image for multimodal analysis
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            pages_content.append({
                "page_number": page_num + 1,
                "text": text,
                "image": img,
                "legibility_score": legibility_score,
                "image_count": len(page_images)
            })
            
            # Extract individual images
            for img_index, img_info in enumerate(page_images):
                xref = img_info[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                images.append({
                    "page": page_num + 1,
                    "index": img_index,
                    "image": Image.open(io.BytesIO(image_bytes))
                })
        
        return {
            "total_pages": len(doc),
            "total_images": image_count,
            "pages_content": pages_content,
            "extracted_images": images,
            "is_legible": all(p["legibility_score"] > 0.3 for p in pages_content)
        }
    
    @staticmethod
    def _process_image(file_path: str) -> Dict:
        """
        Process single image
        """
        img = Image.open(file_path)
        
        # Check image quality
        quality_score = PreprocessingService._calculate_image_quality(img)
        
        return {
            "total_pages": 1,
            "total_images": 1,
            "pages_content": [{
                "page_number": 1,
                "text": "",
                "image": img,
                "legibility_score": quality_score,
                "image_count": 1
            }],
            "extracted_images": [{
                "page": 1,
                "index": 0,
                "image": img
            }],
            "is_legible": quality_score > 0.3
        }
    
    @staticmethod
    def _calculate_legibility(text: str, page) -> float:
        """
        Calculate legibility score based on text density and quality
        """
        if not text or len(text.strip()) == 0:
            return 0.0
        
        # Text density
        page_area = page.rect.width * page.rect.height
        text_length = len(text.strip())
        density = min(text_length / page_area * 1000, 1.0)
        
        # Word count
        word_count = len(text.split())
        word_score = min(word_count / 50, 1.0)
        
        return (density + word_score) / 2
    
    @staticmethod
    def _calculate_image_quality(img: Image.Image) -> float:
        """
        Calculate image quality score
        """
        # Convert to numpy array
        img_array = np.array(img)
        
        # Calculate sharpness using Laplacian variance
        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        
        # Normalize score
        quality_score = min(laplacian_var / 1000, 1.0)
        
        return quality_score