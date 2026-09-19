import re
import json
import html
import urllib.request
import urllib.parse
import unicodedata

from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor, as_completed


UA = {
    "User-Agent": "Mozilla/5.0 (compatible; BrasovNewsDailyBrief/6.0)"
}

TZ = ZoneInfo("Europe/Bucharest")
NOW = datetime.now(TZ)

MAX_AGE_HOURS = 36
MAX_WORKERS = 12


LOCAL = (
    "brasov", "poiana brasov", "rasnov", "sacele",
    "ghimbav", "codlea", "zarnesti", "fagaras",
    "cristian", "sanpetru", "harman", "predeal",
    "bran", "rupea", "victoria", "feldioara",
    "bod", "budila", "cincu", "prejmer"
)


BAD = (
    "cookie", "privacy", "contact", "publicitate",
    "termeni", "facebook", "instagram", "youtube",
    "whatsapp", "abonare", "newsletter",
    "despre noi", "politica de confidentialitate",
    "copyright", "toate drepturile rezervate",
    "ziarul metropolitan brasov"
)


STOPWORDS = {
    "a", "ai", "ale", "al", "am", "an", "are", "au",
    "ca", "care", "cat", "ce", "cei", "cel", "cele",
    "cu", "cum", "de", "din", "dupa", "este", "fost",
    "in", "la", "mai", "o", "pe", "pentru", "prin",
    "sa", "se", "si", "sunt", "un", "una", "unei",
    "unui", "dintr", "intr", "spre", "sau", "iar",
    "brasov", "brasovean", "brasoveni", "brasovului",
    "video", "foto", "astazi", "acum"
}


def safe_url(url):
    parts = urllib.parse.urlsplit(url)

    host = parts.netloc.encode("idna").decode("ascii")

    path = urllib.parse.quote(
        urllib.parse.unquote(parts.path),
        safe="/%:@"
    )

    query = urllib.parse.quote(
        urllib.parse.unquote(parts.query),
        safe="=&?/:;%+"
    )

    fragment = urllib.parse.quote(
        urllib.parse.unquote(parts.fragment),
        safe=""
    )

    return urllib.parse.urlunsplit(
        (parts.scheme, host, path, query, fragment)
    )


def fetch(url, timeout=10):
    req = urllib.request.Request(
        safe_url(url),
        headers=UA
    )

    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def strip_accents(text):
    return "".join(
        c for c in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(c)
    )


def simple(text):
    text = strip_accents(html.unescape(text)).lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(
        r"\s+",
        " ",
        html.unescape(text)
    ).strip()


def canonical_url(url):
    p = urllib.parse.urlsplit(url)

    query = urllib.parse.parse_qsl(
        p.query,
        keep_blank_values=False
    )

    query = [
        (k, v)
        for k, v in query
        if not k.lower().startswith("utm_")
        and k.lower() not in {
            "fbclid", "gclid", "ref", "source"
        }
    ]

    path = re.sub(r"/+$", "", p.path)

    return urllib.parse.urlunsplit((
        p.scheme.lower(),
        p.netloc.lower().replace("www.", ""),
        path,
        urllib.parse.urlencode(query),
        ""
    ))


def words(title):
    return {
        w for w in simple(title).split()
        if len(w) >= 4 and w not in STOPWORDS
    }
def event_fingerprint(title):
    """
    Creează o amprentă semantică simplă a evenimentului.
    Normalizează forme apropiate ale aceluiași cuvânt,
    astfel încât titlurile formulate diferit să poată
    fi recunoscute ca aceeași știre.
    """
    ws = words(title)
    normalized = set()

    stems = {
        "sechestrat": "sechestr",
        "sechestrare": "sechestr",
        "sechestrului": "sechestr",
        "retinut": "retin",
        "retinere": "retin",
        "arestat": "retin",
        "arestare": "retin",
        "copilul": "copil",
        "copilului": "copil",
        "copii": "copil",
        "tatal": "tata",
        "tatalui": "tata",
        "parcari": "parcare",
        "parcarilor": "parcare",
        "sofer": "sofer",
        "soferi": "sofer",
        "soferilor": "sofer",
        "sanctionat": "sanctiune",
        "sanctionati": "sanctiune",
        "sanctiuni": "sanctiune",
        "reabilitata": "reabilitare",
        "reabilitat": "reabilitare",
        "modernizata": "modernizare",
        "modernizat": "modernizare",
    }

    for w in ws:
        normalized.add(stems.get(w, w))

    # Numerele sunt foarte utile pentru identificarea
    # aceluiași eveniment: 2 ani, 58 șoferi etc.
    # Transformă și numerele scrise cu litere în aceeași
    # formă ca numerele scrise cu cifre.
    number_words = {
        "un": "1",
        "unu": "1",
        "una": "1",
        "doi": "2",
        "doua": "2",
        "trei": "3",
        "patru": "4",
        "cinci": "5",
        "sase": "6",
        "sapte": "7",
        "opt": "8",
        "noua": "9",
        "zece": "10",
    }

    clean_title = simple(title)

    for word, number in number_words.items():
        if re.search(r"\b" + re.escape(word) + r"\b", clean_title):
            normalized.add("#" + number)

    # Transformă și numerele scrise cu litere în aceeași
    # formă ca numerele scrise cu cifre.
    number_words = {
        "un": "1",
        "unu": "1",
        "una": "1",
        "doi": "2",
        "doua": "2",
        "trei": "3",
        "patru": "4",
        "cinci": "5",
        "sase": "6",
        "sapte": "7",
        "opt": "8",
        "noua": "9",
        "zece": "10",
    }

    clean_title = simple(title)

    for word, number in number_words.items():
        if re.search(r"\b" + re.escape(word) + r"\b", clean_title):
            normalized.add("#" + number)

    for n in re.findall(r"\b\d+\b", clean_title):
        normalized.add("#" + n)

    return normalized
  

def numbers(title):
    return set(
        re.findall(r"\b\d+\b", simple(title))
    )


def title_is_valid(title):
    s = simple(title)

    if len(title) < 28 or len(title) > 240:
        return False

    if len(words(title)) < 3:
        return False

    if any(b in s for b in BAD):
        return False

    # Elemente de navigație / branding.
    junk_exact = {
        "zmbv ro ziarul metropolitan brasov",
        "ziarul metropolitan brasov",
        "brasov net",
        "biz brasov",
        "transilvania365",
        "stiri brasov"
    }

    if s in junk_exact:
        return False

    return True


def category(title):
    x = simple(title)

    groups = [
        (
            "🚨 Evenimente / urgențe",
            (
                "accident", "incend", "pompier", "smurd",
                "salvamont", "urgenta", "interventie",
                "disparut", "perchezit", "retinut",
                "arest", "politia", "politisti", "crima"
            )
        ),
        (
            "⚽ Sport",
            (
                "fotbal", "hochei", "handbal", "baschet",
                "volei", "schi", "atlet", "campionat",
                "liga", "meci", "turneu", "cupa",
                "corona brasov", "fc brasov"
            )
        ),
        (
            "🎭 Evenimente & timp liber",
            (
                "concert", "festival", "teatru", "opera",
                "targ", "expozit", "spectacol", "cinema",
                "muzeu", "eveniment cultural"
            )
        ),
        (
            "🏙️ Oraș & administrație",
            (
                "primaria", "consiliul local",
                "consiliul judetean", "prefectura",
                "municipiul", "primar", "spital",
                "scoala", "administratie"
            )
        ),
        (
            "🏗️ Dezvoltare",
            (
                "construct", "santier", "moderniz",
                "amenaj", "reabilit", "renov",
                "infrastructur", "lucrari"
            )
        ),
        (
            "💰 Business & economie",
            (
                "business", "afaceri", "companie",
                "fabrica", "investitie", "investitii",
                "antreprenor", "economie", "angajari",
                "salarii", "magazin", "hotel",
                "restaurant"
            )
        )
    ]

    for name, keys in groups:
        if any(k in x for k in keys):
            return name

    traffic = (
        "trafic rutier", "circulatie", "dn1", "dn 1",
        "autostrada", "parcare", "ratbv", "autobuz",
        "troleibuz", "transport public", "gara",
        "restrictii de circulatie", "drum inchis",
        "drum blocat"
    )

    if (
        "trafic de influenta" not in x
        and any(k in x for k in traffic)
    ):
        return "🚗 Trafic & transport"

    return "🔥 Local"


def parse_date(value):
    if not value:
        return None

    value = html.unescape(value).strip()

    # ISO 8601 - formatul folosit de metadata articolelor.
    try:
        v = value.replace("Z", "+00:00")
        d = datetime.fromisoformat(v)

        if d.tzinfo is None:
            d = d.replace(tzinfo=TZ)
        else:
            d = d.astimezone(TZ)

        return d
    except Exception:
        pass

    # dd.mm.yyyy / dd-mm-yyyy / dd/mm/yyyy
    m = re.search(
        r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})"
        r"(?:[ T,]+(\d{1,2}):(\d{2}))?",
        value
    )

    if m:
        try:
            return datetime(
                int(m.group(3)),
                int(m.group(2)),
                int(m.group(1)),
                int(m.group(4) or 12),
                int(m.group(5) or 0),
                tzinfo=TZ
            )
        except Exception:
            pass

    return None


def extract_date(page):
    """
    IMPORTANT:
    Căutăm numai metadata asociată articolului.
    Nu mai folosim orice <time> sau orice dată din HTML,
    deoarece poate aparține sidebar-ului sau altui articol.
    """

    patterns = (
        # OpenGraph
        r'<meta[^>]+property=["\']article:published_time["\']'
        r'[^>]+content=["\']([^"\']+)["\']',

        r'<meta[^>]+content=["\']([^"\']+)["\']'
        r'[^>]+property=["\']article:published_time["\']',

        # Schema.org JSON-LD
        r'"datePublished"\s*:\s*"([^"]+)"',

        # Schema.org meta
        r'<meta[^>]+itemprop=["\']datePublished["\']'
        r'[^>]+content=["\']([^"\']+)["\']',

        r'<meta[^>]+content=["\']([^"\']+)["\']'
        r'[^>]+itemprop=["\']datePublished["\']',

        # Alte meta-taguri comune
        r'<meta[^>]+name=["\'](?:date|pubdate|publish-date|'
        r'publication_date)["\'][^>]+content=["\']([^"\']+)["\']',

        r'<meta[^>]+content=["\']([^"\']+)["\']'
        r'[^>]+name=["\'](?:date|pubdate|publish-date|'
        r'publication_date)["\']'
    )

    dates = []

    for pattern in patterns:
        for m in re.finditer(pattern, page, re.I):
            d = parse_date(m.group(1))

            if d is None:
                continue

            # Eliminăm date evident imposibile.
            if d > NOW + timedelta(hours=3):
                continue

            if d < NOW - timedelta(days=3650):
                continue

            dates.append(d)

    if not dates:
        return None

    # Dacă există mai multe metadata, folosim prima dată
    # validă din partea principală a documentului, nu cea
    # mai recentă dată găsită în întreaga pagină.
    return dates[0]


def recent(date):
    if date is None:
        return False

    age = NOW - date

    return (
        timedelta(hours=-3)
        <= age
        <= timedelta(hours=MAX_AGE_HOURS)
    )


def similarity_values(a, b):
    sa = simple(a)
    sb = simple(b)

    seq = SequenceMatcher(None, sa, sb).ratio()

    wa = words(a)
    wb = words(b)

    if not wa or not wb:
        return seq, 0, 0, 0

    common = wa & wb

    containment = len(common) / min(len(wa), len(wb))
    jaccard = len(common) / len(wa | wb)

    return seq, containment, jaccard, len(common)

def same_story(a, b):
    # Exact același URL.
    if canonical_url(a["url"]) == canonical_url(b["url"]):
        return True

    seq, containment, jaccard, common_count = similarity_values(
        a["title"],
        b["title"]
    )

    na = numbers(a["title"])
    nb = numbers(b["title"])
    same_numbers = bool(na and nb and na & nb)

    # Amprenta evenimentului.
    fa = event_fingerprint(a["title"])
    fb = event_fingerprint(b["title"])
    fingerprint_common = fa & fb

    if fa and fb:
        fingerprint_containment = (
            len(fingerprint_common) / min(len(fa), len(fb))
        )
        fingerprint_jaccard = (
            len(fingerprint_common) / len(fa | fb)
        )
    else:
        fingerprint_containment = 0
        fingerprint_jaccard = 0

    # 1. Titluri foarte asemănătoare.
    if seq >= 0.72:
        return True

    # 2. Un titlu este practic o versiune mai lungă
    # a celuilalt.
    if containment >= 0.68 and common_count >= 4:
        return True

    # 3. Vocabular comun suficient de puternic.
    if jaccard >= 0.44 and common_count >= 4:
        return True

    # 4. Același număr important + context comun.
    # Exemplu: 58 de șoferi.
    if (
        same_numbers
        and common_count >= 3
        and containment >= 0.45
    ):
        return True

    # 5. Amprentă foarte apropiată.
    if (
        len(fingerprint_common) >= 4
        and fingerprint_containment >= 0.60
    ):
        return True

    # 6. Număr comun + amprentă semantică.
    # Foarte util pentru formulări precum:
    # "copil ținut 2 ani" / "copil sechestrat timp de doi ani".
    if (
        same_numbers
        and len(fingerprint_common) >= 3
        and fingerprint_containment >= 0.45
    ):
        return True

    # 7. Amprente cu multe elemente comune,
    # chiar dacă titlurile sunt construite diferit.
    if (
        len(fingerprint_common) >= 5
        and fingerprint_jaccard >= 0.35
    ):
        return True

    return False

def collect_links(source):
    found = []

    try:
        home = fetch(source["url"], timeout=10)

        source_host = (
            urllib.parse.urlparse(source["url"])
            .netloc.lower()
            .replace("www.", "")
        )

        seen_source_urls = set()

        for m in re.finditer(
            r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>'
            r'(.*?)</a>',
            home,
            re.I | re.S
        ):
            url = urllib.parse.urljoin(
                source["url"],
                html.unescape(m.group(1))
            )

            title = clean(m.group(2))

            if not title_is_valid(title):
                continue

            low = simple(title)

            article_host = (
                urllib.parse.urlparse(url)
                .netloc.lower()
                .replace("www.", "")
            )

            if source_host != article_host:
                continue

            if not any(place in low for place in LOCAL):
                continue

            cu = canonical_url(url)

            if cu in seen_source_urls:
                continue

            seen_source_urls.add(cu)

            found.append({
                "title": title,
                "url": url,
                "source": source["name"]
            })

    except Exception as e:
        print("SOURCE ERROR:", source["name"], e)

    return found


def check_article(article):
    try:
        page = fetch(article["url"], timeout=10)

        published = extract_date(page)

        # Fără dată de publicare verificabilă nu intră
        # în Daily Brief.
        if not recent(published):
            return None

        return {
            "title": article["title"],
            "url": article["url"],
            "source": article["source"],
            "category": category(article["title"]),
            "published": published.isoformat()
        }

    except Exception as e:
        print(
            "ARTICLE ERROR:",
            article["source"],
            article["url"],
            e
        )
        return None


cfg = json.loads(
    Path("sources.json").read_text(encoding="utf-8")
)


# 1. Colectăm candidații de pe toate sursele.
links = []

for source in cfg["sources"]:
    links.extend(collect_links(source))


# 2. Eliminăm URL-urile duplicate înainte de download.
unique_links = []
seen_urls = set()

for article in links:
    cu = canonical_url(article["url"])

    if cu in seen_urls:
        continue

    seen_urls.add(cu)
    unique_links.append(article)


print(
    "Checking",
    len(unique_links),
    "candidate article pages in parallel..."
)


# 3. Verificăm data articolelor în paralel.
candidates = []

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    future_map = {
        executor.submit(check_article, article): article
        for article in unique_links
    }

    for future in as_completed(future_map):
        try:
            result = future.result()

            if result is not None:
                candidates.append(result)

        except Exception as e:
            article = future_map[future]

            print(
                "WORKER ERROR:",
                article["source"],
                article["url"],
                e
            )


# Cele mai recente primele.
candidates.sort(
    key=lambda x: x["published"],
    reverse=True
)


# 4. Deduplicare între publicații.
out = []

for article in candidates:
    duplicate = False

    for existing in out:
        if same_story(article, existing):
            duplicate = True
            print(
                "DUPLICATE:",
                article["source"],
                article["title"],
                "==",
                existing["source"],
                existing["title"]
            )
            break

    if not duplicate:
        out.append(article)


# 5. Salvăm rezultatul.
Path("news.json").write_text(
    json.dumps(
        {
            "updated": NOW.strftime("%d.%m.%Y, %H:%M"),
            "count": len(out),
            "raw_count": len(candidates),
            "items": out
        },
        ensure_ascii=False,
        indent=2
    ),
    encoding="utf-8"
)


print(
    "Saved",
    len(out),
    "unique recent Brasov stories from",
    len(candidates),
    "verified recent candidates and",
    len(cfg["sources"]),
    "sources"
)
