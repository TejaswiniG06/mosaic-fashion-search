"""Fashion domain knowledge base.

Single source of truth for:
  * canonical vocabularies (category, occasion, season, climate, material, colour, pattern, style)
  * multilingual surface forms (English, Tamil script, Tanglish, Hindi Devanagari, Hinglish)
  * destination -> climate mapping
  * material physical properties (breathability / warmth / comfort / rain / sustainability)
  * product enrichment: deterministic attribute extraction from product *text* (title, features,
    description, details). Enrichment never reads hidden ground-truth labels.

The LLM path (services/intent/llm.py) is normalised onto these same canonical values, so both
the LLM and the rule engine speak one vocabulary.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

# --------------------------------------------------------------------------- categories
# canonical -> (group, default gender or None, english aliases)
CATEGORIES: dict[str, dict[str, Any]] = {
    "t-shirt": {"group": "topwear", "gender": None, "aliases": ["t-shirt", "tshirt", "t shirt", "tee", "tees", "polo"]},
    "shirt": {"group": "topwear", "gender": None, "aliases": ["shirt", "shirts", "button-down", "button down"]},
    "top": {"group": "topwear", "gender": "women", "aliases": ["top", "tops", "blouse", "crop top", "camisole", "tank top"]},
    "kurta": {"group": "ethnic", "gender": None, "aliases": ["kurta", "kurtas", "pathani"]},
    "kurti": {"group": "ethnic", "gender": "women", "aliases": ["kurti", "kurtis", "tunic"]},
    "saree": {"group": "ethnic", "gender": "women", "aliases": ["saree", "sari", "sarees", "saris"]},
    "lehenga": {"group": "ethnic", "gender": "women", "aliases": ["lehenga", "lehnga", "lehenga choli", "ghagra"]},
    "salwar-suit": {"group": "ethnic", "gender": "women", "aliases": ["salwar suit", "salwar kameez", "churidar", "chudidhar", "anarkali", "salwar"]},
    "dress": {"group": "onepiece", "gender": "women", "aliases": ["dress", "dresses", "frock", "gown", "maxi dress", "sundress", "midi dress", "maxi"]},
    "jeans": {"group": "bottomwear", "gender": None, "aliases": ["jeans", "denims"]},
    "trousers": {"group": "bottomwear", "gender": None, "aliases": ["trousers", "trouser", "pants", "chinos", "formal pants", "slacks"]},
    "shorts": {"group": "bottomwear", "gender": None, "aliases": ["shorts", "bermuda", "bermudas"]},
    "skirt": {"group": "bottomwear", "gender": "women", "aliases": ["skirt", "skirts"]},
    "palazzo": {"group": "bottomwear", "gender": "women", "aliases": ["palazzo", "palazzos", "palazzo pants"]},
    "jacket": {"group": "outerwear", "gender": None, "aliases": ["jacket", "jackets", "windcheater", "puffer", "bomber"]},
    "blazer": {"group": "outerwear", "gender": None, "aliases": ["blazer", "blazers", "suit jacket"]},
    "sweater": {"group": "outerwear", "gender": None, "aliases": ["sweater", "sweaters", "pullover", "cardigan", "jumper", "sweatshirt"]},
    "hoodie": {"group": "outerwear", "gender": None, "aliases": ["hoodie", "hoodies"]},
    "coat": {"group": "outerwear", "gender": None, "aliases": ["coat", "overcoat", "trench coat", "coats"]},
    "sherwani": {"group": "ethnic", "gender": "men", "aliases": ["sherwani", "sherwanis"]},
    "veshti": {"group": "ethnic", "gender": "men", "aliases": ["veshti", "vesti", "dhoti", "mundu", "vetti"]},
    "swimwear": {"group": "onepiece", "gender": None, "aliases": ["swimwear", "swimsuit", "bikini", "swim trunks", "swim shorts", "swimming costume"]},
    "activewear": {"group": "bottomwear", "gender": None, "aliases": ["track pants", "trackpants", "joggers", "gym wear", "activewear", "sports bra", "leggings", "tights"]},
    "sneakers": {"group": "footwear", "gender": None, "aliases": ["sneakers", "running shoes", "sports shoes", "trainers", "shoes", "canvas shoes"]},
    "sandals": {"group": "footwear", "gender": None, "aliases": ["sandals", "flip flops", "flip-flops", "slides", "chappal", "chappals", "slippers"]},
    "heels": {"group": "footwear", "gender": "women", "aliases": ["heels", "stilettos", "pumps", "wedges"]},
    "formal-shoes": {"group": "footwear", "gender": None, "aliases": ["formal shoes", "oxfords", "loafers", "derby shoes", "brogues"]},
    "boots": {"group": "footwear", "gender": None, "aliases": ["boots", "ankle boots", "chelsea boots"]},
    "juttis": {"group": "footwear", "gender": None, "aliases": ["juttis", "jutti", "mojari", "mojaris", "kolhapuri"]},
    "scarf": {"group": "accessory", "gender": None, "aliases": ["scarf", "stole", "shawl", "dupatta", "muffler"]},
    "hat": {"group": "accessory", "gender": None, "aliases": ["hat", "cap", "sun hat", "beanie"]},
    "nightwear": {"group": "lounge", "gender": None, "aliases": ["nightwear", "pyjama", "pajama", "pyjamas", "night suit", "nightsuit", "nighty", "lounge set", "nightdress"]},
}

# multilingual surface forms -> canonical category
CATEGORY_ML: dict[str, str] = {
    # Tamil script
    "சட்டை": "shirt", "டி-ஷர்ட்": "t-shirt", "டீ ஷர்ட்": "t-shirt", "டிஷர்ட்": "t-shirt", "புடவை": "saree", "சேலை": "saree",
    "வேட்டி": "veshti", "குர்தா": "kurta", "குர்தி": "kurti", "ஜீன்ஸ்": "jeans", "ஷார்ட்ஸ்": "shorts", "பாவாடை": "skirt",
    "லெஹங்கா": "lehenga", "சுடிதார்": "salwar-suit", "ஜாக்கெட்": "jacket", "ஸ்வெட்டர்": "sweater", "செருப்பு": "sandals",
    "ஷூ": "sneakers", "ஷூஸ்": "sneakers", "கவுன்": "dress", "டிரஸ்": "dress", "பேன்ட்": "trousers", "டாப்": "top", "ஹூடி": "hoodie",
    "கோட்": "coat", "ஷெர்வானி": "sherwani", "நீச்சல் உடை": "swimwear", "தொப்பி": "hat", "துப்பட்டா": "scarf", "சால்வை": "scarf",
    "இரவு உடை": "nightwear", "பிளேசர்": "blazer", "ஹீல்ஸ்": "heels", "பூட்ஸ்": "boots", "பலாசோ": "palazzo",
    # Tanglish / romanised Tamil
    "sattai": "shirt", "pudavai": "saree", "selai": "saree", "seruppu": "sandals", "paavadai": "skirt", "pavadai": "skirt",
    "thoppi": "hat", "chudi": "salwar-suit",
    # Hindi Devanagari
    "कमीज़": "shirt", "कमीज": "shirt", "शर्ट": "shirt", "टी-शर्ट": "t-shirt", "टीशर्ट": "t-shirt", "साड़ी": "saree", "साडी": "saree",
    "कुर्ता": "kurta", "कुर्ते": "kurta", "कुर्ती": "kurti", "लहंगा": "lehenga", "सलवार सूट": "salwar-suit", "सलवार": "salwar-suit", "सूट": "salwar-suit",
    "ड्रेस": "dress", "फ्रॉक": "dress", "जींस": "jeans", "पैंट": "trousers", "पतलून": "trousers", "शॉर्ट्स": "shorts", "स्कर्ट": "skirt",
    "जैकेट": "jacket", "स्वेटर": "sweater", "हुडी": "hoodie", "कोट": "coat", "शेरवानी": "sherwani", "धोती": "veshti", "जूते": "sneakers",
    "चप्पल": "sandals", "सैंडल": "sandals", "हील्स": "heels", "दुपट्टा": "scarf", "शॉल": "scarf", "स्टोल": "scarf", "टोपी": "hat",
    "पजामा": "nightwear", "नाइटसूट": "nightwear", "स्विमसूट": "swimwear", "जूती": "juttis", "ब्लेज़र": "blazer", "टॉप": "top", "पलाज़ो": "palazzo",
    "बूट": "boots", "स्नीकर्स": "sneakers",
    # Hinglish
    "kameez": "shirt", "joote": "sneakers", "jute": "sneakers", "topi": "hat", "chunni": "scarf", "jooti": "juttis",
}

# --------------------------------------------------------------------------- occasions
OCCASIONS = ["casual", "office", "party", "wedding", "festive", "beach", "sports", "lounge", "travel", "traditional"]
OCCASION_SYN: dict[str, str] = {
    # English
    "beach": "beach", "beachwear": "beach", "seaside": "beach", "pool": "beach", "resort": "beach", "coastal": "beach",
    "office": "office", "work": "office", "workwear": "office", "meeting": "office", "interview": "office", "formal": "office",
    "corporate": "office", "business": "office", "presentation": "office",
    "party": "party", "club": "party", "clubbing": "party", "night out": "party", "date": "party", "cocktail": "party", "partywear": "party",
    "wedding": "wedding", "marriage": "wedding", "reception": "wedding", "sangeet": "wedding", "mehendi": "wedding", "engagement": "wedding",
    "bridal": "wedding", "groom": "wedding",
    "festival": "festive", "festive": "festive", "diwali": "festive", "deepavali": "festive", "pongal": "festive", "eid": "festive",
    "navratri": "festive", "onam": "festive", "durga puja": "festive", "holi": "festive", "christmas": "festive",
    "gym": "sports", "workout": "sports", "running": "sports", "yoga": "sports", "sports": "sports", "jogging": "sports", "training": "sports",
    "home": "lounge", "lounge": "lounge", "loungewear": "lounge", "sleep": "lounge", "sleeping": "lounge", "relaxing": "lounge", "wfh": "lounge",
    "travel": "travel", "trip": "travel", "vacation": "travel", "holiday": "travel", "flight": "travel", "trek": "travel", "trekking": "travel",
    "temple": "traditional", "pooja": "traditional", "puja": "traditional", "religious": "traditional", "traditional": "traditional",
    "college": "casual", "everyday": "casual", "daily": "casual", "casual": "casual", "outing": "casual", "weekend": "casual", "brunch": "casual",
    # Tamil
    "கடற்கரை": "beach", "பீச்": "beach", "அலுவலகம்": "office", "அலுவலக": "office", "ஆபீஸ்": "office", "கல்யாணம்": "wedding", "கல்யாண": "wedding",
    "திருமணம்": "wedding", "திருமண": "wedding", "பார்ட்டி": "party", "பண்டிகை": "festive", "தீபாவளி": "festive", "பொங்கல்": "festive",
    "உடற்பயிற்சி": "sports", "ஜிம்": "sports", "யோகா": "sports", "கோவில்": "traditional", "கோயில்": "traditional", "பூஜை": "traditional",
    "பயணம்": "travel", "சுற்றுலா": "travel", "வீட்டில்": "lounge", "தூங்க": "lounge", "தினசரி": "casual", "சாதாரண": "casual", "கல்லூரி": "casual",
    "நேர்காணல்": "office",
    # Tanglish
    "kalyanam": "wedding", "kalyaanam": "wedding", "kalyana": "wedding", "kovil": "traditional", "koil": "traditional", "deepavali ku": "festive",
    "veetla": "lounge", "veetuku": "lounge", "tour": "travel", "function": "festive", "functionku": "festive",
    # Hindi
    "शादी": "wedding", "विवाह": "wedding", "समुद्र तट": "beach", "बीच": "beach", "ऑफिस": "office", "दफ्तर": "office", "दफ़्तर": "office",
    "इंटरव्यू": "office", "पार्टी": "party", "त्योहार": "festive", "त्यौहार": "festive", "दिवाली": "festive", "होली": "festive", "जिम": "sports",
    "व्यायाम": "sports", "योग": "sports", "मंदिर": "traditional", "पूजा": "traditional", "यात्रा": "travel", "सफर": "travel", "सफ़र": "travel",
    "घर": "lounge", "रोज़": "casual", "रोजाना": "casual", "रोज़ाना": "casual", "कॉलेज": "casual", "कैज़ुअल": "casual",
    # Hinglish
    "shaadi": "wedding", "shadi": "wedding", "tyohar": "festive", "mandir": "traditional", "ghar": "lounge", "safar": "travel", "daftar": "office",
}
OCCASION_COMPAT: dict[tuple[str, str], float] = {
    ("festive", "wedding"): 0.6, ("party", "festive"): 0.4, ("party", "wedding"): 0.3, ("casual", "travel"): 0.5,
    ("beach", "travel"): 0.6, ("beach", "casual"): 0.4, ("lounge", "casual"): 0.4, ("traditional", "festive"): 0.6,
    ("traditional", "wedding"): 0.4, ("office", "casual"): 0.2, ("sports", "casual"): 0.3, ("lounge", "travel"): 0.3,
}


def occasion_compat(a: str, b: str) -> float:
    if a == b:
        return 1.0
    return OCCASION_COMPAT.get((a, b)) or OCCASION_COMPAT.get((b, a)) or 0.0


# --------------------------------------------------------------------------- season / climate / destination
SEASON_SYN: dict[str, str] = {
    "summer": "summer", "hot": "summer", "heat": "summer", "sunny": "summer", "scorching": "summer",
    "winter": "winter", "cold": "winter", "chilly": "winter", "snow": "winter", "freezing": "winter", "snowy": "winter",
    "monsoon": "monsoon", "rain": "monsoon", "rainy": "monsoon", "rains": "monsoon",
    "கோடை": "summer", "வெயில்": "summer", "வெப்பம்": "summer", "குளிர்": "winter", "குளிர்கால": "winter", "மழை": "monsoon", "மழைக்கால": "monsoon",
    "veyil": "summer", "veyila": "summer", "kulir": "winter", "kulru": "winter", "mazhai": "monsoon", "mazha": "monsoon",
    "गर्मी": "summer", "गर्मियों": "summer", "गर्मियां": "summer", "धूप": "summer", "सर्दी": "winter", "सर्दियों": "winter", "ठंड": "winter",
    "ठंडी": "winter", "बारिश": "monsoon", "मानसून": "monsoon", "बरसात": "monsoon",
    "garmi": "summer", "garmiyon": "summer", "sardi": "winter", "sardiyon": "winter", "thand": "winter", "thandi": "winter", "baarish": "monsoon", "barish": "monsoon",
}

# destination -> climate (None = depends on season)
DESTINATIONS: dict[str, str | None] = {
    "chennai": "hot_humid", "mumbai": "hot_humid", "goa": "hot_humid", "kerala": "hot_humid", "kochi": "hot_humid", "kolkata": "hot_humid",
    "pondicherry": "hot_humid", "puducherry": "hot_humid", "vizag": "hot_humid", "andaman": "hot_humid", "singapore": "hot_humid",
    "bali": "hot_humid", "thailand": "hot_humid", "maldives": "hot_humid", "madurai": "hot_dry", "hyderabad": "hot_dry",
    "jaipur": "hot_dry", "rajasthan": "hot_dry", "jaisalmer": "hot_dry", "dubai": "hot_dry", "bangalore": "mild", "bengaluru": "mild",
    "coimbatore": "mild", "pune": "mild", "delhi": None, "lucknow": None, "manali": "cold", "shimla": "cold", "ooty": "cold",
    "kodaikanal": "cold", "munnar": "mild", "kashmir": "cold", "ladakh": "cold", "darjeeling": "cold", "london": "cold", "paris": "cold",
    "switzerland": "cold", "europe": None, "hill station": "cold", "mountains": "cold", "himalayas": "cold", "desert": "hot_dry",
    "cherrapunji": "rainy", "meghalaya": "rainy",
}
DESTINATION_ML: dict[str, str] = {
    "சென்னை": "chennai", "மதுரை": "madurai", "ஊட்டி": "ooty", "கொடைக்கானல்": "kodaikanal", "கோவா": "goa", "மும்பை": "mumbai",
    "டெல்லி": "delhi", "பெங்களூர்": "bangalore", "கோவை": "coimbatore", "கேரளா": "kerala", "மூணாறு": "munnar", "பாண்டிச்சேரி": "pondicherry",
    "चेन्नई": "chennai", "मुंबई": "mumbai", "गोवा": "goa", "दिल्ली": "delhi", "मनाली": "manali", "शिमला": "shimla", "जयपुर": "jaipur",
    "कश्मीर": "kashmir", "बैंगलोर": "bangalore", "केरल": "kerala", "लद्दाख": "ladakh", "दुबई": "dubai", "राजस्थान": "rajasthan", "लंदन": "london",
    "ooty la": "ooty", "kodai": "kodaikanal", "madras": "chennai", "bombay": "mumbai", "pondy": "pondicherry",
}
SEASON_DEFAULT_CLIMATE = {"summer": "hot", "winter": "cold", "monsoon": "rainy"}
CLIMATE_DESC = {
    "hot_humid": "hot and humid weather", "hot_dry": "hot, dry weather", "hot": "hot weather", "cold": "cold weather",
    "rainy": "rainy weather", "mild": "mild weather",
}


def resolve_climate(destination: str | None, season: str | None) -> str | None:
    if destination:
        c = DESTINATIONS.get(destination)
        if c is None:  # season-dependent destination (e.g. Delhi)
            if season == "summer":
                return "hot_dry"
            if season == "winter":
                return "cold"
            if season == "monsoon":
                return "rainy"
            return None
        if season == "monsoon" and c in ("hot_humid", "mild"):
            return "rainy"
        if season == "winter" and c == "hot_dry" and destination in ("jaipur", "rajasthan", "delhi"):
            return "mild"
        return c
    if season:
        return SEASON_DEFAULT_CLIMATE.get(season)
    return None


# --------------------------------------------------------------------------- materials
# name -> (breathability, warmth, comfort, rain_ok, sustainable)
MATERIALS: dict[str, tuple[float, float, float, bool, bool]] = {
    "cotton": (0.9, 0.3, 0.85, False, False), "organic cotton": (0.9, 0.3, 0.9, False, True), "linen": (0.95, 0.2, 0.8, False, False),
    "khadi": (0.9, 0.3, 0.78, False, True), "bamboo": (0.92, 0.25, 0.9, False, True), "rayon": (0.75, 0.25, 0.8, False, False),
    "chiffon": (0.7, 0.15, 0.6, False, False), "georgette": (0.6, 0.2, 0.62, False, False), "silk": (0.5, 0.45, 0.6, False, False),
    "polyester": (0.35, 0.4, 0.5, True, False), "recycled polyester": (0.35, 0.4, 0.5, True, True), "nylon": (0.3, 0.3, 0.5, True, False),
    "denim": (0.4, 0.55, 0.55, False, False), "wool": (0.3, 0.95, 0.6, False, False), "fleece": (0.2, 0.9, 0.82, False, False),
    "leather": (0.2, 0.7, 0.4, False, False), "velvet": (0.2, 0.8, 0.5, False, False), "lycra blend": (0.5, 0.3, 0.88, True, False),
    "canvas": (0.55, 0.4, 0.6, False, False), "mesh": (0.95, 0.1, 0.85, False, False), "suede": (0.3, 0.6, 0.5, False, False),
    "eva rubber": (0.3, 0.2, 0.8, True, False), "modal": (0.85, 0.25, 0.92, False, False),
}
MATERIAL_SYN: dict[str, str] = {
    "cotton": "cotton", "pure cotton": "cotton", "100% cotton": "cotton", "organic cotton": "organic cotton", "linen": "linen",
    "khadi": "khadi", "bamboo": "bamboo", "rayon": "rayon", "viscose": "rayon", "chiffon": "chiffon", "georgette": "georgette",
    "silk": "silk", "art silk": "silk", "kanjivaram": "silk", "kanchipuram": "silk", "banarasi": "silk", "polyester": "polyester",
    "recycled polyester": "recycled polyester", "nylon": "nylon", "denim": "denim", "wool": "wool", "woollen": "wool", "woolen": "wool",
    "merino": "wool", "fleece": "fleece", "leather": "leather", "velvet": "velvet", "lycra": "lycra blend", "spandex": "lycra blend",
    "stretch": "lycra blend", "canvas": "canvas", "mesh": "mesh", "suede": "suede", "eva": "eva rubber", "rubber": "eva rubber", "modal": "modal",
    # Tamil
    "பருத்தி": "cotton", "காட்டன்": "cotton", "பட்டு": "silk", "லினன்": "linen", "கம்பளி": "wool", "டெனிம்": "denim", "தோல்": "leather",
    "கதர்": "khadi", "காஞ்சிபுரம்": "silk",
    # Tanglish
    "paruthi": "cotton", "pattu": "silk", "kambali": "wool",
    # Hindi
    "सूती": "cotton", "कॉटन": "cotton", "रेशम": "silk", "रेशमी": "silk", "सिल्क": "silk", "ऊनी": "wool", "ऊन": "wool", "लिनन": "linen",
    "खादी": "khadi", "डेनिम": "denim", "चमड़ा": "leather", "चमड़े": "leather", "लेदर": "leather", "बनारसी": "silk", "मखमल": "velvet",
    # Hinglish
    "sooti": "cotton", "suti": "cotton", "resham": "silk", "reshmi": "silk", "oonee": "wool", "woolen ka": "wool",
}
MATERIAL_FAMILY = {
    "cotton": "natural", "organic cotton": "natural", "linen": "natural", "khadi": "natural", "bamboo": "natural", "modal": "natural",
    "rayon": "semi", "chiffon": "synthetic_light", "georgette": "synthetic_light", "silk": "luxury", "velvet": "luxury",
    "polyester": "synthetic", "recycled polyester": "synthetic", "nylon": "synthetic", "lycra blend": "synthetic",
    "wool": "warm", "fleece": "warm", "denim": "heavy", "leather": "heavy", "suede": "heavy", "canvas": "heavy", "mesh": "synthetic_light",
    "eva rubber": "synthetic",
}

# --------------------------------------------------------------------------- colours / patterns / styles
COLOURS = ["red", "blue", "navy", "black", "white", "green", "yellow", "pink", "orange", "purple", "grey", "beige", "brown", "maroon", "gold", "olive", "teal", "cream"]
COLOUR_SYN: dict[str, str] = {c: c for c in COLOURS}
COLOUR_SYN.update({
    "gray": "grey", "off-white": "cream", "off white": "cream", "ivory": "cream", "khaki": "beige", "tan": "brown", "golden": "gold",
    "violet": "purple", "lavender": "purple", "magenta": "pink", "peach": "pink", "mustard": "yellow", "burgundy": "maroon", "wine": "maroon",
    "turquoise": "teal", "sky blue": "blue", "navy blue": "navy", "charcoal": "grey", "rust": "orange", "saffron": "orange", "mint": "green",
    "சிவப்பு": "red", "சிகப்பு": "red", "நீல": "blue", "நீலம்": "blue", "நீல நிற": "blue", "கருப்பு": "black", "கறுப்பு": "black", "வெள்ளை": "white",
    "பச்சை": "green", "மஞ்சள்": "yellow", "இளஞ்சிவப்பு": "pink", "பிங்க்": "pink", "ஆரஞ்சு": "orange", "ஊதா": "purple", "சாம்பல்": "grey",
    "தங்க": "gold", "பழுப்பு": "brown", "மெரூன்": "maroon",
    "sivappu": "red", "sigappu": "red", "neelam": "blue", "neela": "blue", "karuppu": "black", "vellai": "white", "pachai": "green", "manjal": "yellow",
    "लाल": "red", "नीला": "blue", "नीले": "blue", "नीली": "blue", "काला": "black", "काली": "black", "काले": "black", "सफ़ेद": "white", "सफेद": "white",
    "हरा": "green", "हरी": "green", "हरे": "green", "पीला": "yellow", "पीली": "yellow", "पीले": "yellow", "गुलाबी": "pink", "नारंगी": "orange",
    "बैंगनी": "purple", "स्लेटी": "grey", "ग्रे": "grey", "सुनहरा": "gold", "सुनहरी": "gold", "भूरा": "brown", "भूरी": "brown", "मैरून": "maroon",
    "laal": "red", "lal": "red", "kaala": "black", "kala": "black", "kaali": "black", "safed": "white", "hara": "green", "peela": "yellow",
    "gulabi": "pink", "neeli": "blue",
})
PATTERNS = ["solid", "floral", "striped", "checked", "printed", "embroidered", "polka dot", "block print"]
PATTERN_SYN: dict[str, str] = {
    "solid": "solid", "plain": "solid", "floral": "floral", "flower": "floral", "flowers": "floral", "flowery": "floral",
    "striped": "striped", "stripes": "striped", "stripe": "striped", "checked": "checked", "checks": "checked", "check": "checked",
    "plaid": "checked", "printed": "printed", "print": "printed", "graphic": "printed", "embroidered": "embroidered",
    "embroidery": "embroidered", "zari": "embroidered", "polka": "polka dot", "polka dot": "polka dot", "dotted": "polka dot",
    "block print": "block print", "block-print": "block print", "ikat": "block print", "bandhani": "block print",
    "பூ": "floral", "பூக்கள்": "floral", "பூ போட்ட": "floral", "கோடு": "striped", "கோடுகள்": "striped", "கட்டம்": "checked", "எம்பிராய்டரி": "embroidered",
    "फूलों": "floral", "फूलदार": "floral", "धारीदार": "striped", "चेक": "checked", "चेक्स": "checked", "कढ़ाई": "embroidered", "कढ़ाईदार": "embroidered",
    "प्रिंटेड": "printed", "सादा": "solid", "सादी": "solid", "phoolon": "floral", "dhaaridar": "striped",
}
STYLE_SYN: dict[str, str] = {
    "ethnic": "ethnic", "traditional": "ethnic", "desi": "ethnic", "indian": "ethnic", "western": "western", "minimal": "minimal",
    "minimalist": "minimal", "boho": "boho", "bohemian": "boho", "sporty": "sporty", "athleisure": "sporty", "elegant": "elegant",
    "classy": "elegant", "sophisticated": "elegant", "trendy": "trendy", "stylish": "trendy", "fashionable": "trendy", "vintage": "vintage",
    "retro": "vintage", "smart": "formal", "sharp": "formal", "streetwear": "trendy", "oversized": "trendy",
    "பாரம்பரிய": "ethnic", "பாரம்பரியமான": "ethnic", "ஸ்டைலான": "trendy", "ஸ்டைலிஷ்": "trendy", "நவீன": "trendy",
    "पारंपरिक": "ethnic", "एथनिक": "ethnic", "देसी": "ethnic", "स्टाइलिश": "trendy", "फैशनेबल": "trendy", "शानदार": "elegant", "वेस्टर्न": "western",
    "stylish ah": "trendy", "semma": "trendy", "grand ah": "elegant", "grand": "elegant",
}
COMFORT_WORDS = {
    "comfortable", "comfy", "comfort", "soft", "breathable", "relaxed", "easy", "loose", "stretchy", "lightweight", "airy", "cozy", "cosy",
    "வசதியான", "வசதியா", "சௌகரியமான", "இதமான", "மென்மையான", "லேசான",
    "jolly", "light ah", "soft ah", "comfortable ah", "free ah",
    "आरामदायक", "आरामदेह", "आराम", "मुलायम", "हल्का", "हल्की", "हल्के", "aaramdayak", "aramdayak", "aaram", "halka", "halki",
}
SUSTAIN_WORDS = {
    "sustainable", "eco", "eco-friendly", "ecofriendly", "organic", "recycled", "ethical", "biodegradable", "planet",
    "சுற்றுச்சூழல்", "இயற்கை", "पर्यावरण", "टिकाऊ", "इको", "जैविक", "ऑर्गेनिक",
}
GENDER_SYN: dict[str, str] = {
    "men": "men", "man": "men", "mens": "men", "men's": "men", "male": "men", "boys": "men", "boy": "men", "gents": "men", "husband": "men",
    "him": "men", "groom": "men", "father": "men", "dad": "men", "brother": "men",
    "women": "women", "woman": "women", "womens": "women", "women's": "women", "ladies": "women", "lady": "women", "girls": "women",
    "girl": "women", "female": "women", "wife": "women", "her": "women", "bride": "women", "mother": "women", "mom": "women", "sister": "women",
    "kids": "kids", "children": "kids", "child": "kids", "baby": "kids",
    "ஆண்": "men", "ஆண்கள்": "men", "ஆண்களுக்கான": "men", "பெண்": "women", "பெண்கள்": "women", "பெண்களுக்கான": "women", "அம்மா": "women",
    "அப்பா": "men", "மனைவி": "women", "கணவர்": "men", "குழந்தை": "kids",
    "ponnu": "women", "ponnuku": "women", "paiyan": "men", "paiyanuku": "men", "aambala": "men", "pombala": "women", "amma": "women", "appa": "men",
    "पुरुष": "men", "पुरुषों": "men", "आदमी": "men", "मर्द": "men", "लड़कों": "men", "लड़का": "men", "पति": "men", "महिला": "women", "महिलाओं": "women",
    "औरत": "women", "लड़की": "women", "लड़कियों": "women", "पत्नी": "women", "बच्चों": "kids", "बच्चे": "kids",
    "ladka": "men", "ladke": "men", "ladki": "women", "mard": "men", "aurat": "women", "biwi": "women", "pati": "men", "patni": "women",
}

# words signalling a visual / "look" request
VISUAL_WORDS = {"looks like", "look like", "similar to", "style like", "this look", "like this", "same as", "colour", "color", "shade", "pattern"}

# Tanglish / Hinglish marker words for code-mixed language detection
TANGLISH_MARKERS = {
    "venum", "vennum", "veanum", "ku", "kku", "kulla", "ulla", "la", "ah", "dha", "tha", "irukka", "iruku", "edhuku", "enna", "oru",
    "semma", "romba", "nalla", "kalyanam", "kovil", "veyil", "mazhai", "kulir", "sattai", "pudavai", "seruppu", "veetla", "ponnu",
    "paiyan", "vaanga", "podu", "kudunga", "venumae", "mattum", "kammi", "vilai", "rooba", "rubai", "pakkalam", "pogum", "poren",
    "porom", "ponum", "panna", "pannanum", "madhiri", "maadhiri", "appa", "amma",
}
HINGLISH_MARKERS = {
    "chahiye", "chaiye", "chahie", "ke", "liye", "ka", "ki", "ko", "mein", "tak", "se", "kam", "wala", "wali", "wale", "shaadi",
    "garmi", "sardi", "thand", "baarish", "acha", "accha", "achha", "sasta", "sasti", "kapde", "kapda", "dikhao", "batao", "hai", "hain",
    "mujhe", "mere", "meri", "andar", "neeche", "upar", "aur", "bhi", "zyada",
}
STOPWORDS_EN = {
    "a", "an", "the", "for", "to", "of", "in", "on", "at", "and", "or", "with", "i", "me", "my", "need", "want", "looking", "show",
    "find", "some", "something", "please", "is", "are", "be", "this", "that", "it", "go", "going", "get", "buy", "suggest", "recommend",
    "can", "you", "would", "like", "should", "what", "wear", "outfit", "outfits", "clothes", "clothing", "under", "below", "within", "upto",
    "up", "rs", "inr", "rupees", "budget", "less", "than", "around", "good", "nice", "best", "new", "from", "by", "as", "so", "very", "will",
}

# --------------------------------------------------------------------------- helpers
_TOKEN_RE = re.compile(r"[\w\-']+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Unicode-aware lowercase tokenizer with light English plural stemming (for BM25)."""
    out = []
    for t in _TOKEN_RE.findall(text.lower()):
        t = t.strip("-'")
        if not t:
            continue
        if t.isascii() and t.isalpha() and len(t) > 3:
            if t.endswith("ies"):
                t = t[:-3] + "y"
            elif t.endswith("es") and t[:-2].endswith(("ss", "sh", "ch", "x")):
                t = t[:-2]
            elif t.endswith("s") and not t.endswith("ss"):
                t = t[:-1]
        out.append(t)
    return out


_MATCHERS: dict[int, tuple[Any, Any, list[tuple[str, str]], dict[str, str]]] = {}


def _matcher(lexicon: dict[str, str] | Iterable[str]):
    """Compile (once per lexicon object) a single alternation regex for Latin phrases (longest first)
    plus an ordered list of non-Latin phrases. Bounded cache keyed by object identity."""
    key = id(lexicon)
    hit = _MATCHERS.get(key)
    if hit is not None and hit[0] is lexicon:
        return hit
    items = list(lexicon.items()) if isinstance(lexicon, dict) else [(w, w) for w in lexicon]
    latin = sorted(((k.lower(), v) for k, v in items if k.isascii()), key=lambda kv: -len(kv[0]))
    native = sorted(((k.lower(), v) for k, v in items if not k.isascii()), key=lambda kv: -len(kv[0]))
    rx = re.compile(r"(?<![\w])(?:" + "|".join(re.escape(k) for k, _ in latin) + r")(?![\w])") if latin else None
    if len(_MATCHERS) > 256:
        _MATCHERS.clear()
    entry = (lexicon, rx, native, dict(latin))
    _MATCHERS[key] = entry
    return entry


def find_terms(text: str, lexicon: dict[str, str] | Iterable[str]) -> list[tuple[str, str]]:
    """Return (surface, canonical) for every lexicon phrase found in `text`, in order of appearance.

    Latin phrases match on word boundaries (leftmost-longest); non-Latin (Tamil / Devanagari) phrases
    match as substrings because those scripts attach case markers/postpositions directly to the stem
    (e.g. "சென்னைக்கு" = Chennai + dative). A matched span is consumed, so "formal shoes" does not
    also yield "shoes".
    """
    _lex, rx, native, latin_map = _matcher(lexicon)
    low = text.lower()
    found: list[tuple[int, str, str]] = []
    for surface, canon in native:
        idx = low.find(surface)
        if idx >= 0:
            found.append((idx, surface, canon))
            low = low.replace(surface, "\x00" * len(surface))
    if rx is not None:
        for m in rx.finditer(low):
            found.append((m.start(), m.group(0), latin_map[m.group(0)]))
    found.sort(key=lambda x: x[0])
    return [(s, c) for _, s, c in found]


def category_lexicon() -> dict[str, str]:
    lex = {alias: canon for canon, meta in CATEGORIES.items() for alias in meta["aliases"]}
    lex.update(CATEGORY_ML)
    return lex


CATEGORY_LEX = category_lexicon()
HEAVY_CATEGORIES = {"coat", "sweater", "jacket", "hoodie", "boots", "blazer", "sherwani"}
WARM_CATEGORIES = {"coat", "sweater", "jacket", "hoodie", "boots", "scarf"}
OPEN_CATEGORIES = {"shorts", "sandals", "swimwear", "t-shirt", "top", "dress", "skirt", "hat"}


# --------------------------------------------------------------------------- product enrichment
COMFORT_TAG_CUES = {
    "relaxed fit": "relaxed fit", "regular fit": None, "loose fit": "relaxed fit", "oversized": "relaxed fit", "breathable": "breathable",
    "soft": "soft", "stretch": "stretch", "stretchable": "stretch", "elastic": "stretch", "cushioned": "cushioned", "cushion": "cushioned",
    "lightweight": "lightweight", "light weight": "lightweight", "airy": "breathable", "moisture-wicking": "breathable", "quick-dry": "quick-dry",
    "quick dry": "quick-dry", "all-day comfort": "soft", "comfortable": "soft", "padded": "cushioned", "memory foam": "cushioned",
}
SEASON_CUES = {
    "summer": "summer", "hot weather": "summer", "keeps you cool": "summer", "beat the heat": "summer", "sunny": "summer", "tropical": "summer",
    "winter": "winter", "warm": "winter", "insulated": "winter", "cold weather": "winter", "chilly": "winter", "keeps you warm": "winter",
    "monsoon": "monsoon", "rain": "monsoon", "water-resistant": "monsoon", "waterproof": "monsoon", "water resistant": "monsoon",
    "all season": "all-season", "all-season": "all-season", "year-round": "all-season", "year round": "all-season",
}


GENDER_LATIN = {k: v for k, v in GENDER_SYN.items() if k.isascii()}
COLOUR_LATIN = {k: v for k, v in COLOUR_SYN.items() if k.isascii()}
PATTERN_LATIN = {k: v for k, v in PATTERN_SYN.items() if k.isascii()}
OCCASION_LATIN = {k: v for k, v in OCCASION_SYN.items() if k.isascii()}
COMFORT_TAGS_LEX = {k: v for k, v in COMFORT_TAG_CUES.items() if v}
STYLE_LATIN = {k: v for k, v in STYLE_SYN.items() if k.isascii() and " " not in k}


NON_DESCRIPTIVE_DETAILS = {"date first available", "item model number", "best sellers rank", "asin", "manufacturer", "package dimensions",
                           "product dimensions", "item weight", "is discontinued by manufacturer", "batteries required", "upc"}


def product_text(p: dict[str, Any]) -> str:
    """Canonical text representation used for BM25 and dense passage embeddings.
    Operational detail fields (dates, model numbers, dimensions) are excluded: they carry no
    semantics and cause false matches (e.g. "Date First Available" -> occasion "date")."""
    parts = [p.get("title") or ""]
    if p.get("store"):
        parts.append(f"Brand: {p['store']}")
    parts.extend(p.get("features") or [])
    parts.extend(p.get("description") or [])
    details = p.get("details") or {}
    for k, v in details.items():
        if str(k).lower() in NON_DESCRIPTIVE_DETAILS:
            continue
        if isinstance(v, (str, int, float)) and len(str(v)) < 120:
            parts.append(f"{k}: {v}")
    cats = p.get("categories") or []
    if cats:
        parts.append(" > ".join(cats))
    return ". ".join(s.strip() for s in parts if s and str(s).strip())


def _first(found: list[tuple[str, str]]) -> str | None:
    return found[0][1] if found else None


def enrich_product(p: dict[str, Any]) -> dict[str, Any]:
    """Deterministically derive structured attributes from product text/metadata.

    Production note: for real Amazon data this rule extractor is the cheap first pass; an
    offline LLM/NER batch job can overwrite `attributes` asynchronously (same schema).
    """
    details = {str(k).lower(): v for k, v in (p.get("details") or {}).items()}
    title = p.get("title") or ""
    text = product_text(p)
    low = text.lower()

    # category: title first (most reliable), then categories path, then full text
    cat = _first(find_terms(title, CATEGORY_LEX)) or _first(find_terms(" ".join(p.get("categories") or []), CATEGORY_LEX)) \
        or _first(find_terms(text, CATEGORY_LEX))

    # gender
    gender = None
    dept = str(details.get("department", "")).lower()
    if dept:
        gender = _first(find_terms(dept, GENDER_SYN))
    if not gender:
        g = find_terms(title, GENDER_LATIN)
        gender = _first(g)
    if (not gender or gender == "kids") and cat and CATEGORIES[cat]["gender"]:
        gender = gender or CATEGORIES[cat]["gender"]
    if not gender and "unisex" in low:
        gender = "unisex"
    gender = gender or "unisex"

    # material: details field first
    mat_src = str(details.get("material", "")) or str(details.get("fabric", ""))
    materials = [c for _, c in find_terms(mat_src, MATERIAL_SYN)] if mat_src else []
    if not materials:
        materials = [c for _, c in find_terms(title + " " + " ".join(p.get("features") or []), MATERIAL_SYN)]
    materials = list(dict.fromkeys(m for m in materials if m in MATERIALS))[:3]

    colour_src = str(details.get("color", "")) or str(details.get("colour", ""))
    colours = [c for _, c in find_terms(colour_src or title, COLOUR_LATIN)]
    colours = list(dict.fromkeys(colours))[:2]

    patterns = list(dict.fromkeys(c for _, c in find_terms(title + " " + str(details.get("pattern", "")), PATTERN_LATIN)))[:2]
    occasions = list(dict.fromkeys(c for _, c in find_terms(low, OCCASION_LATIN)))
    seasons = list(dict.fromkeys(c for _, c in find_terms(low, SEASON_CUES)))
    comfort_tags = list(dict.fromkeys(c for _, c in find_terms(low, COMFORT_TAGS_LEX)))
    styles = list(dict.fromkeys(c for _, c in find_terms(low, STYLE_LATIN)))
    sustainable = any(w in low for w in ("organic", "recycled", "eco-friendly", "sustainable", "biodegradable")) or \
        any(MATERIALS[m][4] for m in materials)

    breath = warmth = mcomfort = 0.5
    rain_ok = False
    if materials:
        props = [MATERIALS[m] for m in materials]
        breath = sum(x[0] for x in props) / len(props)
        warmth = sum(x[1] for x in props) / len(props)
        mcomfort = sum(x[2] for x in props) / len(props)
        rain_ok = any(x[3] for x in props)
    if cat in WARM_CATEGORIES:
        warmth = min(1.0, warmth + 0.3)
        breath = max(0.0, breath - 0.2)
    if "quick-dry" in comfort_tags or "water-resistant" in low or "waterproof" in low:
        rain_ok = True

    return {
        "category": cat, "group": CATEGORIES[cat]["group"] if cat else None, "gender": gender, "materials": materials,
        "colours": colours, "patterns": patterns, "occasions": occasions, "seasons": seasons, "comfort_tags": comfort_tags,
        "styles": styles, "sustainable": bool(sustainable), "breathability": round(breath, 3), "warmth": round(warmth, 3),
        "material_comfort": round(mcomfort, 3), "rain_ok": rain_ok,
    }
