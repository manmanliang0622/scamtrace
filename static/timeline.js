// 風險時間軸：橫軸為訊息序號、縱軸為風險分數；背景依階段分色；標示轉折點。
(function () {
  var box = document.getElementById('timeline');
  if (!box) return;
  var tip = document.getElementById('timeline-tip');
  var NS = 'http://www.w3.org/2000/svg';
  var STAGE_NAMES = { contact: '接觸', rapport: '建立關係', setup: '鋪陳', action: '要求行動', pressure: '施壓', none: '一般' };
  var TACTIC_NAMES = { reciprocity: '互惠', commitment: '承諾一致', social_proof: '社會認同', liking: '喜好',
                       authority: '權威', scarcity: '稀少性', unity: '團結', urgency_threat: '威脅恐嚇' };
  var turning = parseInt(box.dataset.turning, 10) || null;
  var data = [];

  function el(name, attrs, parent) {
    var node = document.createElementNS(NS, name);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (parent) parent.appendChild(node);
    return node;
  }

  function messageText(seq) {
    var p = document.querySelector('#msg-' + seq + ' [data-text]');
    var text = p ? p.textContent.trim() : '';
    return text.length > 60 ? text.slice(0, 60) + '…' : text;
  }

  function scrollToMessage(seq) {
    var target = document.getElementById('msg-' + seq);
    if (!target) return;
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    target.classList.add('flash-target');
    setTimeout(function () { target.classList.remove('flash-target'); }, 1600);
  }

  function draw() {
    box.querySelectorAll('svg').forEach(function (s) { s.remove(); });
    if (!data.length) return;
    var W = Math.max(box.clientWidth, 300), H = 240;
    var m = { top: 22, right: 12, bottom: 26, left: 34 };
    var iw = W - m.left - m.right, ih = H - m.top - m.bottom;
    var n = data.length;
    var step = iw / n;
    var x = function (i) { return m.left + step * (i + 0.5); };
    var y = function (v) { return m.top + ih - (v / 100) * ih; };

    var svg = el('svg', { viewBox: '0 0 ' + W + ' ' + H, preserveAspectRatio: 'none' });
    svg.style.height = H + 'px';

    // 階段背景
    data.forEach(function (d, i) {
      el('rect', { x: m.left + step * i, y: m.top, width: step + 0.5, height: ih, 'class': 'stage-' + d.stage }, svg);
    });

    // 座標軸與格線
    var axis = el('g', { 'class': 'axis' }, svg);
    [0, 40, 70, 100].forEach(function (v) {
      el('line', { x1: m.left, x2: W - m.right, y1: y(v), y2: y(v) }, axis);
      el('text', { x: m.left - 6, y: y(v) + 4, 'text-anchor': 'end' }, axis).textContent = v;
    });
    var tickEvery = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(iw / 40))));
    data.forEach(function (d, i) {
      if (i % tickEvery === 0 || i === n - 1) {
        el('text', { x: x(i), y: H - 8, 'text-anchor': 'middle' }, axis).textContent = d.seq;
      }
    });

    // 轉折點
    if (turning) {
      var ti = data.findIndex(function (d) { return d.seq === turning; });
      if (ti >= 0) {
        el('line', { x1: x(ti), x2: x(ti), y1: m.top - 4, y2: m.top + ih, 'class': 'turning-line' }, svg);
        var label = el('text', { x: x(ti), y: m.top - 8, 'class': 'turning-text',
                                 'text-anchor': ti > n * 0.8 ? 'end' : 'start' }, svg);
        label.textContent = '轉折點 #' + turning;
      }
    }

    // 折線與資料點
    el('polyline', { points: data.map(function (d, i) { return x(i) + ',' + y(d.risk); }).join(' '),
                     'class': 'risk-line' }, svg);
    var r = n > 200 ? 0 : n > 80 ? 2 : 3.5;
    var pts = data.map(function (d, i) { return el('circle', { cx: x(i), cy: y(d.risk), r: r, 'class': 'pt' }, svg); });
    var hover = el('line', { y1: m.top, y2: m.top + ih, 'class': 'hover-line', visibility: 'hidden' }, svg);

    // 互動：以滑鼠位置找最近的訊息
    var overlay = el('rect', { x: m.left, y: m.top, width: iw, height: ih, fill: 'transparent' }, svg);
    overlay.style.cursor = 'pointer';
    var active = -1;
    function indexAt(evt) {
      var rect = svg.getBoundingClientRect();
      var px = (evt.clientX - rect.left) * (W / rect.width);
      return Math.min(n - 1, Math.max(0, Math.floor((px - m.left) / step)));
    }
    overlay.addEventListener('mousemove', function (evt) {
      var i = indexAt(evt), d = data[i];
      if (active >= 0) pts[active].classList.remove('active');
      pts[i].classList.add('active'); pts[i].setAttribute('r', Math.max(r, 4));
      if (active >= 0 && active !== i) pts[active].setAttribute('r', r);
      active = i;
      hover.setAttribute('x1', x(i)); hover.setAttribute('x2', x(i)); hover.setAttribute('visibility', 'visible');
      var tactics = d.tactics.map(function (c) { return TACTIC_NAMES[c] || c; }).join('、');
      tip.textContent = '#' + d.seq + ' ' + d.speaker + (d.sent_at ? '｜' + d.sent_at : '') +
        '\n風險 ' + d.risk + '｜' + (STAGE_NAMES[d.stage] || d.stage) + (tactics ? '｜' + tactics : '') +
        '\n' + messageText(d.seq);
      tip.hidden = false;
      var left = Math.min(evt.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
      tip.style.left = left + 'px';
      tip.style.top = (evt.clientY + 14) + 'px';
    });
    overlay.addEventListener('mouseleave', function () {
      tip.hidden = true; hover.setAttribute('visibility', 'hidden');
      if (active >= 0) { pts[active].classList.remove('active'); pts[active].setAttribute('r', r); active = -1; }
    });
    overlay.addEventListener('click', function (evt) { scrollToMessage(data[indexAt(evt)].seq); });

    box.appendChild(svg);
  }

  fetch(box.dataset.api, { credentials: 'same-origin' })
    .then(function (res) { if (!res.ok) throw new Error(res.status); return res.json(); })
    .then(function (json) { data = json; draw(); })
    .catch(function () { box.textContent = '時間軸載入失敗，請重新整理頁面。'; });

  var timer;
  window.addEventListener('resize', function () { clearTimeout(timer); timer = setTimeout(draw, 150); });
})();
