#!/usr/bin/env python3
"""Phireworx gallery access flyers for a team.

Versions (mode):
  pre   Pre-Shoot Gallery Access Flyer: gallery not live yet; QR and link are
        used to subscribe early so parents get a text when photos are posted.
  post  Post-Shoot Gallery Access Flyer: gallery is live; QR and link open it.
  both  (default) makes both.

Usage: python3 make_flyers.py team.json OUTDIR

team.json:
  team_name     "Verrado"
  program       "Cross Country"
  season_label  "Picture Day 2026-27"
  access_code   taken from the end of the gallery link if left out
                (.../gallery/vcc26 -> VCC26). Also starts every file name.
  gallery_url   optional; built from the access code if left out
                (VCC26 -> https://my.photoday.com/gallery/vcc26)
  logo          path to the team logo (png/jpg/svg); leave out if there isn't one
  team_colors   optional ["#hex", "#hex"]: primary then secondary. Colors the
                no-logo monogram badge and, if no team_color, the band.
  placeholder   no-logo fallback: "monogram" (default) or "stars" (Phireworx mark)
  monogram      optional letters for the badge (default: first letter of team_name)
  mode          "both" (default), "pre" or "post"
  print         which versions get the 4-up print sheet (4.25x5.5in handouts):
                default ["pre"]; also "post", "both"/true, or "none"/false
  team_color    optional "#RRGGBB" (otherwise pulled from the logo)
  sticker       optional false to skip the white die-cut border on the logo

Writes, per version (e.g. VCC26-pre-shoot-flyer-...):
  <CODE>-<mode>-shoot-flyer-square.png   1080x1080 post for team chats
  <CODE>-<mode>-shoot-flyer-story.png    1080x1920 phone-screen version
  <CODE>-<mode>-shoot-flyer-message.txt  paste-ready message with the link
  <CODE>-<mode>-shoot-flyer-print-4up.pdf  Letter sheet, 4 handouts of 4.25x5.5in
                                           to cut apart (pre-shoot by default)
  <CODE>-<mode>-shoot-flyer-print-4up.png  preview of that sheet
  <CODE>-gallery-qr.png                  the QR on its own
"""
import base64, colorsys, io, json, os, re, sys
from collections import Counter
from pathlib import Path

import segno
from PIL import Image
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
ASSETS = Path(os.environ.get("PWX_ASSETS", HERE / "assets"))

NEUTRAL_STRIPE = "#F5F4F0"   # thin accent beside the team band
NEUTRAL_LABEL = "#BDB9B0"    # season label on the dark background
FALLBACK_BAND = "#3C3C3C"    # logo has no clear team color (all black/white)
COAL = "#0D0D0D"
PHOTODAY_GALLERY = "https://my.photoday.com/gallery/"

COPY = {
    "post": {"tag": "Your photos are live",
             "text_line": "to access the gallery",
             "scan_head": "Scan to open<br>the gallery",
             "link_label": "Gallery link",
             "why": "",
             "footnote": "Questions about your order? service@phireworxphoto.com"},
    "pre":  {"tag": "Subscribe early",
             "text_line": "to subscribe",
             "scan_head": "Scan to<br>subscribe",
             "link_label": "Subscribe link",
             "why": "Get a text the moment your photos are live.",
             "footnote": "Once subscribed, you'll automatically be texted a link to your gallery when the photos are live. Photos can take up to 2 weeks to be edited and uploaded to the gallery."},
}


def data_uri(path_or_bytes, mime):
    b = path_or_bytes if isinstance(path_or_bytes, (bytes, bytearray)) else Path(path_or_bytes).read_bytes()
    return f"data:{mime};base64," + base64.b64encode(b).decode()


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def logo_png(path, page):
    p = Path(path)
    if p.suffix.lower() == ".svg":
        svg = p.read_text()
        page.set_viewport_size({"width": 900, "height": 900})
        page.set_content(f'<html><body style="margin:0;background:transparent">'
                         f'<div id="l" style="width:900px;height:900px;display:flex;align-items:center;justify-content:center">'
                         f'<img src="{data_uri(svg.encode(), "image/svg+xml")}" style="max-width:860px;max-height:860px"></div></body></html>')
        return page.locator("#l").screenshot(omit_background=True)
    im = knock_out_background(Image.open(p).convert("RGBA"))
    bbox = im.getchannel("A").getbbox()
    if bbox:
        im = im.crop(bbox)
    buf = io.BytesIO(); im.save(buf, "PNG")
    return buf.getvalue()


def knock_out_background(im, tol=40):
    """Logos often come on a white (or flat) background. If the corners are an
    opaque flat color, flood-fill it from the edges and make it transparent.
    Enclosed areas of the same color inside the logo are left alone."""
    w, h = im.size
    px = im.load()
    corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
    if any(c[3] < 250 for c in corners):
        return im  # already has transparency
    ref = corners[0]
    if any(max(abs(c[i] - ref[i]) for i in range(3)) > tol for c in corners):
        return im  # corners differ: not a flat background, leave it
    from collections import deque
    seen = bytearray(w * h)
    q = deque()
    for x in range(w):
        q.append((x, 0)); q.append((x, h - 1))
    for y in range(h):
        q.append((0, y)); q.append((w - 1, y))
    close = lambda c: max(abs(c[0] - ref[0]), abs(c[1] - ref[1]), abs(c[2] - ref[2])) <= tol
    while q:
        x, y = q.popleft()
        i = y * w + x
        if seen[i]:
            continue
        seen[i] = 1
        c = px[x, y]
        if not close(c):
            continue
        px[x, y] = (c[0], c[1], c[2], 0)
        if x > 0: q.append((x - 1, y))
        if x < w - 1: q.append((x + 1, y))
        if y > 0: q.append((x, y - 1))
        if y < h - 1: q.append((x, y + 1))
    return im


def team_color(png_bytes):
    im = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    im.thumbnail((200, 200))
    counts = Counter()
    for r, g, b, a in im.getdata():
        if a < 200:
            continue
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        if s < 0.3 or l < 0.12 or l > 0.9:
            continue  # skip white, black and greys
        counts[(r // 24 * 24, g // 24 * 24, b // 24 * 24)] += 1
    if not counts:
        return FALLBACK_BAND
    key = counts.most_common(1)[0][0]
    members = [(r, g, b) for r, g, b, a in im.getdata()
               if a >= 200 and (r // 24 * 24, g // 24 * 24, b // 24 * 24) == key]
    r, g, b = (round(sum(c[i] for c in members) / len(members)) for i in range(3))
    return "#{:02X}{:02X}{:02X}".format(r, g, b)


def add_sticker_border(png_bytes, frac=0.03):
    """White die-cut border around the logo so it separates from any color,
    including its own team color."""
    from PIL import ImageFilter
    im = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    im.thumbnail((900, 900), Image.LANCZOS)
    r = max(6, int(max(im.size) * frac))
    pad = r * 2
    canvas = Image.new("RGBA", (im.width + pad * 2, im.height + pad * 2), (0, 0, 0, 0))
    canvas.paste(im, (pad, pad), im)
    a = canvas.getchannel("A").point(lambda v: 255 if v > 40 else 0)
    grown = a.filter(ImageFilter.GaussianBlur(r)).point(lambda v: 255 if v > 10 else 0)
    # fill gaps enclosed by the logo so they read as white, not as see-through holes
    from PIL import ImageDraw
    ImageDraw.floodfill(grown, (0, 0), 128)
    grown = grown.point(lambda v: 0 if v == 128 else 255)
    grown = grown.filter(ImageFilter.GaussianBlur(1.2))
    white = Image.new("RGBA", canvas.size, (255, 255, 255, 0))
    white.putalpha(grown)
    out = Image.alpha_composite(white, canvas)
    out = out.crop(out.getchannel("A").getbbox())
    buf = io.BytesIO(); out.save(buf, "PNG")
    return buf.getvalue()


def _lum(hex_color):
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def band_from_colors(colors):
    """First team color that isn't near-black (a black band vanishes on the dark flyer)."""
    for c in colors or []:
        if max(int(c[i:i + 2], 16) for i in (1, 3, 5)) > 40:
            return c.upper()
    return None


def placeholder_png(page, cfg):
    """Stand-in when a team has no logo: a shield badge with the team's initial in
    the brand display face and the team's colors (default), or the Phireworx stars."""
    if cfg.get("placeholder") == "stars":
        im = knock_out_background(Image.open(ASSETS / "logo-mark.png").convert("RGBA"))
        im = im.crop(im.getchannel("A").getbbox())
        coal = Image.new("RGBA", im.size, (13, 13, 13, 255)); coal.putalpha(im.getchannel("A"))
        out = {}
        for key, img in (("light", im), ("dark", coal)):
            buf = io.BytesIO(); img.save(buf, "PNG"); out[key] = buf.getvalue()
        return out["light"], out["dark"]
    colors = cfg.get("team_colors") or []
    primary = colors[0] if colors else "#2A2A2A"
    secondary = colors[1] if len(colors) > 1 else "#FFFFFF"
    if abs(_lum(primary) - _lum(secondary)) < 0.25:
        secondary = "#FFFFFF" if _lum(primary) < 0.5 else "#0D0D0D"
    letters = (cfg.get("monogram") or cfg["team_name"].strip()[:1]).upper()
    size = 230 if len(letters) == 1 else (165 if len(letters) == 2 else 120)
    page.set_viewport_size({"width": 800, "height": 920})
    page.set_content(f"""<html><head><style>{font_css()}body{{margin:0;background:transparent}}</style></head><body>
<div id="b" style="width:800px;height:920px">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 460" width="800" height="920">
  <path d="M200 12 L372 70 L372 220 C372 330 300 405 200 448 C100 405 28 330 28 220 L28 70 Z" fill="{primary}" stroke="{secondary}" stroke-width="18" stroke-linejoin="round"/>
  <path d="M200 50 L340 97 L340 220 C340 313 281 376 200 413 C119 376 60 313 60 220 L60 97 Z" fill="none" stroke="{secondary}" stroke-opacity=".45" stroke-width="5" stroke-linejoin="round"/>
  <text x="200" y="222" text-anchor="middle" dominant-baseline="central" font-family="ChosenceUpright" font-weight="700" font-size="{size}" fill="{secondary}">{letters}</text>
</svg></div></body></html>""", wait_until="load")
    page.evaluate("document.fonts.ready")
    png = page.locator("#b").screenshot(omit_background=True)
    im = Image.open(io.BytesIO(png)).convert("RGBA")
    im = im.crop(im.getchannel("A").getbbox())
    buf = io.BytesIO(); im.save(buf, "PNG")
    return buf.getvalue(), buf.getvalue()


def ink_on(hex_color):
    """Coal or white text, whichever reads better on the team color."""
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return COAL if lum > 0.55 else "#FFFFFF"


def font_css():
    f = lambda n: data_uri(ASSETS / n, "font/woff2")
    return f"""
@font-face{{font-family:'Chosence';src:url('{f("chosence-bold-italic.woff2")}');font-weight:700;font-style:italic}}
@font-face{{font-family:'ChosenceUpright';src:url('{f("chosence-bold.woff2")}');font-weight:700;font-style:normal}}
@font-face{{font-family:'Evogria';src:url('{f("evogria-italic.woff2")}');font-weight:400;font-style:italic}}
@font-face{{font-family:'Barlow';src:url('{f("barlow-latin-500-normal.woff2")}');font-weight:500}}
@font-face{{font-family:'Barlow';src:url('{f("barlow-latin-600-normal.woff2")}');font-weight:600}}
@font-face{{font-family:'Barlow';src:url('{f("barlow-latin-700-normal.woff2")}');font-weight:700}}
"""


BASE_CSS = """
*{box-sizing:border-box}
body{margin:0;background:#0D0D0D}
.d{font-family:'Chosence',sans-serif;font-weight:700;font-style:italic;text-transform:uppercase;letter-spacing:.5px}
.e{font-family:'Evogria',sans-serif;font-style:italic}
.b{font-family:'Barlow',sans-serif}
.pwx{display:block;mix-blend-mode:lighten}
.slab{position:absolute;top:-40px;bottom:-40px;transform:skewX(-11.86deg)}
.logo{display:block;object-fit:contain;filter:drop-shadow(0 18px 40px rgba(0,0,0,.55))}
.card{background:#fff;color:#0D0D0D}
.qr{background:#fff;display:flex;align-items:center;justify-content:center}
"""


def square_html(t):
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{t['fonts']}{BASE_CSS}</style></head><body>
<div style="width:1080px;height:1080px;position:relative;overflow:hidden;background:#0D0D0D;color:#F5F4F0">
  <div class="slab" style="left:600px;width:620px;background:{t['color']}"></div>
  <div class="slab" style="left:572px;width:14px;background:{NEUTRAL_STRIPE}"></div>
  <img class="logo" src="{t['logo']}" style="position:absolute;left:670px;top:150px;width:340px;height:340px">

  <div style="position:absolute;left:72px;top:68px;width:520px">
    <img class="pwx" src="{t['pwx']}" style="height:58px">
    <div class="e" style="margin-top:56px;font-size:28px;color:{NEUTRAL_LABEL}">{t['season_label']}</div>
    <div class="d" style="margin-top:14px;font-size:92px;line-height:.9">{t['team_name_html']}</div>
    <div class="b" style="margin-top:18px;font-size:32px;font-weight:600;color:#C9C6BE">{t['program']}</div>
    <div class="d" style="display:inline-block;margin-top:40px;font-size:38px;line-height:1;background:#F5F4F0;color:#0D0D0D;padding:10px 20px 8px">{t['copy']['tag']}</div>
    {t['why_square']}
  </div>

  <div class="card" style="position:absolute;left:72px;right:72px;bottom:72px;height:372px;display:flex;flex-direction:column">
   <div style="flex:1;display:flex;align-items:center;gap:30px;padding:0 40px 0 44px">
    <div style="flex:1;min-width:0">
      <div class="b" style="font-size:26px;font-weight:600;color:#3C3C3C">Gallery access code</div>
      <div class="d" style="font-size:128px;line-height:1;margin-top:6px;letter-spacing:4px">{t['access_code']}</div>
      <div class="b" style="font-size:27px;font-weight:600;margin-top:10px">Text it to <span class="d" style="font-size:32px;background:{COAL};color:#FFFFFF;padding:2px 12px">90738</span> {t['copy']['text_line']}</div>
    </div>
    <div style="align-self:stretch;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;padding:30px 0">
      <div style="flex:1;width:3px;background:#0D0D0D"></div>
      <div class="d" style="font-size:34px;line-height:1">Or</div>
      <div style="flex:1;width:3px;background:#0D0D0D"></div>
    </div>
    <div class="qr" style="width:226px;height:226px;border:5px solid #0D0D0D;flex-shrink:0"><img src="{t['qr']}" style="width:204px;height:204px"></div>
   </div>
   <div class="b" style="border-top:2px solid #E3DED3;padding:14px 44px 16px;font-size:24px;font-weight:600;color:#3C3C3C;display:flex;gap:12px;align-items:baseline">{t['copy']['link_label']}: <span style="color:#0D0D0D;font-weight:700">{t['short_url']}</span></div>
  </div>
</div></body></html>"""


def story_html(t):
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{t['fonts']}{BASE_CSS}</style></head><body>
<div style="width:1080px;height:1920px;position:relative;overflow:hidden;background:#0D0D0D;color:#F5F4F0">
  <div style="position:absolute;left:-60px;right:-60px;top:270px;height:450px;background:{t['color']};transform:skewY(-6deg)"></div>
  <div style="position:absolute;left:-60px;right:-60px;top:712px;height:16px;background:{NEUTRAL_STRIPE};transform:skewY(-6deg)"></div>
  <div style="position:absolute;left:0;right:0;top:92px;display:flex;justify-content:center"><img class="pwx" src="{t['pwx']}" style="height:88px"></div>
  <img class="logo" src="{t['logo']}" style="position:absolute;left:375px;top:330px;width:330px;height:330px">

  <div style="position:absolute;left:84px;right:84px;top:820px;height:410px;display:flex;flex-direction:column;justify-content:center;text-align:center">
    <div class="e" style="font-size:32px;color:{NEUTRAL_LABEL}">{t['season_label']}</div>
    <div class="d" style="margin-top:14px;font-size:112px;line-height:.9">{t['team_name_html']}</div>
    <div class="b" style="margin-top:18px;font-size:36px;font-weight:600;color:#C9C6BE">{t['program']}</div>
    <div style="margin-top:30px"><span class="d" style="display:inline-block;font-size:42px;line-height:1;background:#F5F4F0;color:#0D0D0D;padding:10px 22px 8px">{t['copy']['tag']}</span></div>
    {t['why_story']}
  </div>

  <div class="card" style="position:absolute;left:84px;right:84px;top:1262px;padding:32px 44px 34px;text-align:center">
    <div class="b" style="font-size:30px;font-weight:600;color:#3C3C3C">Gallery access code</div>
    <div class="d" style="font-size:150px;line-height:1;margin-top:6px;letter-spacing:5px">{t['access_code']}</div>
    <div class="b" style="font-size:34px;font-weight:600;margin-top:16px">Text it to <span class="d" style="font-size:40px;background:{COAL};color:#FFFFFF;padding:2px 14px">90738</span> {t['copy']['text_line']}</div>
  </div>

  <div style="position:absolute;left:84px;right:84px;top:1622px;display:flex;align-items:center;gap:22px">
    <div style="flex:1;height:3px;background:#F5F4F0"></div>
    <div class="d" style="font-size:38px;line-height:1">Or</div>
    <div style="flex:1;height:3px;background:#F5F4F0"></div>
  </div>
  <div style="position:absolute;left:84px;right:84px;bottom:52px;display:flex;align-items:center;justify-content:center;gap:34px">
    <div class="qr" style="width:176px;height:176px;flex-shrink:0"><img src="{t['qr']}" style="width:160px;height:160px"></div>
    <div>
      <div class="d" style="font-size:46px;line-height:.95">{t['copy']['scan_head']}</div>
      <div class="b" style="margin-top:14px;font-size:20px;font-weight:500;color:#C0C0C0">{t['copy']['link_label']}</div>
      <div class="b" style="margin-top:2px;font-size:27px;font-weight:600;color:#F5F4F0">{t['short_url']}</div>
    </div>
  </div>
</div></body></html>"""


def message_text(t):
    if t.get("mode", "post") == "pre":
        return (f"{t['team_name']} {t['program']} families: subscribe to your picture day gallery early.\n\n"
                f"Subscribe here: {t['gallery_url']}\n"
                f"Access code: {t['access_code']}\n\n"
                f"Or text {t['access_code']} to 90738 to subscribe.\n"
                f"Once subscribed, you'll automatically get a text with your gallery link when the photos are live. "
                f"Photos can take up to 2 weeks to be edited and uploaded.\n")
    return (f"{t['team_name']} {t['program']} families: your picture day photos are live.\n\n"
            f"View the gallery: {t['gallery_url']}\n"
            f"Access code: {t['access_code']}\n\n"
            f"Or text {t['access_code']} to 90738 to access the gallery.\n")


def print_card(t):
    """One 4.25x5.5in handout (408x528 CSS px): white paper, black type, team
    color only as a thin accent, so it prints cheaply and reads in grayscale.
    26px (~0.27in) padding keeps content inside a home printer's margins."""
    return f"""<div style="width:408px;height:528px;box-sizing:border-box;padding:26px 26px 22px;display:flex;flex-direction:column;background:#fff;color:#0D0D0D;overflow:hidden">
  <div style="display:flex;align-items:center;justify-content:space-between">
    <img class="pwx-ink" src="{t['pwx']}" style="height:24px">
    <div class="e" style="font-size:10px;color:#3C3C3C">{t['season_label']}</div>
  </div>
  <div style="margin-top:8px;height:6px;background:{t['color']};transform:skewX(-11.86deg);margin-left:3px;margin-right:3px"></div>

  <div style="margin-top:12px;display:flex;align-items:center;gap:14px">
    <img src="{t['logo_plain']}" style="width:74px;height:74px;object-fit:contain;flex-shrink:0">
    <div style="min-width:0">
      <div class="d" style="font-size:32px;line-height:.9">{t['team_name_html']}</div>
      <div class="b" style="margin-top:4px;font-size:12px;font-weight:600;color:#3C3C3C">{t['program']}</div>
      <div class="d" style="display:inline-block;margin-top:6px;font-size:13px;line-height:1;background:#0D0D0D;color:#fff;padding:4px 8px 3px">{t['copy']['tag']}</div>
    </div>
  </div>

  <div style="margin-top:12px;border:3px solid #0D0D0D;padding:8px 12px 10px;text-align:center">
    <div class="b" style="font-size:10px;font-weight:600;color:#3C3C3C">Gallery access code</div>
    <div class="d" style="font-size:54px;line-height:1;margin-top:2px;letter-spacing:3px">{t['access_code']}</div>
    <div class="b" style="font-size:13px;font-weight:600;margin-top:4px">Text it to <span class="d" style="font-size:15px;background:#0D0D0D;color:#fff;padding:0 6px">90738</span> {t['copy']['text_line']}</div>
  </div>

  <div style="margin-top:9px;display:flex;align-items:center;gap:10px">
    <div style="flex:1;height:1.5px;background:#0D0D0D"></div>
    <div class="d" style="font-size:14px;line-height:1">Or</div>
    <div style="flex:1;height:1.5px;background:#0D0D0D"></div>
  </div>

  <div style="margin-top:9px;display:flex;align-items:center;justify-content:center;gap:16px">
    <img src="{t['qr']}" style="width:124px;height:124px;display:block;flex-shrink:0">
    <div>
      <div class="d" style="font-size:21px;line-height:.95">{t['copy']['scan_head']}</div>
      <div class="b" style="margin-top:6px;font-size:9px;font-weight:500;color:#3C3C3C">{t['copy']['link_label']}</div>
      <div class="b" style="font-size:11.5px;font-weight:700">{t['short_url']}</div>
    </div>
  </div>

  <div class="b" style="margin-top:auto;padding-top:7px;border-top:1.5px solid #0D0D0D;font-size:9px;font-weight:500;line-height:1.4;color:#3C3C3C">{t['copy']['footnote']}</div>
</div>"""


def print_html(t):
    """Letter sheet with 4 identical handouts (2x2), each 4.25x5.5in, and light
    dashed cut lines down the middle both ways."""
    card = print_card(t)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{t['fonts']}{BASE_CSS}
@page{{size:8.5in 11in;margin:0}}
body{{background:#fff}}
.pwx-ink{{display:block;filter:invert(1);mix-blend-mode:multiply}}
</style></head><body>
<div style="width:816px;height:1056px;position:relative;background:#fff;display:grid;grid-template-columns:408px 408px;grid-template-rows:528px 528px">
  {card}{card}{card}{card}
  <div style="position:absolute;left:407.5px;top:0;bottom:0;border-left:1px dashed #9A9A9A"></div>
  <div style="position:absolute;top:527.5px;left:0;right:0;border-top:1px dashed #9A9A9A"></div>
</div></body></html>"""


def verify_qr(files, url):
    """Scan the QR in each finished image and confirm it opens the gallery link."""
    try:
        import cv2
    except ImportError:
        print("QR check skipped (pip install opencv-python-headless to enable)")
        return
    det = cv2.QRCodeDetector()
    for f in files:
        img = cv2.imread(str(f))
        if "4up" in f.name:  # check each of the four handouts on the sheet
            h, w = img.shape[:2]
            parts = [img[y:y + h // 2, x:x + w // 2] for y in (0, h // 2) for x in (0, w // 2)]
        else:
            parts = [img]
        for i, part in enumerate(parts, 1):
            got = det.detectAndDecode(part)[0]
            label = f.name + (f" (copy {i})" if len(parts) > 1 else "")
            status = "ok" if got == url else f"MISMATCH (read {got!r})"
            print(f"QR check {label}: {status}")
            if got != url:
                raise SystemExit(f"QR in {label} does not open {url}")


def code_from_url(url):
    """PhotoDay gallery links end in the access code: .../gallery/vcc26 -> VCC26."""
    last = re.sub(r"[?#].*$", "", url).rstrip("/").rsplit("/", 1)[-1]
    if not re.fullmatch(r"[A-Za-z0-9-]{3,20}", last):
        raise SystemExit(f"Couldn't read an access code from {url}; add access_code to team.json")
    return last.upper()


def main(cfg_path, outdir):
    cfg = json.loads(Path(cfg_path).read_text())
    base = Path(cfg_path).resolve().parent
    if not cfg.get("gallery_url") and not cfg.get("access_code"):
        raise SystemExit("Give gallery_url or access_code")
    if not cfg.get("gallery_url"):
        code = re.sub(r"[^A-Za-z0-9-]+", "", cfg["access_code"])
        cfg["gallery_url"] = f"{PHOTODAY_GALLERY}{code.lower()}"
        print("gallery link (from code):", cfg["gallery_url"])
    if not cfg.get("access_code"):
        cfg["access_code"] = code_from_url(cfg["gallery_url"])
        print("access code (from link):", cfg["access_code"])
    out = Path(outdir); out.mkdir(parents=True, exist_ok=True)
    mode = cfg.get("mode", "both")
    modes = ["pre", "post"] if mode == "both" else [mode]
    if any(m not in COPY for m in modes):
        raise SystemExit('mode must be "both", "pre" or "post"')
    pr = cfg.get("print", ["pre"])
    if pr is True or pr == "both":
        print_modes = {"pre", "post"}
    elif pr in (False, None, "none"):
        print_modes = set()
    else:
        print_modes = {pr} if isinstance(pr, str) else set(pr)
    code = re.sub(r"[^A-Za-z0-9]+", "", cfg["access_code"]).upper()
    short_url = re.sub(r"^https?://(www\.)?", "", cfg["gallery_url"]).rstrip("/")

    qr = segno.make(cfg["gallery_url"], error="m")
    qr_buf = io.BytesIO(); qr.save(qr_buf, kind="png", scale=16, border=1, dark=COAL, light="#FFFFFF")
    qr_file = out / f"{code}-gallery-qr.png"
    qr_file.write_bytes(qr_buf.getvalue())
    to_check = [qr_file]

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        if cfg.get("logo"):
            logo_raw = logo_png(base / cfg["logo"], page)
            logo_print = logo_raw
        else:
            logo_raw, logo_print = placeholder_png(page, cfg)
            print("no logo: using", cfg.get("placeholder", "monogram"), "placeholder")
        color = (cfg.get("team_color") or band_from_colors(cfg.get("team_colors"))
                 or team_color(logo_raw))
        logo = add_sticker_border(logo_raw) if cfg.get("sticker", True) else logo_raw
        words = cfg["team_name"].split()
        name_html = " ".join(words) if len(words) < 2 else " ".join(words[:-1]) + "<br>" + words[-1]
        shared = dict(cfg, fonts=font_css(), color=color, ink=ink_on(color),
                      logo=data_uri(logo, "image/png"), logo_plain=data_uri(logo_print, "image/png"),
                      pwx=data_uri(ASSETS / "logo-full.png", "image/png"),
                      qr=data_uri(qr_buf.getvalue(), "image/png"), team_name_html=name_html,
                      short_url=short_url)
        for m in modes:
            c = COPY[m]
            t = dict(shared, mode=m, copy=c,
                     why_square=(f'<div class="b" style="margin-top:16px;font-size:24px;font-weight:500;color:#C9C6BE">{c["why"]}</div>' if c["why"] else ""),
                     why_story=(f'<div class="b" style="margin-top:16px;font-size:28px;font-weight:500;color:#C9C6BE">{c["why"]}</div>' if c["why"] else ""))
            stem = f"{code}-{m}-shoot-flyer"
            for name, html, (w, h) in (("square", square_html(t), (1080, 1080)), ("story", story_html(t), (1080, 1920))):
                page.set_viewport_size({"width": w, "height": h})
                page.set_content(html, wait_until="load")
                page.evaluate("document.fonts.ready")
                f = out / f"{stem}-{name}.png"
                page.screenshot(path=str(f), clip={"x": 0, "y": 0, "width": w, "height": h})
                to_check.append(f)
            if m in print_modes:
                pp = browser.new_page(viewport={"width": 816, "height": 1056}, device_scale_factor=2)
                pp.set_content(print_html(t), wait_until="load")
                pp.evaluate("document.fonts.ready")
                pp.pdf(path=str(out / f"{stem}-print-4up.pdf"), width="8.5in", height="11in", print_background=True)
                f = out / f"{stem}-print-4up.png"
                pp.screenshot(path=str(f), clip={"x": 0, "y": 0, "width": 816, "height": 1056})
                pp.close()
                to_check.append(f)
            (out / f"{stem}-message.txt").write_text(message_text(t))
        browser.close()

    print("team color", color)
    verify_qr(to_check, cfg["gallery_url"])
    for f in sorted(out.glob(f"{code}-*")):
        print(f)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
