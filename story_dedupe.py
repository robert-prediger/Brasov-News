"""Conservative, source-independent grouping of local news coverage.

No event names or dates are hard-coded. Uses full headlines, URL slugs,
Romanian word forms, article-body evidence and explicit conflict guards.
"""
import hashlib
import html
import re
import unicodedata
from datetime import datetime
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

VERSION = 4
STOP = set('''a ai ale al am an are ar au ca care cat cate ce cei cel cele cu cum
de din dupa e este fost fi in intr intru la le li lor lui mai mi ne nu o pe pentru
prin sa se si sunt spre sau iar un una unei unui va vor vi dintr fara pana peste
sub intre acest aceasta aceste acestui aceea acesta multe multi mult doar deja
azi astazi acum ieri maine nou noua noi noul foarte tot toate toti
brasov brasovul brasovului brasovean brasoveanul brasoveni brasovenii brasovenilor
foto video update exclusiv document vezi lista completa afla detalii eveniment
util fapt divers ore ora minute minut zi zile ani anul lei euro ron romania
roman romani judet judetul judetului oras orasul orasului strada strazile strazi
strad strazi straz str bul bulevardul barbat barbatul femeie femeia persoana
persoane oameni sursa stire stiri spune anunta declarat face fac facut fost
'''.split())

# General vocabulary, rather than rules for individual news events.
FORMS = {}
for root, forms in {
    'abandon': 'abandonat abandonati abandonata abandonate abandonarea aruncat aruncati aruncata aruncate',
    'caine': 'caini cainii cainilor catei cateii catelusi catelusii',
    'amenda': 'amendat amendati amendata amendate amenzi amenzile amenda',
    'atac': 'atacat atacata atacati atacul agresiune agresiunea agresiunii',
    'injunghiere': 'injunghiat injunghiata injunghiati injunghierea',
    'partener': 'sot sotul sotului sotia sotiei soti sotii partenera partenerei concubina',
    'copil': 'copii copiii copiilor copilul copilului',
    'deces': 'murit decedat decedata mort moarta moarte moartea decesul',
    'oprire': 'oprit oprita opriri oprirea intrerupere intreruperi intrerupt intrerupta',
    'autoturism': 'masina masinile masini masinilor autoturisme autoturismul',
    'victorie': 'victorii victoria castigat invins triumfa',
    'infrangere': 'pierdut infrangerea esec invinsa',
    'incendiu': 'incendiul incendiului incendii incendiile',
    'retinere': 'retinut retinuti retinuta arestat arestati arestata arestare',
    'sofer': 'soferi soferii soferilor',
    'permis': 'permise permisele permiselor permisul',
    'suspendat': 'suspendate suspendata suspendati',
    'baut': 'bauti bautii alcoolizat alcoolizati',
}.items():
    FORMS.update({word: root for word in forms.split()})

def normalize(value):
    value = html.unescape(str(value or '')).lower()
    value = ''.join(c for c in unicodedata.normalize('NFKD', value)
                    if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', ' ', value).strip()

def stem(word):
    if word in FORMS:
        return FORMS[word]
    # Definite articles and plural case endings, keeping at least four letters.
    for suffix in ('iilor', 'urilor', 'ului', 'elor', 'ilor', 'iile', 'urile', 'ele', 'ul', 'ii'):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[:-len(suffix)]
    return word

def tokens(value):
    text = normalize(value)
    result = {stem(w) for w in text.split()
              if len(w) >= 3 and not w.isdigit() and w not in STOP}
    if re.search(r'\bfara apa\b', text):
        result.add('oprire')
    return result

def canonical_url(value):
    try:
        p = urlsplit(value or '')
        if p.scheme not in ('http', 'https') or not p.netloc:
            return ''
        query = [(k, v) for k, v in parse_qsl(p.query)
                 if not k.lower().startswith('utm_')
                 and k.lower() not in {'fbclid', 'gclid', 'ref', 'source'}]
        return urlunsplit(('https', p.netloc.lower().removeprefix('www.'),
                           unquote(p.path).rstrip('/'), urlencode(sorted(query)), ''))
    except (ValueError, TypeError):
        return ''

def article_text(item, contextual=False):
    # Longest meaningful path component is the headline slug; excludes dates,
    # article IDs and category names. Query strings never enter similarity.
    try:
        parts = [unquote(p) for p in urlsplit(item.get('url', '')).path.split('/')]
        slug = max((p for p in parts if len(p) >= 20 and '-' in p), key=len, default='')
    except (ValueError, TypeError):
        slug = ''
    text = str(item.get('title', '')) + ' ' + slug
    if contextual:
        text += ' ' + str(item.get('summary', ''))[:1000]
        text += ' ' + ' '.join(item.get('content_terms', []))
    return text

TOWNS = set('sacele ghimbav codlea zarnesti rasnov fagaras cristian sanpetru harman predeal bran rupea feldioara budila prejmer'.split())
SPORTS = set('hochei volei handbal fotbal baschet patinaj rugby tenis'.split())
DAYS = set('luni marti miercuri joi vineri sambata duminica'.split())
GENERIC = tokens('corona csm echipa spital politie pompieri accident incendiu atac deces apa partener copil victorie infrangere primar primaria consiliul judetean bani amenda abandon autoturism')
ACTIONS = tokens('incendiu accident reabilitare modernizare demisie numire candidatura dezbatere abandon adoptie oprire victorie infrangere')

def parsed_time(item):
    try:
        return datetime.fromisoformat(item.get('published', '').replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError):
        return None

def conflicts(a, b):
    ta, tb = parsed_time(a), parsed_time(b)
    if ta is not None and tb is not None and abs(ta - tb) > 36 * 3600:
        return True
    sa, sb = a.get('streets', []), b.get('streets', [])
    if sa and sb and not any(left.endswith(right) or right.endswith(left)
                            for left in sa for right in sb):
        return True
    wa, wb = set(normalize(article_text(a)).split()), set(normalize(article_text(b)).split())
    for vocabulary in (TOWNS, SPORTS, DAYS):
        va, vb = wa & vocabulary, wb & vocabulary
        if va and vb and va.isdisjoint(vb):
            return True
    actions_a, actions_b = tokens(article_text(a)) & ACTIONS, tokens(article_text(b)) & ACTIONS
    if actions_a and actions_b and actions_a.isdisjoint(actions_b):
        return True
    if (wa | wb) & (SPORTS | {'corona'}):
        opponents = lambda words: set(re.findall(
            r'\b(?:cu|contra|impotriva)\s+([a-z]+)', words))
        oa, ob = opponents(normalize(article_text(a))), opponents(normalize(article_text(b)))
        if oa and ob and oa.isdisjoint(ob):
            return True
    # Different numbered roads / bus routes must not collapse on generic words.
    for pattern in (r'\b(?:dn|dj|a)\s*\d+[a-z]?\b',
                    r'\b(?:linia|liniei|autobuzul|autobuzului)\s+(\d+[a-z]?)\b'):
        ra = {re.sub(r'\s+', '', v) for v in re.findall(pattern, normalize(article_text(a)))}
        rb = {re.sub(r'\s+', '', v) for v in re.findall(pattern, normalize(article_text(b)))}
        if ra and rb and ra.isdisjoint(rb):
            return True
    return False

class StoryMatcher:
    def __init__(self, items):
        self.cache = {}

    def words(self, item, contextual=False):
        text = article_text(item, contextual=contextual)
        if text not in self.cache:
            self.cache[text] = tokens(text)
        return self.cache[text]

    def same(self, a, b):
        ua, ub = canonical_url(a.get('url')), canonical_url(b.get('url'))
        if ua and ua == ub:
            return True
        if conflicts(a, b):
            return False
        urls = lambda item: {canonical_url(source.get('url'))
                            for source in [item, *item.get('coverage', [])]}
        references = lambda item: {canonical_url(url) for url in item.get('references', [])}
        cited = (references(a) & urls(b)) | (references(b) & urls(a))
        if cited - {''}:
            context_shared = self.words(a, True) & self.words(b, True)
            if len(context_shared) >= 3 and len(context_shared - GENERIC) >= 2:
                return True
        if normalize(a.get('title')) == normalize(b.get('title')):
            return bool(normalize(a.get('title')))
        wa, wb = self.words(a), self.words(b)
        shared = wa & wb
        # Scores are pairwise and stable: unrelated new articles cannot change
        # whether two existing reports are considered the same story.
        weight = lambda words: sum(.5 if w in GENERIC else 1 for w in words)

        def scores(left, right):
            common = left & right
            if not common:
                return 0, 0, 0
            overlap = weight(common)
            return len(common), overlap / min(weight(left), weight(right)), overlap / weight(left | right)

        count, containment, jaccard = scores(wa, wb)
        if len(shared - GENERIC) >= 2 and (
                (count >= 5 and containment >= .42 and jaccard >= .22)
                or (count >= 4 and containment >= .60 and jaccard >= .22)
                or (count >= 3 and containment >= .78 and jaccard >= .20)):
            return True
        # Page descriptions can confirm heavily rephrased titles, but cannot
        # merge stories on shared site boilerplate without headline evidence.
        if len(shared) >= 2 and a.get('summary') and b.get('summary'):
            ca, cb = self.words(a, True), self.words(b, True)
            count, containment, jaccard = scores(ca, cb)
            if (len((ca & cb) - GENERIC) >= 4 and count >= 6
                    and containment >= .55 and jaccard >= .30):
                return True
        # Actual body evidence can confirm unrelated-looking headlines. Unlike
        # metadata, it must supply numerous specific shared terms; explicit
        # locations, roads, dates and event conflicts are still checked first.
        if a.get('content_terms') or b.get('content_terms'):
            ca, cb = self.words(a, True), self.words(b, True)
            count, containment, jaccard = scores(ca, cb)
            if len((ca & cb) - GENERIC) >= 5:
                return ((count >= 8 and containment >= .66 and jaccard >= .16)
                        or (count >= 12 and containment >= .50 and jaccard >= .18))
        return False

def deduplicate(items):
    """Keep latest article per story and retain every publication as coverage.

    Match against previously grouped variants too. A later, fuller report can
    bridge two groups, provided no members have explicit event conflicts.
    """
    ordered = sorted((dict(x) for x in items if x.get('title')),
                     key=lambda x: parsed_time(x) or 0, reverse=True)
    matcher = StoryMatcher(ordered)
    groups = []
    for item in ordered:
        matches = []
        for index, group in enumerate(groups):
            if (not any(conflicts(item, member) for member in group)
                    and any(matcher.same(item, member) for member in group)):
                matches.append(index)
        if not matches:
            groups.append([item])
            continue
        target = groups[matches[0]]
        target.append(item)
        for index in reversed(matches[1:]):
            other = groups[index]
            if not any(conflicts(left, right) for left in target for right in other):
                target.extend(other)
                groups.pop(index)
    result = []
    for group in groups:
        representative = dict(group[0])
        coverage, seen = [], set()
        for item in group:
            for source in [item, *item.get('coverage', [])]:
                url = canonical_url(source.get('url'))
                if url and url not in seen:
                    seen.add(url)
                    coverage.append({k: source[k] for k in ('title', 'url', 'source') if k in source})
        representative['coverage'] = coverage
        representative['story_id'] = hashlib.sha256(
            (canonical_url(representative.get('url')) or representative['title']).encode()
        ).hexdigest()[:16]
        result.append(representative)
    return result

