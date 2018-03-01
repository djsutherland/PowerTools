// based on https://clipboardjs.com/assets/scripts/tooltips.js
function clearTooltip(e) {
  e.currentTarget.setAttribute('class', 'btn');
  e.currentTarget.removeAttribute('aria-label');
}
function showTooltip(elem, msg) {
  elem.setAttribute('class', 'btn tooltipped tooltipped-s');
  elem.setAttribute('aria-label', msg);
}

if (Clipboard.isSupported()) {
  var clipboard = new Clipboard('.clip');
  clipboard.on('success', function (e) {
    showTooltip(e.trigger, 'Copied!');
  });
  clipboard.on('error', function (e) {
    showTooltip(e.trigger, 'Error :(');
    console.error(e);
    console.error(e.action);
    console.error(e.trigger);
  });

  $('.clip').on('mouseleave', clearTooltip);
  $('.clip').on('blur', clearTooltip);
} else {
  $('.clip-parent').hide();
}
