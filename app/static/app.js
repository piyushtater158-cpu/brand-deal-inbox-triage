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
})();
