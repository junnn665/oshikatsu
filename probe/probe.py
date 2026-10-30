"""お笑いの申込情報を取れる情報元を調べる一時スクリプト（調査が終わったら消す）"""
import re, urllib.request, pathlib, json, html
OUT = pathlib.Path("probe/out"); OUT.mkdir(parents=True, exist_ok=True)
UA = "Mozilla/5.0 (compatible; WarautaBot/1.0; +https://github.com/junnn665/oshikatsu) Python-urllib"
CANDIDATES = {
    "fanymag_feed": "https://magazine.fany.lol/feed/",
    "fanymag_top": "https://magazine.fany.lol/",
    "natalie_owarai": "https://natalie.mu/owarai/feed/news",
    "natalie_music": "https://natalie.mu/music/feed/news",
    "yoshimoto_top": "https://www.yoshimoto.co.jp/",
    "yoshimoto_news": "https://news.yoshimoto.co.jp/",
    "lumine": "https://lumine.yoshimoto.co.jp/",
    "ngk": "https://ngk.yoshimoto.co.jp/",
    "manzaigekijyo": "https://manzaigekijyo.yoshimoto.co.jp/",
    "jimbocho": "https://jimbocho.yoshimoto.co.jp/",
    "eplus_comedy": "https://eplus.jp/sf/play/comedy",
    "ltike_comedy": "https://l-tike.com/play/comedy/",
    "pia_comedy": "https://t.pia.jp/event/comedy.jsp",
    "pia_fan": "https://fan.pia.jp/",
}
log = {}
for key, url in CANDIDATES.items():
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja"})
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read(1_500_000); final = r.geturl(); ctype = r.headers.get("content-type", "")
        text = body.decode("utf-8", "ignore")
        titles = [html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", t)).strip() for t in re.findall(r"<title>(.*?)</title>", text, re.S)][:12]
        (OUT / f"{key}.txt").write_text(text[:300000])
        log[key] = {"url": url, "final": final, "type": ctype, "bytes": len(body),
                    "items": text.count("<item"), "titles": titles,
                    "rss_links": re.findall(r'<link[^>]+type="application/(?:rss|atom)\+xml"[^>]*>', text)[:5]}
    except Exception as e:
        log[key] = {"url": url, "error": f"{type(e).__name__}: {e}"}
(OUT / "log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1))
