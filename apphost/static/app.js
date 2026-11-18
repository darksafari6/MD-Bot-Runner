// Small helpers only. The panel works without JavaScript; this adds polish.

document.addEventListener("htmx:responseError", (event) => {
  const detail = event.detail || {};
  const xhr = detail.xhr;
  let message = "Request failed";
  if (xhr) {
    try {
      const parsed = JSON.parse(xhr.responseText);
      message = parsed.detail || parsed.message || message;
    } catch (_) {
      message = xhr.responseText || message;
    }
  }
  const target = detail.target;
  if (target) {
    const box = document.createElement("div");
    box.className = "error-box";
    box.textContent = message;
    target.appendChild(box);
    setTimeout(() => box.remove(), 8000);
  } else {
    console.error(message);
  }
});

// Keep log panes scrolled to the newest line unless the user scrolled up.
document.addEventListener("htmx:afterSwap", (event) => {
  const el = event.target;
  if (el && el.classList && el.classList.contains("log")) {
    el.scrollTop = el.scrollHeight;
  }
});

// Show the source field that matches the selected radio.
document.addEventListener("change", (event) => {
  const form = event.target.closest("form");
  if (!form) return;
  const chosen = form.querySelector('input[name="source"]:checked');
  if (!chosen) return;
  const path = form.querySelector('[name="path"]');
  const url = form.querySelector('[name="url"]');
  if (!path || !url) return;
  const kind = chosen.value;
  path.closest("label").style.opacity = kind === "folder" ? "1" : "0.35";
  url.closest("label").style.opacity = kind === "git" ? "1" : "0.35";
});
