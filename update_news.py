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

UA = {"User-Agent": "Mozilla/5.0 (compatible; BrasovNewsDailyBrief/7.0)"}
TZ = ZoneInfo("Europe/Bucharest")
NOW = datetime.now(TZ)
MAX_AGE_HOURS = 36
MAX_WORKERS = 12

LOCAL = ("brasov","poiana brasov","rasnov","sacele","ghimbav","codlea","zarnesti",
         "fagaras","cristian","sanpetru","harman","predeal","bran","rupea","victoria",
         "feldioara","bod","budila","cincu","prejmer")
BAD = ("cookie","privacy","contact","publicitate","termeni","facebook","instagram",
       "youtube","whatsapp","abonare","newsletter","despre noi",
       "politica de confidentialitate","copyright","toate drepturile rezervate",
       "ziarul metropolitan brasov")
STOPWORDS = {"a","ai","ale","al","am","an","are","au","ca","care","cat","ce","cei","cel",
             "cele","cu","cum","de","din","dupa","este","fost","in","la","mai","o","pe",
             "pentru","prin","sa","se","si","sunt","un","una","unei","unui","dintr",
             "intr","spre","sau","iar","brasov","brasovean","brasoveni","brasovului",
             "video","foto","astazi","acum"}
NUMBER_WORDS = {"un":"1","unu":"1","una":"1","doi":"2","doua":"2","trei":"3","patru":"4",
                "cinci":"5","sase":"6","sapte":"7","opt":"8","noua":"9","zece":"10"}
STEMS = {
    "sechestrat":"sechestr","sechestrata":"sechestr","sechestrati":"sechestr",
    "sechestrare":"sechestr","retinut":"retin","retinuta":"retin","retinuti":"retin",
    "retinere":"retin","arestat":"retin","arestata":"retin","arestati":"retin",
    "arestare":"retin","copilul":"copil","copilului":"copil","copii":"copil",
    "copiii":"copil","tatal":"tata","tatalui":"tata","parcari":"parcare",
    "parcarilor":"parcare","soferi":"sofer","soferilor":"sofer",
    "sanctionat":"sanctiune","sanctionati":"sanctiune","sanctiuni":"sanctiune",
    "reabilitata":"reabilitare","reabilitat":"reabilitare",
    "modernizata":"modernizare","modernizat":"modernizare"
}

def safe_url(url):
    p=urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((p.scheme,p.netloc.encode("idna").decode("ascii"),
        urllib.parse.quote(urllib.parse.unquote(p.path),safe="/%:@"),
        urllib.parse.quote(urllib.parse.unquote(p.query),safe="=&?/:;%+"),
        urllib.parse.quote(urllib.parse.unquote(p.fragment),safe="")))

def fetch(url,timeout=10):
    req=urllib.request.Request(safe_url(url),headers=UA)
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return r.read().decode("utf-8","ignore")

def strip_accents(text):
    return "".join(c for c in unicodedata.normalize("NFKD",text)
                   if not unicodedata.combining(c))

def simple(text):
    text=strip_accents(html.unescape(text)).lower()
    text=re.sub(r"https?://\S+"," ",text)
    text=re.sub(r"[^a-z0-9 ]+"," ",text)
    return re.sub(r"\s+"," ",text).strip()

def clean(text):
    return re.sub(r"\s+"," ",html.unescape(re.sub(r"<[^>]+>"," ",text))).strip()

def canonical_url(url):
    p=urllib.parse.urlsplit(url)
    q=[(k,v) for k,v in urllib.parse.parse_qsl(p.query,keep_blank_values=False)
       if not k.lower().startswith("utm_") and k.lower() not in {"fbclid","gclid","ref","source"}]
    return urllib.parse.urlunsplit((p.scheme.lower(),p.netloc.lower().replace("www.",""),
        re.sub(r"/+$","",p.path),urllib.parse.urlencode(q),""))

def words(title):
    return {w for w in simple(title).split() if len(w)>=4 and w not in STOPWORDS}

def numbers(title):
    s=simple(title)
    result=set(re.findall(r"\b\d+\b",s))
    for token in s.split():
        if token in NUMBER_WORDS:
            result.add(NUMBER_WORDS[token])
    return result

def event_fingerprint(title):
    result={STEMS.get(w,w) for w in words(title)}
    result.update("#"+n for n in numbers(title))
    return result

def title_is_valid(title):
    s=simple(title)
    if len(title)<28 or len(title)>240 or len(words(title))<3 or any(b in s for b in BAD):
        return False
    return s not in {"zmbv ro ziarul metropolitan brasov","ziarul metropolitan brasov",
                     "brasov net","biz brasov","transilvania365","stiri brasov"}

def category(title):
    x=simple(title)
    groups=[
      ("🚨 Evenimente / urgențe",("accident","incend","pompier","smurd","salvamont","urgenta",
       "interventie","disparut","perchezit","retinut","arest","politia","politisti","crima")),
      ("⚽ Sport",("fotbal","hochei","handbal","baschet","volei","schi","atlet","campionat",
       "liga","meci","turneu","cupa","corona brasov","fc brasov")),
      ("🎭 Evenimente & timp liber",("concert","festival","teatru","opera","targ","expozit",
       "spectacol","cinema","muzeu","eveniment cultural")),
      ("🏙️ Oraș & administrație",("primaria","consiliul local","consiliul judetean","prefectura",
       "municipiul","primar","spital","scoala","administratie")),
      ("🏗️ Dezvoltare",("construct","santier","moderniz","amenaj","reabilit","renov",
       "infrastructur","lucrari")),
      ("💰 Business & economie",("business","afaceri","companie","fabrica","investitie",
       "investitii","antreprenor","economie","angajari","salarii","magazin","hotel","restaurant"))]
    for name,keys in groups:
        if any(k in x for k in keys): return name
    traffic=("trafic rutier","circulatie","dn1","dn 1","autostrada","parcare","ratbv","autobuz",
             "troleibuz","transport public","gara","restrictii de circulatie","drum inchis","drum blocat")
    if "trafic de influenta" not in x and any(k in x for k in traffic):
        return "🚗 Trafic & transport"
    return "🔥 Local"

def parse_date(value):
    if not value: return None
    value=html.unescape(value).strip()
    try:
        d=datetime.fromisoformat(value.replace("Z","+00:00"))
        return d.replace(tzinfo=TZ) if d.tzinfo is None else d.astimezone(TZ)
    except Exception: pass
    m=re.search(r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})(?:[ T,]+(\d{1,2}):(\d{2}))?",value)
    if m:
        try:
            return datetime(int(m.group(3)),int(m.group(2)),int(m.group(1)),
                            int(m.group(4) or 12),int(m.group(5) or 0),tzinfo=TZ)
        except Exception: pass
    return None

def extract_date(page):
    patterns=(
      r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
      r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']article:published_time["\']',
      r'"datePublished"\s*:\s*"([^"]+)"',
      r'<meta[^>]+itemprop=["\']datePublished["\'][^>]+content=["\']([^"\']+)["\']',
      r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+itemprop=["\']datePublished["\']',
      r'<meta[^>]+name=["\'](?:date|pubdate|publish-date|publication_date)["\'][^>]+content=["\']([^"\']+)["\']',
      r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\'](?:date|pubdate|publish-date|publication_date)["\']')
    dates=[]
    for pattern in patterns:
        for m in re.finditer(pattern,page,re.I):
            d=parse_date(m.group(1))
            if d and d<=NOW+timedelta(hours=3) and d>=NOW-timedelta(days=3650):
                dates.append(d)
    return dates[0] if dates else None

def recent(date):
    return date is not None and timedelta(hours=-3)<=NOW-date<=timedelta(hours=MAX_AGE_HOURS)

def similarity_values(a,b):
    sa,sb=simple(a),simple(b)
    seq=SequenceMatcher(None,sa,sb).ratio()
    wa,wb=words(a),words(b)
    if not wa or not wb: return seq,0,0,0
    common=wa&wb
    return seq,len(common)/min(len(wa),len(wb)),len(common)/len(wa|wb),len(common)

def same_story(a,b):
    if canonical_url(a["url"])==canonical_url(b["url"]): return True
    seq,containment,jaccard,common_count=similarity_values(a["title"],b["title"])
    fa,fb=event_fingerprint(a["title"]),event_fingerprint(b["title"])
    common_fp=fa&fb
    fp_containment=len(common_fp)/min(len(fa),len(fb)) if fa and fb else 0
    fp_jaccard=len(common_fp)/len(fa|fb) if fa and fb else 0
    same_numbers=bool(numbers(a["title"]) & numbers(b["title"]))
    if seq>=0.72: return True
    if containment>=0.68 and common_count>=4: return True
    if jaccard>=0.44 and common_count>=4: return True
    if same_numbers and common_count>=3 and containment>=0.42: return True
    if len(common_fp)>=4 and fp_containment>=0.58: return True
    if same_numbers and len(common_fp)>=3 and fp_containment>=0.38: return True
    if len(common_fp)>=5 and fp_jaccard>=0.32: return True
    return False

def collect_links(source):
    found=[]
    try:
        home=fetch(source["url"],10)
        source_host=urllib.parse.urlparse(source["url"]).netloc.lower().replace("www.","")
        seen=set()
        for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',home,re.I|re.S):
            url=urllib.parse.urljoin(source["url"],html.unescape(m.group(1)))
            title=clean(m.group(2))
            if not title_is_valid(title): continue
            if urllib.parse.urlparse(url).netloc.lower().replace("www.","")!=source_host: continue
            if not any(place in simple(title) for place in LOCAL): continue
            cu=canonical_url(url)
            if cu in seen: continue
            seen.add(cu)
            found.append({"title":title,"url":url,"source":source["name"]})
    except Exception as e: print("SOURCE ERROR:",source["name"],e)
    return found

def check_article(article):
    try:
        page=fetch(article["url"],10)
        published=extract_date(page)
        if not recent(published): return None
        return {"title":article["title"],"url":article["url"],"source":article["source"],
                "category":category(article["title"]),"published":published.isoformat()}
    except Exception as e:
        print("ARTICLE ERROR:",article["source"],article["url"],e)
        return None

cfg=json.loads(Path("sources.json").read_text(encoding="utf-8"))
links=[]
for source in cfg["sources"]: links.extend(collect_links(source))

unique_links=[]
seen_urls=set()
for article in links:
    cu=canonical_url(article["url"])
    if cu not in seen_urls:
        seen_urls.add(cu); unique_links.append(article)

print("Checking",len(unique_links),"candidate article pages in parallel...")
candidates=[]
with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    future_map={executor.submit(check_article,a):a for a in unique_links}
    for future in as_completed(future_map):
        try:
            result=future.result()
            if result is not None: candidates.append(result)
        except Exception as e:
            a=future_map[future]; print("WORKER ERROR:",a["source"],a["url"],e)

candidates.sort(key=lambda x:x["published"],reverse=True)
out=[]
for article in candidates:
    duplicate=False
    for existing in out:
        if same_story(article,existing):
            duplicate=True
            print("DUPLICATE:",article["source"],article["title"],"==",existing["source"],existing["title"])
            break
    if not duplicate: out.append(article)

Path("news.json").write_text(json.dumps({
    "updated":NOW.strftime("%d.%m.%Y, %H:%M"),
    "count":len(out),"raw_count":len(candidates),"items":out
},ensure_ascii=False,indent=2),encoding="utf-8")

print("Saved",len(out),"unique recent Brasov stories from",len(candidates),
      "verified recent candidates and",len(cfg["sources"]),"sources")
