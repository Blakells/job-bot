#!/usr/bin/env python3
"""
Convert all .txt resumes and cover letters to PDF format
"""

from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.enums import TA_LEFT

def text_to_pdf(txt_path, pdf_path):
    """Convert a text file to a well-formatted PDF"""
    
    # Read the text content
    with open(txt_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Create PDF
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=letter,
        rightMargin=0.75*inch,
        leftMargin=0.75*inch,
        topMargin=0.75*inch,
        bottomMargin=0.75*inch
    )
    
    # Styles
    styles = getSampleStyleSheet()
    
    # Custom styles for resume
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor='#000000',
        spaceAfter=6,
        alignment=TA_LEFT
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=12,
        textColor='#000000',
        spaceAfter=6,
        spaceBefore=12,
        alignment=TA_LEFT
    )
    
    body_style = ParagraphStyle(
        'CustomBody',
        parent=styles['BodyText'],
        fontSize=10,
        textColor='#000000',
        spaceAfter=6,
        alignment=TA_LEFT,
        leading=14
    )
    
    # Build document
    story = []
    
    # Process content line by line
    lines = content.split('\n')
    
    for line in lines:
        line = line.strip()
        
        if not line:
            # Empty line = spacer
            story.append(Spacer(1, 0.1*inch))
            continue
        
        # Check if it's a separator line
        if line.startswith('---') or line.startswith('==='):
            story.append(Spacer(1, 0.15*inch))
            continue
        
        # Check if it's the name (first substantial line, all caps)
        if len(story) == 0 and line.isupper() and len(line) < 50:
            story.append(Paragraph(line, title_style))
            continue
        
        # Check if it's a section header (all caps or ends with colon)
        if (line.isupper() and len(line) < 60) or line.endswith(':'):
            story.append(Paragraph(f'<b>{line}</b>', heading_style))
            continue
        
        # Check if it's a job title or company line (contains | or specific patterns)
        if ' | ' in line or (' - ' in line and len(line) < 100):
            story.append(Paragraph(f'<b>{line}</b>', body_style))
            continue
        
        # Regular body text
        # Escape HTML special characters and preserve formatting
        line = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        story.append(Paragraph(line, body_style))
    
    # Build PDF
    doc.build(story)

def main():
    tailored_dir = Path("outputs/tailored")
    
    # Get all .txt files
    txt_files = list(tailored_dir.glob("*.txt"))
    
    print(f"\n{'='*60}")
    print("Converting TXT files to PDF")
    print(f"{'='*60}\n")
    
    converted = 0
    errors = 0
    
    for txt_file in txt_files:
        # Skip summary files
        if "SUMMARY" in txt_file.name:
            continue
        
        # Create PDF path
        pdf_file = txt_file.with_suffix('.pdf')
        
        try:
            print(f"Converting: {txt_file.name[:60]}...")
            text_to_pdf(txt_file, pdf_file)
            print(f"  ✅ Created: {pdf_file.name}")
            converted += 1
        except Exception as e:
            print(f"  ❌ Error: {e}")
            errors += 1
    
    print(f"\n{'='*60}")
    print(f"CONVERSION COMPLETE")
    print(f"{'='*60}")
    print(f"✅ Converted: {converted} files")
    if errors > 0:
        print(f"❌ Errors: {errors} files")
    print(f"\nPDF files saved to: {tailored_dir}/")

if __name__ == "__main__":
    main()
