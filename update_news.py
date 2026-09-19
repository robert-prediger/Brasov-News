import re,json,html,urllib.request,urllib.parse
from pathlib import Path
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from difflib import SequenceMatcher

UA={"User-Agent":"Mozilla/5.0 (compatible; BrasovNewsDailyBrief/2.0)"}
LOCAL=("brașov","brasov","poiana","râșnov","rasnov","săcele","sacele","ghimbav","codlea","zărnești","zarnesti","făgăraș","fagaras","cristian","sânpetru","sanpetru","hărman","harman","predeal","bran","rupea","victoria","feldioara","bod","budila","cincu","prejmer")
BAD=("cookie","privacy","contact","publicitate","termeni","facebook","instagram","youtube","whatsapp","abonare","newsletter")

def fetch(u):
 r=urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=25)
 return r.read().decode("utf-8","ignore")

def clean(s): return re.sub(r"\s+"," ",html.unescape(re.sub(r"<[^>]+>"," ",s))).strip()
def norm(s): return re.sub(r"\W+"," ",s.lower()).strip()
def cat(t):
 x=t.lower()
 groups=[
 ("🚗 Trafic & transport",("trafic","rutier","drum","autostrad","parcare","ratbv","tren","gara","circula")),
 ("🚨 Evenimente / urgențe",("isu","pompier","poliți","accident","salvamont","urs","incend","smurd","112")),
 ("⚽ Sport",("sport","fotbal","corona","hochei","meci","campionat","liga")),
 ("🎭 Evenimente & timp liber",("concert","festival","teatru","operă","opera","târg","targ","expozi")),
 ("💰 Business & economie",("business","afaceri","companie","fabric","investi","milioane","euro","lei")),
 ("🏗️ Dezvoltare",("construc","proiect","șantier","santier","moderniz","amenaj")),
 ("🏙️ Oraș & administrație",("primăria","primaria","consili","spital","școal","scoal","administra"))
 ]
 for name,keys in groups:
  if any(k in x for k in keys): return name
 return "🔥 Local"

cfg=json.loads(Path("sources.json").read_text(encoding="utf-8"))
all_items=[]
for s in cfg["sources"]:
 try:
  page=fetch(s["url"]); host=urllib.parse.urlparse(s["url"]).netloc.replace("www.","")
  for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',page,re.I|re.S):
   u=urllib.parse.urljoin(s["url"],html.unescape(m.group(1))); title=clean(m.group(2)); low=title.lower()
   if len(title)<28 or len(title)>240 or any(b in low for b in BAD): continue
   if host not in urllib.parse.urlparse(u).netloc.replace("www.",""): continue
   if not any(k in low for k in LOCAL): continue
   all_items.append({"title":title,"url":u,"source":s["name"],"category":cat(title)})
 except Exception as e: print("SOURCE ERROR:",s["name"],e)

# Deduplicate only near-identical coverage; preserve distinct local stories.
out=[]
for a in all_items:
 n=norm(a["title"])
 if any(a["url"]==b["url"] for b in out): continue
 if any(SequenceMatcher(None,n,norm(b["title"])).ratio()>.88 for b in out): continue
 out.append(a)

now=datetime.now(ZoneInfo("Europe/Bucharest"))
Path("news.json").write_text(json.dumps({"updated":now.strftime("%d.%m.%Y, %H:%M"),"count":len(out),"items":out},ensure_ascii=False,indent=2),encoding="utf-8")
print("Saved",len(out),"Brașov items from",len(cfg["sources"]),"sources")
