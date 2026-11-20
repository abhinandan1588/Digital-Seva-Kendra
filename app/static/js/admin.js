// Digital Seva Kendra - admin panel JS (vanilla)
document.addEventListener('DOMContentLoaded', function () {
  // Mobile sidebar toggle
  var toggle = document.getElementById('sidebarToggle');
  var sidebar = document.getElementById('adminSidebar');
  if (toggle && sidebar) {
    toggle.addEventListener('click', function () { sidebar.classList.toggle('show'); });
    document.addEventListener('click', function (e) {
      if (window.innerWidth < 992 && sidebar.classList.contains('show') &&
          !sidebar.contains(e.target) && e.target !== toggle && !toggle.contains(e.target)) {
        sidebar.classList.remove('show');
      }
    });
  }

  // Confirm dialogs on dangerous forms
  document.querySelectorAll('form[data-confirm]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      if (!window.confirm(form.getAttribute('data-confirm'))) e.preventDefault();
    });
  });

  // Auto-dismiss alerts
  document.querySelectorAll('.alert-dismissible').forEach(function (el) {
    setTimeout(function () {
      try { bootstrap.Alert.getOrCreateInstance(el).close(); } catch (e) {}
    }, 8000);
  });
});
