"""
Il Barista - Cloud Version
Groq LLM + Web Scraping, deployable to Railway/Render
Shared communal database for all users
"""

import json, os, sqlite3, threading, time, re, random
from datetime import datetime
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup

# ── CONFIG ──────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent.parent
DB_PATH    = BASE_DIR / "data" / "barista.db"
FRONT_DIR  = BASE_DIR / "frontend"

# Groq config - set via environment variable on Railway
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL   = "llama3-70b-8192"  # Fast, free, excellent quality

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

app = Flask(__name__, static_folder=str(FRONT_DIR))
CORS(app)

# ── DATABASE ─────────────────────────────────────────────────────────────
def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS coffees (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT NOT NULL,
            roaster      TEXT,
            origin       TEXT,
            roast        TEXT,
            process      TEXT,
            altitude     TEXT,
            price        TEXT,
            rating       REAL,
            rating_src   TEXT,
            flavors      TEXT,
            commentary   TEXT,
            purchase_url TEXT,
            review_url   TEXT,
            agent_pick   INTEGER DEFAULT 0,
            status       TEXT DEFAULT 'new',
            added_by     TEXT DEFAULT 'Agent',
            added_at     TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS purchases (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            bean_name   TEXT,
            roaster     TEXT,
            ordered_at  TEXT,
            amount      TEXT,
            price       TEXT,
            status      TEXT DEFAULT 'ordered',
            notes       TEXT,
            added_by    TEXT DEFAULT 'Anonymous',
            added_at    TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS journal (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            bean_name   TEXT,
            brew_method TEXT,
            grind       TEXT,
            dose        TEXT,
            yield       TEXT,
            time_sec    INTEGER,
            notes       TEXT,
            rating      INTEGER,
            added_by    TEXT DEFAULT 'Anonymous',
            created_at  TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS roasters (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            name      TEXT UNIQUE,
            url       TEXT,
            location  TEXT,
            notes     TEXT,
            added_by  TEXT DEFAULT 'Anonymous',
            saved_at  TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS agent_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            query        TEXT,
            sources      TEXT,
            result_count INTEGER,
            ran_at       TEXT DEFAULT (datetime('now'))
        );
    """)
    con.commit()
    _seed_demo_data(cur, con)
    con.close()

def _seed_demo_data(cur, con):
    cur.execute("SELECT COUNT(*) FROM coffees")
    if cur.fetchone()[0] > 0:
        return
    demo = [
        ("Espresso Classico","Intelligentsia Coffee","Brazil / Ethiopia","Medium Dark","Washed","1200-1800 masl",
         "$21.00 / 12oz",4.6,"CoffeeReview.com 94pts",
         '["Dark Chocolate","Brown Sugar","Dried Cherry","Full Body"]',
         "A quintessential espresso blend with extraordinary balance. Brazil base delivers velvet body, Ethiopian component adds a winey sweetness.",
         "https://www.intelligentsiacoffee.com","https://www.coffeereview.com",1,"tried","Agent"),
        ("Black Cat Classic","Intelligentsia Coffee","Central & South America","Medium Dark","Washed","1400-1900 masl",
         "$20.00 / 12oz",4.7,"Home-Barista.com Community Favourite",
         '["Milk Chocolate","Caramel","Walnut","Heavy Crema"]',
         "Gold standard Italian-style espresso. Exceptionally forgiving and produces outstanding thick crema.",
         "https://www.intelligentsiacoffee.com","https://www.home-barista.com",1,"wishlist","Agent"),
        ("Super Crema","Lavazza","Brazil / Colombia","Medium Dark","Natural","900-1200 masl",
         "$12.00 / 1lb",4.3,"Amazon 4.3 stars",
         '["Hazelnut","Honey","Almond","Thick Crema"]',
         "Italian classic with Robusta for persistent crema. The go-to daily driver for value and consistency.",
         "https://www.lavazza.com","https://www.amazon.com",0,"tried","Agent"),
        ("Espresso Blend No.1","Onyx Coffee Lab","Ethiopia / Guatemala","Medium","Washed","1800-2200 masl",
         "$22.00 / 12oz",4.8,"CoffeeReview.com 97pts",
         '["Hibiscus","Apricot Jam","Milk Chocolate","Bright"]',
         "Multiple SCA award-winning blend. Stone fruit brightness balanced by creamy chocolate body.",
         "https://onyxcoffeelab.com","https://www.coffeereview.com",1,"wishlist","Agent"),
        ("Hair Bender","Stumptown Coffee","Latin America / East Africa / Indonesia","Medium Dark","Mixed","1400-1900 masl",
         "$17.00 / 12oz",4.5,"Home-Barista Community Favourite",
         '["Dark Fruit","Caramel","Citrus","Heavy Body"]',
         "Stumptown flagship espresso blend, a Portland institution since 2001. Three-continent complexity in every cup.",
         "https://www.stumptowncoffee.com","https://www.home-barista.com",1,"new","Agent"),
    ]
    cur.executemany("""
        INSERT INTO coffees (name,roaster,origin,roast,process,altitude,price,rating,rating_src,
        flavors,commentary,purchase_url,review_url,agent_pick,status,added_by)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", demo)
    cur.executemany("""
        INSERT INTO purchases (bean_name,roaster,ordered_at,amount,price,status,added_by)
        VALUES (?,?,?,?,?,?,?)""", [
        ("Lavazza Super Crema","Lavazza","2026-08-10","2 x 1lb","$24.00","delivered","Steve"),
        ("Espresso Classico","Intelligentsia","2026-08-18","1 x 12oz","$21.00","delivered","Steve"),
    ])
    cur.executemany("""
        INSERT INTO roasters (name,url,location,notes,added_by) VALUES (?,?,?,?,?)""", [
        ("Intelligentsia Coffee","https://www.intelligentsiacoffee.com","Chicago, IL","Third-wave pioneer, legendary espresso blends.","Agent"),
        ("Onyx Coffee Lab","https://onyxcoffeelab.com","Rogers, AR","Multiple SCA Roaster of the Year.","Agent"),
        ("Stumptown Coffee","https://www.stumptowncoffee.com","Portland, OR","Pacific Northwest icon, Hair Bender is a must-try.","Agent"),
    ])
    con.commit()

def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

# ── WEB SCRAPER ───────────────────────────────────────────────────────────
def safe_get(url, timeout=12):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"[scraper] {url} -> {e}")
        return None

def scrape_coffee_review():
    items = []
    for url in ["https://www.coffeereview.com/top-rated/","https://www.coffeereview.com/category/espresso/"]:
        soup = safe_get(url)
        if not soup: continue
        for el in soup.select("h2.entry-title, h3.entry-title, .review-title, article h2, article h3")[:8]:
            t = el.get_text(strip=True)
            if t: items.append(f"[CoffeeReview] {t}")
    return items

def scrape_roaster_pages():
    items = []
    sources = [
        ("Intelligentsia",   "https://www.intelligentsiacoffee.com/collections/espresso"),
        ("Stumptown",        "https://www.stumptowncoffee.com/collections/coffee"),
        ("Counter Culture",  "https://counterculturecoffee.com/collections/all"),
        ("Onyx Coffee Lab",  "https://onyxcoffeelab.com/collections/espresso"),
        ("Verve Coffee",     "https://www.vervecoffee.com/collections/espresso"),
        ("Blue Bottle",      "https://bluebottlecoffee.com/en-us/collections/coffee"),
        ("Heart Roasters",   "https://www.heartroasters.com/collections/espresso"),
        ("Ruby Coffee",      "https://rubycoffeeroasters.com/collections/all"),
        ("Madcap Coffee",    "https://madcapcoffee.com/collections/all"),
        ("Passenger Coffee", "https://www.passengercoffee.com/collections/espresso"),
        ("Tandem Coffee",    "https://tandemcoffee.com/collections/coffee"),
        ("Ceremony Coffee",  "https://www.ceremonycoffee.com/collections/espresso"),
        ("Coava Coffee",     "https://coavacoffee.com/collections/all-coffee"),
        ("George Howell",    "https://georgehowellcoffee.com/collections/espresso"),
        ("Equator Coffees",  "https://www.equatorcoffees.com/collections/espresso"),
    ]
    random.shuffle(sources)
    for name, url in sources[:5]:
        soup = safe_get(url)
        if not soup: continue
        for el in soup.select(".product-item__title,.product__title,h2.product-title,.grid-product__title,h3")[:5]:
            t = el.get_text(strip=True)
            if 4 < len(t) < 100:
                items.append(f"[{name}] {t}")
    return items

def scrape_community():
    items = []
    for url, label in [
        ("https://www.coffeereview.com/top-rated/", "CoffeeReview"),
        ("https://sprudge.com/", "Sprudge"),
        ("https://perfectdailygrind.com/", "PerfectDailyGrind"),
    ]:
        soup = safe_get(url)
        if not soup: continue
        for el in soup.select("h2,h3,article h2,.entry-title")[:6]:
            t = el.get_text(strip=True)
            if len(t) > 10 and any(k in t.lower() for k in ["coffee","espresso","roast","bean","blend","origin"]):
                items.append(f"[{label}] {t}")
    return items

def run_all_scrapers():
    results = []
    lock = threading.Lock()
    def run(fn):
        try:
            data = fn()
            with lock: results.extend(data)
        except Exception as e:
            print(f"[scraper] {fn.__name__} error: {e}")
    threads = [
        threading.Thread(target=run, args=(scrape_coffee_review,)),
        threading.Thread(target=run, args=(scrape_roaster_pages,)),
        threading.Thread(target=run, args=(scrape_community,)),
    ]
    for t in threads: t.start()
    for t in threads: t.join(timeout=15)
    print(f"[scraper] Collected {len(results)} items")
    return results

# ── GROQ AGENT ────────────────────────────────────────────────────────────
def check_groq():
    return bool(GROQ_API_KEY)

def groq_query(prompt, system):
    if not GROQ_API_KEY:
        print("[groq] ERROR: No API key")
        return None
    headers = {
        "Authorization": "Bearer " + GROQ_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 1200
    }
    try:
        r = requests.post(GROQ_URL, headers=headers, json=payload, timeout=45)
        print("[groq] HTTP status: " + str(r.status_code))
        if r.status_code != 200:
            print("[groq] Error body: " + r.text[:500])
            return None
        data = r.json()
        text = data["choices"][0]["message"]["content"]
        print("[groq] Got response, length: " + str(len(text)))
        print("[groq] First 200 chars: " + text[:200])
        return text
    except requests.exceptions.Timeout:
        print("[groq] Request timed out after 45s")
        return None
    except Exception as ex:
        print("[groq] Exception: " + str(ex))
        return None

def agent_search(query=""):
    print(f"[agent] Search: '{query or 'general discovery'}'")
    raw = run_all_scrapers()
    raw_text = "\n".join(raw[:25]) if raw else ""

    system = (
        "You are Il Barista, an expert specialty coffee connoisseur. "
        "Return ONLY a valid JSON array. No markdown, no explanation, no preamble. "
        "Start with [ and end with ]."
    )

    prompt = (
        f"USER PREFERENCES: Specialty whole bean coffee enthusiast. "
        f"Loves thick full-bodied espresso and americano. "
        f"Prefers medium-dark to dark roasts with chocolate, caramel, nut profiles. "
        f"Also open to interesting single origins and naturals. "
        f"Price range $12-$40 per bag.\n\n"
        f"USER QUERY: {query or 'Discover excellent espresso beans from diverse roasters.'}\n\n"
        + (f"SCRAPED FROM SPECIALTY SOURCES:\n{raw_text}\n\n" if raw_text else "")
        + "Return exactly 4 whole bean coffee recommendations as a JSON array. "
        "Each object must have: name, roaster, roaster_url, origin, roast, process, altitude, "
        "price, rating (number), rating_source, flavors (array of 3-4 strings), commentary (2 sentences), "
        "purchase_url, review_url, agent_pick (true/false). "
        "Prioritize variety across roasters, origins, and price points. "
        "Return ONLY the JSON array."
    )

    response = groq_query(prompt, system)
    coffees = []
    if response:
        try:
            match = re.search(r'\[.*\]', response, re.DOTALL)
            if match:
                coffees = json.loads(match.group())
                print(f"[groq] Parsed {len(coffees)} results")
        except Exception as e:
            print(f"[groq] Parse error: {e}")

    if not coffees:
        coffees = _fallback_coffees()

    try:
        con = get_db()
        con.execute("INSERT INTO agent_log (query,sources,result_count) VALUES (?,?,?)",
            (query, f"{len(raw)} scraped items", len(coffees)))
        con.commit(); con.close()
    except: pass

    return {"coffees": coffees, "sources_scraped": len(raw), "ran_at": datetime.now().isoformat()}

def _fallback_coffees():
    return [
        {"name":"Espresso Classico","roaster":"Intelligentsia Coffee","roaster_url":"https://www.intelligentsiacoffee.com","origin":"Brazil / Ethiopia","roast":"Medium Dark","process":"Washed","altitude":"1200-1800 masl","price":"$21.00 / 12oz","rating":4.6,"rating_source":"CoffeeReview.com 94pts","flavors":["Dark Chocolate","Brown Sugar","Dried Cherry","Full Body"],"commentary":"A quintessential espresso blend with extraordinary balance. Brazil base delivers velvet body, Ethiopian component adds winey sweetness.","purchase_url":"https://www.intelligentsiacoffee.com/products/espresso-classico","review_url":"https://www.coffeereview.com","agent_pick":True},
        {"name":"Espresso Blend No.1","roaster":"Onyx Coffee Lab","roaster_url":"https://onyxcoffeelab.com","origin":"Ethiopia / Guatemala","roast":"Medium","process":"Washed","altitude":"1800-2200 masl","price":"$22.00 / 12oz","rating":4.8,"rating_source":"CoffeeReview.com 97pts","flavors":["Hibiscus","Apricot Jam","Milk Chocolate","Bright"],"commentary":"Multiple SCA award-winning blend. Stone fruit brightness balanced by creamy chocolate body.","purchase_url":"https://onyxcoffeelab.com/collections/espresso","review_url":"https://www.coffeereview.com","agent_pick":True},
        {"name":"Hair Bender","roaster":"Stumptown Coffee","roaster_url":"https://www.stumptowncoffee.com","origin":"Latin America / East Africa / Indonesia","roast":"Medium Dark","process":"Mixed","altitude":"1400-1900 masl","price":"$17.00 / 12oz","rating":4.5,"rating_source":"Home-Barista Community Favourite","flavors":["Dark Fruit","Caramel","Citrus","Heavy Body"],"commentary":"Stumptown flagship espresso blend, a Portland institution since 2001. Three-continent complexity delivers remarkable consistency.","purchase_url":"https://www.stumptowncoffee.com/products/hair-bender","review_url":"https://www.home-barista.com","agent_pick":True},
        {"name":"Super Crema","roaster":"Lavazza","roaster_url":"https://www.lavazza.com","origin":"Brazil / Colombia","roast":"Medium Dark","process":"Natural","altitude":"900-1200 masl","price":"$12.00 / 1lb","rating":4.3,"rating_source":"Amazon 4.3 stars (8,400+ reviews)","flavors":["Hazelnut","Honey","Almond","Thick Crema"],"commentary":"Italian classic with Robusta for persistent crema. The go-to daily driver for value and consistency.","purchase_url":"https://www.lavazza.com/en-us/coffee/espresso/super-crema-espresso.html","review_url":"https://www.amazon.com","agent_pick":False},
    ]

# ── BACKGROUND REFRESH ────────────────────────────────────────────────────
_cache = {"time": None, "data": None}

def background_refresh():
    time.sleep(20)
    while True:
        try:
            print("[agent] Background refresh...")
            data = agent_search()
            _cache["time"] = datetime.now().isoformat()
            _cache["data"] = data
            print(f"[agent] Refresh complete — {len(data.get('coffees',[]))} results")
        except Exception as e:
            print(f"[agent] Refresh error: {e}")
        time.sleep(6 * 3600)

# ── API ROUTES ────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(str(FRONT_DIR), "index.html")

@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(str(FRONT_DIR), path)

@app.route("/api/status")
def api_status():
    return jsonify({
        "status": "online",
        "groq": check_groq(),
        "groq_model": GROQ_MODEL,
        "last_refresh": _cache["time"],
        "time": datetime.now().isoformat()
    })

@app.route("/api/search")
def api_search():
    query = request.args.get("q", "")
    result = agent_search(query)
    return jsonify(result)

@app.route("/api/coffees", methods=["GET"])
def api_coffees():
    status = request.args.get("status")
    con = get_db()
    if status:
        rows = con.execute("SELECT * FROM coffees WHERE status=? ORDER BY added_at DESC", (status,)).fetchall()
    else:
        rows = con.execute("SELECT * FROM coffees ORDER BY added_at DESC").fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/coffees", methods=["POST"])
def api_add_coffee():
    data = request.json
    con = get_db()
    con.execute("""INSERT INTO coffees
        (name,roaster,origin,roast,process,altitude,price,rating,rating_src,
        flavors,commentary,purchase_url,review_url,agent_pick,status,added_by)
        VALUES (:name,:roaster,:origin,:roast,:process,:altitude,:price,:rating,
        :rating_source,:flavors,:commentary,:purchase_url,:review_url,:agent_pick,:status,:added_by)""",
        {
            "name": data.get("name",""), "roaster": data.get("roaster",""),
            "origin": data.get("origin",""), "roast": data.get("roast",""),
            "process": data.get("process",""), "altitude": data.get("altitude",""),
            "price": data.get("price",""), "rating": data.get("rating",0),
            "rating_source": data.get("rating_source",""),
            "flavors": json.dumps(data.get("flavors",[])) if isinstance(data.get("flavors"),list) else data.get("flavors","[]"),
            "commentary": data.get("commentary",""),
            "purchase_url": data.get("purchase_url",""),
            "review_url": data.get("review_url",""),
            "agent_pick": 1 if data.get("agent_pick") else 0,
            "status": data.get("status","new"),
            "added_by": data.get("added_by","Anonymous")
        })
    con.commit(); con.close()
    return jsonify({"ok": True})

@app.route("/api/coffees/<int:cid>", methods=["PATCH"])
def api_update_coffee(cid):
    data = request.json
    con = get_db()
    for field in ["status","rating","notes"]:
        if field in data:
            con.execute(f"UPDATE coffees SET {field}=? WHERE id=?", (data[field], cid))
    con.commit(); con.close()
    return jsonify({"ok": True})

@app.route("/api/purchases", methods=["GET"])
def api_purchases():
    con = get_db()
    rows = con.execute("SELECT * FROM purchases ORDER BY added_at DESC").fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/purchases", methods=["POST"])
def api_add_purchase():
    data = request.json
    con = get_db()
    con.execute("""INSERT INTO purchases (bean_name,roaster,ordered_at,amount,price,status,notes,added_by)
        VALUES (:bean_name,:roaster,:ordered_at,:amount,:price,:status,:notes,:added_by)""",
        {"bean_name":data.get("bean_name",""),"roaster":data.get("roaster",""),
         "ordered_at":data.get("ordered_at",datetime.now().strftime("%Y-%m-%d")),
         "amount":data.get("amount",""),"price":data.get("price",""),
         "status":data.get("status","ordered"),"notes":data.get("notes",""),
         "added_by":data.get("added_by","Anonymous")})
    con.commit(); con.close()
    return jsonify({"ok": True})

@app.route("/api/journal", methods=["GET"])
def api_journal():
    con = get_db()
    rows = con.execute("SELECT * FROM journal ORDER BY created_at DESC").fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/journal", methods=["POST"])
def api_add_journal():
    data = request.json
    con = get_db()
    con.execute("""INSERT INTO journal (bean_name,brew_method,grind,dose,yield,time_sec,notes,rating,added_by)
        VALUES (:bean_name,:brew_method,:grind,:dose,:yield,:time_sec,:notes,:rating,:added_by)""",
        {"bean_name":data.get("bean_name",""),"brew_method":data.get("brew_method",""),
         "grind":data.get("grind",""),"dose":data.get("dose",""),
         "yield":data.get("yield",""),"time_sec":data.get("time_sec",0),
         "notes":data.get("notes",""),"rating":data.get("rating",0),
         "added_by":data.get("added_by","Anonymous")})
    con.commit(); con.close()
    return jsonify({"ok": True})

@app.route("/api/roasters", methods=["GET"])
def api_roasters():
    con = get_db()
    rows = con.execute("SELECT * FROM roasters ORDER BY saved_at DESC").fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/roasters", methods=["POST"])
def api_add_roaster():
    data = request.json
    con = get_db()
    con.execute("INSERT OR IGNORE INTO roasters (name,url,location,notes,added_by) VALUES (:name,:url,:location,:notes,:added_by)",
        {**data, "added_by": data.get("added_by","Anonymous")})
    con.commit(); con.close()
    return jsonify({"ok": True})

# ── MAIN ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 55)
    print("  ☕  Il Barista Cloud — Coffee Connoisseur")
    print("=" * 55)
    init_db()
    print(f"  Groq AI   : {'✓ Configured' if check_groq() else '✗ Missing GROQ_API_KEY'}")
    print(f"  Database  : {DB_PATH}")
    port = int(os.environ.get("PORT", 5000))
    print(f"  Server    : http://0.0.0.0:{port}")
    print("=" * 55)
    t = threading.Thread(target=background_refresh, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
    
