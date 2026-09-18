from flask import Flask, abort, render_template, jsonify, request
from dotenv import dotenv_values, load_dotenv
from datetime import date
import os
import re
import math
import random
import time
import tempfile
import base64
import difflib
import requests
from functools import lru_cache
from groq import Groq
from pytrends.request import TrendReq
from keywords import all_keywords, keyword_links, CONTACT_URL

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOTENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(DOTENV_PATH)
dotenv_settings = dotenv_values(DOTENV_PATH)
BUNDLED_BLOGS_FOLDER = os.path.join(BASE_DIR, "generated_blogs")
RUNTIME_DIR = os.path.join(tempfile.gettempdir(), "blog-generator") if os.getenv("VERCEL") else BASE_DIR
BLOGS_FOLDER = os.path.join(RUNTIME_DIR, "generated_blogs")
LAST_GEN_FILE = os.path.join(RUNTIME_DIR, "last_generated.txt")
COOLDOWN_SECONDS = 15
MIN_WORD_COUNT = 2000
CURRENT_DATE = date.today().strftime("%B %-d, %Y") if os.name != "nt" else date.today().strftime("%B %#d, %Y")

os.makedirs(BLOGS_FOLDER, exist_ok=True)

groq_key = os.getenv("GROQ_API_KEY") or dotenv_settings.get("GROQ_API_KEY")
pexels_key = os.getenv("PEXELS_API_KEY") or dotenv_settings.get("PEXELS_API_KEY")
client = Groq(api_key=groq_key)


def get_pexels_image(query):
    headers = {"Authorization": pexels_key}
    params = {"query": query, "per_page": 1, "orientation": "landscape"}
    response = requests.get("https://api.pexels.com/v1/search", headers=headers, params=params)
    data = response.json()
    if data.get("photos"):
        return data["photos"][0]["src"]["large"]
    return "https://via.placeholder.com/800x400?text=Image+not+found"


def get_mermaid_diagram(diagram_code):
    encoded = base64.urlsafe_b64encode(diagram_code.encode("utf-8")).decode("utf-8")
    return f"https://mermaid.ink/img/{encoded}"


def extract_bracket_blocks(text, start_marker):
    """
    Finds every `[MARKER: ...]` block in text, correctly handling nested
    square brackets inside (needed for Mermaid diagram syntax like A[Label]).
    """
    blocks = []
    search_start = 0

    while True:
        start_idx = text.find(start_marker, search_start)
        if start_idx == -1:
            break

        depth = 0
        end_idx = None
        for i in range(start_idx, len(text)):
            if text[i] == '[':
                depth += 1
            elif text[i] == ']':
                depth -= 1
                if depth == 0:
                    end_idx = i
                    break

        if end_idx is None:
            break

        full_match = text[start_idx:end_idx + 1]
        inner_content = text[start_idx + len(start_marker):end_idx].strip()
        blocks.append((full_match, inner_content))
        search_start = end_idx + 1

    return blocks


def replace_image_markers(blog_text):
    image_blocks = extract_bracket_blocks(blog_text, "[IMAGE:")
    diagram_blocks = extract_bracket_blocks(blog_text, "[DIAGRAM:")

    for full_match, description in image_blocks:
        image_url = get_pexels_image(description)
        markdown_image = f"![{description}]({image_url})"
        blog_text = blog_text.replace(full_match, markdown_image, 1)

    for full_match, diagram_code in diagram_blocks:
        image_url = get_mermaid_diagram(diagram_code)
        markdown_image = f"![Process diagram]({image_url})"
        blog_text = blog_text.replace(full_match, markdown_image, 1)

    return blog_text, len(image_blocks), len(diagram_blocks)


def correct_keyword_input(keyword):
    matches = difflib.get_close_matches(keyword, all_keywords, n=1, cutoff=0.7)
    if matches:
        return matches[0]
    return keyword


def get_extra_internal_link_pool(current_keyword, limit=4):
    candidates = [url for kw, url in keyword_links.items() if kw != current_keyword]
    unique_urls = list(dict.fromkeys(candidates))
    if len(unique_urls) <= limit:
        return unique_urls
    return random.sample(unique_urls, limit)


def count_markdown_links(text):
    return re.findall(r"\[[^\]]+\]\((https?://[^\)]+)\)", text)


AUTHORITY_EXTERNAL_LINKS = {
    "FBR": "https://www.fbr.gov.pk/",
    "SRB": "https://srb.gos.pk/",
    "PRA": "https://pra.punjab.gov.pk/",
    "KPRA": "https://kpra.kp.gov.pk/",
}


def get_external_link_for_keyword(keyword):
    for authority, url in AUTHORITY_EXTERNAL_LINKS.items():
        if authority in keyword:
            return url, f"{authority} official website"
    return "https://en.wikipedia.org/wiki/Point_of_sale", "Point of sale (Wikipedia)"


def ensure_minimum_links(body, keyword, internal_link, min_internal=4, min_external=3):
    links = count_markdown_links(body)
    internal_count = sum(1 for url in links if "sadahisab.com" in url)
    external_count = len(links) - internal_count

    additions = []

    if internal_count < min_internal:
        needed = min_internal - internal_count
        pool = get_extra_internal_link_pool(keyword, limit=needed + 1)
        for url in pool:
            if url not in links and needed > 0:
                label = url.rstrip("/").split("/")[-1].replace("-", " ").title() or "SadaHisab"
                additions.append(f"- [{label}]({url})")
                needed -= 1
        if internal_link not in links and needed > 0:
            additions.append(f"- [Related SadaHisab resource]({internal_link})")
            needed -= 1
        if CONTACT_URL not in links and needed > 0:
            additions.append(f"- [Book a free demo]({CONTACT_URL})")

    if external_count < min_external:
        needed = min_external - external_count
        keyword_url, keyword_label = get_external_link_for_keyword(keyword)
        external_pool = [(keyword_url, keyword_label)]
        external_pool.extend(
            (url, f"{authority} official website")
            for authority, url in AUTHORITY_EXTERNAL_LINKS.items()
            if url != keyword_url
        )
        external_pool.append(
            ("https://en.wikipedia.org/wiki/Point_of_sale", "Point of sale (Wikipedia)")
        )

        for ext_url, ext_label in external_pool:
            existing_urls = links + [
                re.search(r"\((https?://[^)]+)\)", addition).group(1)
                for addition in additions
                if re.search(r"\((https?://[^)]+)\)", addition)
            ]
            if ext_url not in existing_urls and needed > 0:
                additions.append(f"- [{ext_label}]({ext_url})")
                needed -= 1

    if not additions:
        return body

    section = "\n\n## Related Resources\n\n" + "\n".join(additions) + "\n"
    conclusion_match = re.search(r"\n##\s*Conclusion", body, re.IGNORECASE)
    if conclusion_match:
        idx = conclusion_match.start()
        body = body[:idx] + section + body[idx:]
    else:
        body = body.rstrip() + section

    return body


def fix_keyword_typos(text, keyword):
    keyword_word_count = len(keyword.split())
    target_clean = re.sub(r"[^\w\s]", "", keyword).lower()

    word_spans = [(m.group(), m.start(), m.end()) for m in re.finditer(r"\S+", text)]

    fixed_text = text
    offset = 0
    i = 0

    while i <= len(word_spans) - keyword_word_count:
        window = word_spans[i:i + keyword_word_count]
        window_text = " ".join(w[0] for w in window)
        window_clean = re.sub(r"[^\w\s]", "", window_text).lower()

        similarity = difflib.SequenceMatcher(None, window_clean, target_clean).ratio()

        if 0.75 <= similarity < 1.0:
            start = window[0][1] + offset
            end = window[-1][2] + offset
            fixed_text = fixed_text[:start] + keyword + fixed_text[end:]
            offset += len(keyword) - (end - start)
            i += keyword_word_count
        else:
            i += 1

    return fixed_text


def collapse_duplicate_words(text):
    """Safety net: fixes accidental word-stuffing like 'Lahore Lahore' or 'the the'."""
    return re.sub(r"\b(\w+)(\s+\1\b)+", r"\1", text, flags=re.IGNORECASE)


def clean_keyword_artifacts(text, keyword):
    escaped_keyword = re.escape(keyword)
    duplicated_location = re.compile(
        rf"(?:\*\*)?{escaped_keyword}(?:\s+in\s+Pakistan)+(?:\*\*)?",
        re.IGNORECASE,
    )
    text = duplicated_location.sub(keyword, text)

    bold_keyword = re.compile(
        rf"\*{{2}}\s*{escaped_keyword}\s*\*{{2}}",
        re.IGNORECASE,
    )
    text = bold_keyword.sub(keyword, text)
    text = re.sub(rf"\*{{2}}\s*{escaped_keyword}", keyword, text, flags=re.IGNORECASE)

    repair_patterns = [
        (rf"(Choosing the right\s+{escaped_keyword})\s+the most direct way", r"\1 is the most direct way"),
        (rf"(purpose-built\s+{escaped_keyword})\s+the manual bottlenecks", r"\1 removes the manual bottlenecks"),
        (rf"(comprehensive\s+{escaped_keyword})\s+scales", r"\1 solution that scales"),
        (rf"(hallmark of effective\s+{escaped_keyword})\s+eliminates", r"\1 that eliminates"),
        (rf"(ensures that.*?generated by the\s+{escaped_keyword})\s+Manager reviewing", r"\1. Manager reviewing"),
        (rf"(ensures that the\s+{escaped_keyword})\s+its promised", r"\1 delivers its promised"),
        (rf"(selecting the right\s+{escaped_keyword})\s+committing", r"\1 requires evaluating before committing"),
        (rf"(Choosing the right\s+{escaped_keyword})\s+no longer", r"\1 is no longer"),
    ]
    for pattern, replacement in repair_patterns:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    return text


def enforce_keyword_density(body, keyword, target_per_1000=8.0):
    current_density = keyword_density(body, keyword)
    if current_density >= target_per_1000:
        return body

    reference_sentences = [
        f"For a business managing more than one sales channel, {keyword} is most useful when it keeps product, order, and inventory records aligned.",
        f"When evaluating {keyword}, teams should look beyond the interface and confirm how it handles daily sales, stock changes, and reporting.",
        f"In practice, the value of {keyword} depends on whether staff can use it consistently during busy operating hours.",
        f"Before adopting {keyword}, document the current workflow so gaps in syncing, billing, and reconciliation are easy to identify.",
        f"A reliable {keyword} should reduce manual work without making returns, adjustments, or tax records harder to audit.",
        f"Businesses comparing {keyword} should test a realistic order-to-inventory workflow rather than relying only on a feature list.",
        f"The strongest case for {keyword} is a measurable improvement in how quickly teams move from a sale to an accurate stock update.",
        f"A practical review of {keyword} should include permissions, staff training, backups, and the support available after launch.",
        f"For growing retailers, {keyword} needs to remain dependable as product ranges, order volumes, and fulfilment locations increase.",
        f"The right {keyword} can make routine reconciliation easier by giving managers one consistent view of sales and stock activity.",
        f"Any decision about {keyword} should account for the work involved in importing products, matching SKUs, and validating the first transactions.",
        f"Teams get better results from {keyword} when they define ownership for catalogue changes, stock corrections, and exception handling.",
        f"A useful implementation plan for {keyword} starts with a small set of products and transactions that staff can verify end to end.",
        f"The day-to-day test for {keyword} is simple: a change made in one channel should reach the right records without avoidable manual copying.",
        f"When a business adopts {keyword}, clear rules for cancellations, refunds, and out-of-stock items prevent small exceptions from becoming data problems.",
        f"Managers assessing {keyword} should review not only features but also transaction history, export options, and the clarity of its reports.",
        f"A well-planned rollout of {keyword} gives staff time to practise common sales and correction workflows before the system handles full volume.",
        f"The practical benefit of {keyword} is strongest when it supports the existing team instead of forcing every process into an unfamiliar routine.",
        f"For finance and operations teams, {keyword} is easier to trust when adjustments leave a clear record of what changed and why.",
        f"The first review of {keyword} should focus on the routines staff perform every day, not only on features used once a month.",
        f"A sensible comparison of {keyword} includes the quality of its product search, barcode handling, order status updates, and exports.",
        f"Businesses get more value from {keyword} when the setup reflects their actual branches, sales channels, tax process, and fulfilment responsibilities.",
        f"The transition to {keyword} should include checks for duplicate products, inconsistent prices, and missing stock before live orders are enabled.",
        f"Good documentation makes {keyword} easier to maintain because staff know how to handle exceptions without creating a second unofficial process.",
        f"An effective {keyword} workflow connects customer service, inventory control, sales reporting, and invoice review instead of isolating each task.",
        f"The right controls around {keyword} help owners see which changes are routine, which need approval, and which require investigation.",
        f"A clear owner for each {keyword} workflow makes it easier to resolve mismatches before they affect customers or financial reports.",
        f"The onboarding effort for {keyword} is worthwhile when the team can explain what happens to a product, order, and payment at each step.",
        f"A dependable {keyword} setup should make everyday decisions faster while still leaving managers enough detail to investigate unusual activity.",
        f"Testing {keyword} with real product names, realistic quantities, and normal return cases reveals gaps that a simple demonstration may hide.",
        f"The best way to judge {keyword} is to compare the time and error rate of the old process with the same workflow after implementation.",
        f"Businesses should revisit their {keyword} process as they add channels or locations so small configuration gaps do not become recurring manual work.",
    ]

    paragraphs = body.split("\n\n")
    keyword_terms = {
        term.casefold() for term in re.findall(r"[A-Za-z]{3,}", keyword)
    }
    topic_terms = keyword_terms | {
        "pos", "sales", "retail", "store", "shop", "inventory", "stock",
        "order", "orders", "product", "products", "billing", "invoice",
        "ecommerce", "shopify", "woocommerce", "integration", "sync",
        "payment", "tax", "reporting", "customer", "branch", "channel",
    }

    def suitable_prose(paragraph):
        stripped = paragraph.strip()
        lowered = stripped.casefold()
        words = re.findall(r"\b\w+\b", stripped)
        if len(words) < 10 or len(words) > 500:
            return False
        if not re.search(r"[.!?][\"')\]]?$", stripped):
            return False
        if stripped.startswith(("#", "![", "|", "-", "*", ">")):
            return False
        if any(marker in stripped for marker in ("##", "![", "```", "|", "**")):
            return False
        if lowered.count(":") > 2:
            return False
        return bool(set(re.findall(r"[a-z]{3,}", lowered)) & topic_terms)

    prose_candidates = [
        (index, sum(lowered_word in topic_terms for lowered_word in re.findall(r"[a-z]{3,}", paragraph.casefold())))
        for index, paragraph in enumerate(paragraphs)
        if suitable_prose(paragraph)
    ]
    if not prose_candidates:
        return body

    # Let topic relevance choose the section; randomize ties so separate blogs
    # do not receive the same placement order.
    random.shuffle(prose_candidates)
    prose_candidates.sort(key=lambda item: item[1], reverse=True)
    sentence_order = random.sample(reference_sentences, len(reference_sentences))

    sentence_index = 0
    used_indices = []
    for paragraph_index, _ in prose_candidates:
        if sentence_index >= len(sentence_order):
            break
        if paragraph_index in used_indices:
            continue
        candidate = sentence_order[sentence_index]
        proposed = "\n\n".join(
            paragraphs[:paragraph_index]
            + [paragraphs[paragraph_index].rstrip() + " " + candidate]
            + paragraphs[paragraph_index + 1:]
        )
        proposed_density = keyword_density(proposed, keyword)
        if proposed_density <= 10.0:
            paragraphs[paragraph_index] = paragraphs[paragraph_index].rstrip() + " " + candidate
            used_indices.append(paragraph_index)
            sentence_index += 1
            if proposed_density >= target_per_1000:
                break

    return "\n\n".join(paragraphs)


def keyword_density(text, keyword):
    word_count = len(text.split())
    keyword_count = text.lower().count(keyword.lower())
    return (keyword_count / word_count) * 1000 if word_count else 0


def build_title_prompt_legacy(chosen_keyword):
    return f"""You are the SEO title generation engine for SadaHisab.

SadaHisab is a Pakistani business management, POS, ERP, inventory, billing and digital invoicing platform.

SadaHisab helps businesses with:
- POS billing
- Digital invoicing
- Inventory and stock management
- Purchases and vendors
- Sales and customers
- Udhaar and credit management
- Expenses
- Profit and loss
- Analytics and reporting
- Multi-branch management
- Multi-user access
- Attendance and payroll
- Barcode scanning and generation
- Low-stock alerts
- Batch and expiry tracking
- Quotations
- Loyalty programs
- CRM
- E-commerce integrations
- API and custom integrations
- FBR-related POS/invoicing integration where applicable

SadaHisab is designed for businesses including:
- Pharmacies
- Restaurants
- Grocery stores
- Bakeries
- Clothing stores
- Salons
- Gyms
- Electronics businesses
- Stationery and bookstores
- Auto spare-parts businesses
- Wholesalers
- Retailers
- SMEs

USER'S SEARCH KEYWORD:
{chosen_keyword}

==================================================
MOST IMPORTANT RULE: SEARCH INTENT COMES FIRST
==================================================

The user's keyword is the PRIMARY SUBJECT of every title.

Your job is to create titles that directly answer, explore, or expand on what the user is actually searching for.

DO NOT change the subject of the keyword simply to create a different headline angle.

The keyword and its search intent must remain central to ALL 6 titles.

For example, if the keyword is:

"POS software for grocery store"

All titles must remain clearly about POS software for grocery stores.

Good related topics:
- POS software for grocery stores
- grocery store POS features
- choosing POS software for a grocery store
- benefits of POS software for grocery stores
- grocery inventory and POS management
- implementing POS software in a grocery store

Bad unrelated topics:
- digital invoicing for small businesses
- loyalty programs for restaurants
- multi-branch management for franchises
- pharmacy inventory management
- CRM for restaurants

Those are different search intents and MUST NOT be used.

==================================================
PRESERVE KEYWORD CONTEXT
==================================================

The keyword may contain:
- an industry
- business type
- product
- service
- problem
- location
- audience
- use case
- geographic intent

Preserve all important context.

If the keyword contains a specific industry, every title must remain relevant to that industry.

If the keyword contains a specific city, every title must preserve that city unless doing so would make the title grammatically unnatural.

If the keyword contains a specific business type, do not replace it with a generic business category.

Examples:

Keyword:
"Pharmacy Management System in Lahore"

Correct:
- Best Pharmacy Management System in Lahore: What to Look For
- How to Choose a Pharmacy Management System in Lahore
- Essential Features of a Pharmacy Management System in Lahore
- Pharmacy Management System in Lahore: A Practical Guide
- Common Pharmacy Management Challenges in Lahore
- SadaHisab for Pharmacy Management in Lahore

Incorrect:
- Best POS Software for Pakistani Restaurants
- 7 Benefits of Digital Invoicing for Small Businesses
- Loyalty and CRM Tips for Karachi Restaurants

--------------------------------------------------

Keyword:
"POS Software for Grocery Store"

Correct:
- Best POS Software for Grocery Stores: Key Features to Look For
- How to Choose POS Software for a Grocery Store
- 7 Essential POS Features Every Grocery Store Needs
- POS Software for Grocery Stores: A Practical Guide
- How POS Software Helps Grocery Stores Manage Sales and Stock
- SadaHisab POS for Grocery Stores: Features and Benefits

Incorrect:
- 7 Proven Benefits of Digital Invoicing for Small Businesses
- Expert Tips for Loyalty and CRM
- Multi-Branch Management for Pakistani Franchises
- Pharmacy Inventory Mistakes
- POS Software for Lahore Retailers

--------------------------------------------------

Keyword:
"Inventory Management Software for Pharmacies"

Correct:
- Best Inventory Management Software for Pharmacies
- How to Choose Inventory Management Software for a Pharmacy
- 7 Essential Inventory Features Pharmacies Need
- Inventory Management Software for Pharmacies: A Practical Guide
- Common Pharmacy Inventory Mistakes and How to Avoid Them
- How SadaHisab Helps Pharmacies Manage Inventory

Incorrect:
- Ultimate Guide to SadaHisab POS for Pakistani Retailers
- Loyalty Programs for Restaurants
- Multi-Branch Management for Franchises

==================================================
SADAHiSAB BRAND RULE
==================================================

SadaHisab is the brand being promoted, but SadaHisab is NOT the primary search intent unless the keyword specifically asks about SadaHisab.

DO NOT force "SadaHisab" into every title.

Some titles may mention SadaHisab naturally, while others can focus on the user's actual search query.

The keyword and search intent always come before brand promotion.

For example:

Keyword:
"POS software for grocery store"

Good:
- Best POS Software for Grocery Stores: Key Features to Look For
- How to Choose POS Software for a Grocery Store
- 7 Essential POS Features Every Grocery Store Needs
- POS Software for Grocery Stores: A Practical Guide
- How POS Software Helps Grocery Stores Manage Sales and Stock
- SadaHisab POS for Grocery Stores: Features and Benefits

==================================================
TITLE VARIETY
==================================================

Generate exactly 6 titles.

The titles must be meaningfully different from each other, but they must ALL remain within the same search intent.

Possible angles include:
- Practical guide
- Benefits
- Features
- How-to
- Implementation
- Problems and solutions
- Mistakes to avoid
- Business growth
- Buying guide
- Comparison
- Industry-specific advice

Only use an angle if it genuinely applies to the keyword.

DO NOT force unrelated angles just to make the six titles different.

For example, if the keyword is about pharmacy inventory software, do not create a restaurant loyalty-program title simply because "loyalty" is a SadaHisab feature.

==================================================
LOCATION RULE
==================================================

If the keyword contains a city, province, or location, preserve it.

Examples:

"POS Software Karachi"
→ Keep Karachi.

"Pharmacy Management System in Lahore"
→ Keep Lahore.

"POS Software for Grocery Store"
→ Do NOT randomly add Karachi, Lahore, Islamabad, Multan, or another city.

Do not replace a specific city with "Pakistan" unless the keyword itself has Pakistan-wide intent.

Do not invent a location.

==================================================
NATURAL TITLE RULE
==================================================

Titles must sound like they were written by a professional human SEO writer.

Avoid:
- keyword stuffing
- keyword repetition
- awkward exact-match phrases
- unnecessary punctuation
- long titles
- generic AI wording
- exaggerated claims
- unnatural promotional language
- repeating the same sentence structure

Bad:
"Best Pharmacy Management System in Lahore for Pharmacies in Lahore"

Good:
"Best Pharmacy Management Systems for Pharmacies in Lahore"

Bad:
"POS Software for Grocery Store: The Best POS Software for Grocery Stores"

Good:
"How to Choose POS Software for a Grocery Store"

==================================================
TITLE LENGTH
==================================================

Prefer approximately 8–14 words.

Keep titles concise and readable.

Do not make titles unnecessarily long just to include keywords.

A shorter natural title is better than a longer keyword-stuffed title.

==================================================
SEO RULES
==================================================

1. Generate exactly 6 titles.
2. Every title must be directly relevant to the user's keyword.
3. Keep the user's search intent as the central topic.
4. Preserve industry, business type, product, service and location context.
5. Use the keyword naturally where possible.
6. Do not force exact-match wording when it makes the title awkward.
7. Do not change the subject to another SadaHisab feature.
8. Do not introduce unrelated industries.
9. Do not introduce unrelated cities.
10. Do not introduce unrelated services.
11. Do not automatically add "Pakistan".
12. Do not automatically add "2026".
13. Do not automatically add "Best".
14. Do not automatically add "Ultimate".
15. Do not automatically add numbers.
16. Use numbers only when genuinely useful.
17. Use strong words such as Best, Practical, Proven, Expert, Essential, Complete or Ultimate only when appropriate.
18. Never make unsupported claims.
19. Do not imply that SadaHisab is objectively the best unless the wording clearly presents it as a brand/product title rather than an unsupported factual claim.
20. Do not create six minor variations of the same title.
21. Do not create six completely unrelated topics.
22. Brand promotion must never override search intent.

==================================================
FINAL RELEVANCE CHECK
==================================================

Before returning each title, silently check:

1. Is this title directly related to the user's keyword?
2. Does it preserve the main search intent?
3. Does it preserve the industry or business type?
4. Does it preserve the location if one exists?
5. Could someone searching the exact keyword reasonably click this title expecting relevant information?
6. Does the title stay on the same subject instead of switching to another SadaHisab feature?

If the answer to ANY of these is NO, rewrite the title.

==================================================
FINAL OUTPUT
==================================================

Return ONLY the six titles.

Use exactly this format:

1. Title
2. Title
3. Title
4. Title
5. Title
6. Title

Do not include:
- explanations
- commentary
- bullet points
- quotation marks
- markdown bold
- "Option #"
- "Click to lock H1"
- meta titles
- meta descriptions
- article content
"""


def build_title_prompt(chosen_keyword):
    return f"""You are an experienced SEO editor and headline writer for SadaHisab, a Pakistani business software company.

The current date is {CURRENT_DATE}. Use 2026 when a year is relevant. Do not use 2024 or another outdated year unless the keyword explicitly refers to a historical year.

Create exactly 6 engaging, publish-ready blog title options for this search keyword:

{chosen_keyword}

Understand the keyword before writing. Make the titles feel useful, specific, and appealing to a real person who would search for this topic. Explore different natural angles such as a practical guide, key features, benefits, buying advice, common problems, implementation, comparison, or business outcomes. Choose angles that genuinely fit the keyword rather than forcing a formula. Prefer a concrete business outcome or decision over vague phrases such as "From Ecommerce to Retail" or "Automate Your Business" on their own.

Keep the keyword's main subject, audience, industry, and location clear. You may rephrase the wording slightly when that produces a more natural title, but do not turn the topic into a different product, industry, city, or search intent. Use SadaHisab in one or two titles only when it fits naturally; the keyword's topic comes first.

Grammar rule for exact-match keywords: do not blindly place words such as "Common", "Right", or "How to Choose the Right" directly before a keyword that already begins with "Best". Rewrite the title naturally, for example "Common Challenges When Choosing POS Software for Shopify and WooCommerce Stores" or "How to Choose POS Software for Shopify and WooCommerce Stores in Pakistan".

Aim for concise titles, generally 8-14 words, with varied sentence structures. Make them sound human and distinct from one another. Use numbers, power words, years, or a colon only when they improve the title. Avoid generic filler, awkward exact-match repetition, exaggerated claims, vague slogans, and near-duplicate titles. For POS and e-commerce topics, name the practical decision, workflow, integration, inventory problem, or evaluation criteria the article will address.

Before returning the list, silently check that every title is relevant to the keyword and that the six options offer genuinely different reasons to click.

Return only this format, with no explanations or quotation marks:
1. Title
2. Title
3. Title
4. Title
5. Title
6. Title"""


def get_fallback_titles(keyword):
    keyword = keyword.strip()
    return [
        f"{keyword}: A Practical Guide for Pakistani Businesses",
        f"How to Choose the Right {keyword}",
        f"{keyword}: Key Features, Benefits, and Use Cases",
        f"Common {keyword} Challenges and How to Solve Them",
        f"How {keyword} Can Improve Daily Business Operations",
        f"{keyword}: Questions to Ask Before You Start",
    ]


def extract_title_options(raw_text, keyword):
    candidates = extract_ai_title_candidates(raw_text)

    fallback_titles = get_fallback_titles(keyword)
    for title in fallback_titles:
        if len(candidates) >= 6:
            break
        if title.lower() not in {candidate.lower() for candidate in candidates}:
            candidates.append(title)

    return candidates[:6]


def extract_ai_title_candidates(raw_text):
    candidates = []
    for line in raw_text.splitlines():
        if not re.match(r"^\s*(?:\d+\s*[.)]|[-*])\s+", line):
            continue
        cleaned = re.sub(r"^\s*(?:\d+\s*[.)]|[-*])\s*", "", line).strip()
        cleaned = cleaned.strip('"\'`')
        if len(cleaned.split()) < 4 or not re.search(r"[A-Za-z]", cleaned):
            continue
        if cleaned.lower() in {title.lower() for title in candidates}:
            continue
        candidates.append(cleaned)
    return candidates


def ensure_h1_title(body, chosen_title=None):
    body = body.strip()
    if not body:
        return body

    first_line, separator, remaining = body.partition("\n")
    first_line = first_line.strip()
    title = chosen_title.strip() if chosen_title else ""
    heading_match = re.match(r"^#{1,6}\s+(.+)$", first_line)
    if heading_match:
        heading_text = heading_match.group(1).strip()
        title_index = heading_text.casefold().find(title.casefold()) if title else -1
        if title_index < 0:
            split_match = re.search(
                r"\s+(?=(?:face a daily dilemma|built sales channels|is no longer|means balancing|often face|online merchants|retailers who|businesses that))",
                heading_text,
                re.IGNORECASE,
            )
            if not split_match:
                return body
            title = heading_text[:split_match.start()].rstrip(" :-")
            introduction = heading_text[split_match.end():].strip()
        else:
            introduction = heading_text[title_index + len(title):].lstrip(" :-")
        sentence_match = re.match(r"(.+?[.!?])(?:\s+|$)(.*)", introduction)
        if sentence_match:
            introduction = "\n\n".join(part for part in sentence_match.groups() if part.strip())
        if remaining.strip():
            introduction = "\n\n".join(part for part in (introduction, remaining.strip()) if part)
        return f"# {title}\n\n{introduction}" if introduction else f"# {title}"

    title_match = re.search(re.escape(title), first_line, re.IGNORECASE) if title else None
    if title_match:
        introduction = first_line[title_match.end():].lstrip(" :-")
        opener_index = introduction.casefold().find("this is exactly why")
        if opener_index > 0:
            introduction = introduction[opener_index:]
        sentence_match = re.match(r"(.+?[.!?])(?:\s+|$)(.*)", introduction)
        if sentence_match:
            introduction = "\n\n".join(part for part in sentence_match.groups() if part.strip())
        if remaining.strip():
            introduction = "\n\n".join(part for part in (introduction, remaining.strip()) if part)
    else:
        title_match = re.match(r"^(.+?)(?:\s+This is exactly why\s+.+?\s+continues to gain traction among .+?\.)\s*$", first_line, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).strip(" :-")
            introduction = first_line[len(title):].lstrip(" :-")
            if remaining.strip():
                introduction = "\n\n".join(part for part in (introduction, remaining.strip()) if part)
        else:
            title = first_line
            introduction = remaining.strip()

    return f"# {title}\n\n{introduction}" if introduction else f"# {title}"


def build_prompt(chosen_keyword, chosen_title=None, blog_purpose="", audience_questions="", blog_tone="professional"):
    internal_link = keyword_links.get(chosen_keyword, "https://sadahisab.com/pricing-plan/")
    extra_links = get_extra_internal_link_pool(chosen_keyword)
    extra_links_text = "\n".join(f"- {url}" for url in extra_links) if extra_links else "(none available)"

    if chosen_title:
        title_instruction = f'Use this EXACT text as the H1 title (do not alter it): "{chosen_title}"'
    else:
        title_instruction = f'H1 title that names "{chosen_keyword}" plus a short descriptive subtitle after a colon (e.g. "X: Complete Guide to Y, Z & Compliance") - avoid generic "Best/Ultimate X" phrasing here'

    purpose_context = blog_purpose.strip() or "Create a practical, useful guide that satisfies the search intent behind the keyword."
    questions_context = audience_questions.strip() or "No extra reader questions were provided; infer the most useful questions from the keyword."
    tone_instructions = {
        "professional": "Use a professional, authoritative, and direct tone. Do not use fictional stories, personal anecdotes, dramatic scenes, or informal filler. Open with a concise statement of the real problem or decision the reader faces.",
        "conversational": "Use a conversational and approachable tone while staying accurate and useful. You may use relatable examples, but do not invent personal experiences, named people, or unsupported stories.",
        "informal": "Use a relaxed, friendly tone with simple language and relatable examples. Keep the advice credible and focused; do not add fictional personal stories or exaggerated claims.",
    }
    tone_context = tone_instructions.get(blog_tone, tone_instructions["professional"])

    return f"""You are an expert SEO content writer for SadaHisab, a Pakistani business management, POS, ERP, inventory, billing and digital invoicing platform.

CURRENT DATE:
{CURRENT_DATE}

YEAR ACCURACY RULE:
Use 2026 for current-year references. Do not describe current laws, tax updates, software trends, or business conditions as being from 2024 or 2025. Mention an older year only when clearly discussing historical background and label it as historical. Never invent a dated tax reform or notice.

Write ONE complete, publish-ready blog article about "{chosen_keyword}". The article must feel original and specific to this keyword, not like a reusable template.

BLOG PURPOSE:
{purpose_context}

WRITING TONE:
{tone_context}

READER QUESTIONS AND EDITORIAL DIRECTION:
{questions_context}

OPENING RULE:
Do not open with a broad industry statistic. Follow the selected writing tone. For a professional tone, start directly with the real business problem, decision, or relevant context in clear factual language; do not turn it into a story or fictional scenario. For conversational or informal tones, a brief relatable example is acceptable, but it must not be presented as a real event or personal experience.

TITLE QUALITY RULE:
The H1 must be a practical, specific article title that tells the reader what decision, workflow, or problem the article covers. Do not use vague marketing slogans such as "From Ecommerce to Retail" or "Automate Your Business" without naming the POS, Shopify, WooCommerce, inventory, integration, or evaluation topic.

TOPIC AND ORIGINALITY RULE:
Every section must directly serve "{chosen_keyword}" and the stated blog purpose. Use concrete examples, decisions, workflows, and tradeoffs that fit this topic. Do not reuse a generic sequence of headings or repeat the same explanation in different words.

ANTI-HALLUCINATION RULE:
Never invent specific statistics, prices, customer counts, named competitors, awards, or certifications. Where you reference a regulation, authority, or process, describe it in general, accurate terms (e.g. "SRB's official services include...") rather than fabricating exact figures. You may factually describe SadaHisab's real features: POS billing, digital invoicing, inventory management, purchases, vendors, sales, customers, Udhaar/credit management, expenses, profit and loss, analytics, multi-branch management, multi-user access, attendance, payroll, barcode scanning, low-stock alerts, batch/expiry tracking, quotations, loyalty programs, CRM, e-commerce integrations, and APIs.

EDITORIAL BRIEF:
Treat the keyword, purpose, audience questions, tone, and selected title as the article brief, not as phrases to repeat. Before drafting, decide the reader's business situation, the decision they need to make, the operational problems involved, and the evidence or checks that would help them act. Build sections around that reasoning. For a Shopify and WooCommerce POS topic, cover channel synchronization, product and SKU mapping, inventory updates, order and return workflows, taxes and invoicing in Pakistan, reporting, implementation risks, support, and a practical evaluation checklist when relevant. Explain tradeoffs and give concrete examples. Every paragraph must add a fact, step, example, comparison, or decision rule.

FOCUS-PHRASE PLACEMENT:
If the exact focus phrase needs to appear more often, choose sections that are substantively about the product, workflow, evaluation, implementation, or business outcome. Add it inside a sentence that explains the section's point. Never place it in a heading, table label, list label, image marker, bold fragment, or a sentence that interrupts a list. Keep the phrase out of unrelated paragraphs and do not attach it to a heading or another fragment.

FORMATTING AND LANGUAGE RULES:
Every Markdown heading must be on its own line and contain only the heading text. Never begin a heading with a broken fragment such as "What is {chosen_keyword}" followed by a repeated phrase. Use natural grammar: for example, "What Is PRA Software Integration?" and "How Does It Fit Into an Existing Invoicing Workflow?". Do not put Markdown bold markers inside headings. Do not make the exact keyword appear in every heading.

Never wrap the exact focus keyword in Markdown bold markers. Use the keyword as ordinary prose inside a complete grammatical sentence. Do not insert the keyword where a verb, article, or connector is missing; reread every sentence containing the focus keyword before returning the article.

The article MUST be at least {MIN_WORD_COUNT} words in the body content (not counting meta title/description). Every section should add genuine detail - do not pad with repetition to reach the count.

Format the first two lines exactly as:
META_TITLE: <60 characters max, includes "{chosen_keyword}", includes a power word like Best/Top/Ultimate>
META_DESCRIPTION: <160 characters max, includes "{chosen_keyword}">

Then a blank line, followed by a natural article structure. The first article line MUST be the H1 in Markdown format (`# Title`) on its own line, followed by a blank line and the introduction. Include the most useful topic-specific sections, practical implementation or evaluation guidance where relevant, exactly five useful FAQs, and a conclusion. Choose section names that fit the subject; do not force "What is..." sections or a fixed heading template. Use the selected H1 title when provided: {title_instruction}.

KEYWORD RULES:
- Use the exact phrase "{chosen_keyword}" naturally 8-10 times per 1,000 words, mainly in the title, introduction, relevant sections, and conclusion. Reach this range by planning relevant references in useful paragraphs, never by repeating a sentence, adding filler, or forcing the phrase into unrelated sections.
- Do not force the exact phrase into headings, every paragraph, FAQs, or unrelated sentences. Use clear grammatical variations and related terminology elsewhere.
- Never place the keyword as a detached fragment, repeat it back-to-back, or use bold markers around it in a heading.

LINKING RULES:
- Include the required internal link to {internal_link} with relevant anchor text, and the required link to {CONTACT_URL} with anchor text like "Book a free demo".
- In addition, naturally weave in 1-3 more internal links from this list of other real SadaHisab pages, wherever genuinely relevant to something you're discussing (do not force one in if nothing fits naturally):
{extra_links_text}
- Include as many external links as genuinely support a specific factual claim (at least 1, often 2-3 is better) - real, well-known official government/regulatory sites or Wikipedia. Never invent a URL that doesn't exist.

MEDIA RULES:
- Mark 5-7 regular photo spots with [IMAGE: description], each depicting something genuinely relevant to "{chosen_keyword}", placed every 2-3 paragraphs.
- Mark 1-2 conceptual process visuals as a single-line Mermaid flowchart: [DIAGRAM: flowchart LR; A[Step One] --> B[Step Two] --> C[Step Three]] - 3-6 steps, short labels, letters/numbers/spaces only inside the brackets.

Output only the finished article content described above - no commentary, no explanation, no repeated instructions."""

@app.route("/")
def home():
    files = sorted(set(os.listdir(BUNDLED_BLOGS_FOLDER) + os.listdir(BLOGS_FOLDER)))
    return render_template("index.html", files=files, keywords=all_keywords)


@app.route("/blog/<filename>")
def view_blog(filename):
    import markdown
    safe_filename = os.path.basename(filename)
    if safe_filename != filename:
        abort(404)

    runtime_filepath = os.path.join(BLOGS_FOLDER, safe_filename)
    bundled_filepath = os.path.join(BUNDLED_BLOGS_FOLDER, safe_filename)
    filepath = runtime_filepath if os.path.exists(runtime_filepath) else bundled_filepath
    if not os.path.isfile(filepath):
        abort(404)

    with open(filepath, "r", encoding="utf-8") as f:
        raw_text = f.read()
    html_content = markdown.markdown(raw_text, extensions=["tables"])
    return render_template("blog.html", content=html_content)


def get_fallback_trend_data():
    return {
        "source": "unavailable",
        "searched_keyword": "",
        "top_labels": [],
        "rising_labels": [],
        "labels": [],
        "top": [],
        "rising": []
    }


def normalize_trends_keyword(keyword):
    return re.sub(r"\s+", " ", keyword).strip()


@lru_cache(maxsize=32)
def fetch_trends_data(searched_keyword, timeframe):
    pytrends = TrendReq(
        hl="en-US",
        tz=360,
        retries=1,
        backoff_factor=0.5,
        timeout=(5, 15),
        requests_args={
            "headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                )
            }
        },
    )
    pytrends.build_payload([searched_keyword], timeframe=timeframe)
    related = pytrends.related_queries()

    query_data = related.get(searched_keyword)
    if query_data is None:
        query_data = next(
            (value for key, value in related.items() if key.casefold() == searched_keyword.casefold()),
            {},
        )

    top_df = query_data.get("top")
    rising_df = query_data.get("rising")
    top_slice = top_df.head(10) if top_df is not None else None
    rising_slice = rising_df.head(10) if rising_df is not None else None

    top_labels = top_slice["query"].astype(str).tolist() if top_slice is not None else []
    top_values = top_slice["value"].fillna(0).astype(int).tolist() if top_slice is not None else []
    rising_labels = rising_slice["query"].astype(str).tolist() if rising_slice is not None else []

    rising_values = []
    if rising_slice is not None and len(rising_slice) > 0:
        rising_values = rising_slice["value"].apply(
            lambda value: 100 if str(value).casefold() == "breakout" else float(value)
        ).tolist()
        max_rising = max(rising_values)
        if max_rising:
            rising_values = [round((value / max_rising) * 100) for value in rising_values]

    return top_labels, top_values, rising_labels, rising_values


@app.route("/api/trends/<path:keyword>")
def api_trends(keyword):
    searched_keyword = normalize_trends_keyword(keyword)
    if not searched_keyword:
        return jsonify({"error": "Please enter a search term."}), 400

    timeframe_options = {
        "7d": "now 7-d",
        "1m": "today 1-m",
        "12m": "today 12-m",
    }
    timeframe_key = request.args.get("timeframe", "1m")
    timeframe = timeframe_options.get(timeframe_key)
    if timeframe is None:
        return jsonify({"error": "Invalid timeframe. Use 7d, 1m, or 12m."}), 400

    try:
        top_labels, top_values, rising_labels, rising_values = fetch_trends_data(
            searched_keyword, timeframe
        )

        if not top_labels and not rising_labels:
            fallback = get_fallback_trend_data()
            fallback["searched_keyword"] = searched_keyword
            return jsonify(fallback)

        return jsonify({
            "source": "live",
            "searched_keyword": searched_keyword,
            "timeframe": timeframe_key,
            "top_labels": top_labels,
            "rising_labels": rising_labels,
            "labels": top_labels,
            "top": top_values,
            "rising": rising_values
        })
    except Exception as error:
        app.logger.warning("Google Trends request failed for %r: %s", searched_keyword, error)
        fallback = get_fallback_trend_data()
        fallback["searched_keyword"] = searched_keyword
        fallback["source"] = "rate-limited" if "429" in str(error) else "unavailable"
        return jsonify(fallback)
        return jsonify(get_fallback_trend_data())


@app.route("/api/titles/<path:keyword>")
def api_titles(keyword):
    keyword = keyword.strip()
    if not keyword:
        return jsonify({"error": "Please enter a keyword first."}), 400

    try:
        prompt = build_title_prompt(keyword)
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1200
        )
        message = response.choices[0].message
        raw_text = (message.content or getattr(message, "reasoning", "") or "").strip()

        ai_titles = extract_ai_title_candidates(raw_text)
        titles = extract_title_options(raw_text, keyword)

        return jsonify({
            "keyword": keyword,
            "titles": titles,
            "source": "ai" if ai_titles else "fallback",
            "notice": None if ai_titles else "The AI returned no usable title lines, so relevant local titles were supplied."
        })

    except Exception as e:
        app.logger.exception("AI title request failed")
        return jsonify({
            "keyword": keyword,
            "titles": get_fallback_titles(keyword),
            "source": "fallback",
            "notice": "AI title generation failed, so relevant local title ideas were supplied."
        })


@app.route("/api/generate/<path:keyword>")
def api_generate(keyword):
    keyword = correct_keyword_input(keyword)
    chosen_title = request.args.get("title")
    blog_purpose = request.args.get("purpose", "")
    audience_questions = request.args.get("questions", "")
    blog_tone = request.args.get("tone", "professional")

    if os.path.exists(LAST_GEN_FILE):
        with open(LAST_GEN_FILE, "r") as f:
            last_time = float(f.read())
    else:
        last_time = 0

    seconds_since = time.time() - last_time
    if seconds_since < COOLDOWN_SECONDS:
        wait_left = int(COOLDOWN_SECONDS - seconds_since)
        return jsonify({"error": f"Please wait {wait_left} more seconds before generating another blog."}), 429

    try:
        prompt = build_prompt(keyword, chosen_title, blog_purpose, audience_questions, blog_tone)
        raw_text = ""

        for attempt in range(3):
            response = client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4000
            )
            raw_text = response.choices[0].message.content.strip()
            body_preview = re.sub(r"META_TITLE:.*\n?", "", raw_text)
            body_preview = re.sub(r"META_DESCRIPTION:.*\n?", "", body_preview).strip()
            body_preview = clean_keyword_artifacts(body_preview, keyword)
            preview_word_count = len(body_preview.split())
            preview_density = keyword_density(body_preview, keyword)

            if preview_word_count >= MIN_WORD_COUNT and 8.0 <= preview_density <= 10.0:
                break

            feedback = []
            if preview_word_count < MIN_WORD_COUNT:
                feedback.append(
                    f"The previous attempt was only about {preview_word_count} words. Expand every section with useful examples, steps, tradeoffs, and decision criteria to reach at least {MIN_WORD_COUNT} words."
                )
            if preview_density < 8.0:
                feedback.append(
                    f"The previous draft used the exact focus phrase at {preview_density:.1f} per 1,000 words. Add relevant, topic-specific references to the phrase in sections where it is genuinely being discussed until the natural rate is 8-10 per 1,000 words. Do not add filler or repeat sentences."
                )
            elif preview_density > 10.0:
                feedback.append(
                    f"The previous draft used the exact focus phrase at {preview_density:.1f} per 1,000 words. Replace unnecessary repetitions with natural synonyms and topic-specific wording until the rate is 8-10 per 1,000 words. Do not remove useful detail."
                )
            prompt += "\n\nRevise the complete article based on this quality feedback:\n- " + "\n- ".join(feedback)

        meta_title_match = re.search(r"META_TITLE:\s*(.*)", raw_text)
        meta_desc_match = re.search(r"META_DESCRIPTION:\s*(.*)", raw_text)
        meta_title = meta_title_match.group(1).strip() if meta_title_match else (chosen_title or keyword)
        meta_description = meta_desc_match.group(1).strip() if meta_desc_match else ""

        body = re.sub(r"META_TITLE:.*\n?", "", raw_text)
        body = re.sub(r"META_DESCRIPTION:.*\n?", "", body).strip()

        body = ensure_h1_title(body, chosen_title)
        body = fix_keyword_typos(body, keyword)
        body = collapse_duplicate_words(body)
        body = clean_keyword_artifacts(body, keyword)
        internal_link = keyword_links.get(keyword, "https://sadahisab.com/pricing-plan/")
        body = ensure_minimum_links(body, keyword, internal_link)
        body, photo_count, diagram_count = replace_image_markers(body)
        body = ensure_h1_title(body, chosen_title)
        body = clean_keyword_artifacts(body, keyword)
        body = enforce_keyword_density(body, keyword)
        body = clean_keyword_artifacts(body, keyword)

        word_count = len(body.split())
        keyword_count = body.lower().count(keyword.lower())
        rate_per_1000 = round((keyword_count / word_count) * 1000, 1) if word_count else 0

        safe_filename = keyword.lower().replace(" ", "_")
        filepath = os.path.join(BLOGS_FOLDER, f"{safe_filename}.md")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(body)

        with open(LAST_GEN_FILE, "w") as f:
            f.write(str(time.time()))

        return jsonify({
            "keyword": keyword,
            "meta_title": meta_title,
            "meta_description": meta_description,
            "content": body,
            "word_count": word_count,
            "keyword_count": keyword_count,
            "rate_per_1000": rate_per_1000,
            "photo_count": photo_count,
            "diagram_count": diagram_count,
            "filename": f"{safe_filename}.md"
        })

    except Exception as e:
        error_text = str(e)
        if "rate_limit" in error_text.lower() or "429" in error_text:
            return jsonify({"error": "Daily/rate limit reached on the AI service. Wait a bit and try again, or check your Groq dashboard for reset time."}), 429
        return jsonify({"error": error_text}), 500


if __name__ == "__main__":
    app.run(debug=True)
