// Visor de fotos: se abre al tocar una foto; se desliza con el dedo o con las flechas.
(function () {
  var visor = document.querySelector('.visor');
  if (!visor) return;
  var tira = visor.querySelector('.tira');
  var figs = tira.querySelectorAll('figure');
  var pos = visor.querySelector('.pos');

  function cargar(i) {
    [i - 1, i, i + 1].forEach(function (j) {
      var img = figs[j] && figs[j].querySelector('img');
      if (img && img.dataset.src) { img.src = img.dataset.src; delete img.dataset.src; }
    });
  }
  function actual() { return Math.round(tira.scrollLeft / tira.clientWidth); }
  function marcar() { var i = actual(); pos.textContent = (i + 1) + ' / ' + figs.length; cargar(i); }

  function abrir(i) {
    visor.hidden = false;
    document.body.style.overflow = 'hidden';
    cargar(i);
    tira.scrollLeft = i * tira.clientWidth;
    marcar();
    visor.querySelector('.cerrar').focus();
  }
  function cerrar() { visor.hidden = true; document.body.style.overflow = ''; }

  document.querySelectorAll('[data-i]').forEach(function (b) {
    b.addEventListener('click', function () { abrir(+b.dataset.i); });
  });
  visor.querySelector('.cerrar').addEventListener('click', cerrar);
  tira.addEventListener('scroll', function () { window.requestAnimationFrame(marcar); });
  document.addEventListener('keydown', function (e) {
    if (visor.hidden) return;
    if (e.key === 'Escape') cerrar();
    if (e.key === 'ArrowRight') tira.scrollBy({ left: tira.clientWidth });
    if (e.key === 'ArrowLeft') tira.scrollBy({ left: -tira.clientWidth });
  });
})();
