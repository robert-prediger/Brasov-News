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


UA = {
    "User-Agent":
    "Mozilla/5.0 (compatible; BrasovNewsDailyBrief/4.0)"
}

TZ = ZoneInfo("Europe/Bucharest")
NOW = datetime.now(TZ)

# Păstrăm doar articole recente.
# 36h oferă puțină marjă pentru articolele publicate seara precedentă.
MAX_AGE_HOURS = 36

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
    "despre noi", "politica de confidentialitate"
)

STOPWORDS = {
    "a", "ai", "ale", "al", "am", "an", "are", "au",
    "ca", "care", "cat", "ce", "cei", "cel", "cele",
    "cu", "cum", "de", "din", "dupa", "este", "fost",
    "in", "la", "mai", "o", "pe", "pentru", "prin",
    "sa", "se", "si", "sunt", "un", "una", "unei",
    "unui", "dintr", "intr", "spre", "sau", "iar",
    "brasov", "brasovean", "brasoveni", "brasovului"
}


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
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
        r"\s+", " ", html.unescape(text)
    ).strip()


def canonical_url(url):
    p = urllib.parse.urlsplit(url)

    query = urllib.parse.parse_qsl(
        p.query, keep_blank_values=False
    )

    query = [
        (k, v) for k, v in query
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


def numbers(title):
    return set(re.findall(r"\b\d+\b", simple(title)))


def similarity(a, b):
    sa = simple(a)
    sb = simple(b)

    seq = SequenceMatcher(None, sa, sb).ratio()

    wa = words(a)
    wb = words(b)

    if not wa or not wb:
        return seq

    overlap = len(wa & wb) / min(len(wa), len(wb))
    union = len(wa & wb) / len(wa | wb)

    return max(seq, overlap, union)


def same_story(a, b):
    if canonical_url(a["url"]) == canonical_url(b["url"]):
        return True

    score = similarity(a["title"], b["title"])

    na = numbers(a["title"])
    nb = numbers(b["title"])

    # Numere identice + vocabular comun sunt un semnal puternic:
    # ex. "58 de șoferi..." publicat de mai multe site-uri.
    common_numbers = bool(na & nb)

    if score >= 0.78:
        return True

    if common_numbers and score >= 0.55:
        return True

    wa = words(a["title"])
    wb = words(b["title"])

    common = wa & wb

    # Minimum 4 cuvinte relevante comune.
    if len(common) >= 4:
        coverage = len(common) / min(len(wa), len(wb))
        if coverage >= 0.55:
            return True

    return False


def category(title):
    x = simple(title)

    # Ordinea contează. "trafic de influență" NU este trafic rutier.
    emergency = (
        "accident", "incend", "pompier", "smurd",
        "salvamont", "urgenta", "interventie",
        "disparut", "perchezit", "retinut",
        "arest", "politia", "politisti", "isu brasov"
    )

    sport = (
        "fotbal", "hochei", "handbal", "baschet",
        "volei", "schi", "atlet", "campionat",
        "liga", "meci", "turneu", "cupa",
        "corona brasov", "fc brasov"
    )

    culture = (
        "concert", "festival", "teatru", "opera",
        "targ", "expozit", "spectacol", "cinema",
        "muzeu", "eveniment cultural"
    )

    administration = (
        "primaria", "consiliul local",
        "consiliul judetean", "prefectura",
        "municipiul", "primar", "spital",
        "scoala", "administratie"
    )

    development = (
        "construct", "santier", "moderniz",
        "amenaj", "reabilit", "renov",
        "infrastructur", "lucrari"
    )

    business = (
        "business", "afaceri", "companie",
        "fabrica", "investitie", "investitii",
        "antreprenor", "economie", "angajari",
        "salarii", "magazin", "hotel",
        "restaurant"
    )

    traffic = (
        "trafic rutier", "circulatie", "dn1",
        "dn 1", "autostrada", "parcare",
        "ratbv", "autobuz", "troleibuz",
        "transport public", "gara",
        "restrictii de circulatie",
        "drum inchis", "drum blocat"
    )

    if any(k in x for k in emergency):
        return "🚨 Evenimente / urgențe"

    if any(k in x for k in sport):
        return "⚽ Sport"

    if any(k in x for k in culture):
        return "🎭 Evenimente & timp liber"

    if any(k in x for k in administration):
        return "🏙️ Oraș & administrație"

    if any(k in x for k in development):
        return "🏗️ Dezvoltare"

    if any(k in x for k in business):
        return "💰 Business & economie"

    if (
        "trafic de influenta" not in x
        and any(k in x for k in traffic)
    ):
        return "🚗 Trafic & transport"

    return "🔥 Local"


DATE_PATTERNS = [
    # ISO / OpenGraph
    r'(?:article:published_time|datePublished|datepublished)'
    r'["\':=\s]+(?:content=["\'])?'
    r'(\d{4}-\d{2}-\d{2}(?:[T ][0-9:]+)?(?:Z|[+-]\d{2}:?\d{2})?)',

    # data calendaristică numerică
    r'\b(\d{1,2}[./-]\d{1,2}[./-]20\d{2})\b'
]


MONTHS = {
    "ianuarie": 1,
    "februarie": 2,
    "martie": 3,
    "aprilie": 4,
    "mai": 5,
    "iunie": 6,
    "iulie": 7,
    "august": 8,
    "septembrie": 9,
    "octombrie": 10,
    "noiembrie": 11,
    "decembrie": 12
}


def parse_date(value):
    value = html.unescape(value).strip()

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

    m = re.search(
        r'\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b',
        value
    )

    if m:
        try:
            return datetime(
                int(m.group(3)),
                int(m.group(2)),
                int(m.group(1)),
                tzinfo=TZ
            )
        except Exception:
            pass

    x = simple(value)

    m = re.search(
        r'\b(\d{1,2})\s+('
        + "|".join(MONTHS.keys())
        + r')\s+(20\d{2})\b',
        x
    )

    if m:
        try:
            return datetime(
                int(m.group(3)),
                MONTHS[m.group(2)],
                int(m.group(1)),
                tzinfo=TZ
            )
        except Exception:
            pass

    return None


def extract_date(page):
    # JSON-LD / meta / HTML date formats
    candidates = []

    patterns = [
        r'property=["\']article:published_time["\'][^>]*'
        r'content=["\']([^"\']+)',

        r'name=["\']date["\'][^>]*'
        r'content=["\']([^"\']+)',

        r'"datePublished"\s*:\s*"([^"]+)"',

        r'datetime=["\']([^"\']+)["\']'
    ]

    for pattern in patterns:
        for m in re.finditer(pattern, page, re.I):
            candidates.append(m.group(1))

    # Date românești în text
    month_names = "|".join(MONTHS.keys())

    for m in re.finditer(
        r'\b\d{1,2}\s+(?:'
        + month_names +
        r')\s+20\d{2}\b',
        simple(page)
    ):
        candidates.append(m.group(0))

    for value in candidates:
        d = parse_date(value)

        if d:
            # Ignorăm date evident imposibile.
            if d <= NOW + timedelta(days=1):
                return d

    return None


def recent(date):
    if date is None:
        return False

    age = NOW - date

    return (
        timedelta(hours=-2)
        <= age
        <= timedelta(hours=MAX_AGE_HOURS)
    )


cfg = json.loads(
    Path("sources.json").read_text(encoding="utf-8")
)

candidates = []

for source in cfg["sources"]:
    try:
        home = fetch(source["url"])

        source_host = urllib.parse.urlparse(
            source["url"]
        ).netloc.lower().replace("www.", "")

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
            low = simple(title)

            if len(title) < 28 or len(title) > 240:
                continue

            if any(b in low for b in BAD):
                continue

            article_host = urllib.parse.urlparse(
                url
            ).netloc.lower().replace("www.", "")

            if source_host != article_host:
                continue

            if not any(place in low for place in LOCAL):
                continue

            cu = canonical_url(url)

            if cu in seen_source_urls:
                continue

            seen_source_urls.add(cu)

            try:
                article_page = fetch(url)
                published = extract_date(article_page)
            except Exception as e:
                print(
                    "ARTICLE ERROR:",
                    source["name"],
                    url,
                    e
                )
                continue

            # Pentru Daily Brief nu păstrăm articole fără o dată
            # verificabilă și nici articole mai vechi de 36h.
            if not recent(published):
                continue

            candidates.append({
                "title": title,
                "url": url,
                "source": source["name"],
                "category": category(title),
                "published": published.isoformat()
            })

    except Exception as e:
        print(
            "SOURCE ERROR:",
            source["name"],
            e
        )


# Cele mai noi primele
candidates.sort(
    key=lambda x: x["published"],
    reverse=True
)


# Deduplicare între publicații.
out = []

for article in candidates:
    duplicate = False

    for existing in out:
        if same_story(article, existing):
            duplicate = True
            break

    if not duplicate:
        out.append(article)


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
    "recent candidates and",
    len(cfg["sources"]),
    "sources"
)
