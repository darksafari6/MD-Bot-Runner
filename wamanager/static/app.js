// Live status via Server-Sent Events. Keeps the dashboard honest: when the
// stream drops the pill says so instead of pretending everything is fine.
(function () {
  const pill = document.getElementById('live-pill');
  if (!pill || !window.EventSource) return;

  const dot = pill.querySelector('.dot');
  let source = null;
  let retry = 1000;

  function setState(state) {
    pill.classList.toggle('live', state === 'open');
    pill.title = state === 'open' ? 'Connected to the manager' : 'Live stream disconnected';
    if (dot) {
      dot.style.background = state === 'open' ? 'var(--accent)' : 'var(--failed, #f43f5e)';
      dot.style.boxShadow = state === 'open' ? '0 0 6px var(--accent)' : 'none';
    }
  }

  function connect() {
    source = new EventSource('/api/events');
    source.onopen = () => {
      retry = 1000;
      setState('open');
    };
    source.onerror = () => {
      setState('closed');
      source.close();
      // Exponential backoff, capped — the browser default hammers the server.
      setTimeout(connect, retry);
      retry = Math.min(retry * 2, 30000);
    };
    // Status changes refresh the grid; the lightweight parts of the page
    // poll on their own via htmx triggers.
    source.addEventListener('bot', () => {
      const grid = document.getElementById('bot-grid');
      if (grid && window.htmx) window.htmx.trigger(grid, 'refresh');
    });
  }

  connect();
})();

// Forms rendered by htmx keep native validation.
document.addEventListener('htmx:validation:validate', function (event) {
  const form = event.detail.elt;
  if (form && form.reportValidity && !form.reportValidity()) {
    event.preventDefault();
  }
});
