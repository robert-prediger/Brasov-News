import re
import json
import html
import urllib.request
import urllib.parse
import unicodedata

from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from difflib import SequenceMatcher


UA = {
    "User-Agent":
    "Mozilla/5.0 (compatible; BrasovNewsDailyBrief/4.0)"
}


LOCAL = (
    "brașov", "brasov",
    "poiana brașov", "poiana brasov",
    "râșnov", "rasnov",
    "săcele", "sacele",
    "ghimbav",
    "codlea",
    "zărnești", "zarnesti",
    "făgăraș", "fagaras",
    "cristian",
    "sânpetru", "sanpetru",
    "hărman", "harman",
    "predeal",
    "bran",
    "rupea",
    "victoria",
    "feldioara",
    "bod",
    "budila",
    "cincu",
    "prejmer"
)


BAD = (
    "cookie",
    "privacy",
    "contact",
    "publicitate",
    "termeni",
    "facebook",
    "instagram",
    "youtube",
    "whatsapp",
    "abonare",
    "newsletter"
)


STOP_WORDS = {
    "brasov",
    "video",
    "foto",
    "exclusiv",
    "update",
    "astazi",
    "azi",
    "din",
    "de",
    "la",
    "in",
    "pe",
    "si",
    "cu",
    "un",
    "o",
    "al",
    "ale",
    "pentru",
    "dupa",
    "care",
    "mai",
    "este",
    "sunt",
    "prin",
    "spre",
    "peste",
    "sub"
}


def fetch(url):
    request = urllib.request.Request(
        url,
        headers=UA
    )

    response = urllib.request.urlopen(
        request,
        timeout=25
    )

    return response.read().decode(
        "utf-8",
        "ignore"
    )


def clean(text):
    text = re.sub(
        r"<[^>]+>",
        " ",
        text
    )

    text = html.unescape(text)

    return re.sub(
        r"\s+",
        " ",
        text
    ).strip()


def normalize(text):

    text = text.lower()

    text = "".join(
        char
        for char in unicodedata.normalize(
            "NFKD",
            text
        )
        if not unicodedata.combining(char)
    )

    text = re.sub(
        r"[^a-z0-9 ]+",
        " ",
        text
    )

    return re.sub(
        r"\s+",
        " ",
        text
    ).strip()


def important_words(text):

    return {
        word
        for word in normalize(text).split()
        if len(word) >= 4
        and word not in STOP_WORDS
    }


def same_story(first, second):

    title_a = normalize(
        first["title"]
    )

    title_b = normalize(
        second["title"]
    )

    similarity = SequenceMatcher(
        None,
        title_a,
        title_b
    ).ratio()

    # Titluri foarte asemănătoare
    if similarity >= 0.72:
        return True

    words_a = important_words(
        first["title"]
    )

    words_b = important_words(
        second["title"]
    )

    if not words_a or not words_b:
        return False

    common = len(
        words_a & words_b
    )

    union = len(
        words_a | words_b
    )

    smaller = min(
        len(words_a),
        len(words_b)
    )

    jaccard = (
        common / union
        if union else 0
    )

    containment = (
        common / smaller
        if smaller else 0
    )

    # Titlurile pot fi scrise foarte diferit,
    # dar trebuie să aibă minimum 4 cuvinte
    # importante comune.
    if (
        common >= 4
        and (
            jaccard >= 0.42
            or containment >= 0.62
        )
    ):
        return True

    return False


def category(title):

    text = title.lower()

    groups = [

        (
            "🚨 Evenimente / urgențe",
            (
                "isu",
                "pompier",
                "poliți",
                "politi",
                "accident",
                "salvamont",
                "incend",
                "smurd",
                "112",
                "urgență",
                "urgenta",
                "intervenție",
                "interventie",
                "dispărut",
                "disparut",
                "perchezi",
                "reținut",
                "retinut",
                "razie"
            )
        ),

        (
            "🚗 Trafic & transport",
            (
                "trafic",
                "rutier",
                "dn1",
                "dn 1",
                "drum",
                "autostrad",
                "parcare",
                "ratbv",
                "tren",
                "gara",
                "circula",
                "transport",
                "autobuz",
                "troleibuz",
                "restricții",
                "restrictii"
            )
        ),

        (
            "🏙️ Oraș & administrație",
            (
                "primăria",
                "primaria",
                "consili",
                "spital",
                "școal",
                "scoal",
                "administra",
                "municip",
                "prefect",
                "consiliul local",
                "consiliul județean",
                "consiliul judetean",
                "primar",
                "ajofm"
            )
        ),

        (
            "🏗️ Dezvoltare",
            (
                "construc",
                "proiect",
                "șantier",
                "santier",
                "moderniz",
                "amenaj",
                "reabilit",
                "renov",
                "lucrări",
                "lucrari",
                "infrastructur",
                "asfalt"
            )
        ),

        (
            "💰 Business & economie",
            (
                "business",
                "afaceri",
                "companie",
                "fabric",
                "investi",
                "milioane",
                "euro",
                "antreprenor",
                "economie",
                "angaj",
                "salari",
                "magazin",
                "hotel",
                "restaurant"
            )
        ),

        (
            "🎭 Evenimente & timp liber",
            (
                "concert",
                "festival",
                "teatru",
                "operă",
                "opera",
                "târg",
                "targ",
                "expozi",
                "spectacol",
                "cinema",
                "muzeu",
                "eveniment",
                "weekend"
            )
        ),

        (
            "⚽ Sport",
            (
                "sport",
                "fotbal",
                "corona brașov",
                "corona brasov",
                "hochei",
                "meci",
                "campionat",
                "liga",
                "handbal",
                "baschet",
                "volei",
                "schi",
                "atlet",
                "turneu",
                "cupă",
                "cupa"
            )
        )
    ]

    for name, keywords in groups:

        if any(
            keyword in text
            for keyword in keywords
        ):
            return name

    return "🔥 Local"


config = json.loads(
    Path(
        "sources.json"
    ).read_text(
        encoding="utf-8"
    )
)


all_items = []


for source in config["sources"]:

    try:

        page = fetch(
            source["url"]
        )

        host = urllib.parse.urlparse(
            source["url"]
        ).netloc.replace(
            "www.",
            ""
        )

        links = re.finditer(
            r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            page,
            re.I | re.S
        )

        for match in links:

            url = urllib.parse.urljoin(
                source["url"],
                html.unescape(
                    match.group(1)
                )
            )

            title = clean(
                match.group(2)
            )

            low = title.lower()

            if (
                len(title) < 28
                or len(title) > 240
            ):
                continue

            if any(
                bad in low
                for bad in BAD
            ):
                continue

            article_host = (
                urllib.parse.urlparse(
                    url
                ).netloc.replace(
                    "www.",
                    ""
                )
            )

            if host not in article_host:
                continue

            if not any(
                place in low
                for place in LOCAL
            ):
                continue

            all_items.append(
                {
                    "title": title,
                    "url": url,
                    "source":
                        source["name"],
                    "category":
                        category(title)
                }
            )

    except Exception as error:

        print(
            "SOURCE ERROR:",
            source["name"],
            error
        )


# Eliminăm mai întâi URL-urile identice,
# apoi articolele despre același eveniment.

news = []


for article in all_items:

    duplicate_url = any(
        article["url"]
        == existing["url"]
        for existing in news
    )

    if duplicate_url:
        continue

    duplicate_story = any(
        same_story(
            article,
            existing
        )
        for existing in news
    )

    if duplicate_story:
        continue

    news.append(
        article
    )


priority = {

    "🚨 Evenimente / urgențe": 0,

    "🚗 Trafic & transport": 1,

    "🏙️ Oraș & administrație": 2,

    "🏗️ Dezvoltare": 3,

    "💰 Business & economie": 4,

    "🎭 Evenimente & timp liber": 5,

    "⚽ Sport": 6,

    "🔥 Local": 7
}


news.sort(
    key=lambda article:
    priority.get(
        article["category"],
        99
    )
)


now = datetime.now(
    ZoneInfo(
        "Europe/Bucharest"
    )
)


Path(
    "news.json"
).write_text(

    json.dumps(
        {
            "updated":
                now.strftime(
                    "%d.%m.%Y, %H:%M"
                ),

            "count":
                len(news),

            "items":
                news
        },

        ensure_ascii=False,
        indent=2
    ),

    encoding="utf-8"
)


print(
    "Saved",
    len(news),
    "deduplicated Brasov items from",
    len(config["sources"]),
    "sources"
)
