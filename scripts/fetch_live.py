#!/usr/bin/env python3
"""わらうた: お笑い・アーティストのライブ情報と申込（チケット）情報を集めて data/live.json を更新する。

GitHub Actions から毎日実行される。標準ライブラリだけで動く。

取得元
  - Bing ニュース RSS（キーワード検索。記事への直リンクとサムネイルが取れる）
  - Google ニュース RSS（キーワード検索。件数の補完用）
  - PR TIMES 新着 RSS（事務所・主催者の公式発表）
  - oshi.json に書いた芸人・アーティスト名での検索
"""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import email.utils
import hashlib
import html
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import eplus  # e+ のお笑いチケット一覧（scripts/eplus.py）

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "live.json"
STATUS_FILE = ROOT / "data" / "status.json"
OSHI_FILE = ROOT / "oshi.json"

JST = dt.timezone(dt.timedelta(hours=9))
NOW = dt.datetime.now(dt.timezone.utc)

KEEP_DAYS = 45        # この日数より古い記事は消す（ただし申込締切・公演日がまだ先なら残す）
INGEST_DAYS = 10      # この日数より古い記事は新しく取り込まない
MAX_ITEMS = 600       # 保存する最大件数
MAX_IMAGE_FETCH = 120 # 1回の実行で写真を探しにいく最大件数

UA = "Mozilla/5.0 (compatible; WarautaBot/1.0; +https://github.com/) Python-urllib"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# 検索キーワード（キーワード, ジャンルの初期値）  geinin = お笑い / artist = アーティスト
# ここを書き換えれば集める情報を調整できる
# ---------------------------------------------------------------------------
QUERIES = [
    # お笑い
    ("お笑いライブ 開催", "geinin"),
    ("お笑いライブ チケット", "geinin"),
    ("芸人 単独ライブ", "geinin"),
    ("芸人 単独公演 決定", "geinin"),
    ("芸人 全国ツアー", "geinin"),
    ("お笑い 先行抽選 OR 先行受付", "geinin"),
    ("漫才 ライブ 開催決定", "geinin"),
    ("コント ライブ 開催決定", "geinin"),
    ("よしもと 公演 チケット", "geinin"),
    ("吉本 ライブ 決定", "geinin"),
    ("漫才劇場 公演", "geinin"),
    ("ルミネtheよしもと OR なんばグランド花月 公演", "geinin"),
    ("お笑いフェス", "geinin"),
    ("お笑いライブ 配信 チケット", "geinin"),
    ("M-1 OR キングオブコント 芸人 ライブ", "geinin"),
    ("人力舎 OR ワタナベエンターテインメント OR 太田プロ OR マセキ芸能社 ライブ", "geinin"),
    ("独演会 チケット", "geinin"),
    # FANY（よしもとのチケット・配信）に載る公演
    ("FANY 先行 OR 抽選 OR 受付", "geinin"),
    ("FANYチケット", "geinin"),
    ("チケットよしもと", "geinin"),
    ("FANYオンライン 配信 ライブ", "geinin"),
    ("よしもと 単独ライブ 開催決定", "geinin"),
    # アーティスト
    ("ライブ 先行受付 チケット", "artist"),
    ("ツアー 開催決定 チケット", "artist"),
    ("全国ツアー 発表", "artist"),
    ("ワンマンライブ 開催決定", "artist"),
    ("アリーナツアー 決定", "artist"),
    ("ドームツアー 決定", "artist"),
    ("ホールツアー 開催", "artist"),
    ("追加公演 決定", "artist"),
    ("最速先行 抽選", "artist"),
    ("ファンクラブ先行 ライブ", "artist"),
    ("チケット 一般発売 ライブ", "artist"),
    ("音楽フェス 出演者 発表", "artist"),
    ("フェス 第1弾 OR 第2弾 OR 第3弾 出演アーティスト", "artist"),
    ("対バン ライブ 決定", "artist"),
    ("アーティスト ライブ 中止 OR 延期", "artist"),
]

PRTIMES_FEED = "https://prtimes.jp/index.rdf"

# 公式メディアの RSS（そのまま全部見る。ジャンルは固定）
DIRECT_FEEDS = [
    ("https://magazine.fany.lol/feed/", "geinin", "FANY Magazine"),
    ("https://natalie.mu/owarai/feed/news", "geinin", "お笑いナタリー"),
    ("https://natalie.mu/music/feed/news", "artist", "音楽ナタリー"),
]

# ---------------------------------------------------------------------------
# 判定ルール
# ---------------------------------------------------------------------------
# ライブ・申込に関係する言葉（どれかが見出しに無ければ載せない）
LIVE_WORDS = [
    "ライブ", "LIVE", "Live", "公演", "ツアー", "TOUR", "Tour", "フェス", "FES", "Fes",
    "チケット", "先行", "抽選", "受付", "申込", "申し込み", "一般発売", "開催",
    "単独", "独演会", "ワンマン", "寄席", "興行", "コンサート", "追加公演", "千秋楽",
    "劇場公演", "漫才劇場", "ドーム", "アリーナ", "ホール", "武道館",
]

COMEDY_WORDS = [
    "芸人", "お笑い", "漫才", "コント", "漫談", "ピン芸", "吉本", "よしもと", "ヨシモト",
    "人力舎", "ワタナベエンターテインメント", "太田プロ", "マセキ", "ホリプロコム", "ケイダッシュ",
    "サンミュージック", "松竹芸能", "M-1", "Ｍ－１", "キングオブコント", "R-1", "THE W", "THE SECOND",
    "漫才劇場", "ルミネtheよしもと", "なんばグランド花月", "NGK", "無限大ホール", "神保町よしもと",
    "単独ライブ", "独演会", "コンビ", "トリオ", "ネタ", "大喜利", "相方", "FANY", "チケットよしもと",
]

MUSIC_WORDS = [
    "バンド", "歌手", "シンガー", "アーティスト", "アイドル", "グループ", "ボーカル",
    "アルバム", "シングル", "楽曲", "新曲", "ワンマン", "ツアー", "TOUR", "フェス", "FES",
    "ドーム", "アリーナ", "武道館", "ホールツアー", "ライブハウス", "対バン", "コンサート",
    "オーケストラ", "ミュージック", "音楽", "MV", "ラッパー", "DJ",
]

# 種類（上から順に判定し、最初に当たったものにする）
TYPES = [
    ("chushi", ["中止", "延期", "振替", "払い戻し", "払戻", "開催見送り", "休演"]),
    ("moushikomi", ["先行", "抽選", "受付", "申込", "申し込み", "一般発売", "チケット発売", "エントリー",
                    "先着", "販売開始", "発売開始", "リセール", "当日券", "チケット情報", "プレイガイド"]),
    ("fes", ["フェス", "FES", "Fes", "出演者", "第1弾", "第2弾", "第3弾", "第4弾", "第5弾", "最終発表",
             "ラインナップ", "出演決定"]),
    ("kettei", ["開催決定", "決定", "発表", "追加公演", "開催へ", "開催する", "ツアー", "TOUR",
                "単独", "ワンマン", "独演会", "公演", "開催"]),
    ("report", ["レポ", "レポート", "ライブ写真", "終演", "千秋楽", "大盛況", "熱狂", "完走", "閉幕",
                "披露", "語った", "明かした", "観客", "会見", "取材会"]),
]

# エリア（見出しに出てくる地名 → 表示名）
AREAS = [
    ("北海道", ["北海道", "札幌"]),
    ("東北", ["東北", "仙台", "宮城", "青森", "岩手", "秋田", "山形", "福島", "盛岡"]),
    ("関東", ["東京", "都内", "渋谷", "新宿", "池袋", "下北沢", "神保町", "有楽町", "日比谷", "表参道", "六本木",
              "お台場", "両国", "武道館", "東京ドーム", "有明", "横浜", "神奈川", "川崎", "千葉", "幕張",
              "埼玉", "さいたま", "茨城", "栃木", "群馬", "関東", "ルミネtheよしもと"]),
    ("東海", ["名古屋", "愛知", "岐阜", "三重", "静岡", "浜松", "東海", "栄", "金山"]),
    ("北陸・甲信越", ["新潟", "富山", "金沢", "石川", "福井", "長野", "松本", "山梨", "甲府", "北陸"]),
    ("関西", ["大阪", "なんば", "難波", "梅田", "心斎橋", "京セラドーム", "城ホール", "京都", "神戸", "兵庫",
              "奈良", "和歌山", "滋賀", "関西", "なんばグランド花月", "NGK", "祇園花月"]),
    ("中国・四国", ["広島", "岡山", "山口", "鳥取", "島根", "四国", "香川", "高松", "愛媛", "松山", "徳島", "高知"]),
    ("九州・沖縄", ["福岡", "博多", "九州", "北九州", "熊本", "長崎", "大分", "宮崎", "鹿児島", "佐賀", "沖縄", "那覇"]),
    ("配信", ["配信", "オンライン", "生配信", "見逃し配信", "FANY"]),
]

# エンタメと関係ない記事を外す（「ライブ」「公演」などを別の意味で使うもの）
NOT_WANTED_WORDS = [
    "株価", "決算", "競馬", "競輪", "競艇", "ボートレース", "プロ野球", "Jリーグ", "サッカー", "ゴルフ",
    "ライブコマース", "ライブカメラ", "ライブ映像で見る", "天気", "地震", "火災", "事故", "逮捕", "容疑",
    "グラビア", "水着", "写真集", "求人", "不動産", "選挙", "議会", "ゲーム実況", "Vtuber",
    "歌舞伎", "宝塚", "ミュージカル", "演劇", "舞台「", "バレエ",
]

# 載せないサイト
BLOCKED_LINKS = [
    "unisba.ac.id",
    "thetv.jp/program/",
]


# ---------------------------------------------------------------------------
# 共通の道具
# ---------------------------------------------------------------------------
def http_get(url: str, limit: int | None = None, timeout: int = 15,
             browser: bool = False) -> tuple[bytes, str]:
    headers = {"User-Agent": BROWSER_UA if browser else UA, "Accept-Language": "ja,en;q=0.5"}
    if browser:
        headers["Accept"] = "text/html,application/xhtml+xml,*/*;q=0.8"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        body = res.read(limit) if limit else res.read()
        return body, res.geturl()


def clean(text: str | None) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def norm_key_full(title: str) -> str:
    t = re.sub(r"\s*(\.\.\.|…)\s*$", "", title)
    return re.sub(r"[\s　「」『』【】()（）\[\]!！?？、。・…:：\-ー〜~|｜/]", "", t)


def norm_key(title: str) -> str:
    return norm_key_full(title)[:30]


def parse_date(text: str | None) -> dt.datetime | None:
    if not text:
        return None
    text = text.strip()
    try:
        d = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        d = None
    if d is None:
        try:
            d = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc)


def child_text(node: ET.Element, suffix: str) -> str | None:
    for c in node:
        if c.tag.split("}")[-1] == suffix:
            return c.text
    return None


def child_nodes(node: ET.Element, suffix: str) -> list[ET.Element]:
    return [c for c in node if c.tag.split("}")[-1] == suffix]


def item_id(link: str) -> str:
    return hashlib.sha1(link.encode("utf-8")).hexdigest()[:16]


def load_oshi() -> dict[str, list[str]]:
    try:
        data = json.loads(OSHI_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        return {"geinin": [], "artist": []}
    return {
        "geinin": [n.strip() for n in data.get("geinin", []) if isinstance(n, str) and n.strip()],
        "artist": [n.strip() for n in data.get("artist", []) if isinstance(n, str) and n.strip()],
    }


OSHI = load_oshi()


# ---------------------------------------------------------------------------
# 判定
# ---------------------------------------------------------------------------
def oshi_in(title: str) -> list[str]:
    low = title.lower()
    return [n for n in OSHI["geinin"] + OSHI["artist"] if n.lower() in low]


# 写真ギャラリーなど、本文記事の重複になるページ
JUNK_PATTERNS = [
    re.compile(r"^画像・写真\s*[|｜]"),
    re.compile(r"\s\d+\s*枚目\s*$"),
    re.compile(r"(画像|写真)\s*\d+\s*/\s*\d+"),
    re.compile(r"【(画像|写真)】"),
]


# 公式メディアの記事だけは、出演者発表などの言葉でも載せる
TRUSTED_EXTRA_WORDS = ["出演者", "ラインナップ", "イベント", "大会", "追加出演", "ゲスト"]


def is_wanted(title: str, trusted: bool = False) -> bool:
    """trusted は、お笑い・音楽専門の公式メディアの記事（ジャンルの言葉が無くても載せる）。"""
    if any(p.search(title) for p in JUNK_PATTERNS):
        return False
    if any(w in title for w in NOT_WANTED_WORDS):
        return False
    if trusted:
        return any(w in title for w in LIVE_WORDS + TRUSTED_EXTRA_WORDS)
    if not any(w in title for w in LIVE_WORDS):
        return False
    # ジャンルの手がかり（芸人・音楽の言葉、または推しの名前）がひとつは欲しい
    return bool(oshi_in(title)) or any(w in title for w in COMEDY_WORDS + MUSIC_WORDS)


def detect_genre(title: str, default: str) -> str:
    low = title.lower()
    if any(n.lower() in low for n in OSHI["geinin"]):
        return "geinin"
    if any(n.lower() in low for n in OSHI["artist"]):
        return "artist"
    comedy = sum(1 for w in COMEDY_WORDS if w in title)
    music = sum(1 for w in MUSIC_WORDS if w in title)
    if comedy > music:
        return "geinin"
    if music > comedy:
        return "artist"
    return default


def detect_type(title: str) -> str:
    for name, words in TYPES:
        if any(w in title for w in words):
            return name
    return "sonota"


def detect_areas(title: str) -> list[str]:
    return [name for name, words in AREAS if any(w in title for w in words)]


# 見出しの中の日付（「11/15」「11月15日」「2026年1月10日」）
DATE_RE = re.compile(r"(?:(20\d{2})\s*[年/.])?\s*(\d{1,2})\s*[月/]\s*(\d{1,2})\s*日?")
DEADLINE_AFTER_RE = re.compile(r"^\s*(?:\([^)]*\)|（[^）]*）)?\s*(?:\d{1,2}:\d{2})?\s*(?:まで|締切|締め切り|〆切)")
DEADLINE_BEFORE_RE = re.compile(r"(?:締切|締め切り|〆切|受付期間|期限)[^0-9]{0,6}$")
START_AFTER_RE = re.compile(r"^\s*(?:\([^)]*\)|（[^）]*）)?\s*(?:\d{1,2}:\d{2})?\s*(?:から|より|〜|～|-)\s*\S{0,6}?(?:受付|発売|販売|抽選|先行|申込)")


def extract_dates(title: str, published: dt.datetime) -> dict:
    """見出しから日付を拾い、申込締切らしい日付（deadline）も見分ける。"""
    pub = published.astimezone(JST).date()
    dates: list[str] = []
    deadline = None
    sale_start = None
    for m in DATE_RE.finditer(title):
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            continue
        # 「2/3公演」「3/10」など年が無いとき、記事日付より大きく前なら翌年
        year = int(y) if y else pub.year
        try:
            day = dt.date(year, mo, d)
        except ValueError:
            continue
        if not y and day < pub - dt.timedelta(days=60):
            try:
                day = dt.date(year + 1, mo, d)
            except ValueError:
                continue
        iso = day.isoformat()
        if iso not in dates:
            dates.append(iso)
        after = title[m.end(): m.end() + 14]
        before = title[max(0, m.start() - 10): m.start()]
        if DEADLINE_AFTER_RE.search(after) or DEADLINE_BEFORE_RE.search(before):
            deadline = iso
        elif START_AFTER_RE.search(after):
            sale_start = iso
    return {"dates": dates[:6], "deadline": deadline, "sale_start": sale_start}


# ---------------------------------------------------------------------------
# 各取得元
# ---------------------------------------------------------------------------
def bing_url(q: str) -> str:
    return "https://www.bing.com/news/search?" + urllib.parse.urlencode(
        {"q": q, "format": "rss", "setlang": "ja", "cc": "JP", "mkt": "ja-JP"}
    )


def google_url(q: str) -> str:
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": q + " when:7d", "hl": "ja", "gl": "JP", "ceid": "JP:ja"}
    )


def unwrap_bing_link(link: str) -> str:
    p = urllib.parse.urlparse(link)
    if "bing.com" in p.netloc:
        qs = urllib.parse.parse_qs(p.query)
        if qs.get("url"):
            return qs["url"][0]
    return link


def parse_rss(xml_bytes: bytes, provider: str) -> list[dict]:
    """RSS（<item>）と Atom（<entry>）の両方を読む。"""
    root = ET.fromstring(xml_bytes)
    out = []
    for it in root.iter():
        if it.tag.split("}")[-1] not in ("item", "entry"):
            continue
        title = clean(child_text(it, "title"))
        link = (child_text(it, "link") or "").strip()
        if not link:
            for ln in child_nodes(it, "link"):
                if ln.get("href") and ln.get("rel", "alternate") == "alternate":
                    link = ln.get("href").strip()
                    break
        summary = clean(child_text(it, "description") or child_text(it, "summary"))[:240]
        if not title or not link:
            continue
        source = clean(child_text(it, "source") or child_text(it, "Source") or child_text(it, "creator"))
        image = None
        for img in child_nodes(it, "Image"):  # Bing の <News:Image>
            if img.text and img.text.strip().startswith("http"):
                image = img.text.strip()
        if provider == "bing":
            link = unwrap_bing_link(link)
        if provider == "google" and source and title.endswith(" - " + source):
            title = title[: -len(" - " + source)].strip()
        if provider == "prtimes" and not source:
            source = "PR TIMES"
        published = parse_date(child_text(it, "pubDate") or child_text(it, "date")
                               or child_text(it, "published") or child_text(it, "updated"))
        out.append({"title": title, "link": link, "source": source, "image": image,
                    "published": published, "summary": summary})
    return out


def all_queries() -> list[tuple[str, str]]:
    qs = list(QUERIES)
    for name in OSHI["geinin"]:
        qs.append((f'"{name}" ライブ OR 単独 OR 公演 OR チケット', "geinin"))
    for name in OSHI["artist"]:
        qs.append((f'"{name}" ライブ OR ツアー OR チケット OR 先行', "artist"))
    return qs


def collect() -> tuple[list[dict], int]:
    found: list[dict] = []
    errors = 0
    jobs = []
    for q, genre in all_queries():
        jobs.append(("bing", bing_url(q), genre))
        jobs.append(("google", google_url(q), genre))
    jobs.append(("prtimes", PRTIMES_FEED, "artist"))
    for url, genre, name in DIRECT_FEEDS:
        jobs.append(("feed:" + name, url, genre))

    def work(job):
        provider, url, genre = job
        body, _ = http_get(url)
        if provider.startswith("feed:"):
            rows = parse_rss(body, "feed")
            for r in rows:
                r.update(default_genre=genre, provider="feed", source=provider[5:], force_genre=genre)
            return rows
        rows = parse_rss(body, provider)
        for r in rows:
            r.update(default_genre=genre, provider=provider)
        return rows

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(work, j): j for j in jobs}
        for f in concurrent.futures.as_completed(futs):
            try:
                found.extend(f.result())
            except Exception as e:  # 1つの取得元が落ちても続ける
                errors += 1
                p, url, _ = futs[f]
                print(f"[warn] {p} {url[:90]}: {e}", file=sys.stderr)

    print(f"fetched {len(found)} raw items from {len(jobs)} feeds ({errors} errors)")
    return found, errors


# ---------------------------------------------------------------------------
# 写真（記事ページの og:image）と Google ニュースの元記事URL
# ---------------------------------------------------------------------------
OG_RE = re.compile(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]*>', re.I)
CONTENT_RE = re.compile(r'content=["\']([^"\']+)["\']', re.I)


def decode_google_link(link: str) -> str | None:
    m = re.search(r"/articles/([^/?#]+)", link)
    if not m:
        return None
    art_id = m.group(1)
    try:
        sig = ts = None
        for base in ("https://news.google.com/articles/", "https://news.google.com/rss/articles/"):
            body, _ = http_get(base + art_id + "?hl=ja&gl=JP&ceid=JP:ja", timeout=10)
            page = body.decode("utf-8", errors="ignore")
            sig = re.search(r'data-n-a-sg="([^"]+)"', page)
            ts = re.search(r'data-n-a-ts="([^"]+)"', page)
            if sig and ts:
                break
        if not (sig and ts):
            return None
        inner = (
            '["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],'
            f'"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{art_id}",{ts.group(1)},"{sig.group(1)}"]'
        )
        data = "f.req=" + urllib.parse.quote(json.dumps([[["Fbv4je", inner]]]))
        req = urllib.request.Request(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            data=data.encode("utf-8"),
            headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
        )
        with urllib.request.urlopen(req, timeout=10) as res:
            text = res.read().decode("utf-8", errors="ignore")
        parsed = json.loads(text.split("\n\n")[1])[:-2]
        url = json.loads(parsed[0][2])[1]
        return url if isinstance(url, str) and url.startswith("http") else None
    except Exception:
        return None


def find_og_image(link: str) -> str | None:
    if "news.google.com" in urllib.parse.urlparse(link).netloc:
        return None
    try:
        body, final_url = http_get(link, limit=400_000, timeout=10, browser=True)
    except Exception:
        return None
    text = body.decode("utf-8", errors="ignore")
    for tag in OG_RE.findall(text):
        m = CONTENT_RE.search(tag)
        if m:
            src = urllib.parse.urljoin(final_url, html.unescape(m.group(1).strip()))
            if src.startswith("https://"):
                return src
    return None


def add_images(items: list[dict]) -> None:
    targets = [it for it in items if not it.get("image_checked")][:MAX_IMAGE_FETCH]

    def work(it: dict) -> str | None:
        if "news.google.com" in urllib.parse.urlparse(it["link"]).netloc:
            real = decode_google_link(it["link"])
            if real:
                it["link"] = real  # 読者が元記事へ直接飛べるように
        if it.get("image"):
            return it["image"]
        return find_og_image(it["link"])

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        for it, img in zip(targets, ex.map(work, targets)):
            it["image"] = img if img and img.startswith("https://") else None
            it["image_checked"] = True


# ---------------------------------------------------------------------------
# まとめて保存
# ---------------------------------------------------------------------------
def load_existing() -> list[dict]:
    try:
        return json.loads(DATA_FILE.read_text("utf-8")).get("items", [])
    except (OSError, ValueError):
        return []


def still_useful(it: dict) -> bool:
    """締切や公演日がまだ先なら、古い記事でも残す。"""
    today = NOW.astimezone(JST).date().isoformat()
    if it.get("deadline") and it["deadline"] >= today:
        return True
    return any(d >= today for d in it.get("dates", []))


def enrich(it: dict, default_genre: str, published: dt.datetime) -> dict:
    title = it["title"]
    text = title + " " + (it.get("summary") or "")   # 日付・エリアは要約からも拾う
    it["genre"] = it.get("force_genre") or detect_genre(title, default_genre)
    it["type"] = detect_type(title)
    it["areas"] = detect_areas(text)
    it["oshi"] = oshi_in(text)
    it.update(extract_dates(text, published))
    return it


def build(raw: list[dict], existing: list[dict]) -> list[dict]:
    items: dict[str, dict] = {}
    seen: dict[str, str] = {}

    def add(it: dict) -> None:
        if it["id"] in items:
            return
        key = norm_key(it["title"])
        if key not in seen and len(key) >= 15:
            for k in seen:
                if len(k) >= 15 and (k.startswith(key) or key.startswith(k)):
                    key = k
                    break
        if key in seen:
            prev = items[seen[key]]
            if not prev.get("image") and it.get("image"):
                prev["image"] = it["image"]
            if len(norm_key_full(it["title"])) > len(norm_key_full(prev["title"])):
                prev["title"] = it["title"]
            return
        items[it["id"]] = it
        seen[key] = it["id"]

    cutoff_keep = NOW - dt.timedelta(days=KEEP_DAYS)
    for it in existing:
        d = parse_date(it.get("published"))
        if not d or any(b in it["link"] for b in BLOCKED_LINKS) or not is_wanted(it["title"], bool(it.get("force_genre"))):
            continue
        if d >= cutoff_keep or still_useful(it):
            # 推しリストや判定ルールを変えたときに、前の記事にも反映する
            add(enrich(it, it.get("genre", "artist"), d))

    cutoff_new = NOW - dt.timedelta(days=INGEST_DAYS)
    # 公式メディアの直リンク → 写真付き（Bing）の順に優先して残す
    order = {"feed": 0, "bing": 1, "prtimes": 2, "google": 3}
    for r in sorted(raw, key=lambda r: order.get(r["provider"], 9)):
        title = r["title"]
        if not is_wanted(title, bool(r.get("force_genre"))) or any(b in r["link"] for b in BLOCKED_LINKS):
            continue
        published = r["published"] or NOW
        if published < cutoff_new or published > NOW + dt.timedelta(hours=1):
            continue
        image = r.get("image")
        add(enrich({
            "id": item_id(r["link"]),
            "title": title,
            "link": r["link"],
            "source": r["source"] or "",
            "image": image if image and image.startswith("https://") else None,
            "published": published.astimezone(JST).isoformat(timespec="seconds"),
            "provider": r["provider"],
            "added": NOW.astimezone(JST).isoformat(timespec="seconds"),
            "summary": r.get("summary") or "",
            "force_genre": r.get("force_genre"),
        }, r["default_genre"], published))

    out = sorted(items.values(), key=lambda it: it["published"], reverse=True)
    return out[:MAX_ITEMS]


# ---------------------------------------------------------------------------
# e+ のお笑いチケット（同じ公演名の回はひとつにまとめる）
# ---------------------------------------------------------------------------
STATUS_ORDER = {"受付中": 0, "受付前": 1}


def build_tickets(rows: list[dict]) -> list[dict]:
    today = NOW.astimezone(JST).date().isoformat()
    groups: dict[str, dict] = {}
    for r in rows:
        if r["date"] and r["date"] < today:
            continue
        base = re.sub(r"\s*[<＜][^>＞]*[>＞]\s*$", "", r["title"]).strip()
        g = groups.get(base)
        if not g:
            g = groups[base] = {
                "id": item_id(r["link"]), "title": base, "link": r["link"], "label": r["label"],
                "dates": [], "venues": [], "status": r["status"], "online": r["online"],
                "areas": [], "oshi": oshi_in(base),
            }
        if r["date"] and r["date"] not in g["dates"]:
            g["dates"].append(r["date"])
        if r["venue"] and r["venue"] not in g["venues"]:
            g["venues"].append(r["venue"])
        # 受付中の回があれば、そちらを代表にする
        if STATUS_ORDER.get(r["status"], 9) < STATUS_ORDER.get(g["status"], 9):
            g["status"], g["link"], g["label"] = r["status"], r["link"], r["label"]
    for g in groups.values():
        g["dates"].sort()
        g["areas"] = detect_areas(" ".join(g["venues"]) + (" 配信" if g["online"] else ""))
        g["venues"] = g["venues"][:4]
    return sorted(groups.values(), key=lambda g: (g["dates"][0] if g["dates"] else "9999", g["title"]))


def load_ticket_rows() -> list[dict]:
    try:
        return json.loads(DATA_FILE.read_text("utf-8")).get("ticket_rows", [])
    except (OSError, ValueError):
        return []


def merge_ticket_rows(prev: list[dict], got: dict[int, list[dict]]) -> list[dict]:
    """今回読めたページの公演を、前回までの分に足す。過ぎた公演と、3日見かけない公演は消す。"""
    today = NOW.astimezone(JST).date().isoformat()
    stamp = NOW.astimezone(JST).isoformat(timespec="seconds")
    stale = (NOW - dt.timedelta(days=3)).astimezone(JST).isoformat(timespec="seconds")
    rows: dict[str, dict] = {}
    for r in prev:
        if r.get("page") in got:          # このページは読み直したので、古い分は捨てる
            continue
        if (r.get("date") and r["date"] < today) or r.get("seen", "") < stale:
            continue
        rows[r["link"]] = r
    for page, items in got.items():
        for r in items:
            rows[r["link"]] = dict(r, page=page, seen=stamp)
    return list(rows.values())


def main() -> int:
    existing = load_existing()
    eplus_note = ""
    run_no = int(NOW.timestamp() // (6 * 3600))  # 実行ごとに、読むページを順番に変える
    try:
        got = eplus.fetch(NOW.astimezone(JST).date(), run_no)
        eplus_note = eplus.LAST_NOTE
    except Exception as e:
        got = {}
        eplus_note = f"{type(e).__name__}: {e}"
        print(f"[warn] eplus: {eplus_note}", file=sys.stderr)
    ticket_rows = merge_ticket_rows(load_ticket_rows(), got)  # 読めなかったときは前回の分が残る
    tickets = build_tickets(ticket_rows)
    raw, errors = collect()
    if not raw and existing:
        print("ニュースを取得できなかったので前回のデータを残します")
        raw = []
    items = build(raw, existing)
    add_images(items)
    new_count = sum(1 for it in items if it.get("added") == NOW.astimezone(JST).isoformat(timespec="seconds"))

    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    stamp = NOW.astimezone(JST).isoformat(timespec="seconds")
    DATA_FILE.write_text(json.dumps(
        {"updated": stamp, "oshi": OSHI, "items": items, "tickets": tickets, "ticket_rows": ticket_rows}, ensure_ascii=False, indent=1), "utf-8")
    STATUS_FILE.write_text(json.dumps({
        "updated": stamp, "total": len(items), "new": new_count,
        "raw": len(raw), "errors": errors, "tickets": len(tickets), "eplus": eplus_note,
    }, ensure_ascii=False, indent=1), "utf-8")
    print(f"saved {len(items)} items ({new_count} new)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
