"""MOSAIC-Fashion — Streamlit UI.

Pages: Search (product grid, interactive cards, details dialog, feedback, "no results" helper,
Explain mode with the full pipeline) · Compare (BM25 / Dense / Hybrid / MOSAIC side by side with
constraint checks) · Catalogue (ADD / UPDATE / DELETE, time-to-searchable) · Health (service status,
KPIs, evaluation / load / scale / resilience charts). Light & dark themes.
"""
from __future__ import annotations

import base64
import html
import json
import os
import sys
from pathlib import Path

import httpx
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "libs"), str(ROOT)]
from mosaic_common.config import get_settings  # noqa: E402

S = get_settings()
API = os.environ.get("GATEWAY_URL", S.gateway_url)
ADMIN_KEY = S.admin_api_key.get_secret_value()
REPORTS = ROOT / "evaluation" / "reports"

st.set_page_config(page_title="MOSAIC-Fashion", page_icon="🧵", layout="wide", initial_sidebar_state="expanded")

LANG = {"en": ("English", "🇬🇧"), "ta": ("Tamil", "🇮🇳"), "tanglish": ("Tanglish", "🔀"), "hi": ("Hindi", "🇮🇳"),
        "hinglish": ("Hinglish", "🔀"), "unknown": ("Unknown", "❔")}
EXAMPLES = {
    "Tanglish · Chennai summer dress": "Chennai summer ku comfortable cotton dress venum under 2000",
    "English · beach outfit": "I need an outfit to go to the beach this summer",
    "Tamil · wedding silk saree": "கல்யாணத்துக்கு சிவப்பு பட்டு புடவை 10000 ரூபாய்க்குள்",
    "Hindi · wedding lehenga": "शादी के लिए लाल लहंगा 15000 से कम",
    "Hinglish · sherwani": "shaadi ke liye sherwani chahiye 10k tak",
    "English · Manali winter": "warm jacket for a manali trip in december, size M",
    "English · office shirt": "blue striped shirt for office men size L",
    "Tamil · Chennai cotton kurti": "சென்னை வெயிலுக்கு வசதியான பருத்தி குர்தி",
    "English · eco t-shirt": "eco friendly organic cotton t-shirt under 1000",
    "English · tight budget (no results demo)": "silk sherwani for wedding under 500",
}
SIGNAL_LABEL = {"semantic": "Meaning", "lexical": "Keywords", "visual": "Look & colour", "occasion": "Occasion",
                "climate": "Weather fit", "material": "Fabric", "comfort": "Comfort", "rrf": "Hybrid rank"}
CLIMATE_TXT = {"hot_humid": "hot & humid", "hot_dry": "hot & dry", "hot": "hot weather", "cold": "cold weather",
               "rainy": "rainy weather", "mild": "mild weather"}

# ------------------------------------------------------------------ state
for k, v in {"theme": "light", "explain": False, "q": "", "res": None, "voted": {}, "relax": [], "budget": None,
             "cmp": None, "top_k": 9, "use_llm": True, "run": False}.items():
    st.session_state.setdefault(k, v)

# ------------------------------------------------------------------ theme / CSS
PALETTES = {
    "light": dict(bg="#f6f6fb", surface="#ffffff", surface2="#f0f1f7", text="#1b1d2a", muted="#686d80", border="#e3e5ee",
                  accent="#7c3aed", accent2="#db2777", chip="#f1ebfe", chiptext="#5b21b6", good="#15803d", goodbg="#e7f6ec",
                  bad="#b91c1c", badbg="#fdecec", warn="#a16207", warnbg="#fdf6e3", shadow="0 6px 20px rgba(30,30,60,.10)"),
    "dark": dict(bg="#0e1016", surface="#171a24", surface2="#1f2331", text="#e9eaf2", muted="#9ca2b6", border="#2b3040",
                 accent="#a78bfa", accent2="#f472b6", chip="#2a2246", chiptext="#d8ccff", good="#4ade80", goodbg="#14301f",
                 bad="#f87171", badbg="#3a1717", warn="#facc15", warnbg="#3a3112", shadow="0 6px 22px rgba(0,0,0,.45)"),
}


def inject_css(theme: str) -> None:
    p = PALETTES[theme]
    vars_ = ";".join(f"--{k}:{v}" for k, v in p.items())
    st.markdown(f"""<style>
:root {{{vars_}}}
.stApp, [data-testid="stAppViewContainer"] {{ background: var(--bg) !important; color: var(--text); }}
[data-testid="stHeader"] {{ background: transparent !important; }}
[data-testid="stSidebar"] {{ background: var(--surface) !important; border-right: 1px solid var(--border); }}
.stApp h1,.stApp h2,.stApp h3,.stApp h4,.stApp p,.stApp label,.stApp li,.stApp span,.stApp div[data-testid="stMarkdownContainer"],
[data-testid="stSidebar"] * {{ color: var(--text); }}
[data-testid="stCaptionContainer"], .stApp small {{ color: var(--muted) !important; }}
[data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div, [data-baseweb="base-input"] {{
  background: var(--surface2) !important; border-color: var(--border) !important; }}
.stApp input, .stApp textarea {{ color: var(--text) !important; -webkit-text-fill-color: var(--text) !important; }}
[data-baseweb="popover"] li, [data-baseweb="menu"] {{ background: var(--surface) !important; color: var(--text) !important; }}
.stButton > button, .stDownloadButton > button, [data-testid="stLinkButton"] a, .stFormSubmitButton > button {{
  background: var(--surface) !important; color: var(--text) !important; border: 1px solid var(--border) !important;
  border-radius: 10px !important; transition: all .15s ease; }}
.stButton > button:hover, .stFormSubmitButton > button:hover, [data-testid="stLinkButton"] a:hover {{
  border-color: var(--accent) !important; color: var(--accent) !important; }}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primaryFormSubmit"] {{
  background: linear-gradient(135deg, var(--accent), var(--accent2)) !important; color: #fff !important; border: none !important; }}
.stButton > button[kind="primary"] p {{ color: #fff !important; }}
[data-testid="stExpander"] details, [data-testid="stForm"] {{ background: var(--surface) !important; border: 1px solid var(--border) !important;
  border-radius: 14px !important; }}
[data-testid="stFileUploaderDropzone"] {{ background: var(--surface2) !important; border: 1px dashed var(--border) !important; }}
[data-testid="stPills"] button, [data-testid="stButtonGroup"] button {{ background: var(--surface) !important; color: var(--text) !important;
  border: 1px solid var(--border) !important; }}
[data-testid="stPills"] button[aria-checked="true"], [data-testid="stButtonGroup"] button[aria-checked="true"] {{
  background: var(--chip) !important; color: var(--chiptext) !important; border-color: var(--accent) !important; }}
[data-testid="stTextInputRootElement"], [data-testid="stTextAreaRootElement"], [data-testid="stNumberInputContainer"],
[data-testid="stNumberInput"] input, [data-testid="stNumberInputStepDown"], [data-testid="stNumberInputStepUp"] {{
  background: var(--surface2) !important; border-color: var(--border) !important; color: var(--text) !important; }}
.stApp input::placeholder, .stApp textarea::placeholder {{ color: var(--muted) !important; -webkit-text-fill-color: var(--muted) !important; }}
[data-testid="stDialog"] > div {{ background: var(--surface) !important; border: 1px solid var(--border); }}
[data-testid="stDialog"] h1, [data-testid="stDialog"] h2, [data-testid="stDialog"] h3, [data-testid="stDialog"] h4,
[data-testid="stDialog"] p, [data-testid="stDialog"] li, [data-testid="stDialog"] span, [data-testid="stDialog"] div,
[data-testid="stDialog"] label {{ color: var(--text); }}
[data-testid="stDialog"] button {{ color: var(--text) !important; }}
[data-testid="stAlert"] {{ background: var(--surface2) !important; border: 1px solid var(--border); border-radius: 12px; }}
[data-testid="stAlert"] * {{ color: var(--text) !important; }}
hr {{ border-color: var(--border) !important; }}

[data-testid="stSidebarNav"] {{ padding-top: .4rem; }}
[data-testid="stSidebarNav"] ul {{ gap: 6px; display: flex; flex-direction: column; }}
[data-testid="stSidebarNav"] a {{ border-radius: 12px !important; padding: 10px 12px !important; border: 1px solid var(--border);
  background: var(--surface2) !important; transition: all .15s ease; }}
[data-testid="stSidebarNav"] a:hover {{ border-color: var(--accent); transform: translateX(2px); }}
[data-testid="stSidebarNav"] a[aria-current="page"] {{ background: linear-gradient(135deg, var(--accent), var(--accent2)) !important;
  border-color: transparent; }}
[data-testid="stSidebarNav"] a[aria-current="page"] span {{ color: #fff !important; font-weight: 700; }}
[data-testid="stSidebarNav"] span {{ font-size: .95rem; }}
[data-testid="stSidebarNavSeparator"] {{ display:none; }}
[data-testid="stSidebarHeader"] img, [data-testid="stLogo"] {{ height: 2.6rem !important; max-width: 100% !important; }}
[data-testid="stToolbar"] {{ visibility: hidden; }}
/* ---------- MOSAIC components ---------- */
.m-hero h1 {{ font-size: 2.3rem; margin: 0; background: linear-gradient(90deg, var(--accent), var(--accent2));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-weight: 800; letter-spacing: -.5px; }}
.m-hero p {{ color: var(--muted) !important; margin: .2rem 0 .8rem 0; }}
.m-chip {{ display:inline-block; padding: 3px 10px; margin: 2px 4px 2px 0; border-radius: 999px; font-size: .78rem;
  background: var(--chip); color: var(--chiptext) !important; border: 1px solid transparent; white-space: nowrap; }}
.m-chip.lock {{ background: var(--surface2); color: var(--text) !important; border-color: var(--border); }}
.m-chip.good {{ background: var(--goodbg); color: var(--good) !important; }}
.m-chip.bad {{ background: var(--badbg); color: var(--bad) !important; }}
.m-chip.warn {{ background: var(--warnbg); color: var(--warn) !important; }}
.m-bar-row {{ display:flex; align-items:center; gap:10px; margin: 5px 0; font-size: .85rem; }}
.m-bar-label {{ width: 120px; color: var(--muted) !important; flex-shrink: 0; }}
.m-bar-track {{ flex: 1; height: 10px; background: var(--surface2); border-radius: 999px; overflow: hidden; }}
.m-bar-fill {{ height: 100%; border-radius: 999px; background: linear-gradient(90deg, var(--accent), var(--accent2)); }}
.m-bar-val {{ width: 64px; text-align:right; font-variant-numeric: tabular-nums; }}
.m-panel {{ background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 16px 18px; margin: 8px 0; }}
.m-panel h4 {{ margin: 0 0 8px 0; font-size: 1rem; }}
.m-kpi {{ background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 14px 16px; }}
.m-kpi .v {{ font-size: 1.6rem; font-weight: 750; }}
.m-kpi .l {{ font-size: .8rem; color: var(--muted) !important; text-transform: uppercase; letter-spacing: .4px; }}
.m-step {{ background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 12px 14px; height: 100%; }}
.m-step .n {{ display:inline-flex; width:22px; height:22px; border-radius:50%; align-items:center; justify-content:center; font-size:.75rem;
  background: linear-gradient(135deg, var(--accent), var(--accent2)); color:#fff !important; margin-right:6px; font-weight:700; }}
.m-step .t {{ font-weight: 650; }}
.m-step .d {{ color: var(--muted) !important; font-size: .82rem; margin-top: 6px; }}
.m-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 18px; overflow: hidden;
  transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease; margin-bottom: 6px; }}
.m-card:hover {{ transform: translateY(-4px); box-shadow: var(--shadow); border-color: var(--accent); }}
.m-img {{ position: relative; aspect-ratio: 1 / 1; background: var(--surface2); display:flex; align-items:center; justify-content:center; }}
.m-img img {{ width: 100%; height: 100%; object-fit: contain; }}
.m-img .noimg {{ color: var(--muted) !important; font-size: .85rem; }}
.m-badge {{ position:absolute; top:10px; left:10px; padding: 4px 10px; border-radius: 999px; font-size:.78rem; font-weight:700;
  background: linear-gradient(135deg, var(--accent), var(--accent2)); color: #fff !important; }}
.m-rank {{ position:absolute; top:10px; right:10px; padding: 3px 9px; border-radius: 999px; font-size:.75rem;
  background: rgba(0,0,0,.55); color:#fff !important; }}
.m-overlay {{ position:absolute; inset:auto 0 0 0; padding: 10px 12px; background: linear-gradient(transparent, rgba(10,10,20,.82));
  color:#fff !important; font-size:.8rem; opacity: 0; transform: translateY(8px); transition: all .2s ease; }}
.m-overlay * {{ color:#fff !important; }}
.m-card:hover .m-overlay {{ opacity: 1; transform: translateY(0); }}
.m-body {{ padding: 12px 14px 10px 14px; }}
.m-store {{ font-size: .74rem; color: var(--muted) !important; text-transform: uppercase; letter-spacing: .5px; }}
.m-title {{ font-weight: 650; font-size: .93rem; line-height: 1.3; height: 2.6em; overflow: hidden; margin: 2px 0 6px 0; }}
.m-price {{ font-size: 1.15rem; font-weight: 800; }}
.m-why {{ font-size: .8rem; color: var(--muted) !important; margin-top: 6px; line-height: 1.35; }}
.m-status {{ display:flex; align-items:center; gap:10px; padding: 12px 14px; background: var(--surface); border:1px solid var(--border);
  border-radius: 14px; }}
.m-dot {{ width: 11px; height: 11px; border-radius: 50%; flex-shrink:0; }}
.m-table {{ width:100%; border-collapse: collapse; font-size: .86rem; }}
.m-table th {{ text-align:left; color: var(--muted) !important; font-weight: 600; border-bottom: 1px solid var(--border); padding: 7px 8px; }}
.m-table td {{ border-bottom: 1px solid var(--border); padding: 7px 8px; }}
.m-table tr.hl td {{ background: var(--chip); font-weight: 650; }}
.m-explain {{ background: var(--chip); border-radius: 12px; padding: 10px 12px; font-size: .88rem; }}
.m-explain * {{ color: var(--chiptext) !important; }}
.m-legend {{ font-size:.8rem; color: var(--muted) !important; }}
</style>""", unsafe_allow_html=True)


# ------------------------------------------------------------------ helpers
def esc(x) -> str:
    return html.escape(str(x)) if x is not None else ""


def H(markup: str) -> None:
    """Render HTML (lines are stripped so markdown never turns indented HTML into code blocks)."""
    st.markdown("\n".join(line.strip() for line in markup.splitlines()), unsafe_allow_html=True)


def api(method: str, path: str, **kw):
    try:
        with httpx.Client(base_url=API, timeout=90) as c:
            r = c.request(method, path, **kw)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text
            if r.status_code == 404 and path in ("/search", "/compare", "/system/status"):
                return None, ("The search API answered 404 — the gateway is running the wrong code. Check that "
                              "services\\gateway\\app.py is the gateway file (its first line mentions 'Query API gateway'), "
                              "then run stop_windows.bat and start_windows.bat.")
            return None, f"{r.status_code}: {str(detail)[:300]}"
        return r.json(), None
    except Exception as e:
        return None, f"Cannot reach the MOSAIC API at {API} ({type(e).__name__}). Is start_windows.bat running?"


@st.cache_data(show_spinner=False, max_entries=4000)
def img_src(ref: str | None) -> str | None:
    if not ref:
        return None
    if ref.startswith("local://"):
        p = S.image_root / ref[len("local://"):]
        if p.exists():
            mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
            return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()
        return None
    if ref.startswith("http"):
        return ref
    return None


def money(x) -> str:
    return f"₹{x:,.0f}" if isinstance(x, (int, float)) else "—"


def bars(rows: list[tuple[str, float, str]], vmax: float | None = None) -> str:
    vmax = vmax or max([v for _, v, _ in rows] + [1e-9])
    out = []
    for label, v, txt in rows:
        pct = 0 if vmax <= 0 else max(0.0, min(100.0, 100 * v / vmax))
        out.append(f'<div class="m-bar-row"><div class="m-bar-label">{esc(label)}</div><div class="m-bar-track">'
                   f'<div class="m-bar-fill" style="width:{pct:.1f}%"></div></div><div class="m-bar-val">{esc(txt)}</div></div>')
    return "".join(out)


def reasons(r: dict, intent: dict | None) -> list[str]:
    """Short, grounded reason chips from the top contributing signals + real product attributes."""
    a = r.get("attributes") or {}
    contrib = r.get("contributions") or {}
    out = []
    for sig, _ in sorted(contrib.items(), key=lambda kv: (kv[0] in ("semantic", "lexical", "rrf"), -kv[1])):
        val = (r.get("components") or {}).get(sig, 0)
        if val < 0.5:
            continue
        if sig == "occasion" and intent and intent.get("occasion"):
            hit = [o for o in intent["occasion"] if o in (a.get("occasions") or [])]
            if hit:
                out.append(f"for {hit[0]}")
        elif sig == "climate" and intent and intent.get("climate"):
            out.append(f"suits {CLIMATE_TXT.get(intent['climate'], intent['climate'])}")
        elif sig == "material" and a.get("materials"):
            out.append(a["materials"][0])
        elif sig == "comfort":
            out.append("comfortable")
        elif sig == "visual":
            out.append("matches the look")
        elif sig == "semantic":
            out.append("close match")
        elif sig == "lexical":
            out.append("keyword match")
        if len(out) == 3:
            break
    return list(dict.fromkeys(out))


def constraint_check(r: dict, f: dict | None) -> tuple[bool, list[str]]:
    """Client-side check of a result against the constraints MOSAIC understood (used in Compare)."""
    if not f:
        return True, []
    bad = []
    a = r.get("attributes") or {}
    price = r.get("price")
    if f.get("price_max") is not None and (price is None or price > f["price_max"]):
        bad.append(f"over budget ({money(price)})")
    if f.get("price_min") is not None and (price is None or price < f["price_min"]):
        bad.append("below min price")
    if f.get("size"):
        sizes = [s.upper() for s in r.get("sizes") or []]
        if f["size"].upper() not in sizes and "FREE SIZE" not in sizes:
            bad.append(f"no size {f['size']}")
    if f.get("categories") and a.get("category") not in f["categories"]:
        bad.append(f"is a {a.get('category') or 'other item'}")
    if f.get("gender") and a.get("gender") not in (f["gender"], "unisex"):
        bad.append(f"for {a.get('gender')}")
    if not r.get("in_stock", True):
        bad.append("out of stock")
    return not bad, bad


def card_html(r: dict, intent: dict | None, compact: bool = False, check: tuple[bool, list[str]] | None = None) -> str:
    src = img_src(r.get("image"))
    img = f'<img src="{src}" alt="">' if src else '<div class="noimg">no image</div>'
    match = f'{round(100 * float(r.get("score") or 0))}% match'
    sizes = ", ".join(r.get("sizes") or []) or "—"
    stock = "In stock" if r.get("in_stock") else "Out of stock"
    rating = f'★ {r["rating"]:.1f}' if r.get("rating") else ""
    chips = "".join(f'<span class="m-chip">{esc(c)}</span>' for c in reasons(r, intent)) if not compact else ""
    chk = ""
    if check is not None:
        ok, why = check
        chk = '<span class="m-chip good">✓ meets your constraints</span>' if ok else \
              "".join(f'<span class="m-chip bad">✗ {esc(w)}</span>' for w in why[:2])
    why_line = ""
    if not compact and r.get("explanation"):
        txt = r["explanation"].replace("Why: ", "").split(" Constraints met:")[0]
        why_line = f'<div class="m-why">{esc(txt[:150])}{"…" if len(txt) > 150 else ""}</div>'
    return f"""<div class="m-card">
<div class="m-img">{img}<div class="m-badge">{match}</div><div class="m-rank">#{r.get("rank")}</div>
<div class="m-overlay"><b>{esc(money(r.get("price")))}</b> · {esc(stock)} {esc(rating)}<br>Sizes: {esc(sizes)}</div></div>
<div class="m-body"><div class="m-store">{esc(r.get("store") or "")}</div>
<div class="m-title">{esc(r.get("title"))}</div>
<div class="m-price">{esc(money(r.get("price")))}</div>
<div>{chips}{chk}</div>{why_line}</div></div>"""


def send_feedback(res: dict, r: dict, vote: str) -> None:
    body = {"request_id": res.get("request_id", "-"), "query": res.get("query", ""), "parent_asin": r["parent_asin"], "rank": r["rank"],
            "vote": vote, "mode": res.get("mode", "mosaic"), "score": r.get("score"), "components": r.get("components") or {}}
    _, err = api("POST", "/feedback", json=body)
    if err:
        st.toast(f"Feedback not saved: {err}")
    else:
        st.session_state["voted"][f'{res.get("request_id")}:{r["parent_asin"]}'] = vote
        st.toast("Thanks — feedback recorded 👍" if vote == "up" else "Thanks — we'll learn from that 👎")


@st.dialog("Product details", width="large")
def details_dialog(r: dict, intent: dict | None) -> None:
    p, err = api("GET", f"/catalogue/products/{r['parent_asin']}")
    p = p or {}
    a = p.get("attributes") or r.get("attributes") or {}
    c1, c2 = st.columns([1, 1.25])
    with c1:
        src = img_src(r.get("image"))
        if src:
            H(f'<div class="m-img" style="border-radius:16px;overflow:hidden"><img src="{src}"></div>')
        else:
            st.caption("No product image — ranked on text and attributes only (image fallback).")
    with c2:
        H(f'<div class="m-store">{esc(p.get("store") or r.get("store") or "")}</div>'
          f'<h3 style="margin:2px 0 6px 0">{esc(r.get("title"))}</h3>'
          f'<div class="m-price" style="font-size:1.5rem">{esc(money(r.get("price")))}</div>')
        rating = p.get("average_rating")
        info = []
        if rating:
            info.append(f'<span class="m-chip lock">★ {rating:.1f} ({p.get("rating_number") or 0:,} ratings)</span>')
        qty = p.get("stock_qty")
        info.append(f'<span class="m-chip {"good" if r.get("in_stock") else "bad"}">{"In stock" if r.get("in_stock") else "Out of stock"}'
                    f'{f" · {qty} left" if qty else ""}</span>')
        info += [f'<span class="m-chip lock">{esc(s)}</span>' for s in (r.get("sizes") or [])]
        H("<div>" + "".join(info) + "</div>")
        attrs = [*(a.get("materials") or []), *(a.get("colours") or []), *(a.get("patterns") or []), *(a.get("occasions") or []),
                 *(a.get("seasons") or []), *(a.get("comfort_tags") or [])]
        if attrs:
            H("<div style='margin-top:6px'>" + "".join(f'<span class="m-chip">{esc(x)}</span>' for x in dict.fromkeys(attrs)) + "</div>")
        if r.get("url"):
            st.link_button("View on Amazon ↗", r["url"])
    if r.get("explanation"):
        H(f'<div class="m-explain" style="margin-top:12px"><b>Why this matches:</b> {esc(r["explanation"].replace("Why: ", ""))}</div>')
    d1, d2 = st.columns(2)
    with d1:
        feats = p.get("features") or []
        desc = p.get("description") or []
        if feats or desc:
            H('<div class="m-panel"><h4>Product information</h4>' + "".join(f"<li>{esc(f)}</li>" for f in feats) +
              "".join(f"<p class='m-why'>{esc(x)}</p>" for x in desc) + "</div>")
    with d2:
        contrib = r.get("contributions") or {}
        if contrib:
            rows = [(SIGNAL_LABEL.get(k, k), v, f"{v:.3f}") for k, v in sorted(contrib.items(), key=lambda kv: -kv[1])]
            H(f'<div class="m-panel"><h4>Score breakdown · {r.get("score", 0):.3f}</h4>{bars(rows)}'
              f'<div class="m-legend">Each bar = signal value × its query-specific weight.</div></div>')
        cons = r.get("constraints_satisfied") or []
        if cons:
            H('<div class="m-panel"><h4>Constraints satisfied</h4>' + "".join(f'<span class="m-chip good">✓ {esc(c)}</span>' for c in cons) + "</div>")
    if err:
        st.caption(f"(Full product record unavailable: {err})")


# ------------------------------------------------------------------ sidebar
st.logo(str(ROOT / "ui" / "assets" / "logo.svg"), size="large")
with st.sidebar:
    st.caption("Multilingual fashion search")
    dark = st.toggle("🌙 Dark mode", value=st.session_state["theme"] == "dark")
    st.session_state["theme"] = "dark" if dark else "light"
    st.session_state["explain"] = st.toggle("🧠 Explain mode", value=st.session_state["explain"],
                                            help="Show how MOSAIC understood the query: language, intent, filters, weights and scores.")
    st.session_state["top_k"] = st.slider("Results", 3, 18, st.session_state["top_k"], step=3)
    st.session_state["use_llm"] = st.toggle("Use LLM (if configured)", value=st.session_state["use_llm"])
    st.caption("Search runs fully on your machine. LLM is optional (set in .env).")

inject_css(st.session_state["theme"])


# ------------------------------------------------------------------ search page
def run_search(query: str, image_b64: str | None = None, extra: dict | None = None) -> None:
    body = {"query": query, "mode": "mosaic", "top_k": st.session_state["top_k"], "use_llm": st.session_state["use_llm"]}
    if image_b64:
        body["image_b64"] = image_b64
    if extra:
        body.update(extra)
    with st.spinner("Understanding your request and searching the catalogue…"):
        res, err = api("POST", "/search", json=body)
    if err:
        st.session_state["res"] = None
        st.error(err)
    else:
        st.session_state["res"] = res


def pick_example() -> None:
    choice = st.session_state.get("ex")
    if choice:
        st.session_state["q"] = EXAMPLES[choice]
        st.session_state["run"] = True


def search_page() -> None:
    H('<div class="m-hero"><h1>Find the right outfit, in your own words</h1>'
      '<p>Type the way you speak — English, Tamil, Tanglish, Hindi or Hinglish. Language is detected automatically.</p></div>')
    c1, c2 = st.columns([6, 1])
    with c1:
        q = st.text_input("Search", key="q", label_visibility="collapsed",
                          placeholder="e.g. Chennai summer ku comfortable cotton dress venum under 2000")
    with c2:
        go = st.button("Search", type="primary", use_container_width=True)
    st.pills("Try an example", list(EXAMPLES), key="ex", on_change=pick_example, label_visibility="collapsed")
    with st.expander("📷  Search with a photo (optional)"):
        up = st.file_uploader("Upload a reference image", type=["png", "jpg", "jpeg", "webp"], label_visibility="collapsed")
        if up:
            st.image(up, width=160)
    if (go or st.session_state.pop("run", False)) and (q or up):
        st.session_state["relax"], st.session_state["budget"] = [], None
        run_search(q, base64.b64encode(up.getvalue()).decode() if up else None)
    res = st.session_state.get("res")
    if res:
        render_results(res)


def render_results(res: dict) -> None:
    intent = res.get("intent") or {}
    lang, flag = LANG.get(intent.get("language", "unknown"), LANG["unknown"])
    understood = []
    for k in ("category", "occasion", "material", "colour", "pattern", "style"):
        understood += intent.get(k) or []
    if intent.get("climate"):
        understood.append(CLIMATE_TXT.get(intent["climate"], intent["climate"]))
    if intent.get("destination"):
        understood.append(f"📍 {intent['destination'].title()}")
    if intent.get("season"):
        understood.append(intent["season"])
    if intent.get("comfort"):
        understood.append("comfortable")
    if intent.get("sustainability"):
        understood.append("eco-friendly")
    if intent.get("gender"):
        understood.append(intent["gender"])
    chips = "".join(f'<span class="m-chip">{esc(x)}</span>' for x in dict.fromkeys(understood))
    locks = "".join(f'<span class="m-chip lock">🔒 {esc(c)}</span>' for c in res.get("constraints_applied") or [])
    t = res.get("timings_ms", {}).get("total", 0)
    H(f"""<div class="m-panel">
<span class="m-chip good">{flag} Detected: {esc(lang)}</span>
<span class="m-chip lock">⚡ {t:.0f} ms{' · cached' if res.get('cached') else ''}</span>
<span class="m-chip lock">🧩 {len(res.get('results') or [])} results from {res.get('index_size', 0):,} products</span>
<div style="margin-top:8px"><b>Understood:</b> {chips or '<span class="m-legend">no specific attributes — using meaning only</span>'}</div>
<div style="margin-top:4px"><b>Must-haves:</b> {locks or '<span class="m-legend">none</span>'}</div></div>""")
    for d in res.get("degraded") or []:
        st.warning(f"Running in degraded mode: {d}")
    for w in intent.get("warnings") or []:
        if "llm" in w.lower():
            st.caption(f"⚠️ {w}")

    if st.session_state["explain"]:
        render_explain(res)

    results = res.get("results") or []
    if not results:
        render_no_results(res)
        return
    cols = st.columns(3)
    for i, r in enumerate(results):
        with cols[i % 3]:
            H(card_html(r, intent))
            b1, b2, b3 = st.columns([2.2, 1, 1])
            key = f'{res.get("request_id")}:{r["parent_asin"]}'
            voted = st.session_state["voted"].get(key)
            if b1.button("Details", key=f"d_{key}", use_container_width=True):
                details_dialog(r, intent)
            if b2.button("👍" + (" ✓" if voted == "up" else ""), key=f"u_{key}", use_container_width=True):
                send_feedback(res, r, "up")
                st.rerun()
            if b3.button("👎" + (" ✓" if voted == "down" else ""), key=f"x_{key}", use_container_width=True):
                send_feedback(res, r, "down")
                st.rerun()
            if r.get("url"):
                st.link_button("View on Amazon ↗", r["url"], use_container_width=True)


def render_explain(res: dict) -> None:
    intent = res.get("intent") or {}
    st.markdown("#### How MOSAIC handled this query")
    s1, s2, s3, s4 = st.columns(4)
    lang = LANG.get(intent.get("language", "unknown"), LANG["unknown"])[0]
    steps = [
        (s1, "Understand", f"{lang} detected · parser: <b>{esc(intent.get('parser'))}</b><br>“{esc((intent.get('normalized_query_en') or '')[:90])}”"),
        (s2, "Filter", "<br>".join(esc(c) for c in res.get("constraints_applied") or []) or "no hard constraints"),
        (s3, "Retrieve", f"{esc(res.get('retrieval_mode'))}<br>BM25 keywords + multilingual vectors (+ image)"),
        (s4, "Rank & explain", f"{len([w for w in (res.get('weights') or {}).values() if w > 0])} active signals, weights adapted to this query"),
    ]
    for i, (col, title, desc) in enumerate(steps, 1):
        with col:
            H(f'<div class="m-step"><span class="n">{i}</span><span class="t">{title}</span><div class="d">{desc}</div></div>')
    w = res.get("weights") or {}
    c1, c2 = st.columns([1.1, 1])
    with c1:
        rows = [(SIGNAL_LABEL.get(k, k), v, f"{v:.0%}") for k, v in sorted(w.items(), key=lambda kv: -kv[1])]
        H(f'<div class="m-panel"><h4>Adaptive ranking weights</h4>{bars(rows, 1.0 if rows and max(v for _, v, _ in rows) > .5 else None)}</div>')
    with c2:
        why = "".join(f"<li>{esc(x)}</li>" for x in res.get("weight_rationale") or [])
        H(f'<div class="m-panel"><h4>Why these weights</h4><ul style="margin:0;padding-left:18px">{why}</ul></div>')
    tm = res.get("timings_ms") or {}
    main = [(k, v) for k, v in tm.items() if "." not in k and k != "total"]
    if main:
        rows = [(k.title(), v, f"{v:.0f} ms") for k, v in main]
        H(f'<div class="m-panel"><h4>Where the time went · {tm.get("total", 0):.0f} ms total</h4>{bars(rows)}</div>')


def render_no_results(res: dict) -> None:
    sugg = res.get("suggestions") or []
    H('<div class="m-panel"><h4>No products match all your must-haves</h4>'
      '<div class="m-legend">Every result has to satisfy the constraints above. Relax one of them:</div></div>')
    if not sugg:
        st.info("Nothing matches even after relaxing a single constraint — try rephrasing the request.")
        return
    cols = st.columns(len(sugg))
    for col, s in zip(cols, sugg):
        with col:
            if st.button(f"{s['label']}  ·  {s['matches']}{'+' if s['matches'] >= 50 else ''} options", key=f"relax_{s['relax']}", use_container_width=True):
                extra = {"relax": list(dict.fromkeys(st.session_state["relax"] + ([] if s["relax"] == "price" and s.get("budget_max_override") else [s["relax"]])))}
                if s.get("budget_max_override"):
                    extra["budget_max_override"] = s["budget_max_override"]
                run_search(res.get("query", ""), None, extra)
                st.rerun()


# ------------------------------------------------------------------ compare page
def compare_page() -> None:
    H('<div class="m-hero"><h1>Compare search approaches</h1>'
      '<p>Same query through keyword search (BM25), vector search (Dense), their fusion (Hybrid) and MOSAIC.</p></div>')
    c1, c2 = st.columns([6, 1])
    with c1:
        cq = st.text_input("Query", value=EXAMPLES["Tanglish · Chennai summer dress"], key="cq", label_visibility="collapsed")
    with c2:
        go = st.button("Compare", type="primary", use_container_width=True)
    if go and cq:
        with st.spinner("Running all four systems…"):
            out, err = api("POST", "/compare", json={"query": cq, "top_k": 6})
        if err:
            st.error(err)
        else:
            st.session_state["cmp"] = out
    out = st.session_state.get("cmp")
    if not out:
        st.caption("MOSAIC's understanding of the query (budget, size, category…) is used to check every system's results.")
        return
    mos = out.get("mosaic") or {}
    f = mos.get("filters")
    names = {"bm25": "BM25", "dense": "Dense", "hybrid": "Hybrid", "mosaic": "MOSAIC"}
    rows = []
    for m in names:
        r = out.get(m) or {}
        res = r.get("results") or []
        ok = sum(1 for x in res if constraint_check(x, f)[0])
        rows.append((m, ok, len(res), r.get("timings_ms", {}).get("total", 0)))
    table = "".join(f'<tr class="{"hl" if m == "mosaic" else ""}"><td>{names[m]}</td><td>{ok}/{n}</td><td>{t:.0f} ms</td></tr>'
                    for m, ok, n, t in rows)
    H(f'<div class="m-panel"><h4>Constraint satisfaction</h4><table class="m-table"><tr><th>System</th>'
      f'<th>Results meeting your constraints</th><th>Latency</th></tr>{table}</table>'
      f'<div class="m-legend" style="margin-top:6px">Constraints understood: {esc(", ".join(mos.get("constraints_applied") or []) or "none")}</div></div>')
    cols = st.columns(4)
    for col, m in zip(cols, names):
        with col:
            st.markdown(f"#### {names[m]}")
            r = out.get(m) or {}
            if "error" in r:
                st.error(r["error"])
                continue
            for x in r.get("results") or []:
                H(card_html(x, mos.get("intent"), compact=True, check=constraint_check(x, f)))


# ------------------------------------------------------------------ catalogue page
def kpis(items: list[tuple[str, str]]) -> None:
    cols = st.columns(len(items))
    for col, (label, value) in zip(cols, items):
        with col:
            H(f'<div class="m-kpi"><div class="l">{esc(label)}</div><div class="v">{esc(value)}</div></div>')


def catalogue_page() -> None:
    H('<div class="m-hero"><h1>Evolving catalogue</h1>'
      '<p>Add, update or delete products. Changes become searchable in well under a second — no re-indexing.</p></div>')
    stats, err = api("GET", "/system/status")
    if stats:
        cs, rs = stats.get("catalogue_stats", {}), stats.get("retrieval_stats", {})
        kpis([("Products", f'{cs.get("products", 0):,}'), ("Keyword index", f'{rs.get("bm25_docs", 0):,}'),
              ("Vector index", f'{rs.get("qdrant_points") or 0:,}'), ("Catalogue version", f'{cs.get("catalogue_version", 0):,}')])
    elif err:
        st.error(err)
    t1, t2, t3 = st.tabs(["➕ Add product", "✏️ Update / delete", "⏱️ Time-to-searchable"])
    with t1:
        with st.form("add", border=True):
            c1, c2 = st.columns([1, 2])
            asin = c1.text_input("Product ID", "NEW0001")
            title = c2.text_input("Title", "Marina Bay Women's Seafoam Linen Kaftan Dress - Beach Wear")
            c3, c4, c5 = st.columns(3)
            price = c3.number_input("Price (₹)", 0.0, 1e6, 1499.0, step=100.0)
            stock = c4.number_input("Stock", 0, 100000, 20)
            sizes = c5.text_input("Sizes (comma separated)", "S,M,L")
            c6, c7, c8 = st.columns(3)
            material = c6.text_input("Material", "Linen")
            colour = c7.text_input("Colour", "Teal")
            dept = c8.segmented_control("Department", ["Womens", "Mens", "Unisex"], default="Womens") or "Unisex"
            feats = st.text_area("Features (one per line)", "Fabric: Linen – breathable and soft\nIdeal for beach holidays and resort wear")
            img = st.text_input("Image (local://renders/<file>.png or https URL, optional)", "local://renders/dress__teal__solid.png")
            if st.form_submit_button("Add product", type="primary"):
                p = {"parent_asin": asin, "title": title, "price": price, "stock_qty": int(stock),
                     "sizes": [s.strip() for s in sizes.split(",") if s.strip()], "features": [x for x in feats.splitlines() if x.strip()],
                     "details": {"Material": material, "Color": colour, "Department": dept}, "store": title.split()[0],
                     "images": [{"large": img}] if img else []}
                r, e = api("POST", "/catalogue/products", json=p, headers={"x-api-key": ADMIN_KEY})
                if r:
                    a = r.get("attributes") or {}
                    st.success(f"Added **{asin}** (version {r.get('version')}). Detected: {a.get('category')}, "
                               f"{', '.join(a.get('materials') or [])}, for {a.get('gender')}. It is searchable now.")
                else:
                    st.error(e)
    with t2:
        c1, c2, c3 = st.columns(3)
        uid = c1.text_input("Product ID", "NEW0001", key="uid")
        new_price = c2.number_input("New price (₹)", 0.0, 1e6, 999.0, step=100.0, key="np")
        new_stock = c3.number_input("New stock", 0, 100000, 0, key="ns")
        b1, b2, _ = st.columns([1, 1, 3])
        if b1.button("Update price & stock", type="primary"):
            r, e = api("PATCH", f"/catalogue/products/{uid}", json={"price": new_price, "stock_qty": int(new_stock)},
                       headers={"x-api-key": ADMIN_KEY})
            st.success(f"Updated {uid} → version {r['version']}. Out-of-stock items disappear from search instantly.") if r else st.error(e)
        if b2.button("Delete product"):
            r, e = api("DELETE", f"/catalogue/products/{uid}", headers={"x-api-key": ADMIN_KEY})
            st.success(f"Deleted {uid}.") if r else st.error(e)
    with t3:
        st.caption("Adds a temporary probe product, measures how fast keyword and vector search return it, then removes it.")
        if st.button("Measure now", type="primary"):
            with st.spinner("Adding probe product and polling search…"):
                r, e = api("POST", "/catalogue/time-to-searchable", json={}, headers={"x-api-key": ADMIN_KEY})
            if r:
                kpis([("Write acknowledged", f'{r["write_ack_ms"]:.0f} ms'),
                      ("Searchable · keywords", f'{r["searchable_lexical_ms"] or 0:.0f} ms'),
                      ("Searchable · vectors", f'{r["searchable_dense_ms"] or 0:.0f} ms')])
                rows = [("Write", r["write_ack_ms"], f'{r["write_ack_ms"]:.0f} ms'),
                        ("Keyword index", r["searchable_lexical_ms"] or 0, f'{r["searchable_lexical_ms"] or 0:.0f} ms'),
                        ("Vector index", r["searchable_dense_ms"] or 0, f'{r["searchable_dense_ms"] or 0:.0f} ms')]
                H(f'<div class="m-panel"><h4>Freshness timeline</h4>{bars(rows)}</div>')
            else:
                st.error(e)


# ------------------------------------------------------------------ health page
def load_report(name: str):
    p = REPORTS / name
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except Exception:
        return None


def health_page() -> None:
    H('<div class="m-hero"><h1>System health</h1><p>Live service status plus the measured evaluation, load, scale and resilience results.</p></div>')
    stats, err = api("GET", "/system/status")
    fb, _ = api("GET", "/feedback/stats", params={"limit": 8})
    if err:
        st.error(err)
    else:
        names = list(stats["ready"])
        cols = st.columns(len(names))
        for col, n in zip(cols, names):
            ok = stats["ready"][n]
            br = stats["breakers"].get(n, "-")
            with col:
                H(f'<div class="m-status"><div class="m-dot" style="background:{"var(--good)" if ok else "var(--bad)"}"></div>'
                  f'<div><b>{n.title()}</b><br><span class="m-legend">{"ready" if ok else "down"} · breaker {br}</span></div></div>')
        cs, rs = stats.get("catalogue_stats", {}), stats.get("retrieval_stats", {})
        lag = (rs.get("stream_lag") or {}).get("lag")
        sat = fb.get("satisfaction") if fb else None
        st.write("")
        kpis([("Products", f'{cs.get("products", 0):,}'), ("Vectors indexed", f'{rs.get("qdrant_points") or 0:,}'),
              ("Index lag (events)", f"{lag if lag is not None else 0}"), ("Catalogue DB", str(cs.get("backend", "-"))),
              ("User satisfaction", f"{sat:.0%}" if sat is not None else "no votes yet")])
    ev = load_report("offline_eval.json")
    if ev:
        ov = ev["summary"]["overall"]
        st.markdown("### Search quality (120 multilingual queries)")
        c1, c2 = st.columns(2)
        with c1:
            sel = [s for s in ("BM25", "Dense", "Hybrid", "Hybrid+filters", "MOSAIC") if s in ov]
            rows = [(x, ov[x]["NDCG@10"], "%.3f" % ov[x]["NDCG@10"]) for x in sel]
            H('<div class="m-panel"><h4>NDCG@10 by system</h4>' + bars(rows, 1.0) + "</div>")
        with c2:
            rows = [(x, ov[x]["ConstraintSat@10"], "%.0f%%" % (100 * ov[x]["ConstraintSat@10"])) for x in sel]
            H('<div class="m-panel"><h4>Results meeting the stated constraints</h4>' + bars(rows, 1.0) + "</div>")
        pl = ev["summary"]["per_language"]
        c3, c4 = st.columns(2)
        with c3:
            langs = ["en", "ta", "tanglish", "hi"]
            body = "".join(f"<tr class='{'hl' if s == 'MOSAIC' else ''}'><td>{s}</td>" + "".join(
                f"<td>{pl[s][l]['NDCG@10']:.3f}</td>" for l in langs) + "</tr>" for s in ("BM25", "Dense", "Hybrid", "MOSAIC") if s in pl)
            H(f'<div class="m-panel"><h4>NDCG@10 by language</h4><table class="m-table"><tr><th>System</th><th>English</th>'
              f'<th>Tamil</th><th>Tanglish</th><th>Hindi</th></tr>{body}</table></div>')
        with c4:
            sig = ev["summary"].get("significance_vs_mosaic", {})
            abl = [("Fixed weights", "MOSAIC-fixed-weights"), ("No image", "MOSAIC-text-only"), ("Dense-only candidates", "MOSAIC-dense-candidates"),
                   ("No context signals", "MOSAIC-no-context"), ("No intent parsing", "MOSAIC-no-intent")]
            rows = [(lbl, sig[k]["NDCG@10"]["delta"], f'−{sig[k]["NDCG@10"]["delta"]:.3f}') for lbl, k in abl if k in sig]
            H(f'<div class="m-panel"><h4>Ablations: NDCG lost when a part is removed</h4>{bars(rows)}'
              f'<div class="m-legend">All differences significant (paired permutation test, p ≤ 0.0002).</div></div>')
    lt = load_report("load_test_5k.json")
    sc = load_report("scale_test.json")
    if lt or sc:
        st.markdown("### Performance")
        c1, c2 = st.columns(2)
        if lt:
            with c1:
                mos = [r for r in lt["results"] if r["mode"] == "mosaic"]
                rows = []
                for r in mos:
                    rows.append((f'{r["concurrency"]} users · P50', r["latency_ms"]["p50"], f'{r["latency_ms"]["p50"]:.0f} ms'))
                    rows.append((f'{r["concurrency"]} users · P95', r["latency_ms"]["p95"], f'{r["latency_ms"]["p95"]:.0f} ms'))
                tp = max((r["throughput_rps"] for r in mos), default=0)
                H(f'<div class="m-panel"><h4>Latency under load (5K products, 2 vCPU)</h4>{bars(rows)}'
                  f'<div class="m-legend">Peak throughput ≈ {tp:.0f} req/s · error rate 0%</div></div>')
        if sc:
            with c2:
                body = "".join(
                    f"<tr><td>{s['size']:,}</td><td>{s['quality']['MOSAIC']['NDCG@10']:.3f}</td>"
                    f"<td>{next(l['p50'] for l in s['latency'] if l['mode'] == 'mosaic' and l['concurrency'] == 1):.0f} ms</td>"
                    f"<td>{(s.get('tts') or {}).get('searchable_dense_ms') or 0:.0f} ms</td></tr>" for s in sc["steps"])
                H(f'<div class="m-panel"><h4>Scale test (measured at each size)</h4><table class="m-table"><tr><th>Products</th><th>NDCG@10</th>'
                  f'<th>P50 latency</th><th>Time-to-searchable</th></tr>{body}</table></div>')
    fi = load_report("fault_injection.json")
    if fi:
        st.markdown("### Resilience drills")
        body = "".join(f"<tr><td>{esc(d['drill'])}</td><td><span class='m-chip {'good' if d['success_rate'] == 1 else 'bad'}'>"
                       f"{d['success_rate']:.0%}</span></td><td>{esc(', '.join(d.get('degraded_flags') or []) or '—')}</td>"
                       f"<td>{'' if 'recovered' not in d else format(d['recovered'], '.0%')}</td></tr>" for d in fi)
        H(f'<div class="m-panel"><table class="m-table"><tr><th>What was broken</th><th>Queries answered</th>'
          f'<th>Fallback reported</th><th>Recovered</th></tr>{body}</table></div>')
    if fb and fb.get("recent"):
        st.markdown("### Recent feedback")
        body = "".join(f"<tr><td>{'👍' if x['vote'] == 'up' else '👎'}</td><td>{esc(x['query'][:60])}</td><td>{esc(x['parent_asin'])}</td>"
                       f"<td>#{x['rank']}</td></tr>" for x in fb["recent"])
        H(f'<div class="m-panel"><table class="m-table"><tr><th></th><th>Query</th><th>Product</th><th>Rank</th></tr>{body}</table></div>')
    with st.expander("Technical details (raw status JSON)"):
        st.json(stats or {})


nav = st.navigation([
    st.Page(search_page, title="Search", icon=":material/search:", url_path="search", default=True),
    st.Page(compare_page, title="Compare", icon=":material/compare_arrows:", url_path="compare"),
    st.Page(catalogue_page, title="Catalogue", icon=":material/inventory_2:", url_path="catalogue"),
    st.Page(health_page, title="Health", icon=":material/monitor_heart:", url_path="health"),
], position="sidebar")
nav.run()