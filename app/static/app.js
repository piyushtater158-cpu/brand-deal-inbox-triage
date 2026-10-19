// Copy-to-clipboard for reply drafts. The only script besides HTMX: without it the
// textarea is still selectable and every action still records the decision.
(function () {
  function copyFrom(selector) {
    var box = document.querySelector(selector);
    if (!box) return;
    var done = function () {
      var reply = box.closest(".reply");
      if (!reply) return;
      reply.classList.add("is-copied");
      var now = new Date();
      var hhmm = String(now.getHours()).padStart(2, "0") + ":" + String(now.getMinutes()).padStart(2, "0");
      reply.querySelectorAll("[data-copy-status]").forEach(function (el) {
        el.textContent = "Copied " + hhmm + " · not sent — paste it into the creator's mailbox.";
      });
    };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(box.value).then(done, function () { box.select(); });
    } else {
      box.select();
      try { if (document.execCommand("copy")) done(); } catch (e) { /* text stays selected */ }
    }
  }

  document.addEventListener("click", function (evt) {
    var trigger = evt.target.closest("[data-copy]");
    if (trigger) copyFrom(trigger.getAttribute("data-copy"));
  });

  // Forms that can wait on a free AI model say so instead of looking frozen.
  function markBusy(form) {
    var msg = form.getAttribute("data-busy");
    var btn = form.querySelector("button[type=submit], button:not([type])");
    if (!msg || !btn || btn.dataset.busy) return;
    btn.dataset.busy = "1";
    btn.setAttribute("aria-busy", "true");
    btn.textContent = msg;
  }
  document.addEventListener("submit", function (evt) {
    if (evt.target.matches("form[data-busy]")) markBusy(evt.target);
  });
})();
