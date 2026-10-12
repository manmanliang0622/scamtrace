// 預覽頁：選取文字後自動填入「要遮罩的文字」；送出分析時顯示等待訊息。
(function () {
  var area = document.getElementById('preview-text');
  var input = document.getElementById('fragment');
  if (area && input) {
    var capture = function () {
      var sel = window.getSelection();
      if (!sel || sel.isCollapsed || !area.contains(sel.anchorNode)) return;
      var text = sel.toString().trim();
      if (text && text.length <= 100 && text.indexOf('\n') < 0) input.value = text;
    };
    area.addEventListener('mouseup', capture);
    area.addEventListener('touchend', function () { setTimeout(capture, 0); });
  }

  var form = document.getElementById('confirm-form');
  if (form) {
    form.addEventListener('submit', function () {
      var btn = document.getElementById('confirm-btn');
      // 延後停用，確保按鈕值仍隨表單送出
      setTimeout(function () { btn.disabled = true; }, 0);
      document.getElementById('analyzing').hidden = false;
    });
  }
})();
