#!/usr/bin/env python3
"""Phireworx publish step (runs on Netlify before every deploy).

Writes the content people edit in /admin straight into the HTML so search
engines and AI crawlers see it without running any JavaScript:
  - data-cms* bindings (homepage text/stats, prices, photos) from /data
  - reviews (homepage + Reviews page), including any added in /admin
  - structured data (JSON-LD) for Google and AI assistants
  - sitemap.xml and llms.txt

Standard library only. Each step is wrapped so one bad value never blocks
a deploy; the page just keeps the content already in its HTML.
"""
import datetime
import glob
import html
import json
import os
import re
import struct
import subprocess
import sys
import traceback
from urllib.parse import quote, unquote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
SITE = 'https://phireworxphoto.com'
WARN = []


def warn(msg):
    WARN.append(msg)
    print('WARNING:', msg)


def load(path, default=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:  # noqa
        warn(f'could not read {path}: {e}')
        return default


def get(obj, path):
    for k in path.split('.'):
        if obj is None:
            return None
        m = re.match(r'^(\w+)\[(\d+)\]$', k)
        if m:
            lst = obj.get(m.group(1)) if isinstance(obj, dict) else None
            i = int(m.group(2))
            obj = lst[i] if isinstance(lst, list) and i < len(lst) else None
        else:
            obj = obj.get(k) if isinstance(obj, dict) else None
    return obj


def esc(s):
    return html.escape(str(s), quote=False)


def attr_esc(s):
    return html.escape(str(s), quote=True)


# ── image size (JPEG / PNG / WebP) for photo aspect ratios ──────────────
def image_size(path):
    try:
        with open(path, 'rb') as f:
            head = f.read(32)
            if head[:8] == b'\x89PNG\r\n\x1a\n':
                return struct.unpack('>II', head[16:24])
            if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
                chunk = head[12:16]
                f.seek(0)
                data = f.read(40)
                if chunk == b'VP8X':
                    w = 1 + int.from_bytes(data[24:27], 'little')
                    h = 1 + int.from_bytes(data[27:30], 'little')
                    return w, h
                if chunk == b'VP8 ':
                    w, h = struct.unpack('<HH', data[26:30])
                    return w & 0x3fff, h & 0x3fff
                if chunk == b'VP8L':
                    b = data[21:25]
                    w = 1 + (((b[1] & 0x3F) << 8) | b[0])
                    h = 1 + (((b[3] & 0xF) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
                    return w, h
                return None
            if head[:2] == b'\xff\xd8':
                f.seek(2)
                while True:
                    b = f.read(1)
                    while b and b != b'\xff':
                        b = f.read(1)
                    while b == b'\xff':
                        b = f.read(1)
                    if not b:
                        return None
                    marker = b[0]
                    if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                        continue
                    seg_len = struct.unpack('>H', f.read(2))[0]
                    if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                        f.read(1)
                        h, w = struct.unpack('>HH', f.read(4))
                        return w, h
                    f.seek(seg_len - 2, 1)
    except Exception:
        return None
    return None


def cdn(path, width=1800):
    p = '/' + path.lstrip('/')
    return '/.netlify/images?url=' + quote(p, safe='') + f'&w={width}&q=82'


def src_path(src):
    """Plain /assets/... path for a src that may be a Netlify CDN URL."""
    m = re.search(r'[?&]url=([^&]+)', src or '')
    p = unquote(m.group(1)) if m else (src or '')
    return '/' + p.lstrip('/')


# ── HTML helpers ─────────────────────────────────────────────────────────
OPEN_TAG = re.compile(r'<([a-zA-Z][a-zA-Z0-9]*)(\s[^<>]*?)?(/?)>')
BIND = re.compile(r'\sdata-cms(-num|-list|-img|-tpl)?="([^"]*)"')


def find_close(doc, name, pos):
    """Index of the matching </name> for an element whose open tag ends at pos."""
    depth = 1
    for m in re.finditer(r'<(/?)' + name + r'\b[^>]*?(/?)>', doc[pos:], re.I):
        if m.group(1):
            depth -= 1
            if depth == 0:
                return pos + m.start(), pos + m.end()
        elif not m.group(2):
            depth += 1
    return None


def set_attr(tag, name, value):
    if value is None:
        return re.sub(r'\s' + name + r'="[^"]*"', '', tag)
    if re.search(r'\s' + name + r'="[^"]*"', tag):
        return re.sub(r'(\s' + name + r'=")[^"]*(")', lambda m: m.group(1) + attr_esc(value) + m.group(2), tag, count=1)
    return tag[:-1] + f' {name}="{attr_esc(value)}">' if not tag.endswith('/>') else tag[:-2] + f' {name}="{attr_esc(value)}"/>'


def apply_bindings(doc, data_files):
    ops = []
    for m in OPEN_TAG.finditer(doc):
        attrs = m.group(2) or ''
        if 'data-cms' not in attrs:
            continue
        for b in BIND.finditer(attrs):
            ops.append((m.start(), m.group(1).lower(), b.group(1) or '', b.group(2)))
    changed = 0
    for start, name, kind, spec in sorted(ops, key=lambda o: -o[0]):
        try:
            if kind == '-tpl':
                file, tpl = spec.split('|', 1)
            else:
                file, path = spec.split(':', 1)
            data = data_files.get(file)
            if data is None:
                continue
            tm = OPEN_TAG.match(doc, start)
            tag, tag_end = tm.group(0), tm.end()
            if kind == '-img':
                slot = get(data, path)
                img = slot.get('image') if isinstance(slot, dict) else slot
                alt = slot.get('alt') if isinstance(slot, dict) else None
                new = tag
                cur_alt = re.search(r'\salt="([^"]*)"', tag)
                if alt and (not cur_alt or html.unescape(cur_alt.group(1)) != alt):
                    new = set_attr(new, 'alt', alt)
                if img and src_path(img) != src_path(re.search(r'\ssrc="([^"]*)"', tag).group(1)):
                    w = (re.search(r'data-cms-w="(\d+)"', tag) or [None, '1800'])[1]
                    new = set_attr(new, 'src', cdn(img, w))
                    size = image_size(os.path.join(ROOT, src_path(img).lstrip('/')))
                    if size and size[1]:
                        new = set_attr(new, 'width', str(size[0]))
                        new = set_attr(new, 'height', str(size[1]))
                        ar = f'{size[0] / size[1]:.4f}'
                        if '--ar:' in new:
                            new = re.sub(r'--ar:\s*[0-9.]+', '--ar:' + ar, new)
                    else:
                        new = set_attr(set_attr(new, 'width', None), 'height', None)
                if new != tag:
                    doc = doc[:start] + new + doc[tag_end:]
                    changed += 1
                continue
            close = find_close(doc, name, tag_end)
            if not close:
                continue
            inner = doc[tag_end:close[0]]
            if kind == '':
                v = get(data, path)
                if isinstance(v, (int, float)):
                    v = str(v)
                if isinstance(v, str) and v.strip() and '<' not in inner and html.unescape(inner) != v:
                    doc = doc[:tag_end] + esc(v) + doc[close[0]:]
                    changed += 1
            elif kind == '-num':
                v = get(data, path)
                if v is not None and str(v).strip():
                    v = str(v).strip()
                    m2 = re.match(r'(\s*)([^<]*?)(\s*)(<|$)', inner)
                    if m2 and m2.group(2) != v:
                        new_inner = m2.group(1) + esc(v) + m2.group(3) + inner[m2.end(3):]
                        doc = doc[:tag_end] + new_inner + doc[close[0]:]
                        changed += 1
            elif kind == '-tpl':
                missing = []

                def fill(mm):
                    x = get(data, mm.group(1))
                    if x is None or x == '':
                        missing.append(mm.group(1))
                        return mm.group(0)
                    return str(x)
                out = re.sub(r'\$\{([^}]+)\}', fill, html.unescape(tpl))
                if not missing and '<' not in inner and html.unescape(inner) != out:
                    doc = doc[:tag_end] + esc(out) + doc[close[0]:]
                    changed += 1
            elif kind == '-list':
                items = get(data, path)
                if isinstance(items, list) and items:
                    lines = [i if isinstance(i, str) else (i or {}).get('item', '') for i in items]
                    indent = re.search(r'\n(\s*)<li', inner)
                    ind = indent.group(1) if indent else ''
                    closing_ind = re.search(r'\n(\s*)$', inner)
                    new_inner = ''.join(f'\n{ind}<li>{esc(x)}</li>' for x in lines) + ('\n' + closing_ind.group(1) if closing_ind else '')
                    if new_inner != inner:
                        doc = doc[:tag_end] + new_inner + doc[close[0]:]
                        changed += 1
        except Exception as e:  # keep going; this element keeps its HTML content
            warn(f'binding {spec!r}: {e}')
    return doc, changed


# ── reviews ─────────────────────────────────────────────────────────────
def reviews_in_order(doc):
    files = {os.path.splitext(os.path.basename(p))[0] for p in glob.glob('data/reviews/*.json')}
    m = re.search(r'reviewFiles\s*=\s*\[([^\]]*)\]', doc)
    listed = re.findall(r"'([^']+)'", m.group(1)) if m else []
    order = [f for f in listed if f in files] + sorted(files - set(listed))
    revs = []
    for name in order:
        r = load(f'data/reviews/{name}.json')
        if isinstance(r, dict):
            r['_file'] = name
            revs.append(r)
    return order, revs


def set_review_list(doc, order):
    arr = ',\n    '.join(', '.join(f"'{x}'" for x in order[i:i + 4]) for i in range(0, len(order), 4))
    return re.sub(r'(reviewFiles\s*=\s*\[)[^\]]*(\])', lambda m: m.group(1) + '\n    ' + arr + '\n  ' + m.group(2), doc, count=1)


def replace_inner_by_id(doc, el_id, new_inner):
    m = re.search(r'<([a-zA-Z0-9]+)\b[^>]*\sid="' + re.escape(el_id) + r'"[^>]*>', doc)
    if not m:
        return doc, False
    close = find_close(doc, m.group(1), m.end())
    if not close:
        return doc, False
    return doc[:m.end()] + new_inner + doc[close[0]:], True


def home_reviews_html(revs):
    picks = [r for r in revs if r.get('homepage')]
    if not picks:
        return None
    lead_i = next((i for i, r in enumerate(picks) if re.search('coach', r.get('role', ''), re.I)), 0)
    lead = picks.pop(lead_i)
    role = lambda r: esc(r.get('role', '')).replace(' · ', ', ')
    out = ('\n      <figure class="hp-feature">'
           f'<blockquote>“{esc(lead.get("quote", ""))}”</blockquote>'
           f'<figcaption><span class="hp-tab">{esc(lead.get("name", ""))}</span><span>{role(lead)}</span></figcaption>'
           '</figure>')
    if picks:
        cards = ''
        for r in picks:
            n = int(r.get('stars') or 5)
            cards += ('<figure class="hp-review">'
                      f'<div class="testimonial-stars" role="img" aria-label="{n} out of 5 stars">' + '<div class="star"></div>' * n + '</div>'
                      f'<blockquote>“{esc(r.get("quote", ""))}”</blockquote>'
                      f'<figcaption><strong>{esc(r.get("name", ""))}</strong>{role(r)}</figcaption></figure>')
        out += '<div class="hp-reviews-grid">' + cards + '</div>'
    return out + '\n    '


def reviews_page_html(revs):
    active = [r for r in revs if r.get('reviews_page', True) is not False]
    if not active:
        return None
    out = ''
    for r in active:
        n = int(r.get('stars') or 5)
        out += f'''
      <div class="review-card">
        <div class="review-stars">{'<div class="star"></div>' * n}</div>
        <p class="review-text">"{esc(r.get('quote', ''))}"</p>
        <div class="review-author">
          <div class="review-name">{esc(r.get('name', ''))}</div>
          <div class="review-role">{esc(r.get('role', ''))}</div>
          <div class="review-source">Google Review</div>
        </div>
      </div>'''
    return out + '\n        '


# ── structured data ─────────────────────────────────────────────────────
CITIES = ['Phoenix', 'Scottsdale', 'Chandler', 'Mesa', 'Gilbert', 'Peoria', 'Goodyear', 'Avondale', 'Surprise',
          'Buckeye', 'Litchfield Park', 'Tolleson', 'Laveen', 'Ahwatukee', 'Fountain Hills', 'Paradise Valley',
          'El Mirage', 'Waddell', 'Maricopa']
BIZ_ID = SITE + '/#business'


def money(v):
    try:
        return str(float(str(v).replace(',', ''))).rstrip('0').rstrip('.')
    except Exception:
        return None


def offer(name, price, desc=None, unit=None, url=None):
    p = money(price)
    if p is None:
        return None
    o = {'@type': 'Offer', 'name': name, 'price': p, 'priceCurrency': 'USD'}
    if unit:
        o['priceSpecification'] = {'@type': 'UnitPriceSpecification', 'price': p, 'priceCurrency': 'USD', 'unitText': unit}
    if desc:
        o['description'] = desc
    if url:
        o['url'] = url
    return o


def services(prices):
    b = prices.get('banners', {}) or {}
    md = prices.get('media_day', {}) or {}
    pd = prices.get('picture_day', {}) or {}
    sizes = [('Individual / senior banner', 'individual', [('2x3', '2×3 ft'), ('25x4', '2.5×4 ft'), ('3x5', '3×5 ft'), ('4x6', '4×6 ft')]),
             ('Traditional team banner', 'team', [('5x3', '5×3 ft'), ('6x4', '6×4 ft'), ('7x5', '7×5 ft'), ('10x6', '10×6 ft')]),
             ('Composite team banner', 'composite', [('5x3', '5×3 ft'), ('6x4', '6×4 ft'), ('7x5', '7×5 ft'), ('10x6', '10×6 ft')])]
    banner_offers = [offer(f'{label}, {sz}', b.get(f'{key}_{k}'), url=SITE + '/banners') for label, key, ss in sizes for k, sz in ss]
    area = [{'@type': 'City', 'name': c + ', AZ'} for c in CITIES]
    picture = {
        '@type': 'Service', '@id': SITE + '/pictureday#service', 'name': 'Team & Individual Picture Day',
        'serviceType': 'Sports team and individual photography',
        'description': 'Organized team and individual picture days for high school and youth sports programs, on location or as composites, with online ordering for every family. No cost to the program; families order online.',
        'provider': {'@id': BIZ_ID}, 'areaServed': area, 'url': SITE + '/pictureday',
        'offers': [o for o in [
            offer('Picture day for the program', 0, 'No cost to the organization. Families order prints and digitals online.'),
            offer('Small-program session fee', pd.get('small_program_fee'),
                  f"May apply to high school programs under {pd.get('hs_min_athletes', '')} athletes or youth organizations under {pd.get('youth_min_athletes', '')} athletes."),
        ] if o]}
    banners = {
        '@type': 'Service', '@id': SITE + '/banners#service', 'name': 'Pro Banners',
        'serviceType': 'Custom vinyl senior and team sports banners',
        'description': 'Individual senior banners, traditional team banners, and composite team banners on weatherproof vinyl, with professional photography and design. 3–7 business day turnaround.',
        'provider': {'@id': BIZ_ID}, 'areaServed': area, 'url': SITE + '/banners',
        'offers': [o for o in banner_offers if o]}
    media = {
        '@type': 'Service', '@id': SITE + '/media#service', 'name': 'Phireworx Media Day Experience',
        'serviceType': 'Team media day photography',
        'description': f"A prepaid, creative-first team media shoot with advanced lighting and every edited digital delivered to the program. ${md.get('minimum', '')} minimum booking.",
        'provider': {'@id': BIZ_ID}, 'areaServed': area, 'url': SITE + '/media',
        'offers': [o for o in [
            offer('Media Day, 20+ athletes', md.get('tier_20_plus'), unit='per athlete'),
            offer('Media Day, 10–19 athletes', md.get('tier_10_19'), unit='per athlete'),
            offer('Media Day, 5–9 athletes', md.get('tier_5_9'), unit='per athlete'),
        ] if o]}
    return picture, banners, media


def business(prices, full=True):
    biz = {
        '@type': 'ProfessionalService', '@id': BIZ_ID,
        'name': 'Phireworx Photography', 'alternateName': 'Phireworx', 'url': SITE + '/',
        'logo': SITE + '/assets/images/logo-full.png',
        'image': [SITE + '/assets/images/og-default.jpg', SITE + '/assets/images/hero-composite-saguaro.jpg'],
        'description': 'Phoenix-based sports photography company serving Arizona high school programs and youth leagues since 2012: team and individual picture days, Pro Banners, and the Phireworx Media Day Experience.',
        'slogan': 'Where Athletes Become Icons.',
        'telephone': '+1-480-709-9969', 'email': 'service@phireworxphoto.com',
        'foundingDate': '2012', 'founder': {'@type': 'Person', 'name': 'Rashad Griffin'},
        'address': {'@type': 'PostalAddress', 'addressLocality': 'Phoenix', 'addressRegion': 'AZ', 'addressCountry': 'US'},
        'areaServed': [{'@type': 'City', 'name': c + ', AZ'} for c in CITIES],
        'priceRange': '$$',
        'sameAs': ['https://instagram.com/phireworx_photo', 'https://facebook.com/Phireworx'],
        'knowsAbout': ['High school sports photography', 'Youth sports photography', 'Team photos', 'Individual athlete portraits',
                       'Composite team photos', 'Senior banners', 'Team banners', 'Media day photography'],
    }
    if full:
        p, b, m = services(prices)
        biz['hasOfferCatalog'] = {'@type': 'OfferCatalog', 'name': 'Sports photography services',
                                  'itemListElement': [{'@type': 'Offer', 'itemOffered': s} for s in (p, b, m)]}
    return biz


def breadcrumb(name, path):
    return {'@type': 'BreadcrumbList', 'itemListElement': [
        {'@type': 'ListItem', 'position': 1, 'name': 'Home', 'item': SITE + '/'},
        {'@type': 'ListItem', 'position': 2, 'name': name, 'item': SITE + path}]}


def faq_page(faq):
    qs = []
    for cat in (faq or {}).get('categories', []) or []:
        for q in cat.get('questions', []) or []:
            if q.get('q') and q.get('a'):
                qs.append({'@type': 'Question', 'name': q['q'], 'acceptedAnswer': {'@type': 'Answer', 'text': q['a']}})
    return {'@type': 'FAQPage', '@id': SITE + '/faq#faq', 'mainEntity': qs} if qs else None


def page_graph(page, canonical, title, prices, faq):
    name = re.sub(r'\s*\|.*$', '', title).strip()
    p, b, m = services(prices)
    path = canonical.replace(SITE, '') or '/'
    if page == 'index.html':
        g = [business(prices, True), {'@type': 'WebSite', '@id': SITE + '/#website', 'name': 'Phireworx Photography',
                                      'url': SITE + '/', 'publisher': {'@id': BIZ_ID}}]
    else:
        g = [business(prices, False)]
        extra = {'photo-day.html': [p], 'banners.html': [b], 'media-day.html': [m], 'services.html': [p, b, m]}.get(page, [])
        g += extra
        if page == 'faq.html':
            f = faq_page(faq)
            if f:
                g.append(f)
        g.append(breadcrumb(name, path))
    return {'@context': 'https://schema.org', '@graph': g}


def inject_ld(doc, graph):
    block = '<script type="application/ld+json" id="ld-site">' + json.dumps(graph, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/') + '</script>\n'
    doc = re.sub(r'<script type="application/ld\+json" id="ld-site">.*?</script>\n?', '', doc, flags=re.S)
    return doc.replace('</head>', block + '</head>', 1)


# ── llms.txt ────────────────────────────────────────────────────────────
def llms_txt(prices, faq, revs):
    b = prices.get('banners', {}) or {}
    md = prices.get('media_day', {}) or {}
    pd = prices.get('picture_day', {}) or {}
    L = []
    L.append('# Phireworx Photography')
    L.append('')
    L.append('> Phoenix, Arizona sports photography company (founded 2012) serving high school programs and youth leagues across the Phoenix metro: team and individual picture days, Pro Banners (senior and team vinyl banners), and the Phireworx Media Day Experience.')
    L.append('')
    L.append('Phireworx works with coaches, athletic directors, booster clubs, and club/travel team directors. Picture days come to the school or field, families order online, and coaches have no post-shoot work. Rated 5.0 on Google.')
    L.append('')
    L.append('Areas served: ' + ', '.join(CITIES) + ' (Arizona).')
    L.append('Contact: service@phireworxphoto.com, (480) 709-9969. Booking requests go through the website forms.')
    L.append('')
    L.append('## Services and pricing')
    L.append(f"- [Team & Individual Picture Day]({SITE}/pictureday): No cost to the program; families order prints and digitals online. On-location or composite sessions. A ${pd.get('small_program_fee', '')} session fee may apply to high school programs under {pd.get('hs_min_athletes', '')} athletes or youth organizations under {pd.get('youth_min_athletes', '')} athletes.")
    L.append(f"- [Pro Banners]({SITE}/banners): Individual/senior banners ${b.get('individual_2x3', '')} (2×3 ft), ${b.get('individual_25x4', '')} (2.5×4 ft), ${b.get('individual_3x5', '')} (3×5 ft), ${b.get('individual_4x6', '')} (4×6 ft). Traditional team banners ${b.get('team_5x3', '')}–${b.get('team_10x6', '')}. Composite team banners ${b.get('composite_5x3', '')}–${b.get('composite_10x6', '')}. Orders of 1–3 individual banners add ${b.get('small_order_upcharge', '')} each. Banner-only sessions have a ${b.get('minimum_order', '')} minimum. 3–7 business day turnaround.")
    L.append(f"- [Phireworx Media Day Experience]({SITE}/media): Prepaid by the program, every edited digital included. ${md.get('tier_20_plus', '')}/athlete for 20+ athletes, ${md.get('tier_10_19', '')}/athlete for 10–19, ${md.get('tier_5_9', '')}/athlete for 5–9. ${md.get('minimum', '')} minimum booking.")
    L.append('')
    L.append('## Key pages')
    for t, u in [('Services overview', '/services'), ('Book a picture day, banners, or Media Day', '/book'), ('Areas we serve', '/areas'),
                 ('Reviews', '/reviews'), ('FAQ', '/faq'), ('About', '/about'), ('Policies', '/policies'), ('Find your photos (gallery access)', '/galleryaccess')]:
        L.append(f'- [{t}]({SITE}{u})')
    good = [r for r in revs if r.get('quote')][:6]
    if good:
        L.append('')
        L.append('## What clients say')
        for r in good:
            q = re.sub(r'\s+', ' ', r['quote']).strip()
            L.append(f'- "{q}" ({r.get("name", "")}, {r.get("role", "").replace(" · ", ", ")})')
    qs = [(q.get('q'), q.get('a')) for c in (faq or {}).get('categories', []) or [] for q in c.get('questions', []) or [] if q.get('q') and q.get('a')]
    if qs:
        L.append('')
        L.append('## Frequently asked questions')
        for q, a in qs:
            L.append(f'- **{q}** {re.sub(chr(10), " ", a)}')
    return '\n'.join(L) + '\n'


# ── main ────────────────────────────────────────────────────────────────
def lastmod(path):
    try:
        out = subprocess.run(['git', 'log', '-1', '--format=%cs', '--', path], capture_output=True, text=True, timeout=10).stdout.strip()
        return out or None
    except Exception:
        return None


def main():
    data_files = {}
    for p in glob.glob('data/*.json') + glob.glob('data/photos/*.json'):
        key = os.path.splitext(p[len('data/'):])[0]
        d = load(p)
        if d is not None:
            data_files[key] = d
    prices = data_files.get('prices', {}) or {}
    faq = data_files.get('faq', {}) or {}
    all_revs = []
    sitemap = []

    for page in sorted(glob.glob('*.html')):
        if page.startswith('_'):
            continue
        try:
            with open(page, encoding='utf-8') as f:
                doc = f.read()
            orig = doc
            doc, n = apply_bindings(doc, data_files)

            if 'reviewFiles' in doc:
                order, revs = reviews_in_order(doc)
                all_revs = all_revs or revs
                doc = set_review_list(doc, order)
                if 'id="cms-testimonials-grid"' in doc:
                    h = home_reviews_html(revs)
                    if h:
                        doc, _ = replace_inner_by_id(doc, 'cms-testimonials-grid', h)
                if 'id="cms-reviews-grid"' in doc:
                    h = reviews_page_html(revs)
                    if h:
                        doc, _ = replace_inner_by_id(doc, 'cms-reviews-grid', h)

            noindex = re.search(r'<meta name="robots" content="[^"]*noindex', doc)
            can = re.search(r'<link rel="canonical" href="([^"]+)"', doc)
            title = re.search(r'<title>([^<]*)</title>', doc)
            if can and not noindex:
                doc = inject_ld(doc, page_graph(page, can.group(1), html.unescape(title.group(1) if title else ''), prices, faq))
                sitemap.append((can.group(1), lastmod(page)))

            if doc != orig:
                with open(page, 'w', encoding='utf-8') as f:
                    f.write(doc)
            print(f'{page}: {n} values from /admin' + (' + structured data' if can and not noindex else ''))
        except Exception:
            warn(f'{page}: ' + traceback.format_exc().splitlines()[-1])

    try:
        urls = ''.join(f'  <url><loc>{u}</loc>' + (f'<lastmod>{d}</lastmod>' if d else '') + '</url>\n'
                       for u, d in sorted(sitemap, key=lambda x: (x[0] != SITE + '/', x[0])))
        with open('sitemap.xml', 'w', encoding='utf-8') as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + urls + '</urlset>\n')
        print(f'sitemap.xml: {len(sitemap)} pages')
    except Exception:
        warn('sitemap: ' + traceback.format_exc().splitlines()[-1])

    try:
        if not all_revs:
            _, all_revs = reviews_in_order('')
        with open('llms.txt', 'w', encoding='utf-8') as f:
            f.write(llms_txt(prices, faq, all_revs))
        print('llms.txt written')
    except Exception:
        warn('llms.txt: ' + traceback.format_exc().splitlines()[-1])

    print(f'done, {len(WARN)} warning(s)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
