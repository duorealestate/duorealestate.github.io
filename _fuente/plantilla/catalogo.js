// Filtros del portafolio: muestran u ocultan tarjetas ya escritas en la página y las reordenan.
(function () {
  var form = document.querySelector('.filtros');
  var grid = document.querySelector('.grid');
  if (!form || !grid) return;
  var cards = Array.prototype.slice.call(grid.querySelectorAll('.card'));
  var conteo = document.querySelector('.conteo b');
  var vacio = document.querySelector('.vacio');
  var campos = form.querySelectorAll('[data-f]');

  // Recordar los filtros en la URL (?tipo=Casa&sector=…) para poder compartir una búsqueda.
  var params = new URLSearchParams(location.search);
  campos.forEach(function (c) { if (params.get(c.dataset.f)) c.value = params.get(c.dataset.f); });

  function valor(f) { var c = form.querySelector('[data-f="' + f + '"]'); return c ? c.value : ''; }

  function aplicar() {
    var tipo = valor('tipo'), sector = valor('sector'), ops = valor('ops');
    var precio = +valor('precio') || 0, alc = +valor('alc') || 0, orden = valor('orden');
    var visibles = 0;
    cards.forEach(function (c) {
      var d = c.dataset, ok = true;
      if (tipo && d.tipo !== tipo) ok = false;
      if (sector && d.sector !== sector) ok = false;
      if (ops && d.ops.split(',').indexOf(ops) < 0) ok = false;
      if (precio && !(+d.venta > 0 && +d.venta <= precio)) ok = false;
      if (alc && +d.alc < alc) ok = false;
      c.hidden = !ok;
      if (ok) visibles++;
    });
    var orden_fn = {
      'nuevas': function (a, b) { return a.dataset.cod < b.dataset.cod ? 1 : -1; },
      'precio-asc': function (a, b) { return (+a.dataset.venta || 9e15) - (+b.dataset.venta || 9e15); },
      'precio-desc': function (a, b) { return (+b.dataset.venta || 0) - (+a.dataset.venta || 0); },
      'area-desc': function (a, b) { return +b.dataset.area - +a.dataset.area; }
    }[orden || 'nuevas'];
    cards.slice().sort(orden_fn).forEach(function (c) { grid.appendChild(c); });
    conteo.textContent = visibles;
    conteo.nextSibling.textContent = visibles === 1 ? ' propiedad' : ' propiedades';
    vacio.hidden = visibles > 0;

    var q = new URLSearchParams();
    campos.forEach(function (c) { if (c.value && !(c.dataset.f === 'orden' && c.value === 'nuevas')) q.set(c.dataset.f, c.value); });
    var nueva = location.pathname + (q.toString() ? '?' + q : '') + location.hash;
    history.replaceState(null, '', nueva);
  }

  campos.forEach(function (c) { c.addEventListener('change', aplicar); });
  aplicar();
})();
