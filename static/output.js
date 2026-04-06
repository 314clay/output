/* Output — Client-side JavaScript */

(function () {
  'use strict';

  const channelId = document.body.dataset.channel;
  if (!channelId) return; // index page, no SSE needed

  const isDashboard = document.body.dataset.dashboard === 'true';
  const itemList = document.getElementById('item-list');
  const emptyMsg = document.getElementById('empty-msg');

  // ========================================
  // SSE Connection
  // ========================================
  let evtSource = null;
  let reconnectTimer = null;

  function connect() {
    if (evtSource) {
      evtSource.close();
    }
    evtSource = new EventSource(`/api/listen/${channelId}`);

    evtSource.addEventListener('new_item', function (e) {
      const data = JSON.parse(e.data);
      if (emptyMsg) emptyMsg.remove();
      const frag = document.createElement('div');
      frag.innerHTML = data.html;
      const el = frag.firstElementChild;
      itemList.prepend(el);
      // Initialize any chart or JSON in the new item
      initChartsIn(el);
      initJsonIn(el);
      initDiffsIn(el);
      initMathIn(el);
    });

    evtSource.addEventListener('append_log', function (e) {
      const data = JSON.parse(e.data);
      const logEl = document.getElementById('log-' + data.item_id);
      if (!logEl) return;
      data.lines.forEach(function (line) {
        const div = document.createElement('div');
        div.className = 'log-line ' + (data.level || '');
        div.textContent = line;
        logEl.appendChild(div);
      });
      // Auto-scroll to bottom
      logEl.scrollTop = logEl.scrollHeight;
    });

    evtSource.addEventListener('item_deleted', function (e) {
      const data = JSON.parse(e.data);
      const el = document.getElementById('item-' + data.item_id);
      if (el) {
        el.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
        el.style.opacity = '0';
        el.style.transform = 'scale(0.95)';
        setTimeout(function () { el.remove(); }, 300);
      }
    });

    evtSource.addEventListener('slot_update', function (e) {
      const data = JSON.parse(e.data);
      const container = document.getElementById('slot-content-' + data.slot_name);
      if (!container) return;
      container.innerHTML = data.html;
      initChartsIn(container);
      initJsonIn(container);
      initDiffsIn(container);
      initMathIn(container);
    });

    evtSource.addEventListener('channel_cleared', function () {
      if (isDashboard) {
        document.querySelectorAll('.slot-content').forEach(function (el) {
          el.innerHTML = '<div class="slot-empty">--</div>';
        });
      } else {
        itemList.innerHTML = '<div class="channel-empty" id="empty-msg">Waiting for output...</div>';
      }
    });

    evtSource.addEventListener('template_updated', function () {
      window.location.reload();
    });

    evtSource.addEventListener('heartbeat', function () {
      // Connection alive, nothing to do
    });

    evtSource.onerror = function () {
      evtSource.close();
      // Reconnect after 3 seconds
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(connect, 3000);
    };
  }

  connect();

  // ========================================
  // Chart.js initialization
  // ========================================
  function initChartsIn(root) {
    const canvases = root.querySelectorAll('canvas[data-chart]');
    canvases.forEach(function (canvas) {
      if (canvas._chartInstance) return;
      try {
        const config = JSON.parse(canvas.dataset.chart);
        canvas._chartInstance = new Chart(canvas, config);
      } catch (err) {
        console.error('Chart init error:', err);
      }
    });
  }

  // Initialize charts already on the page
  if (typeof Chart !== 'undefined') {
    initChartsIn(document);
  } else {
    // Wait for Chart.js to load
    window.addEventListener('load', function () {
      if (typeof Chart !== 'undefined') initChartsIn(document);
    });
  }

  // ========================================
  // JSON tree renderer
  // ========================================
  function renderJsonTree(val, key) {
    if (val === null) {
      return (key !== undefined ? '<span class="json-key">' + escHtml(String(key)) + '</span>: ' : '') +
        '<span class="json-null">null</span>';
    }
    if (typeof val === 'boolean') {
      return (key !== undefined ? '<span class="json-key">' + escHtml(String(key)) + '</span>: ' : '') +
        '<span class="json-bool">' + val + '</span>';
    }
    if (typeof val === 'number') {
      return (key !== undefined ? '<span class="json-key">' + escHtml(String(key)) + '</span>: ' : '') +
        '<span class="json-number">' + val + '</span>';
    }
    if (typeof val === 'string') {
      return (key !== undefined ? '<span class="json-key">' + escHtml(String(key)) + '</span>: ' : '') +
        '<span class="json-string">"' + escHtml(val) + '"</span>';
    }
    if (Array.isArray(val)) {
      if (val.length === 0) {
        return (key !== undefined ? '<span class="json-key">' + escHtml(String(key)) + '</span>: ' : '') + '[]';
      }
      let html = '<details open><summary>' +
        (key !== undefined ? '<span class="json-key">' + escHtml(String(key)) + '</span>: ' : '') +
        'Array[' + val.length + ']</summary><div style="margin-left:16px">';
      val.forEach(function (item, i) {
        html += '<div>' + renderJsonTree(item, i) + '</div>';
      });
      html += '</div></details>';
      return html;
    }
    if (typeof val === 'object') {
      const keys = Object.keys(val);
      if (keys.length === 0) {
        return (key !== undefined ? '<span class="json-key">' + escHtml(String(key)) + '</span>: ' : '') + '{}';
      }
      let html = '<details open><summary>' +
        (key !== undefined ? '<span class="json-key">' + escHtml(String(key)) + '</span>: ' : '') +
        '{' + keys.length + ' keys}</summary><div style="margin-left:16px">';
      keys.forEach(function (k) {
        html += '<div>' + renderJsonTree(val[k], k) + '</div>';
      });
      html += '</div></details>';
      return html;
    }
    return String(val);
  }

  function escHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function initJsonIn(root) {
    root.querySelectorAll('.output-json[data-json]').forEach(function (el) {
      if (el._jsonRendered) return;
      try {
        const data = JSON.parse(el.dataset.json);
        el.innerHTML = renderJsonTree(data);
        el._jsonRendered = true;
      } catch (err) {
        el.textContent = el.dataset.json;
      }
    });
  }

  initJsonIn(document);

  // ========================================
  // Diff viewer initialization
  // ========================================
  function initDiffsIn(root) {
    root.querySelectorAll('.output-diff[data-diff]').forEach(function (el) {
      if (el._diffRendered) return;
      if (typeof Diff2HtmlUI !== 'undefined') {
        try {
          var diff2htmlUi = new Diff2HtmlUI(el, el.dataset.diff, {
            drawFileList: false,
            outputFormat: 'side-by-side',
            matching: 'lines'
          });
          diff2htmlUi.draw();
          el._diffRendered = true;
        } catch (err) {
          el.innerHTML = '<pre>' + escHtml(el.dataset.diff) + '</pre>';
        }
      } else {
        el.innerHTML = '<pre>' + escHtml(el.dataset.diff) + '</pre>';
      }
    });
  }

  initDiffsIn(document);

  // ========================================
  // KaTeX math initialization
  // ========================================
  function initMathIn(root) {
    root.querySelectorAll('.output-math[data-math]').forEach(function (el) {
      if (el._mathRendered) return;
      if (typeof katex !== 'undefined') {
        try {
          katex.render(el.dataset.math, el, {
            displayMode: el.dataset.display !== 'inline',
            throwOnError: false,
          });
          el._mathRendered = true;
        } catch (err) {
          el.textContent = el.dataset.math;
        }
      } else {
        el.textContent = el.dataset.math;
      }
    });
  }

  // KaTeX loads with defer, so wait for it
  if (typeof katex !== 'undefined') {
    initMathIn(document);
  } else {
    window.addEventListener('load', function () {
      initMathIn(document);
    });
  }

  // ========================================
  // Relative time updater
  // ========================================
  function updateTimestamps() {
    document.querySelectorAll('.item-timestamp[data-ts]').forEach(function (el) {
      const ts = el.dataset.ts;
      if (!ts) return;
      const date = new Date(ts);
      const now = new Date();
      const diffMs = now - date;
      const diffSec = Math.floor(diffMs / 1000);
      const diffMin = Math.floor(diffSec / 60);
      const diffHour = Math.floor(diffMin / 60);
      const diffDay = Math.floor(diffHour / 24);

      if (diffSec < 10) {
        el.textContent = 'just now';
      } else if (diffSec < 60) {
        el.textContent = diffSec + 's ago';
      } else if (diffMin < 60) {
        el.textContent = diffMin + 'm ago';
      } else if (diffHour < 24) {
        el.textContent = diffHour + 'h ago';
      } else {
        el.textContent = diffDay + 'd ago';
      }
    });
  }

  updateTimestamps();
  setInterval(updateTimestamps, 60000);

})();
