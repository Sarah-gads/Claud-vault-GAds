import pdfplumber
import csv
import re
from collections import defaultdict

PDF_PATH = "MSPL _ Negative keywords.pdf"
OUTPUT_CSV = "compiled_negative_keywords_homer_glen.csv"

# Actual column mapping discovered from PDF structure:
# Col 0  -> Local Institutions
# Col 2  -> Local IT Services Providers
# Col 4  -> Competitors (URLs - reference only)
# Col 5  -> Keywords (phrase match, in quotes)
# Col 7  -> Keywords (broad match)
# Col 8  -> Keywords (broad match)
# Col 9  -> Keywords (phrase match, in quotes)
# Col 10 -> Excluded Negative Keywords (exact match, in brackets)

COL_MAP = {
    0: "Local Institutions",
    2: "Local IT Services Providers",
    4: "Competitors",
    5: "Keywords",
    7: "Keywords",
    8: "Keywords",
    9: "Keywords",
    10: "Excluded Negative Keywords",
}

SKIP_PATTERNS = [
    r"location:",
    r"local institutions negative",
    r"local it services",
    r"competitors",
    r"^keywords$",
    r"excluded negative keywords",
    r"^\s*$",
]

def should_skip(text):
    t = text.lower().strip()
    if not t or len(t) <= 1:
        return True
    for pat in SKIP_PATTERNS:
        if re.search(pat, t):
            return True
    return False

def normalize(text):
    # Normalize quotes and brackets, clean whitespace
    text = text.strip()
    # Fix encoding issues with smart quotes
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("‘", "'").replace("’", "'")
    # Replace replacement character
    text = text.replace("�", "")
    # Collapse internal whitespace
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()

def main():
    buckets = defaultdict(set)

    with pdfplumber.open(PDF_PATH) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            tables = page.extract_tables()
            if not tables:
                continue
            for table in tables:
                for row in table:
                    if not row:
                        continue
                    for col_idx, cell in COL_MAP.items():
                        if col_idx >= len(row):
                            continue
                        raw = row[col_idx]
                        if not raw:
                            continue
                        # A cell may contain multiple newline-separated entries
                        for item in raw.split("\n"):
                            item = normalize(item)
                            if not item or should_skip(item):
                                continue
                            # Remove bracket wrappers from Local IT Providers col
                            # (some entries appear as [IT Support Guys])
                            if cell == "Local IT Services Providers":
                                item = item.strip("[]")
                            buckets[cell].add(item)

    # Order for output
    CATEGORIES = [
        "Local Institutions",
        "Local IT Services Providers",
        "Competitors",
        "Keywords",
        "Excluded Negative Keywords",
    ]

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        for cat in CATEGORIES:
            keywords = sorted(buckets[cat], key=lambda x: x.lstrip('"[').lower())
            writer.writerow([f"=== {cat.upper()} — {len(keywords)} unique keywords ==="])
            writer.writerow(["Keyword"])
            for kw in keywords:
                writer.writerow([kw])
            writer.writerow([])  # blank line separator

    # Console summary
    print(f"\n{'='*65}")
    print(f"COMPILED NEGATIVE KEYWORDS — HOMER GLEN, IL")
    print(f"{'='*65}")
    total = 0
    for cat in CATEGORIES:
        count = len(buckets[cat])
        total += count
        print(f"  {cat:<40} {count:>5} unique")
    print(f"  {'-'*46}")
    print(f"  {'TOTAL':<40} {total:>5}")
    print(f"\n  Saved to: {OUTPUT_CSV}\n")

if __name__ == "__main__":
    main()
