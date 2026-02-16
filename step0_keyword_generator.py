"""
Education Finance & Policy Journal - Keyword Extraction Tool
============================================================

This script extracts controlled keywords from Education Finance and Policy journal articles
by analyzing abstracts and method sections from the last 10 years.

Features:
- Year-by-year processing for memory efficiency
- Progress checkpointing (resume from interruptions)
- Hybrid approach: CrossRef API + Semantic Scholar API
- Comprehensive method section detection (20+ keywords)
- AI-powered keyword extraction using GPT-4o-mini

Author: Hojung Lee & Claude 
Last Updated: 2026
"""

from openai import OpenAI
import requests
import time
from collections import Counter
from datetime import datetime
import os
import re
import json
import PyPDF2
from io import BytesIO

# ==========================================
# [CONFIGURATION]
# ==========================================
OPENAI_KEY = ''  

# Year range to analyze
START_YEAR = 2015
END_YEAR = 2025

# Number of final keywords to extract
TOP_N_KEYWORDS = 100

# Output file paths
OUTPUT_FILE = ""
PROGRESS_FILE = ""

# Education Finance and Policy ISSN
EFP_ISSN = "1557-3060"

# ==========================================

client = OpenAI(api_key=OPENAI_KEY)

def load_progress():
    """Load saved progress from previous runs"""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {'completed_years': [], 'all_keywords': []}
    return {'completed_years': [], 'all_keywords': []}

def save_progress(progress):
    """Save current progress to JSON file"""
    os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)

def get_papers_for_year(year):
    """Fetch papers for a specific year from CrossRef API"""
    
    print(f"\n{'='*60}")
    print(f"📅 Fetching papers from {year}...")
    print(f"{'='*60}")
    
    base_url = "https://api.crossref.org/works"
    
    params = {
        'filter': f'issn:{EFP_ISSN},from-pub-date:{year},until-pub-date:{year}',
        'rows': 1000,
        'select': 'title,abstract,DOI,published,author,container-title',
        'mailto': 'researcher@example.com'
    }
    
    try:
        response = requests.get(base_url, params=params, timeout=30)
        
        if response.status_code != 200:
            print(f"   ❌ CrossRef API error: HTTP {response.status_code}")
            return []
        
        data = response.json()
        items = data.get('message', {}).get('items', [])
        
        papers = []
        
        for item in items:
            title_list = item.get('title', [])
            if not title_list:
                continue
            title = title_list[0] if isinstance(title_list, list) else title_list
            
            abstract = item.get('abstract', '')
            if abstract:
                # Remove XML tags from abstract
                abstract = re.sub(r'<[^>]+>', '', abstract).strip()
            
            # Only include papers with substantial abstracts
            if abstract and len(abstract) > 100:
                papers.append({
                    'title': title,
                    'abstract': abstract,
                    'doi': item.get('DOI', ''),
                    'year': year
                })
        
        print(f"   ✅ Collected {len(papers)} papers")
        return papers
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return []

def search_semantic_scholar_by_doi(doi):
    """Search Semantic Scholar API for paper metadata by DOI"""
    
    if not doi:
        return None
    
    url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"
    params = {'fields': 'paperId,title,abstract,year,authors,openAccessPdf'}
    
    try:
        response = requests.get(url, params=params, timeout=15)
        if response.status_code == 200:
            return response.json()
        return None
    except:
        return None

def download_pdf_and_extract_method(pdf_url):
    """Download PDF and extract method section using comprehensive pattern matching"""
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        
        response = requests.get(pdf_url, headers=headers, timeout=30)
        if response.status_code != 200:
            return None
        
        # Parse PDF
        pdf_file = BytesIO(response.content)
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        
        full_text = ""
        for page in pdf_reader.pages:
            full_text += page.extract_text() + "\n"
        
        # Comprehensive list of method-related keywords
        method_keywords = [
            'methods?', 'methodology', 'empirical strategy', 'empirical strategies',
            'empirical approach', 'empirical approaches', 'analytical approach',
            'analytic approach', 'analytical approaches', 'analytic approaches',
            'research design', 'empirical analysis', 'empirical framework',
            'empirical methodology', 'identification strategy', 'identification strategies',
            'data and methods?', 'estimation strategy', 'estimation strategies',
            'econometric approach', 'statistical approach', 'causal identification'
        ]
        
        keyword_pattern = '|'.join(method_keywords)
        
        # Pattern 1: Explicit section headers with Roman/Arabic numerals
        section_header_patterns = [
            rf'(?i)\n\s*(?:II+|III+|IV+|V+|2|3|4|5)\.?\s*({keyword_pattern})\s*\n(.*?)(?=\n\s*(?:II+|III+|IV+|V+|VI+|\d+)\.?\s+[A-Z]|\nReferences|\nConclusion|\nAppendix|$)',
            rf'(?i)\n\s*({keyword_pattern})\s*\n(.*?)(?=\n\s*[A-Z][a-z]+\s*\n|\nReferences|\nConclusion|\nResults|\nDiscussion|\nAppendix|$)',
        ]
        
        # Pattern 2: Combined Data + Method sections (common in education research)
        data_with_method_patterns = [
            rf'(?i)\n\s*(?:II+|III+|IV+|2|3|4)\.?\s*(data.*?(?:{keyword_pattern}))\s*\n(.*?)(?=\n\s*(?:II+|III+|IV+|V+|VI+|\d+)\.?\s+[A-Z]|\nReferences|\nConclusion|$)',
            rf'(?i)\n\s*(data.*?(?:{keyword_pattern}))\s*\n(.*?)(?=\n\s*[A-Z][a-z]+\s*\n|\nReferences|\nConclusion|$)',
        ]
        
        all_patterns = section_header_patterns + data_with_method_patterns
        
        # Find best match (longest section)
        best_match = None
        best_length = 0
        
        for pattern in all_patterns:
            matches = list(re.finditer(pattern, full_text, re.DOTALL))
            for match in matches:
                method_text = match.group(0)
                
                # Skip sections that are too short
                if len(method_text) < 200:
                    continue
                
                # Truncate sections that are too long
                if len(method_text) > 25000:
                    method_text = method_text[:25000]
                
                # Keep the longest (most comprehensive) match
                if len(method_text) > best_length:
                    best_match = method_text
                    best_length = len(method_text)
        
        if best_match:
            return best_match
        
        # Pattern 3: Content-based detection (fallback)
        # Find paragraphs with high density of method keywords
        paragraphs = full_text.split('\n\n')
        method_rich_section = ""
        max_method_mentions = 0
        current_section = []
        
        for para in paragraphs:
            method_count = sum(1 for kw in method_keywords if re.search(rf'\b{kw}\b', para, re.IGNORECASE))
            if method_count > 0:
                current_section.append(para)
            elif current_section:
                section_text = '\n\n'.join(current_section)
                section_method_count = sum(1 for kw in method_keywords if re.search(rf'\b{kw}\b', section_text, re.IGNORECASE))
                if section_method_count > max_method_mentions and len(section_text) > 500:
                    max_method_mentions = section_method_count
                    method_rich_section = section_text
                current_section = []
        
        if method_rich_section and len(method_rich_section) > 500:
            if len(method_rich_section) > 25000:
                method_rich_section = method_rich_section[:25000]
            return method_rich_section
        
        return None
        
    except Exception as e:
        return None

def extract_keywords_from_text(title, text, text_type):
    """Extract keywords from text using GPT-4o-mini"""
    
    if text_type == "abstract":
        prompt = f"""
You are analyzing an academic paper in education finance and policy.

[Title]: {title}
[Abstract]: {text}

Extract 8-12 relevant keywords or key phrases covering ALL aspects:
1. Methodological approaches (e.g., "regression discontinuity", "difference-in-differences", "fixed effects")
2. Policy topics (e.g., "school funding", "Title I", "charter schools")
3. Outcome measures (e.g., "student achievement", "graduation rates", "test scores")
4. Contextual factors (e.g., "socioeconomic status", "educational inequality")
5. Data types (e.g., "administrative data", "panel data", "survey data")

REQUIREMENTS:
- Use lowercase for all keywords
- Use standard academic terminology
- Prefer multi-word phrases when more precise
- Separate keywords with semicolons
- Only keywords, no explanations

Keywords:"""
    
    else:  # method section
        prompt = f"""
You are analyzing the METHODS section of an education policy research paper.

[Title]: {title}
[Methods Section]: {text}

Extract 6-10 keywords focusing on METHODOLOGY:
1. Statistical methods (e.g., "regression discontinuity design", "difference-in-differences", "instrumental variables", "propensity score matching")
2. Research design (e.g., "quasi-experimental design", "randomized controlled trial", "event study")
3. Data sources (e.g., "administrative data", "longitudinal data", "census data")
4. Analytical techniques (e.g., "fixed effects", "local polynomial regression", "synthetic control")

REQUIREMENTS:
- Use lowercase for all keywords
- Use precise methodological terminology
- Separate keywords with semicolons
- Only keywords, no explanations

Keywords:"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert in education policy research with deep knowledge of quantitative methods and education finance literature."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=200
        )
        
        keywords_text = response.choices[0].message.content.strip()
        keywords = [kw.strip().lower() for kw in keywords_text.split(';') if kw.strip()]
        
        return keywords
        
    except Exception as e:
        print(f"   ❌ AI error: {e}")
        return []

def process_year(year, progress):
    """Process all papers from a specific year"""
    
    # Skip if year already processed
    if year in progress['completed_years']:
        print(f"\n⏭️  Year {year} already processed. Skipping.")
        return
    
    # 1. Collect papers
    papers = get_papers_for_year(year)
    
    if not papers:
        print(f"   ⚠️ No papers found for {year}")
        return
    
    # 2. Search Semantic Scholar for full-text access
    print(f"\n📚 Searching Semantic Scholar for open access PDFs...")
    
    pdf_found = 0
    method_extracted = 0
    
    for idx, paper in enumerate(papers, 1):
        print(f"   [{idx}/{len(papers)}] {paper['title'][:40]}...")
        
        s2_data = search_semantic_scholar_by_doi(paper['doi'])
        
        if s2_data:
            open_access = s2_data.get('openAccessPdf')
            if open_access and open_access.get('url'):
                pdf_url = open_access['url']
                print(f"      📥 PDF found")
                pdf_found += 1
                
                method_text = download_pdf_and_extract_method(pdf_url)
                if method_text:
                    paper['method_text'] = method_text
                    method_extracted += 1
                    print(f"      ✅ Method extracted ({len(method_text)} chars)")
                else:
                    print(f"      ⚠️ Method extraction failed")
                
                time.sleep(2)  # Rate limiting for PDF downloads
        
        time.sleep(1)  # Rate limiting for API calls
    
    print(f"\n   📊 PDFs: {pdf_found}/{len(papers)}, Methods: {method_extracted}/{len(papers)}")
    
    # 3. Extract keywords using AI
    print(f"\n🧠 Extracting keywords...")
    
    year_keywords = []
    
    for idx, paper in enumerate(papers, 1):
        print(f"   [{idx}/{len(papers)}] {paper['title'][:40]}... (abstract)")
        
        # Analyze abstract
        keywords = extract_keywords_from_text(paper['title'], paper['abstract'], 'abstract')
        year_keywords.extend(keywords)
        print(f"      ✅ {len(keywords)} keywords")
        
        # Analyze method section (if available)
        if paper.get('method_text'):
            print(f"   [{idx}/{len(papers)}] {paper['title'][:40]}... (method)")
            method_keywords = extract_keywords_from_text(paper['title'], paper['method_text'], 'method')
            year_keywords.extend(method_keywords)
            print(f"      ✅ {len(method_keywords)} keywords")
        
        time.sleep(0.5)  # Rate limiting
    
    # 4. Save progress
    progress['all_keywords'].extend(year_keywords)
    progress['completed_years'].append(year)
    save_progress(progress)
    
    print(f"\n✅ Year {year} completed: {len(year_keywords)} keywords extracted")
    print(f"💾 Progress saved\n")

def consolidate_similar_keywords(keyword_counts):
    """Consolidate similar keywords (e.g., merge substrings)"""
    
    print("\n🔄 Consolidating similar keywords...")
    
    consolidated = {}
    processed = set()
    keywords_sorted = sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True)
    
    for keyword, count in keywords_sorted:
        if keyword in processed:
            continue
        
        # Find similar keywords (substring matching)
        similar_group = [keyword]
        for other_kw, other_count in keywords_sorted:
            if other_kw in processed or other_kw == keyword:
                continue
            if keyword in other_kw or other_kw in keyword:
                similar_group.append(other_kw)
                processed.add(other_kw)
        
        # Use longest (most specific) keyword as representative
        representative = max(similar_group, key=len)
        total_count = sum(keyword_counts[kw] for kw in similar_group)
        consolidated[representative] = total_count
        processed.add(keyword)
    
    return consolidated

def main():
    
    print("="*60)
    print("📚 Education Finance & Policy - Keyword Extractor")
    print("   (Year-by-year processing with progress checkpoints)")
    print("="*60)
    print(f"📅 Analysis period: {START_YEAR}-{END_YEAR}")
    print(f"🎯 Target keywords: {TOP_N_KEYWORDS}\n")
    
    # Load saved progress
    progress = load_progress()
    
    if progress['completed_years']:
        print(f"📂 Previous progress found:")
        print(f"   - Completed years: {sorted(progress['completed_years'])}")
        print(f"   - Accumulated keywords: {len(progress['all_keywords'])}\n")
        
        response = input("Continue from checkpoint? (y/n): ")
        if response.lower() != 'y':
            print("Starting fresh...")
            progress = {'completed_years': [], 'all_keywords': []}
    
    # Process each year
    for year in range(START_YEAR, END_YEAR + 1):
        process_year(year, progress)
    
    # Generate final results
    print(f"\n{'='*60}")
    print("📊 Final keyword aggregation")
    print(f"{'='*60}\n")
    
    all_keywords = progress['all_keywords']
    print(f"Total extracted keywords: {len(all_keywords)}")
    
    keyword_counts = Counter(all_keywords)
    print(f"Unique keywords: {len(keyword_counts)}")
    
    consolidated_counts = consolidate_similar_keywords(keyword_counts)
    print(f"After consolidation: {len(consolidated_counts)} unique keywords")
    
    top_keywords = sorted(consolidated_counts.items(), key=lambda x: x[1], reverse=True)[:TOP_N_KEYWORDS]
    
    # Save final results
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(f"# Education Finance & Policy - Top {TOP_N_KEYWORDS} Keywords\n")
        f.write(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"# Based on papers from {START_YEAR}-{END_YEAR}\n")
        f.write(f"# Completed years: {sorted(progress['completed_years'])}\n")
        f.write(f"# Source: CrossRef API + Semantic Scholar API\n\n")
        
        f.write("# 📋 Python List Format (for direct copy-paste)\n")
        f.write("CONTROLLED_KEYWORDS = [\n")
        for keyword, count in top_keywords:
            f.write(f'    "{keyword}",  # appeared {count} times\n')
        f.write("]\n\n")
        
        f.write("# 📊 Ranked by Frequency\n")
        for idx, (keyword, count) in enumerate(top_keywords, 1):
            f.write(f"{idx}. {keyword} ({count} occurrences)\n")
    
    print(f"\n✅ Results saved to: {OUTPUT_FILE}")
    print(f"\n{'='*60}")
    print("📈 Top 20 Keywords Preview:")
    print(f"{'='*60}")
    
    for idx, (keyword, count) in enumerate(top_keywords[:20], 1):
        print(f"{idx:2d}. {keyword:40s} ({count:3d} times)")
    
    print(f"\n💡 Progress file: {PROGRESS_FILE}")
    print("   (Delete this file to start fresh on next run)")

if __name__ == "__main__":
    main()