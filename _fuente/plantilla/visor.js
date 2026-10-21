// Carrusel de la ficha (se desliza con el dedo o las flechas) y visor de fotos a pantalla completa.
(function () {
  // ---- Carrusel ----
  var car = document.querySelector('.carrusel');
  if (car) {
    var cinta = car.querySelector('.car-tira');
    var total = cinta.children.length;
    var n = car.querySelector('.car-n');
    function idx() { return Math.round(cinta.scrollLeft / cinta.clientWidth); }
    function ir(i) { cinta.scrollTo({ left: ((i + total) % total) * cinta.clientWidth, behavior: 'smooth' }); }
    var ant = car.querySelector('.car-ant'), sig = car.querySelector('.car-sig');
    if (ant) ant.addEventListener('click', function () { ir(idx() - 1); });
    if (sig) sig.addEventListener('click', function () { ir(idx() + 1); });
    cinta.addEventListener('scroll', function () {
      window.requestAnimationFrame(function () { if (n) n.textContent = idx() + 1; });
    });
    car.querySelector('.car-pos').addEventListener('click', function () { abrir(idx()); });
    cinta.querySelectorAll('img').forEach(function (img) {
      img.addEventListener('click', function () { abrir(+img.dataset.i); });
    });
  }

  // ---- Visor ----
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

  visor.querySelector('.cerrar').addEventListener('click', cerrar);
  tira.addEventListener('scroll', function () { window.requestAnimationFrame(marcar); });
  document.addEventListener('keydown', function (e) {
    if (visor.hidden) {
      if (car && e.key === 'ArrowRight') car.querySelector('.car-sig') && car.querySelector('.car-sig').click();
      if (car && e.key === 'ArrowLeft') car.querySelector('.car-ant') && car.querySelector('.car-ant').click();
      return;
    }
    if (e.key === 'Escape') cerrar();
    if (e.key === 'ArrowRight') tira.scrollBy({ left: tira.clientWidth });
    if (e.key === 'ArrowLeft') tira.scrollBy({ left: -tira.clientWidth });
  });
})();
