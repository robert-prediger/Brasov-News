import re, json, html, urllib.request, urllib.parse
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from difflib import SequenceMatcher

UA = {
    "User-Agent": "Mozilla/5.0 (compatible; BrasovNewsDailyBrief/3.0)"
}

LOCAL = (
    "brașov", "brasov", "poiana brașov", "poiana brasov",
    "râșnov", "rasnov", "săcele", "sacele", "ghimbav",
    "codlea", "zărnești", "zarnesti", "făgăraș", "fagaras",
    "cristian", "sânpetru", "sanpetru", "hărman", "harman",
    "predeal", "bran", "rupea", "victoria", "feldioara",
    "bod", "budila", "cincu", "prejmer"
)

BAD = (
    "cookie", "privacy", "contact", "publicitate", "termeni",
    "facebook", "instagram", "youtube", "whatsapp",
    "abonare", "newsletter"
)


def fetch(u):
    r = urllib.request.urlopen(
        urllib.request.Request(u, headers=UA),
        timeout=25
    )
    return r.read().decode("utf-8", "ignore")


def clean(s):
    return re.sub(
        r"\s+",
        " ",
        html.unescape(re.sub(r"<[^>]+>", " ", s))
    ).strip()


def norm(s):
    return re.sub(r"\W+", " ", s.lower()).strip()


def cat(t):
    x = t.lower()

    # Ordinea contează: categoriile foarte specifice sunt verificate primele.
    groups = [
        (
            "🚗 Trafic & transport",
            (
                "trafic", "rutier", "dn1", "dn 1", "drum",
                "autostrad", "parcare", "ratbv", "tren",
                "gara", "circula", "transport", "autobuz",
                "troleibuz", "restricții", "restrictii"
            )
        ),
        (
            "🚨 Evenimente / urgențe",
            (
                "isu", "pompier", "poliți", "politi",
                "accident", "salvamont", "incend", "smurd",
                "112", "urgență", "urgenta", "intervenție",
                "interventie", "dispărut", "disparut",
                "perchezi", "reținut", "retinut"
            )
        ),
        (
            "⚽ Sport",
            (
                "sport", "fotbal", "corona brașov",
                "corona brasov", "hochei", "meci",
                "campionat", "liga", "handbal",
                "baschet", "volei", "schi", "atlet",
                "turneu", "cupă", "cupa"
            )
        ),
        (
            "🎭 Evenimente & timp liber",
            (
                "concert", "festival", "teatru", "operă",
                "opera", "târg", "targ", "expozi",
                "spectacol", "cinema", "muzeu",
                "eveniment", "weekend"
            )
        ),
        (
            "💰 Business & economie",
            (
                "business", "afaceri", "companie",
                "fabric", "investi", "milioane",
                "euro", "antreprenor", "economie",
                "angaj", "salari", "magazin",
                "hotel", "restaurant"
            )
        ),
        (
            "🏗️ Dezvoltare",
            (
                "construc", "proiect", "șantier",
                "santier", "moderniz", "amenaj",
                "reabilit", "renov", "lucrări",
                "lucrari", "infrastructur"
            )
        ),
        (
            "🏙️ Oraș & administrație",
            (
                "primăria", "primaria", "consili",
                "spital", "școal", "scoal",
                "administra", "municip", "prefect",
                "consiliul local", "consiliul județean",
                "consiliul judetean", "primar"
            )
        )
    ]

    for name, keys in groups:
        if any(k in x for k in keys):
            return name

    return "🔥 Local"


cfg = json.loads(
    Path("sources.json").read_text(encoding="utf-8")
)

all_items = []

for s in cfg["sources"]:
    try:
        page = fetch(s["url"])

        host = urllib.parse.urlparse(
            s["url"]
        ).netloc.replace("www.", "")

        for m in re.finditer(
            r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            page,
            re.I | re.S
        ):
            u = urllib.parse.urljoin(
                s["url"],
                html.unescape(m.group(1))
            )

            title = clean(m.group(2))
            low = title.lower()

            if len(title) < 28 or len(title) > 240:
                continue

            if any(b in low for b in BAD):
                continue

            article_host = urllib.parse.urlparse(
                u
            ).netloc.replace("www.", "")

            if host not in article_host:
                continue

            if not any(k in low for k in LOCAL):
                continue

            all_items.append({
                "title": title,
                "url": u,
                "source": s["name"],
                "category": cat(title)
            })

    except Exception as e:
        print("SOURCE ERROR:", s["name"], e)


# Elimină URL-urile identice și titlurile aproape identice,
# dar păstrează articole locale diferite despre același subiect.
out = []

for a in all_items:
    n = norm(a["title"])

    if any(a["url"] == b["url"] for b in out):
        continue

    if any(
        SequenceMatcher(
            None,
            n,
            norm(b["title"])
        ).ratio() > 0.88
        for b in out
    ):
        continue

    out.append(a)


# Categoriile importante apar primele în news.json.
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

out.sort(
    key=lambda a: priority.get(a["category"], 99)
)


now = datetime.now(
    ZoneInfo("Europe/Bucharest")
)

Path("news.json").write_text(
    json.dumps(
        {
            "updated": now.strftime("%d.%m.%Y, %H:%M"),
            "count": len(out),
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
    "Brașov items from",
    len(cfg["sources"]),
    "sources"
)
