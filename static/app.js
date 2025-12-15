// Small helper: set default datetime-local to now (local timezone)
document.addEventListener('DOMContentLoaded', function () {
  var el = document.getElementById('logged_at');
  if (!el) return;
  if (!el.value) {
    var now = new Date();
    now.setSeconds(0,0);
    var tzOffset = -now.getTimezoneOffset();
    var diff = tzOffset >= 0 ? '+' : '-';
    var pad = function(n){ return (n < 10 ? '0' : '') + n };
    var local = now.getFullYear() + '-' + pad(now.getMonth()+1) + '-' + pad(now.getDate()) + 'T' + pad(now.getHours()) + ':' + pad(now.getMinutes());
    el.value = local;
  }
});

// Handle ISBN add form via AJAX to immediately update the book select
document.addEventListener('DOMContentLoaded', function () {
  var form = document.querySelector('form[action="/add_book"]');
  if (!form) return;
  form.addEventListener('submit', function (ev) {
    ev.preventDefault();
    var fd = new FormData(form);
    fetch(form.action, {
      method: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      body: fd,
      credentials: 'same-origin'
    }).then(function (res) {
      // Try to parse JSON when possible
      var ctype = res.headers.get('content-type') || '';
      if (ctype.indexOf('application/json') !== -1) {
        return res.json().then(function(data) { return { res: res, data: data }; });
      }
      // If not JSON, try to get text (could be an HTML redirect)
      return res.text().then(function(text){ return { res: res, data: null, text: text }; });
    }).then(function (obj) {
      var res = obj.res, data = obj.data, text = obj.text;
      if (data && data.ok) {
        // find book select and add new option
        var sel = document.querySelector('select[name="isbn"]');
        if (sel) {
          // avoid duplicate
          var exists = false;
          for (var i = 0; i < sel.options.length; i++) {
            if (sel.options[i].value === data.isbn) { exists = true; break; }
          }
          if (!exists) {
            var opt = document.createElement('option');
            opt.value = data.isbn;
            opt.text = (data.title || data.isbn) + ' — ' + data.isbn;
            sel.appendChild(opt);
          }
          // select the newly added book
          sel.value = data.isbn;
        }
        // show success flash (simple alert fallback)
        alert('書籍を登録しました: ' + (data.title || data.isbn));
        form.reset();
      } else if (data && !data.ok) {
        var msg = data.error || data.message || '書籍登録に失敗しました。';
        alert('登録失敗: ' + msg);
      } else {
        // non-json response (likely a redirect or HTML) -> show small message and reload to reflect changes
        alert('サーバーから予期しないレスポンスを受け取りました。ページをリロードします。');
        window.location.reload();
      }
    }).catch(function (err) {
      console.error(err);
      alert('通信エラーが発生しました。開発者ツールのコンソールを確認してください。');
    });
  });
});

// Handle user add form via AJAX to immediately update the user select
document.addEventListener('DOMContentLoaded', function () {
  var uform = document.querySelector('form[action="/add_user"]');
  if (!uform) return;
  uform.addEventListener('submit', function (ev) {
    ev.preventDefault();
    var fd = new FormData(uform);
    fetch(uform.action, {
      method: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      body: fd,
      credentials: 'same-origin'
    }).then(function (res) {
      var ctype = res.headers.get('content-type') || '';
      if (ctype.indexOf('application/json') !== -1) {
        return res.json().then(function(data) { return { res: res, data: data }; });
      }
      return res.text().then(function(text){ return { res: res, data: null, text: text }; });
    }).then(function (obj) {
      var data = obj.data;
      if (data && data.ok) {
        var sel = document.querySelector('select[name="user_id"]');
        if (sel) {
          var exists = false;
          for (var i = 0; i < sel.options.length; i++) {
            if (sel.options[i].value === String(data.user_id)) { exists = true; break; }
          }
          if (!exists) {
            var opt = document.createElement('option');
            opt.value = data.user_id;
            opt.text = data.name + ' (ID: ' + data.user_id + ')';
            sel.appendChild(opt);
          }
          sel.value = data.user_id;
        }
        alert('ユーザーを追加しました: ' + data.name);
        uform.reset();
      } else if (data && !data.ok) {
        alert('ユーザー登録失敗: ' + (data.error || data.message || '不明なエラー'));
      } else {
        alert('サーバーから予期しないレスポンスを受け取りました。リロードします。');
        window.location.reload();
      }
    }).catch(function (err) {
      console.error(err);
      alert('通信エラーが発生しました。コンソールを確認してください。');
    });
  });
});

// --- Simple camera barcode scanner using the BarcodeDetector API (fallback: clipboard paste) ---
document.addEventListener('DOMContentLoaded', function () {
  var startBtn = document.getElementById('scan-start');
  if (!startBtn) return; // scanner UI not present
  var stopBtn = document.getElementById('scan-stop');
  var pasteBtn = document.getElementById('paste-isbn');
  var video = document.getElementById('scanner-video');
  var resultSpan = document.getElementById('scanned_result');
  // prefer the existing ISBN input if present
  var isbnInput = document.querySelector('input[name="isbn_new"]') || document.querySelector('input[name="isbn"]') || null;
  var stream = null;

  async function startScan() {
    if (!('BarcodeDetector' in window)) {
      alert('このブラウザはカメラ直接スキャンに対応していません。ScanAppでスキャン→「クリップボード貼り付け」を使ってください。');
      return;
    }
    var detector;
    try {
      detector = new BarcodeDetector({formats: ['ean_13']});
    } catch (err) {
      console.error('BarcodeDetector init error', err);
      alert('BarcodeDetector の初期化に失敗しました。ブラウザの対応状況を確認してください。');
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({video: {facingMode: 'environment'}});
      video.srcObject = stream;
      await video.play();
      startBtn.disabled = true;
      stopBtn.disabled = false;
      // detection loop
      var running = true;
      stopBtn.addEventListener('click', function onStop() { running = false; stopScan(); stopBtn.removeEventListener('click', onStop); });
      (async function loop() {
        while (running && stream && stream.getTracks().length) {
          try {
            const barcodes = await detector.detect(video);
            if (barcodes && barcodes.length > 0) {
              const code = barcodes[0].rawValue || (barcodes[0].rawData && new TextDecoder().decode(barcodes[0].rawData));
              if (code) {
                if (isbnInput) isbnInput.value = code;
                resultSpan.textContent = code;
                // stop after first successful read
                running = false;
                stopScan();
                break;
              }
            }
          } catch (err) {
            console.error('detect error', err);
            // break to avoid tight error loop
            break;
          }
          await new Promise(r => setTimeout(r, 300));
        }
      })();
    } catch (err) {
      console.error(err);
      alert('カメラの起動に失敗しました。サイトのカメラ許可を確認してください。');
    }
  }

  function stopScan() {
    startBtn.disabled = false;
    stopBtn.disabled = true;
    if (video && video.srcObject) {
      video.pause();
      var tracks = video.srcObject.getTracks();
      tracks.forEach(function (t) { t.stop(); });
      video.srcObject = null;
    }
    stream = null;
  }

  startBtn.addEventListener('click', startScan);
  stopBtn.addEventListener('click', stopScan);

  pasteBtn.addEventListener('click', function () {
    if (!navigator.clipboard) {
      alert('クリップボードAPIが利用できません。手動で貼り付けてください。');
      return;
    }
    navigator.clipboard.readText().then(function (text) {
      if (!text) { alert('クリップボードにテキストがありません。'); return; }
      var trimmed = text.trim();
      if (isbnInput) isbnInput.value = trimmed;
      resultSpan.textContent = trimmed;
    }).catch(function (err) {
      console.error('clipboard read failed', err);
      alert('クリップボードの読み取りに失敗しました。権限を確認してください。');
    });
  });
});
