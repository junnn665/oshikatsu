/* わらうた：data/live.json を読み込んで表示する */
(function () {
  'use strict';

  var TYPES = [
    ['all', 'すべて'],
    ['moushikomi', '申込・チケット'],
    ['kettei', '開催決定'],
    ['fes', 'フェス・出演'],
    ['chushi', '中止・延期'],
    ['report', 'レポート'],
    ['sonota', 'その他']
  ];
  var TYPE_NAME = {};
  TYPES.forEach(function (t) { TYPE_NAME[t[0]] = t[1]; });
  var SHORT = { moushikomi: '申込', kettei: '開催決定', fes: 'フェス', chushi: '中止・延期', report: 'レポ', sonota: '' };
  var PAGE = 24;
  var DAY = 86400000;

  var state = { genre: 'all', type: 'all', area: '', q: '', oshiOnly: false, savedOnly: false, shown: PAGE };
  var data = { items: [], oshi: { geinin: [], artist: [] } };
  var $ = function (id) { return document.getElementById(id); };

  function load(key, fallback) {
    try { var v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch (e) { return fallback; }
  }
  function save(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* 保存できなくても続ける */ }
  }
  var myOshi = load('warauta.oshi', []);
  var hiddenOshi = load('warauta.oshiHidden', []);
  var saved = load('warauta.saved', {});
  state.genre = load('warauta.genre', 'all');

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function today() { var d = new Date(); return new Date(d.getFullYear(), d.getMonth(), d.getDate()); }
  function parseDay(iso) { var p = iso.split('-'); return new Date(+p[0], +p[1] - 1, +p[2]); }
  function md(iso) { var d = parseDay(iso); return (d.getMonth() + 1) + '/' + d.getDate(); }
  function daysLeft(iso) { return Math.round((parseDay(iso) - today()) / DAY); }
  function ago(iso) {
    var h = Math.floor((Date.now() - new Date(iso).getTime()) / 3600000);
    if (h < 1) return 'さっき';
    if (h < 24) return h + '時間前';
    var d = Math.floor(h / 24);
    if (d < 7) return d + '日前';
    var t = new Date(iso);
    return (t.getMonth() + 1) + '/' + t.getDate();
  }
  function left(days) { return days === 0 ? '今日' : days === 1 ? '明日' : 'あと' + days + '日'; }

  // 写真がないカードに大きく載せる言葉：公演名（「」『』の中）か、見出しの頭
  function flyerText(title) {
    var t = title.replace(/^【[^】]*】\s*/, '').replace(/^画像[^|｜]*[|｜]\s*/, '');
    var lead = t.match(/^[『「]([^』」]{2,24})[』」]/);
    if (lead) return lead[1];
    var head = t.split(/[、，,。！!？?：:｜|\s]/)[0];
    if (head.length >= 2 && head.length <= 16) return head;
    var m = t.match(/[『「]([^』」]{2,24})[』」]/);
    if (m) return m[1];
    return t.slice(0, 16);
  }

  // ---- 推し ----
  function oshiAll() {
    var list = [], seen = {};
    function push(name, genre) {
      var k = name.toLowerCase();
      if (seen[k] || hiddenOshi.indexOf(name) >= 0) return;
      seen[k] = true;
      list.push({ name: name, genre: genre });
    }
    (data.oshi.geinin || []).forEach(function (n) { push(n, 'geinin'); });
    (data.oshi.artist || []).forEach(function (n) { push(n, 'artist'); });
    myOshi.forEach(function (o) { push(o.name, o.genre); });
    return list;
  }
  function oshiHits(it, list) {
    var t = it.title.toLowerCase();
    return list.filter(function (o) { return t.indexOf(o.name.toLowerCase()) >= 0; }).map(function (o) { return o.name; });
  }
  function renderOshi() {
    var list = oshiAll();
    $('oshi-count').textContent = list.length + '人';
    $('oshi-list').innerHTML = list.length ? list.map(function (o) {
      var n = data.items.filter(function (it) { return it.title.toLowerCase().indexOf(o.name.toLowerCase()) >= 0; }).length;
      return '<li class="oshi-item' + (o.genre === 'artist' ? ' is-artist' : '') + '">' + esc(o.name) +
        '<small>' + n + '件</small><button type="button" data-remove="' + esc(o.name) + '" aria-label="' + esc(o.name) + 'を外す">×</button></li>';
    }).join('') : '<li class="note">まだいません。名前を入れて追加してください。</li>';
  }

  // ---- 絞り込み ----
  function matches(it, oshiList) {
    if (state.genre !== 'all' && it.genre !== state.genre) return false;
    if (state.type !== 'all' && it.type !== state.type) return false;
    if (state.area && (it.areas || []).indexOf(state.area) < 0) return false;
    if (state.savedOnly && !saved[it.id]) return false;
    if (state.oshiOnly && !oshiHits(it, oshiList).length) return false;
    if (state.q) {
      var hay = (it.title + ' ' + (it.source || '') + ' ' + (it.venue || '')).toLowerCase();
      var words = state.q.toLowerCase().split(/[\s　]+/).filter(Boolean);
      for (var i = 0; i < words.length; i++) if (hay.indexOf(words[i]) < 0) return false;
    }
    return true;
  }

  function renderSoon(oshiList) {
    var rows = [];
    data.items.forEach(function (it) {
      if (state.genre !== 'all' && it.genre !== state.genre) return;
      if (state.oshiOnly && !oshiHits(it, oshiList).length) return;
      var iso = it.deadline || it.sale_start;
      if (!iso) return;
      var d = daysLeft(iso);
      if (d >= 0 && d <= 21) rows.push({ it: it, days: d, dl: !!it.deadline });
    });
    rows.sort(function (a, b) { return a.days - b.days; });
    $('soon-count').textContent = rows.length ? rows.length + '件' : '';
    $('soon').innerHTML = rows.length ? rows.slice(0, 24).map(function (r) {
      var iso = r.dl ? r.it.deadline : r.it.sale_start;
      return '<a class="soon-card is-' + esc(r.it.genre) + '" href="' + esc(r.it.link) + '" target="_blank" rel="noopener">' +
        '<span class="soon-when">' + (r.days > 1 ? '<span>あと</span><b>' + r.days + '</b><span>日</span>' : '<b>' + left(r.days) + '</b>') + '</span>' +
        '<span class="soon-kind">' + md(iso) + (r.dl ? ' 締切' : ' 受付開始') + '</span>' +
        '<span class="soon-title">' + esc(r.it.title) + '</span></a>';
    }).join('') : '<p class="empty">締切日・受付開始日がわかっている申込は、いまありません。</p>';
  }

  function card(it, oshiList) {
    var isNew = it.added && Date.now() - new Date(it.added).getTime() < DAY;
    var hits = oshiHits(it, oshiList);
    var visual = it.image
      ? '<img src="' + esc(it.image) + '" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.outerHTML=\'<span class=&quot;flyer&quot;><span>' + esc(esc(flyerText(it.title))) + '</span></span>\'">'
      : '<span class="flyer"><span>' + esc(flyerText(it.title)) + '</span></span>';
    var badges = (isNew ? '<span class="badge new">NEW</span>' : '') +
      (SHORT[it.type] ? '<span class="badge t-' + esc(it.type) + '">' + SHORT[it.type] + '</span>' : '');
    var due = '';
    if (it.deadline && daysLeft(it.deadline) >= 0) {
      due = '<span class="due"><span>' + md(it.deadline) + ' 締切</span><b>' + left(daysLeft(it.deadline)) + '</b></span>';
    } else if (it.sale_start && daysLeft(it.sale_start) >= 0) {
      due = '<span class="due"><span>' + md(it.sale_start) + ' 受付開始</span><b>' + left(daysLeft(it.sale_start)) + '</b></span>';
    } else if (it.event_date) {
      due = '<span class="due"><span>公演 ' + md(it.event_date) + '</span><b>' + esc(it.venue || '') + '</b></span>';
    }
    return '<article class="card is-' + esc(it.genre) + '">' +
      '<button class="save" type="button" data-save="' + esc(it.id) + '" aria-pressed="' + (saved[it.id] ? 'true' : 'false') + '" aria-label="保存">★</button>' +
      '<a class="card-link" href="' + esc(it.link) + '" target="_blank" rel="noopener">' +
        '<span class="visual">' + visual + '<span class="badges">' + badges + '</span></span>' +
        '<span class="body">' +
          (hits.length ? '<span class="oshi-tags">' + hits.map(function (n) { return '<span class="oshi-tag-s">' + esc(n) + '</span>'; }).join('') + '</span>' : '') +
          '<h3 class="title">' + esc(it.title) + '</h3>' +
          '<span class="meta"><span>' + esc(it.source || '') + '</span><span>' + ago(it.published) + '</span>' +
            ((it.areas || []).length ? '<span>' + esc(it.areas.join('・')) + '</span>' : '') + '</span>' +
        '</span>' + due +
      '</a></article>';
  }

  // FANYは外から検索結果を開けないので、FANYの公演ページをGoogleで探すリンクにする
  function fanyUrl(name) {
    return 'https://www.google.com/search?q=' + encodeURIComponent('site:ticket.fany.lol ' + name);
  }
  function renderFany(oshiList) {
    var show = state.genre === 'geinin';
    $('fany').hidden = !show;
    if (!show) return;
    var names = oshiList.filter(function (o) { return o.genre === 'geinin'; });
    $('fany-list').innerHTML = names.length ? names.map(function (o) {
      return '<a href="' + fanyUrl(o.name) + '" target="_blank" rel="noopener">' + esc(o.name) + '</a>';
    }).join('') : '<p class="note">下の推しリストに芸人を追加すると、ここから FANY の公演を探せます。</p>';
  }

  function render() {
    var oshiList = oshiAll();
    renderFany(oshiList);
    document.querySelectorAll('.genre-btn').forEach(function (b) {
      b.setAttribute('aria-pressed', b.dataset.genre === state.genre ? 'true' : 'false');
    });
    document.querySelectorAll('#type-chips .chip-btn').forEach(function (b) {
      b.setAttribute('aria-pressed', b.dataset.type === state.type ? 'true' : 'false');
    });
    $('oshi-only').setAttribute('aria-pressed', state.oshiOnly ? 'true' : 'false');
    $('saved-only').setAttribute('aria-pressed', state.savedOnly ? 'true' : 'false');
    renderSoon(oshiList);
    var list = data.items.filter(function (it) { return matches(it, oshiList); });
    $('count').textContent = list.length + '件';
    $('cards').innerHTML = list.length
      ? list.slice(0, state.shown).map(function (it) { return card(it, oshiList); }).join('')
      : '<p class="empty">条件に合う情報がありません。種類を「すべて」、エリアを「全国」に戻してみてください。</p>';
    $('more').hidden = list.length <= state.shown;
  }

  function reset() { state.shown = PAGE; render(); }

  function setup() {
    $('type-chips').innerHTML = TYPES.map(function (t) {
      return '<button type="button" class="chip-btn" data-type="' + t[0] + '" aria-pressed="false">' + t[1] + '</button>';
    }).join('');
    document.querySelector('.genre').addEventListener('click', function (e) {
      var b = e.target.closest('.genre-btn'); if (!b) return;
      state.genre = b.dataset.genre; save('warauta.genre', state.genre); reset();
    });
    $('type-chips').addEventListener('click', function (e) {
      var b = e.target.closest('.chip-btn'); if (!b) return;
      state.type = b.dataset.type; reset();
    });
    $('area').addEventListener('change', function (e) { state.area = e.target.value; reset(); });
    $('q').addEventListener('input', function (e) { state.q = e.target.value.trim(); reset(); });
    $('oshi-only').addEventListener('click', function () { state.oshiOnly = !state.oshiOnly; reset(); });
    $('saved-only').addEventListener('click', function () { state.savedOnly = !state.savedOnly; reset(); });
    $('more').addEventListener('click', function () { state.shown += PAGE; render(); });

    $('cards').addEventListener('click', function (e) {
      var b = e.target.closest('[data-save]'); if (!b) return;
      e.preventDefault();
      var id = b.dataset.save;
      if (saved[id]) delete saved[id]; else saved[id] = true;
      save('warauta.saved', saved);
      b.setAttribute('aria-pressed', saved[id] ? 'true' : 'false');
    });

    $('oshi-form').addEventListener('submit', function (e) {
      e.preventDefault();
      var name = $('oshi-input').value.trim(); if (!name) return;
      var h = hiddenOshi.indexOf(name);
      if (h >= 0) { hiddenOshi.splice(h, 1); save('warauta.oshiHidden', hiddenOshi); }
      if (!oshiAll().some(function (o) { return o.name.toLowerCase() === name.toLowerCase(); })) {
        myOshi.push({ name: name, genre: state.genre !== 'all' ? state.genre : guessGenre(name) });
        save('warauta.oshi', myOshi);
      }
      $('oshi-input').value = '';
      renderOshi(); render();
    });
    $('oshi-list').addEventListener('click', function (e) {
      var b = e.target.closest('[data-remove]'); if (!b) return;
      var name = b.dataset.remove, before = myOshi.length;
      myOshi = myOshi.filter(function (o) { return o.name !== name; });
      if (myOshi.length === before) { hiddenOshi.push(name); save('warauta.oshiHidden', hiddenOshi); }
      save('warauta.oshi', myOshi);
      renderOshi(); render();
    });
  }

  function guessGenre(name) {
    var g = 0, a = 0, k = name.toLowerCase();
    data.items.forEach(function (it) {
      if (it.title.toLowerCase().indexOf(k) < 0) return;
      if (it.genre === 'geinin') g++; else a++;
    });
    return g > a ? 'geinin' : 'artist';
  }

  function fillAreas() {
    var counts = {};
    data.items.forEach(function (it) { (it.areas || []).forEach(function (a) { counts[a] = (counts[a] || 0) + 1; }); });
    var order = ['北海道', '東北', '関東', '東海', '北陸・甲信越', '関西', '中国・四国', '九州・沖縄', '配信'];
    $('area').innerHTML = '<option value="">全国</option>' + order.filter(function (a) { return counts[a]; }).map(function (a) {
      return '<option value="' + a + '">' + a + '（' + counts[a] + '）</option>';
    }).join('');
  }

  setup();
  fetch('data/live.json?t=' + Date.now(), { cache: 'no-store' })
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function (json) {
      data = json; data.items = data.items || []; data.oshi = data.oshi || { geinin: [], artist: [] };
      if (json.updated) {
        var u = new Date(json.updated);
        $('updated').textContent = (u.getMonth() + 1) + '/' + u.getDate() + ' ' +
          ('0' + u.getHours()).slice(-2) + ':' + ('0' + u.getMinutes()).slice(-2) + ' 更新';
      }
      fillAreas(); renderOshi(); render();
    })
    .catch(function () {
      $('cards').innerHTML = '<p class="empty">情報をまだ読み込めません。初回の自動更新が終わると表示されます。</p>';
      $('soon').innerHTML = ''; renderOshi();
    });
})();
