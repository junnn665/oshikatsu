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
  var GENRE_NAME = { geinin: 'お笑い', artist: 'アーティスト' };
  var PAGE = 40;
  var DAY = 86400000;

  var state = { genre: 'all', type: 'all', area: '', q: '', oshiOnly: false, savedOnly: false, shown: PAGE };
  var data = { items: [], oshi: { geinin: [], artist: [] } };
  var $ = function (id) { return document.getElementById(id); };

  // ---- 端末に保存（使えない環境でも動くように） ----
  function load(key, fallback) {
    try { var v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch (e) { return fallback; }
  }
  function save(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* 保存できなくても続ける */ }
  }
  var myOshi = load('warauta.oshi', []);          // [{name, genre}]
  var hiddenOshi = load('warauta.oshiHidden', []); // oshi.json から外した名前
  var saved = load('warauta.saved', {});           // {id: true}
  state.genre = load('warauta.genre', 'all');

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function today() {
    var d = new Date();
    return new Date(d.getFullYear(), d.getMonth(), d.getDate());
  }
  function parseDay(iso) {
    var p = iso.split('-');
    return new Date(+p[0], +p[1] - 1, +p[2]);
  }
  function md(iso) {
    var d = parseDay(iso);
    return (d.getMonth() + 1) + '/' + d.getDate();
  }
  function daysLeft(iso) { return Math.round((parseDay(iso) - today()) / DAY); }
  function ago(iso) {
    var diff = Date.now() - new Date(iso).getTime();
    var h = Math.floor(diff / 3600000);
    if (h < 1) return 'さっき';
    if (h < 24) return h + '時間前';
    var d = Math.floor(h / 24);
    if (d < 7) return d + '日前';
    var t = new Date(iso);
    return (t.getMonth() + 1) + '/' + t.getDate();
  }

  // ---- 推し ----
  function oshiAll() {
    var list = [];
    var seen = {};
    function push(name, genre, mine) {
      var k = name.toLowerCase();
      if (seen[k] || hiddenOshi.indexOf(name) >= 0) return;
      seen[k] = true;
      list.push({ name: name, genre: genre, mine: mine });
    }
    (data.oshi.geinin || []).forEach(function (n) { push(n, 'geinin', false); });
    (data.oshi.artist || []).forEach(function (n) { push(n, 'artist', false); });
    myOshi.forEach(function (o) { push(o.name, o.genre, true); });
    return list;
  }
  function oshiHits(it, list) {
    var t = it.title.toLowerCase();
    return list.filter(function (o) { return t.indexOf(o.name.toLowerCase()) >= 0; }).map(function (o) { return o.name; });
  }

  function renderOshi() {
    var list = oshiAll();
    $('oshi-count').textContent = list.length + '人';
    var ul = $('oshi-list');
    if (!list.length) {
      ul.innerHTML = '<li class="empty">まだいません。下の欄に名前を入れて追加してください。</li>';
      return;
    }
    ul.innerHTML = list.map(function (o) {
      var n = data.items.filter(function (it) { return it.title.toLowerCase().indexOf(o.name.toLowerCase()) >= 0; }).length;
      return '<li class="oshi-tag' + (o.genre === 'artist' ? ' is-artist' : '') + '">' + esc(o.name) +
        ' <span class="hits">' + n + '件</span>' +
        '<button type="button" data-remove="' + esc(o.name) + '" aria-label="' + esc(o.name) + 'を外す">×</button></li>';
    }).join('');
  }

  // ---- 絞り込み ----
  function matches(it, oshiList) {
    if (state.genre !== 'all' && it.genre !== state.genre) return false;
    if (state.type !== 'all' && it.type !== state.type) return false;
    if (state.area && (it.areas || []).indexOf(state.area) < 0) return false;
    if (state.savedOnly && !saved[it.id]) return false;
    if (state.oshiOnly && !oshiHits(it, oshiList).length) return false;
    if (state.q) {
      var hay = (it.title + ' ' + (it.source || '')).toLowerCase();
      var words = state.q.toLowerCase().split(/[\s　]+/).filter(Boolean);
      for (var i = 0; i < words.length; i++) if (hay.indexOf(words[i]) < 0) return false;
    }
    return true;
  }

  function renderUpcoming(oshiList) {
    var rows = [];
    data.items.forEach(function (it) {
      if (state.genre !== 'all' && it.genre !== state.genre) return;
      if (state.oshiOnly && !oshiHits(it, oshiList).length) return;
      if (it.deadline) {
        var d = daysLeft(it.deadline);
        if (d >= 0 && d <= 21) rows.push({ it: it, days: d, kind: 'deadline' });
      } else if (it.sale_start) {
        var s = daysLeft(it.sale_start);
        if (s >= 0 && s <= 21) rows.push({ it: it, days: s, kind: 'start' });
      }
    });
    rows.sort(function (a, b) { return a.days - b.days; });
    var box = $('upcoming');
    if (!rows.length) {
      box.innerHTML = '<p class="empty">いま締切日・発売日がわかっている申込はありません。下の「申込・チケット」も見てください。</p>';
      return;
    }
    box.innerHTML = rows.slice(0, 20).map(function (r) {
      var dl = r.kind === 'deadline';
      var big = r.days === 0 ? '今日' : r.days;
      var unit = r.days === 0 ? '' : '日後';
      return '<a class="stub' + (dl ? ' is-deadline' : '') + '" href="' + esc(r.it.link) + '" target="_blank" rel="noopener">' +
        '<span class="stub-date"><span class="stub-days">' + big + '</span><span class="stub-unit">' + unit + '</span>' +
        '<span class="stub-kind">' + (dl ? md(r.it.deadline) + '締切' : md(r.it.sale_start) + '開始') + '</span></span>' +
        '<span class="stub-body">' + esc(r.it.title) + '</span></a>';
    }).join('');
  }

  function card(it, oshiList) {
    var isNew = it.added && Date.now() - new Date(it.added).getTime() < DAY;
    var hits = oshiHits(it, oshiList);
    var chips = hits.map(function (n) { return '<span class="chip is-oshi">' + esc(n) + '</span>'; })
      .concat((it.areas || []).map(function (a) { return '<span class="chip">' + esc(a) + '</span>'; }));
    var side = '';
    if (it.deadline) {
      side = '<span class="side-date is-deadline"><b>' + md(it.deadline) + '</b>締切</span>';
    } else if (it.sale_start) {
      side = '<span class="side-date"><b>' + md(it.sale_start) + '</b>受付開始</span>';
    } else if (it.dates && it.dates.length) {
      side = '<span class="side-date"><b>' + md(it.dates[0]) + '</b>' + (it.dates.length > 1 ? 'ほか' : '') + '</span>';
    }
    var img = it.image ? '<img class="card-thumb" src="' + esc(it.image) + '" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">' : '';
    return '<article class="card is-' + esc(it.genre) + '">' +
      '<div class="card-main"><div class="card-text">' +
        '<div class="card-meta">' + (isNew ? '<span class="new">NEW</span>' : '') +
          '<span class="type-label t-' + esc(it.type) + '">' + esc(TYPE_NAME[it.type] || '') + '</span>' +
          '<span>' + esc(GENRE_NAME[it.genre] || '') + '</span>' +
          '<span>' + esc(it.source || '') + '</span><span>' + ago(it.published) + '</span></div>' +
        '<h3 class="card-title"><a href="' + esc(it.link) + '" target="_blank" rel="noopener">' + esc(it.title) + '</a></h3>' +
        (chips.length ? '<div class="chips">' + chips.join('') + '</div>' : '') +
      '</div>' + img + '</div>' +
      '<div class="card-side"><button class="save" type="button" data-save="' + esc(it.id) + '" aria-pressed="' + (saved[it.id] ? 'true' : 'false') +
        '" aria-label="気になるに追加">★</button>' + side + '</div>' +
      '</article>';
  }

  function render() {
    var oshiList = oshiAll();
    document.querySelectorAll('.genre-btn').forEach(function (b) {
      b.setAttribute('aria-pressed', b.dataset.genre === state.genre ? 'true' : 'false');
    });
    document.querySelectorAll('.type-chip').forEach(function (b) {
      b.setAttribute('aria-pressed', b.dataset.type === state.type ? 'true' : 'false');
    });
    renderUpcoming(oshiList);
    var list = data.items.filter(function (it) { return matches(it, oshiList); });
    $('count').textContent = list.length + '件';
    var box = $('cards');
    if (!list.length) {
      box.innerHTML = '<p class="empty">条件に合う情報がありません。種類やエリアを「すべて」「全国」に戻してみてください。</p>';
    } else {
      box.innerHTML = list.slice(0, state.shown).map(function (it) { return card(it, oshiList); }).join('');
    }
    $('more').hidden = list.length <= state.shown;
  }

  // ---- 操作 ----
  function setup() {
    $('type-chips').innerHTML = TYPES.map(function (t) {
      return '<button type="button" class="type-chip" data-type="' + t[0] + '" aria-pressed="false">' + t[1] + '</button>';
    }).join('');

    document.querySelector('.genre-switch').addEventListener('click', function (e) {
      var b = e.target.closest('.genre-btn');
      if (!b) return;
      state.genre = b.dataset.genre; state.shown = PAGE;
      save('warauta.genre', state.genre);
      render();
    });
    $('type-chips').addEventListener('click', function (e) {
      var b = e.target.closest('.type-chip');
      if (!b) return;
      state.type = b.dataset.type; state.shown = PAGE;
      render();
    });
    $('area').addEventListener('change', function (e) { state.area = e.target.value; state.shown = PAGE; render(); });
    $('q').addEventListener('input', function (e) { state.q = e.target.value.trim(); state.shown = PAGE; render(); });
    $('oshi-only').addEventListener('change', function (e) { state.oshiOnly = e.target.checked; state.shown = PAGE; render(); });
    $('saved-only').addEventListener('change', function (e) { state.savedOnly = e.target.checked; state.shown = PAGE; render(); });
    $('more').addEventListener('click', function () { state.shown += PAGE; render(); });

    $('cards').addEventListener('click', function (e) {
      var b = e.target.closest('[data-save]');
      if (!b) return;
      var id = b.dataset.save;
      if (saved[id]) delete saved[id]; else saved[id] = true;
      save('warauta.saved', saved);
      b.setAttribute('aria-pressed', saved[id] ? 'true' : 'false');
    });

    $('oshi-form').addEventListener('submit', function (e) {
      e.preventDefault();
      var name = $('oshi-input').value.trim();
      if (!name) return;
      var hidden = hiddenOshi.indexOf(name);
      if (hidden >= 0) { hiddenOshi.splice(hidden, 1); save('warauta.oshiHidden', hiddenOshi); }
      if (!oshiAll().some(function (o) { return o.name.toLowerCase() === name.toLowerCase(); })) {
        myOshi.push({ name: name, genre: state.genre === 'artist' ? 'artist' : (state.genre === 'geinin' ? 'geinin' : guessGenre(name)) });
        save('warauta.oshi', myOshi);
      }
      $('oshi-input').value = '';
      renderOshi(); render();
    });
    $('oshi-list').addEventListener('click', function (e) {
      var b = e.target.closest('[data-remove]');
      if (!b) return;
      var name = b.dataset.remove;
      var before = myOshi.length;
      myOshi = myOshi.filter(function (o) { return o.name !== name; });
      if (myOshi.length === before) { hiddenOshi.push(name); save('warauta.oshiHidden', hiddenOshi); }
      save('warauta.oshi', myOshi);
      renderOshi(); render();
    });
  }

  // 名前が載っている記事のジャンルが多い方にする
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
      data = json;
      data.items = data.items || [];
      data.oshi = data.oshi || { geinin: [], artist: [] };
      if (json.updated) {
        var u = new Date(json.updated);
        $('updated').textContent = (u.getMonth() + 1) + '月' + u.getDate() + '日 ' +
          ('0' + u.getHours()).slice(-2) + ':' + ('0' + u.getMinutes()).slice(-2) + ' 更新（1日3回自動）';
      }
      fillAreas(); renderOshi(); render();
    })
    .catch(function () {
      $('cards').innerHTML = '<p class="empty">情報をまだ読み込めません。初回の自動更新が終わると表示されます（README の手順をご確認ください）。</p>';
      $('upcoming').innerHTML = '';
      renderOshi();
    });
})();
