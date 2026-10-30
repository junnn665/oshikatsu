"""FANYチケットのページ構造を調べるための一時スクリプト（調査が終わったら消す）"""
import re, urllib.request, urllib.parse, pathlib, json
OUT = pathlib.Path("probe/out"); OUT.mkdir(parents=True, exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
def get(url, name):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja"})
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read(); final = r.geturl(); ctype = r.headers.get("content-type", "")
        (OUT / name).write_bytes(body)
        return {"url": url, "final": final, "status": 200, "type": ctype, "bytes": len(body)}
    except Exception as e:
        return {"url": url, "error": f"{type(e).__name__}: {e}"}
log = []
base = "https://ticket.fany.lol"
for path, name in [("/", "top.html"), ("/robots.txt", "robots.txt"), ("/sitemap.xml", "sitemap.xml"),
                   ("/search", "search.html"), ("/search/event", "search_event.html"), ("/news", "news.html")]:
    log.append(get(base + path, name))
top = (OUT / "top.html").read_text("utf-8", "ignore") if (OUT / "top.html").exists() else ""
links = sorted(set(re.findall(r'href="([^"#]+)"', top)))
(OUT / "links.txt").write_text("\n".join(links))
scripts = re.findall(r'<script[^>]+src="([^"]+)"', top)
apis = set()
for i, s in enumerate(scripts[:15]):
    u = urllib.parse.urljoin(base + "/", s)
    r = get(u, f"js_{i}.js"); log.append(r)
    if "error" not in r:
        js = (OUT / f"js_{i}.js").read_text("utf-8", "ignore")
        apis.update(re.findall(r'["\'`](/api/[^"\'`\s]{1,120}|https?://[a-z0-9.-]*fany[^"\'`\s]{0,120})', js))
        (OUT / f"js_{i}.js").unlink()
(OUT / "apis.txt").write_text("\n".join(sorted(apis)))
# 公演詳細らしいリンクを2つだけ保存
detail = [l for l in links if re.search(r"/event|/ticket|/performance|/detail", l)][:2]
for i, l in enumerate(detail):
    log.append(get(urllib.parse.urljoin(base + "/", l), f"detail_{i}.html"))
(OUT / "log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1))
