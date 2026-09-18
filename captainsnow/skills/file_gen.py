"""
File Generation Skill — Create PDF and DOCX files.
"""
from .base import Skill
import os
import json
import re

class FileGenSkill(Skill):
    """Generate DOCX and PDF documents from text/markdown."""

    async def execute(self, payload: dict) -> dict:
        prompt = payload.get("prompt", "")
        
        parse_prompt = (
            "Extract the filename (without extension), the format (pdf or docx), and the document content from the prompt.\\n"
            "Respond ONLY with a JSON block like this:\\n"
            "{\\\"filename\\\": \\\"my_doc\\\", \\\"format\\\": \\\"pdf\\\", \\\"content\\\": \\\"The actual text content.\\\"}\\n"
            f"Prompt: {prompt}"
        )
        
        try:
            raw = await self.router.query("You are a document extraction parser.", parse_prompt, complexity="medium")
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if not match:
                return {"status": "error", "details": f"Failed to parse file generation payload from: {raw}"}
            data = json.loads(match.group(0))
            
            filename = data.get("filename", "document").replace(" ", "_")
            fmt = data.get("format", "pdf").lower()
            content = data.get("content", "Empty document.")
            
            reports_dir = self.config.get("reports_dir", "./reports")
            os.makedirs(reports_dir, exist_ok=True)
            
            filepath = os.path.join(reports_dir, f"{filename}.{fmt}")
            
            if fmt == "docx":
                from docx import Document
                doc = Document()
                doc.add_paragraph(content)
                doc.save(filepath)
                return {"status": "success", "action": "file_gen", "details": f"Created DOCX: {filepath}"}
                
            elif fmt == "pdf":
                from reportlab.pdfgen import canvas
                from reportlab.lib.pagesizes import letter
                c = canvas.Canvas(filepath, pagesize=letter)
                textobject = c.beginText(40, 750)
                # handle newlines properly
                for line in content.replace("\\n", "\n").splitlines():
                    # rudimentary wrapping, ideally we'd use reportlab Paragraph but this is v1
                    textobject.textLine(line[:100])
                    if len(line) > 100: textobject.textLine(line[100:200])
                c.drawText(textobject)
                c.save()
                return {"status": "success", "action": "file_gen", "details": f"Created PDF: {filepath}"}
            else:
                return {"status": "error", "details": f"Unsupported format {fmt}"}
                
        except Exception as e:
            return {"status": "error", "action": "file_gen", "details": str(e)}
