"""
Zotero to Obsidian - Paper Analyzer with Dynamic Keyword Loading
================================================================

This script automatically analyzes papers from your Zotero library and creates
structured Obsidian notes with AI-generated summaries.

Key features:
- Automatically loads controlled keywords from generated file
- Analyzes both full-text PDFs and abstracts
- Creates Obsidian-compatible markdown files
- Handles duplicate files intelligently

Author: Hojung Lee & Claude
Last Updated: 2026
"""

from pyzotero import zotero
from openai import OpenAI
import os
from datetime import datetime
import requests
import PyPDF2
from io import BytesIO
import time
import re

# ==========================================
# [CONFIGURATION] — loaded from config.py
# ==========================================
from config import (
    ZOTERO_ID, ZOTERO_KEY, OPENAI_KEY,
    OBSIDIAN_FOLDER, KEYWORDS_FILE, COLLECTION_ID,
)

DUPLICATE_MODE = "suffix"  # "suffix" adds 2024a/2024b; "replace" overwrites
# ==========================================

def load_controlled_keywords(filepath):
    """
    Load controlled keywords from the generated file.
    Parses the Python list format from the keyword extractor output.
    """
    
    if not os.path.exists(filepath):
        print(f"⚠️ Warning: Keywords file not found at {filepath}")
        print("   Using empty keyword list. Run keyword extractor first!")
        return []
    
    keywords = []
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Find the CONTROLLED_KEYWORDS list in the file
        # Pattern: "keyword",  # appeared X times
        pattern = r'"([^"]+)",\s*#\s*appeared\s+\d+\s+times'
        matches = re.findall(pattern, content)
        
        if matches:
            keywords = matches
            print(f"✅ Loaded {len(keywords)} controlled keywords from file")
        else:
            print("⚠️ Warning: Could not parse keywords from file")
            print("   File format may have changed. Check the keywords file.")
    
    except Exception as e:
        print(f"❌ Error loading keywords: {e}")
        return []
    
    return keywords

# Load controlled keywords at startup
CONTROLLED_KEYWORDS = load_controlled_keywords(KEYWORDS_FILE)

os.makedirs(OBSIDIAN_FOLDER, exist_ok=True)

zot = zotero.Zotero(ZOTERO_ID, 'user', ZOTERO_KEY)
client = OpenAI(api_key=OPENAI_KEY)

def extract_year(date_str):
    """Extract year from various date formats"""
    if not date_str:
        return 'n.d.'
    
    date_str = date_str.strip()
    
    if len(date_str) >= 4 and date_str[:4].isdigit():
        return date_str[:4]
    
    if '/' in date_str:
        parts = date_str.split('/')
        for part in reversed(parts):
            part = part.strip()
            if len(part) == 4 and part.isdigit():
                return part
            elif len(part) == 2 and part.isdigit():
                year_int = int(part)
                return str(2000 + year_int) if year_int <= 30 else str(1900 + year_int)
    
    match = re.search(r'\b(19|20)\d{2}\b', date_str)
    if match:
        return match.group()
    
    return 'n.d.'

def get_unique_filename(base_author, base_year, folder, mode):
    """Handle duplicate filenames based on mode (replace or suffix)"""
    filename = f"{base_author} ({base_year}).md"
    filepath = os.path.join(folder, filename)
    
    if mode == "replace":
        return filename, base_year, os.path.exists(filepath)
    
    elif mode == "suffix":
        if not os.path.exists(filepath):
            return filename, base_year, False
        
        for suffix in 'abcdefghijklmnopqrstuvwxyz':
            year_with_suffix = f"{base_year}{suffix}"
            filename = f"{base_author} ({year_with_suffix}).md"
            filepath = os.path.join(folder, filename)
            
            if not os.path.exists(filepath):
                return filename, year_with_suffix, False
        
        counter = 1
        while True:
            year_with_suffix = f"{base_year}-{counter}"
            filename = f"{base_author} ({year_with_suffix}).md"
            filepath = os.path.join(folder, filename)
            
            if not os.path.exists(filepath):
                return filename, year_with_suffix, False
            counter += 1

print("="*60)
print("📚 Zotero to Obsidian - Paper Analyzer")
print("="*60)
print(f"🔍 Fetching items from collection...")
print(f"📋 Duplicate handling mode: {DUPLICATE_MODE}")
print(f"📌 Controlled keywords loaded: {len(CONTROLLED_KEYWORDS)}\n")

if len(CONTROLLED_KEYWORDS) == 0:
    print("⚠️ WARNING: No controlled keywords loaded!")
    print(f"   Expected file: {KEYWORDS_FILE}")
    print("   Run the keyword extractor first to generate this file.\n")
    response = input("Continue anyway? (y/n): ")
    if response.lower() != 'y':
        print("Exiting...")
        exit()

items = zot.collection_items(COLLECTION_ID)

print(f"📊 Found {len(items)} total items\n")

success_count = 0
fail_count = 0
skip_count = 0
replace_count = 0

for idx, item in enumerate(items, 1):
    
    data = item['data']
    item_type = data.get('itemType')
    item_key = item['key']
    
    is_paper = item_type in ['journalArticle', 'conferencePaper', 'book', 'bookSection', 'report', 'thesis']
    # Only process standalone PDFs (no parentItem) — PDFs attached to a paper
    # are already handled when the parent paper item is processed below.
    is_standalone_pdf = (
        item_type == 'attachment'
        and data.get('contentType') == 'application/pdf'
        and not data.get('parentItem')
    )

    if not is_paper and not is_standalone_pdf:
        skip_count += 1
        continue
    
    title = data.get('title', 'Untitled')
    abstract = data.get('abstractNote', '')
    creators = data.get('creators', [])

    year = extract_year(data.get('date', ''))
    is_pdf_attachment = is_standalone_pdf  # alias used later in the logic
    
    print(f"\n{'='*60}")
    print(f"[{idx}/{len(items)}] 📄 {title[:60]}...")
    print(f"{'='*60}")
    
    # Generate APA-style author name
    if len(creators) == 0:
        if is_pdf_attachment:
            parent_key = data.get('parentItem')
            if parent_key:
                try:
                    parent = zot.item(parent_key)
                    creators = parent['data'].get('creators', [])
                    if year == 'n.d.':
                        year = extract_year(parent['data'].get('date', ''))
                except:
                    pass
        
        if len(creators) == 0:
            author_part = "Unknown"
    
    if len(creators) > 0:
        if len(creators) == 1:
            c = creators[0]
            last = c.get('lastName', '')
            first = c.get('firstName', '')
            first_initial = first[0] + '.' if first else ''
            author_part = f"{last}, {first_initial}".strip(', ')
        elif len(creators) == 2:
            author_part = f"{creators[0].get('lastName', '')} & {creators[1].get('lastName', '')}"
        else:
            author_part = f"{creators[0].get('lastName', '')} et al."
    
    # Sanitize filename
    safe_author = re.sub(r'[/\\:*?"<>|]', '-', author_part)
    safe_year = re.sub(r'[/\\:*?"<>|]', '-', year)
    
    filename, final_year, is_replacing = get_unique_filename(safe_author, safe_year, OBSIDIAN_FOLDER, DUPLICATE_MODE)
    filepath = os.path.join(OBSIDIAN_FOLDER, filename)
    
    if DUPLICATE_MODE == "replace" and is_replacing:
        print(f"🔄 Replacing existing file: {filename}")
        replace_count += 1
    elif DUPLICATE_MODE == "suffix" and final_year != safe_year:
        print(f"⚠️ Duplicate found! Changed year '{safe_year}' → '{final_year}'")
    
    # Find PDF
    pdf_url = None
    
    if is_pdf_attachment:
        pdf_url = f"https://api.zotero.org/users/{ZOTERO_ID}/items/{item_key}/file"
    else:
        attachments = zot.children(item_key)
        pdf_attachments = [
            att for att in attachments
            if att['data'].get('contentType') == 'application/pdf'
        ]

        if pdf_attachments:
            # Filter out supplementary/appendix files by filename
            SUPPLEMENT_PATTERN = re.compile(
                r'supplement|appendix|supporting.?info|suppl|SI[\s_-]|ESM',
                re.IGNORECASE
            )
            main_pdfs = [
                att for att in pdf_attachments
                if not SUPPLEMENT_PATTERN.search(att['data'].get('title', ''))
            ]
            candidates = main_pdfs if main_pdfs else pdf_attachments

            # Among candidates, prefer the largest file (most likely the full paper)
            def _pdf_size(att):
                return att['data'].get('filesize', 0) or 0

            selected = max(candidates, key=_pdf_size)
            pdf_key = selected['key']
            pdf_url = f"https://api.zotero.org/users/{ZOTERO_ID}/items/{pdf_key}/file"

            if len(pdf_attachments) > 1:
                print(f"📎 {len(pdf_attachments)} PDFs found → selected: {selected['data'].get('title', pdf_key)}")
    
    content_to_analyze = None
    content_type = None
    
    if pdf_url:
        print("📥 Downloading PDF...")
        
        headers = {'Zotero-API-Key': ZOTERO_KEY}
        response = requests.get(pdf_url, headers=headers)
        
        if response.status_code == 200:
            print("📖 Extracting text from PDF...")
            
            try:
                pdf_file = BytesIO(response.content)
                pdf_reader = PyPDF2.PdfReader(pdf_file)
                
                full_text = ""
                for page in pdf_reader.pages:
                    full_text += page.extract_text()
                
                max_chars = 100000
                if len(full_text) > max_chars:
                    full_text = full_text[:max_chars]
                
                content_to_analyze = full_text
                content_type = "full_text"
                print(f"✅ Extracted {len(full_text):,} characters")
                
            except Exception as e:
                print(f"⚠️ PDF extraction failed: {e}")
                content_to_analyze = abstract
                content_type = "abstract"
        else:
            print(f"⚠️ PDF download failed: HTTP {response.status_code}")
            content_to_analyze = abstract
            content_type = "abstract"
    else:
        print("📝 No PDF found, using abstract")
        content_to_analyze = abstract
        content_type = "abstract"
    
    if not content_to_analyze:
        print("❌ Cannot analyze (no PDF or abstract available)")
        fail_count += 1
        continue
    
    # AI Analysis
    try:
        print(f"🧠 Analyzing with AI... (source: {content_type})")
        
        # Build keyword list for prompt
        if CONTROLLED_KEYWORDS:
            keywords_list = "\n".join([f"- {kw}" for kw in CONTROLLED_KEYWORDS])
            keyword_instruction = f"""
2. Select 5-7 keywords from the CONTROLLED KEYWORD LIST below.
   - ONLY use keywords from this list
   - Choose the most relevant ones for this paper
   - Format each as [[keyword]]
   - If a perfect match doesn't exist, choose the closest related keyword
   
CONTROLLED KEYWORD LIST:
{keywords_list}
"""
        else:
            keyword_instruction = """
2. Generate 5-7 relevant keywords for this paper.
   - Use lowercase
   - Format each as [[keyword]]
   - Focus on methodology, policy topics, and outcomes
"""
        
        if content_type == "full_text":
            prompt = f"""
Analyze the following full-text academic paper and provide a structured summary in English.

[Paper Title]: {title}
[Full Text]:
{content_to_analyze}

[Requirements - ALL IN ENGLISH]:
1. One-sentence summary (core contribution only)

{keyword_instruction}

3. Research question(s)
4. Key findings (3-5 bullet points)
5. Methodology summary (data, analytical approach)
6. Significance and limitations of this study
"""
        else:
            prompt = f"""
Analyze the following paper abstract and provide a structured summary in English.

[Paper Title]: {title}
[Abstract]:
{content_to_analyze}

[Requirements - ALL IN ENGLISH]:
1. One-sentence summary (core contribution only)

{keyword_instruction}

3. Research question(s) (infer from abstract if not explicit)
4. Key findings (based on abstract)
5. Methodology (if mentioned in abstract)
6. Significance of this study
"""
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an expert research assistant specializing in education policy and quantitative social science. You must ONLY use keywords from the provided controlled vocabulary list. Do not create new keywords."},
                {"role": "user", "content": prompt}
            ]
        )
        
        ai_result = response.choices[0].message.content
        
        # Save to file
        source_tag = "full-text" if content_type == "full_text" else "abstract-only"
        
        markdown_content = f"""---
title: {title}
author: {author_part}
year: {final_year}
date: {datetime.now().strftime('%Y-%m-%d')}
tags: [paper, auto-generated, {source_tag}]
source: {content_type}
---

# {title}

**Author(s):** {author_part}  
**Year:** {final_year}  
**Analysis based on:** {content_type.replace('_', ' ').title()}

{ai_result}
"""
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(markdown_content)
        
        print(f"✅ Saved: {filename}")
        success_count += 1
        
        # Rate limiting
        time.sleep(1)
        
    except Exception as e:
        print(f"❌ Processing failed: {e}")
        fail_count += 1
        continue

# Final summary
print(f"\n{'='*60}")
print(f"🎉 Processing complete!")
print(f"✅ Success: {success_count}")
if DUPLICATE_MODE == "replace":
    print(f"🔄 Replaced: {replace_count}")
print(f"❌ Failed: {fail_count}")
print(f"⏭️  Skipped: {skip_count}")
print(f"📂 Output location: {OBSIDIAN_FOLDER}")
print(f"{'='*60}")