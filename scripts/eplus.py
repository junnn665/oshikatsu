"""e+（イープラス）のお笑いチケット一覧を読む（scripts/fetch_live.py から使う）。

一覧ページ（1ページ50件）を順に読み、公演名・公演日・会場・受付状況を取り出す。
robots.txt で許可されていないときは何もしない。1ページごとに1秒あける。
"""

from __future__ import annotations

import datetime as dt
import html
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

BASE = "https://eplus.jp"
LIST_PATH = "/sf/play/comedy"
MAX_PAGES = 12
LAST_NOTE = ""  # 直近の取得結果のメモ（data/status.json に書く）
UA = "Mozilla/5.0 (compatible; WarautaBot/1.0; +https://github.com/junnn665/oshikatsu) Python-urllib"

ITEM_RE = re.compile(r'<a class="ticket-item[^"]*" href="(/sf/detail/[^"]+)">(.*?)</a>', re.S)
PAGE_RE = re.compile(r'href="/sf/play/comedy/p(\d+)"')


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "ignore")


def _text(fragment: str | None) -> str:
    if not fragment:
        return ""
    t = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return re.sub(r"\s+", " ", t).strip()


def _find(cls: str, block: str) -> str:
    m = re.search(r'class="' + re.escape(cls) + r'[^"]*"[^>]*>(.*?)</(?:div|p|span|h3)>', block, re.S)
    return _text(m.group(1)) if m else ""


def allowed() -> bool:
    rp = urllib.robotparser.RobotFileParser()
    try:
        rp.parse(_get(BASE + "/robots.txt").splitlines())
    except Exception:
        return True  # robots.txt が読めないときは、通常のアクセスとして扱う
    return rp.can_fetch(UA, BASE + LIST_PATH)


def parse_page(page: str, today: dt.date) -> list[dict]:
    out = []
    for href, block in ITEM_RE.findall(page):
        title_html = re.search(r'class="ticket-item__title">(.*?)</h3>', block, re.S)
        if not title_html:
            continue
        label = _text((re.search(r'class="label-ticket">(.*?)</span>', title_html.group(1), re.S) or [None, ""])[1])
        title = _text(re.sub(r'<span class="label-ticket">.*?</span>', "", title_html.group(1), flags=re.S))
        yyyy = re.sub(r"\D", "", _find("ticket-item__yyyy", block))
        mmdd = re.match(r"(\d{1,2})/(\d{1,2})", _find("ticket-item__mmdd", block))
        date = None
        if mmdd:
            year = int(yyyy) if yyyy else today.year
            try:
                date = dt.date(year, int(mmdd.group(1)), int(mmdd.group(2))).isoformat()
            except ValueError:
                date = None
        venue = _find("ticket-item__venue", block)
        streaming = _find("ticket-item__stpl-text", block)
        time_text = _find("ticket-item__text", block)
        status = _find("ticket-status__item", block)
        out.append({
            "link": BASE + href,
            "title": title,
            "label": label,          # 先着 / 抽選 など
            "date": date,
            "venue": venue or streaming,
            "online": bool(streaming) and not venue,
            "time": time_text,
            "status": status,        # 受付中 / 受付前 / 予定枚数終了 など
        })
    return out


def _get_retry(url: str) -> str:
    """混んでいる（429/503）ときだけ、30秒待って1回だけやり直す。"""
    try:
        return _get(url)
    except urllib.error.HTTPError as e:
        if e.code not in (429, 503):
            raise
        time.sleep(30)
        return _get(url)


def fetch(today: dt.date, run_no: int, per_run: int = 3) -> dict[int, list[dict]]:
    """1ページ目と、ほかのページから per_run ページだけ読む（実行ごとに順番に回す）。

    返り値は {ページ番号: そのページの公演}。読めなかったページは入らない。
    """
    global LAST_NOTE
    if not allowed():
        LAST_NOTE = "robots.txt で許可されていないので読みません"
        return {}
    first = _get_retry(BASE + LIST_PATH)
    pages = {int(p) for p in PAGE_RE.findall(first)}
    last = min(max(pages) if pages else 1, MAX_PAGES)
    got: dict[int, list[dict]] = {1: parse_page(first, today)}
    others = list(range(2, last + 1))
    if others:
        start = (run_no * per_run) % len(others)
        targets = [others[(start + i) % len(others)] for i in range(min(per_run, len(others)))]
    else:
        targets = []
    errors = []
    for n in targets:
        time.sleep(3)
        try:
            got[n] = parse_page(_get_retry(f"{BASE}{LIST_PATH}/p{n}"), today)
        except Exception as e:
            errors.append(f"p{n}: {type(e).__name__}: {e}")
            break  # 断られたら、この回はそれ以上読まない
    total = sum(len(v) for v in got.values())
    LAST_NOTE = f"{total} 公演（全{last}ページ中 {sorted(got)} を読んだ）" + (" / " + " / ".join(errors) if errors else "")
    print("[eplus] " + LAST_NOTE)
    return got
