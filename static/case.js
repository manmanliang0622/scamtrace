// 結果頁互動：手法標籤標亮依據字句、刪除前確認。
(function () {
  // 標亮：以 textContent 重建內容，訊息文字永遠以純文字插入，不使用 innerHTML
  function highlight(p, evidence) {
    if (p.dataset.original === undefined) p.dataset.original = p.textContent;
    var text = p.dataset.original;
    p.textContent = '';
    var idx = evidence ? text.indexOf(evidence) : -1;
    if (idx < 0) { p.textContent = text; return; }
    p.appendChild(document.createTextNode(text.slice(0, idx)));
    var mark = document.createElement('mark');
    mark.textContent = evidence;
    p.appendChild(mark);
    p.appendChild(document.createTextNode(text.slice(idx + evidence.length)));
  }

  document.querySelectorAll('.tag[data-evidence]').forEach(function (tag) {
    tag.setAttribute('aria-pressed', 'false');
    tag.addEventListener('click', function () {
      var bubble = tag.closest('.bubble');
      var p = bubble.querySelector('[data-text]');
      var on = tag.getAttribute('aria-pressed') !== 'true';
      bubble.querySelectorAll('.tag').forEach(function (t) { t.setAttribute('aria-pressed', 'false'); });
      tag.setAttribute('aria-pressed', on ? 'true' : 'false');
      highlight(p, on ? tag.dataset.evidence : '');
    });
  });

  document.querySelectorAll('form[data-confirm]').forEach(function (form) {
    form.addEventListener('submit', function (evt) {
      if (!window.confirm(form.dataset.confirm)) evt.preventDefault();
    });
  });
})();
