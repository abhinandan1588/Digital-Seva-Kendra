// Digital Seva Kendra - public site JS (vanilla)
document.addEventListener('DOMContentLoaded', function () {
  // Auto-dismiss flash messages after 6s
  document.querySelectorAll('.flash-area .alert').forEach(function (el) {
    setTimeout(function () {
      try { bootstrap.Alert.getOrCreateInstance(el).close(); } catch (e) {}
    }, 6000);
  });

  // File input: show selected names
  document.querySelectorAll('input[type="file"]').forEach(function (input) {
    input.addEventListener('change', function () {
      var names = Array.from(input.files || []).map(function (f) { return f.name; }).join(', ');
      if (!names) return;
      var help = input.parentElement.querySelector('.selected-files-note');
      if (!help) {
        help = document.createElement('div');
        help.className = 'form-text selected-files-note text-success';
        input.parentElement.appendChild(help);
      }
      help.textContent = names;
    });
  });
});
