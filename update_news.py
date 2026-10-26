import re
import json
import html
import urllib.request
import urllib.parse
import unicodedata
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from html.parser import HTMLParser
from story_dedupe import VERSION as DEDUPE_VERSION, deduplicate, tokens as story_tokens
from concurrent.futures import ThreadPoolExecutor, as_completed

UA = {"User-Agent": "Mozilla/5.0 (compatible; BrasovNewsDailyBrief/9.0)"}
TZ = ZoneInfo("Europe/Bucharest")
NOW = datetime.now(TZ)
MAX_AGE_HOURS = 36
MAX_WORKERS = 12

LOCAL = (
    "brasov","poiana brasov","rasnov","sacele","ghimbav","codlea","zarnesti",
    "fagaras","cristian","sanpetru","harman","predeal","bran","rupea","victoria",
    "feldioara","bod","budila","cincu","prejmer"
)

BAD = (
    "cookie","privacy","contact","publicitate","termeni","facebook","instagram",
    "youtube","whatsapp","abonare","newsletter","despre noi",
    "politica de confidentialitate","copyright","toate drepturile rezervate",
    "ziarul metropolitan brasov"
)

STOPWORDS = {
    "a","ai","ale","al","am","an","are","au","ca","care","cat","ce","cei","cel",
    "cele","cu","cum","de","din","dupa","este","fost","in","la","mai","o","pe",
    "pentru","prin","sa","se","si","sunt","un","una","unei","unui","dintr",
    "intr","spre","sau","iar","brasov","brasovean","brasoveni","brasovului",
    "video","foto","astazi","acum"
}

NUMBER_WORDS = {
    "un":"1","unu":"1","una":"1","doi":"2","doua":"2","trei":"3","patru":"4",
    "cinci":"5","sase":"6","sapte":"7","opt":"8","noua":"9","zece":"10"
}

STEMS = {
    "sechestrat":"sechestr","sechestrata":"sechestr","sechestrati":"sechestr",
    "sechestrare":"sechestr","retinut":"retin","retinuta":"retin","retinuti":"retin",
    "retinere":"retin","arestat":"retin","arestata":"retin","arestati":"retin",
    "arestare":"retin","copilul":"copil","copilului":"copil","copii":"copil",
    "copiii":"copil","tatal":"tata","tatalui":"tata","parcari":"parcare",
    "parcarilor":"parcare","soferi":"sofer","soferilor":"sofer",
    "sanctionat":"sanctiune","sanctionati":"sanctiune","sanctiuni":"sanctiune",
    "reabilitata":"reabilitare","reabilitat":"reabilitare",
    "modernizata":"modernizare","modernizat":"modernizare",
    "masina":"autoturism","masini":"autoturism","autovehicul":"autoturism",
    "autovehicule":"autoturism","vehicul":"autoturism","vehicule":"autoturism",
    "rasturnata":"rasturnat","rasturnate":"rasturnat","rasturnare":"rasturnat",
    "circulatia":"trafic","circulatie":"trafic","traficul":"trafic",
    "ingreunat":"trafic","blocata":"trafic","blocat":"trafic",
    "incendiu":"incend","incendiul":"incend","incendii":"incend",
    "pompieri":"pompier","politisti":"politie","politistii":"politie"
}


def safe_url(url):
    p = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((
        p.scheme,
        p.netloc.encode("idna").decode("ascii"),
        urllib.parse.quote(urllib.parse.unquote(p.path), safe="/%:@"),
        urllib.parse.quote(urllib.parse.unquote(p.query), safe="=&?/:;%+"),
        urllib.parse.quote(urllib.parse.unquote(p.fragment), safe="")
    ))


def fetch(url, timeout=10):
    req = urllib.request.Request(safe_url(url), headers=UA)
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
    return re.sub(
        r"\s+", " ",
        html.unescape(re.sub(r"<[^>]+>", " ", text))
    ).strip()


def canonical_url(url):
    p = urllib.parse.urlsplit(url)

    q = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(
            p.query,
            keep_blank_values=False
        )
        if not k.lower().startswith("utm_")
        and k.lower() not in {
            "fbclid","gclid","ref","source"
        }
    ]

    return urllib.parse.urlunsplit((
        p.scheme.lower(),
        p.netloc.lower().replace("www.", ""),
        re.sub(r"/+$", "", p.path),
        urllib.parse.urlencode(q),
        ""
    ))


def words(title):
    return {
        w for w in simple(title).split()
        if len(w) >= 4 and w not in STOPWORDS
    }


def numbers(title):
    s = simple(title)
    result = set(re.findall(r"\b\d+\b", s))

    for token in s.split():
        if token in NUMBER_WORDS:
            result.add(NUMBER_WORDS[token])

    return result


def normalized_words(title):
    return {STEMS.get(w, w) for w in words(title)}


def event_fingerprint(title):
    result = normalized_words(title)
    result.update("#" + n for n in numbers(title))
    return result


def event_core(title):
    w = normalized_words(title)

    event_terms = {
        "accident","autoturism","rasturnat","trafic","incend","pompier",
        "politie","retin","sechestr","copil","parcare","sofer",
        "sanctiune","meci","corona","spital","reabilitare",
        "modernizare","aeroport","drum","transport","tampa",
        "poiana","dn1e","ghimbav","sacele","rasnov","codlea","zarnesti"
    }

    core = w & event_terms
    core.update("#" + n for n in numbers(title))

    return core


def title_is_valid(title):
    s = simple(title)

    if (
        len(title) < 28
        or len(title) > 240
        or len(words(title)) < 3
        or any(b in s for b in BAD)
    ):
        return False

    return s not in {
        "zmbv ro ziarul metropolitan brasov",
        "ziarul metropolitan brasov",
        "brasov net",
        "biz brasov",
        "transilvania365",
        "stiri brasov"
    }


def has_word(wordset, *wanted):
    return any(word in wordset for word in wanted)


def has_phrase(text, *phrases):
    return any(phrase in text for phrase in phrases)


def category(title):
    x = simple(title)
    w = set(x.split())

    # ------------------------------------------------
    # 🌦️ METEO
    # Folosim cuvinte întregi și expresii meteo clare.
    # "furtuna" singură NU este suficientă deoarece
    # poate apărea metaforic: "furtună pe piața valutară".
    # ------------------------------------------------

    weather_words = {
        "meteo",
        "vreme",
        "ploi",
        "ploaie",
        "lapovita",
        "ninsoare",
        "ninsori",
        "zapada",
        "viscol",
        "canicula",
        "ger",
        "grindina"
    }

    weather_phrases = (
        "prognoza meteo",
        "prognoza pentru brasov",
        "cod galben",
        "cod portocaliu",
        "cod rosu",
        "avertizare meteo",
        "avertizare meteorologica",
        "temperaturi scazute",
        "temperaturi ridicate",
        "grade celsius",
        "rafale de vant",
        "vant puternic",
        "conditii de iarna",
        "vremea se schimba",
        "vreme rea"
    )

    if (w & weather_words) or has_phrase(x, *weather_phrases):
        return "🌦️ Meteo"

    # ------------------------------------------------
    # ⚽ SPORT
    # ------------------------------------------------

    sport_words = {
        "fotbal",
        "hochei",
        "handbal",
        "baschet",
        "volei",
        "schi",
        "atletism",
        "campionat",
        "meci",
        "turneu",
        "cupa",
        "antrenor",
        "antrenorul",
        "sportiv",
        "sportive",
        "sportivi",
        "olimpismului",
        "olimpism",
        "playoff"
    }

    sport_phrases = (
        "fc brasov",
        "corona brasov",
        "club sportiv",
        "liga 1",
        "liga 2",
        "liga 3",
        "liga i",
        "liga ii",
        "liga iii",
        "play off",
        "fote 2027",
        "festivalul olimpic",
        "bazele sportive",
        "competitii sportive",
        "echipa de fotbal",
        "echipa de handbal",
        "echipa de hochei",
        "echipa de baschet",
        "echipa de volei"
    )

    if (w & sport_words) or has_phrase(x, *sport_phrases):
        return "⚽ Sport"

    # ------------------------------------------------
    # 🚗 TRAFIC & TRANSPORT
    # Înainte de urgențe, astfel încât articolele strict
    # despre circulație să nu fie etichetate automat
    # drept urgențe.
    # ------------------------------------------------

    traffic_words = {
        "autostrada",
        "parcare",
        "parcari",
        "ratbv",
        "autobuz",
        "autobuze",
        "troleibuz",
        "troleibuze",
        "tren",
        "trenuri",
        "gara"
    }

    traffic_phrases = (
        "trafic rutier",
        "restrictii de circulatie",
        "restrictie de circulatie",
        "drum inchis",
        "drum blocat",
        "transport public",
        "transport in comun",
        "dn1",
        "dn 1",
        "dn10",
        "dn 10",
        "dn13",
        "dn 13",
        "aeroportul brasov",
        "aeroportul ghimbav",
        "aeroportul international brasov",
        "zbor direct",
        "ruta iasi brasov"
    )

    if (
        "trafic de influenta" not in x
        and (
            (w & traffic_words)
            or has_phrase(x, *traffic_phrases)
        )
    ):
        return "🚗 Trafic & transport"

    # ------------------------------------------------
    # 🚨 EVENIMENTE / URGENȚE
    # Evităm termeni foarte generali precum "politia"
    # sau "urgenta" folosiți singuri.
    # ------------------------------------------------

    emergency_words = {
        "accident",
        "incendiu",
        "incendii",
        "pompieri",
        "smurd",
        "disparut",
        "disparuta",
        "perchezitie",
        "perchezitii",
        "retinut",
        "retinuta",
        "arest",
        "arestat",
        "arestata",
        "crima",
        "cocaina",
        "droguri"
    }

    emergency_phrases = (
        "accident rutier",
        "incendiu puternic",
        "interventia pompierilor",
        "interventie salvamont",
        "operatiune de salvare",
        "persoana disparuta",
        "persoana disparuta",
        "a fost retinut",
        "a fost retinuta",
        "a fost arestat",
        "a fost arestata",
        "arest preventiv",
        "urmarire in trafic",
        "fara permis",
        "coma alcoolica",
        "trafic de droguri",
        "trafic international de cocaina",
        "kilograme de cocaina"
    )

    if (w & emergency_words) or has_phrase(x, *emergency_phrases):
        return "🚨 Evenimente / urgențe"

    # ------------------------------------------------
    # 🎭 EVENIMENTE & TIMP LIBER
    # ------------------------------------------------

    leisure_words = {
        "concert",
        "festival",
        "teatru",
        "opera",
        "targ",
        "expozitie",
        "expozitia",
        "spectacol",
        "cinema",
        "muzeu",
        "premiera"
    }

    leisure_phrases = (
        "eveniment cultural",
        "noaptea cercetatorilor",
        "dracula film festival",
        "nod festival",
        "muzeul de etnografie",
        "centrul cultural reduta"
    )

    if (w & leisure_words) or has_phrase(x, *leisure_phrases):
        return "🎭 Evenimente & timp liber"

    # ------------------------------------------------
    # 🏙️ ORAȘ & ADMINISTRAȚIE
    # ------------------------------------------------

    admin_words = {
        "primaria",
        "prefectura",
        "municipiul",
        "primar",
        "viceprimar",
        "spital",
        "spitalul",
        "clinica",
        "medical",
        "sanatate",
        "scoala",
        "administratie"
    }

    admin_phrases = (
        "consiliul local",
        "consiliul judetean",
        "politia locala",
        "dezbatere publica",
        "locuinta sociala",
        "locuinte sociale",
        "cresele din brasov",
        "spitalul clinic judetean",
        "spitalul de copii",
        "regina maria",
        "hub medical"
    )

    if (w & admin_words) or has_phrase(x, *admin_phrases):
        return "🏙️ Oraș & administrație"

    # ------------------------------------------------
    # 🏗️ DEZVOLTARE
    # ------------------------------------------------

    development_words = {
        "constructie",
        "constructii",
        "santier",
        "modernizare",
        "modernizari",
        "amenajare",
        "amenajari",
        "reabilitare",
        "renovare",
        "infrastructura"
    }

    development_phrases = (
        "lucrari de constructie",
        "lucrari de modernizare",
        "lucrari de reabilitare",
        "proiect rezidential",
        "intra in santier",
        "contractul de lucrari"
    )

    if (w & development_words) or has_phrase(x, *development_phrases):
        return "🏗️ Dezvoltare"

    # ------------------------------------------------
    # 💰 BUSINESS & ECONOMIE
    # ------------------------------------------------

    business_words = {
        "business",
        "afaceri",
        "companie",
        "fabrica",
        "investitie",
        "investitii",
        "antreprenor",
        "economie",
        "economic",
        "angajari",
        "salarii",
        "magazin",
        "hotel",
        "restaurant"
    }

    business_phrases = (
        "piata valutara",
        "fond de investitii",
        "milioane de euro",
        "milioane de lei",
        "locuri de munca",
        "al doilea job",
        "part time",
        "venituri suplimentare",
        "pretul benzinei",
        "pretul motorinei"
    )

    if (w & business_words) or has_phrase(x, *business_phrases):
        return "💰 Business & economie"

    return "🔥 Local"


def parse_date(value):
    if not value:
        return None

    value = html.unescape(value).strip()

    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))

        return (
            d.replace(tzinfo=TZ)
            if d.tzinfo is None
            else d.astimezone(TZ)
        )

    except Exception:
        pass

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
    patterns = (
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']article:published_time["\']',
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'<meta[^>]+itemprop=["\']datePublished["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+itemprop=["\']datePublished["\']',
        r'<meta[^>]+name=["\'](?:date|pubdate|publish-date|publication_date)["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\'](?:date|pubdate|publish-date|publication_date)["\']'
    )

    dates = []

    for pattern in patterns:
        for m in re.finditer(pattern, page, re.I):
            d = parse_date(m.group(1))

            if (
                d
                and d <= NOW + timedelta(hours=3)
                and d >= NOW - timedelta(days=3650)
            ):
                dates.append(d)

    return dates[0] if dates else None


def recent(date):
    return (
        date is not None
        and timedelta(hours=-3)
        <= NOW - date
        <= timedelta(hours=MAX_AGE_HOURS)
    )


class ArticleHeadlineParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.h1 = []
        self.in_h1 = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            key = (attrs.get("property") or attrs.get("name") or "").lower()
            if key in {"og:title", "twitter:title", "og:description", "description"} and attrs.get("content"):
                self.meta.setdefault(key, attrs["content"])
        elif tag == "h1" and not self.h1:
            self.in_h1 = True

    def handle_endtag(self, tag):
        if tag == "h1":
            self.in_h1 = False

    def handle_data(self, data):
        if self.in_h1:
            self.h1.append(data)


class ArticleLeadParser(HTMLParser):
    """Read opening body paragraphs, excluding navigation, ads and related posts."""
    VOID = set("area base br col embed hr img input link meta param source track wbr".split())
    BLOCKED = {"script", "style", "nav", "aside", "header", "footer", "form"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.paragraph = None
        self.paragraphs = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        marker = " ".join([attrs.get("id", ""), attrs.get("class", "")]).lower()
        active = bool(self.stack and self.stack[-1][1])
        active |= tag == "article" or attrs.get("itemprop", "").lower() == "articlebody" or bool(
            re.search(r"(?:entry-content|post-content|article-content|content-main|article-body)", marker))
        blocked = bool(self.stack and self.stack[-1][2]) or tag in self.BLOCKED or bool(
            re.search(r"(?:^|[\s_-])(?:ads?|advert\w*|related|recommended|comments?|author|newsletter|social|share)(?:$|[\s_-])", marker))
        if tag not in self.VOID:
            self.stack.append((tag, active, blocked))
        if tag == "p" and active and not blocked and len(self.paragraphs) < 4:
            self.paragraph = []

    def handle_endtag(self, tag):
        if tag == "p" and self.paragraph is not None:
            text = clean(" ".join(self.paragraph))
            if len(text) >= 50:
                self.paragraphs.append(text)
            self.paragraph = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self.paragraph is not None and self.stack and not self.stack[-1][2]:
            self.paragraph.append(data)


def extract_content_evidence(page):
    parser = ArticleLeadParser()
    try:
        parser.feed(page)
    except Exception:
        return [], []
    lead = " ".join(parser.paragraphs)[:1800]
    # Store only unordered terms and address facts, not copied article prose.
    terms = sorted(story_tokens(lead))[:160]
    streets = re.findall(
        r"\b(?:strada|str\.?|bulevardul|bdul\.?)\s+([A-ZĂÂÎȘȚ0-9][\w-]*(?:\s+[A-ZĂÂÎȘȚ0-9][\w-]*){0,2})",
        lead)
    return terms, sorted({simple(street) for street in streets})


def clean_headline(title, source=""):
    """Remove publisher suffixes, retaining separators inside the headline."""
    parts = re.split(r"\s+[-|•»]\s+", title)
    publisher = simple(source).replace(" ", "")
    boilerplate = {"stiri", "news", "din", "brasov", "ro"}
    while len(parts) > 1:
        tail = simple(parts[-1])
        if (set(tail.split()) <= boilerplate or
                (publisher and publisher in tail.replace(" ", "") and len(tail.split()) <= 10)):
            parts.pop()
        else:
            break
    return " - ".join(parts)


def extract_metadata(page, fallback, source=""):
    parser = ArticleHeadlineParser()
    try:
        parser.feed(page)
    except Exception:
        return fallback, ""
    descriptions = [clean(parser.meta.get(key) or "")[:1000]
                    for key in ("og:description", "description")]
    for value in (parser.meta.get("og:title"), parser.meta.get("twitter:title"),
                  " ".join(parser.h1)):
        title = clean(value or "")
        if 20 <= len(title) <= 500 and len(words(title)) >= 3:
            summary = choose_description(descriptions, title)
            return clean_headline(title, source), summary
    return fallback, choose_description(descriptions, fallback)


def choose_description(descriptions, title):
    title_terms = story_tokens(title)
    relevant = [text for text in descriptions
                if len(story_tokens(text) & title_terms) >= 2
                and len(story_tokens(text) & title_terms) / max(1, len(title_terms)) >= .25]
    return max(relevant,
               key=lambda text: len(story_tokens(text) - title_terms),
               default=descriptions[0] if descriptions else "")


def extract_headline(page, fallback):
    return extract_metadata(page, fallback)[0]


def collect_links(source):
    found = []

    try:
        home = fetch(source["url"], 10)

        source_host = (
            urllib.parse.urlparse(source["url"])
            .netloc.lower()
            .replace("www.", "")
        )

        seen = set()

        for m in re.finditer(
            r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
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

            if (
                urllib.parse.urlparse(url)
                .netloc.lower()
                .replace("www.", "")
                != source_host
            ):
                continue

            if not any(
                place in simple(title)
                for place in LOCAL
            ):
                continue

            cu = canonical_url(url)

            if cu in seen:
                continue

            seen.add(cu)

            found.append({
                "title": title,
                "url": url,
                "source": source["name"]
            })

    except Exception as e:
        print(
            "SOURCE ERROR:",
            source["name"],
            e
        )

    return found


def check_article(article):
    try:
        page = fetch(article["url"], 10)

        published = extract_date(page)

        if not recent(published):
            return None

        title, summary = extract_metadata(page, article["title"], article["source"])
        content_terms, streets = extract_content_evidence(page)
        return {
            "title": title,
            "summary": summary,
            "content_terms": content_terms,
            "streets": streets,
            "url": article["url"],
            "source": article["source"],
            "category": category(title),
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


def main():
    cfg = json.loads(
        Path("sources.json").read_text(
            encoding="utf-8"
        )
    )

    links = []

    for source in cfg["sources"]:
        links.extend(
            collect_links(source)
        )


    unique_links = []
    seen_urls = set()

    for article in links:
        cu = canonical_url(article["url"])

        if cu not in seen_urls:
            seen_urls.add(cu)
            unique_links.append(article)


    print(
        "Checking",
        len(unique_links),
        "candidate article pages in parallel..."
    )


    candidates = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        future_map = {
            executor.submit(check_article, a): a
            for a in unique_links
        }

        for future in as_completed(future_map):

            try:
                result = future.result()

                if result is not None:
                    candidates.append(result)

            except Exception as e:
                a = future_map[future]

                print(
                    "WORKER ERROR:",
                    a["source"],
                    a["url"],
                    e
                )


    candidates.sort(
        key=lambda x: x["published"],
        reverse=True
    )


    out = deduplicate(candidates)


    Path("news.json").write_text(
        json.dumps(
            {
                "updated": NOW.strftime(
                    "%d.%m.%Y, %H:%M"
                ),
                "count": len(out),
                "dedupe_version": DEDUPE_VERSION,
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


if __name__ == "__main__":
    main()

