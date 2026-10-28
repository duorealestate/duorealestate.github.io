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

  // Barra de precio con dos puntos (pasos en millones; el último es "sin límite").
  var rpMin = form.querySelector('[data-f="pmin"]'), rpMax = form.querySelector('[data-f="pmax"]');
  var rpTxt = form.querySelector('.rp-txt'), rpSel = form.querySelector('.rp-sel');
  var PASOS = rpTxt ? rpTxt.dataset.pasos.split(',').map(Number) : [];
  var ULT = PASOS.length - 1;
  function mill(n) { return '$' + n.toLocaleString('es-CO'); }
  function rango() {
    if (!rpMin) return [0, Infinity];
    var a = +rpMin.value, b = +rpMax.value;
    if (a >= b) {  // siempre al menos un paso entre los dos puntos
      if (this === rpMin) { b = Math.min(a + 1, ULT); a = b - 1; } else { a = Math.max(b - 1, 0); b = a + 1; }
      rpMin.value = a; rpMax.value = b;
    }
    var lo = PASOS[a], hi = b === ULT ? Infinity : PASOS[b];
    rpSel.style.left = 'calc(11px + (100% - 22px) * ' + a / ULT + ')';
    rpSel.style.width = 'calc((100% - 22px) * ' + (b - a) / ULT + ')';
    rpTxt.textContent = !lo && hi === Infinity ? 'Cualquier precio'
      : !lo ? 'Hasta ' + mill(hi) + ' millones'
      : hi === Infinity ? 'Desde ' + mill(lo) + ' millones'
      : mill(lo) + ' a ' + mill(hi) + ' millones';
    return [lo * 1e6, hi * 1e6];
  }
  function porDefecto(c) { return (c.dataset.f === 'pmin' && +c.value === 0) || (c.dataset.f === 'pmax' && +c.value === ULT) || (c.dataset.f === 'orden' && c.value === 'nuevas'); }

  function aplicar() {
    var tipo = valor('tipo'), sector = valor('sector'), ops = valor('ops');
    var r = rango.call(this), alc = +valor('alc') || 0, orden = valor('orden');
    var filtraPrecio = r[0] > 0 || r[1] < Infinity;
    var visibles = 0;
    cards.forEach(function (c) {
      var d = c.dataset, ok = true;
      if (tipo && d.tipo !== tipo) ok = false;
      if (sector && d.sector !== sector) ok = false;
      if (ops && d.ops.split(',').indexOf(ops) < 0) ok = false;
      if (filtraPrecio && !(+d.venta > 0 && +d.venta >= r[0] && +d.venta <= r[1])) ok = false;
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
    var filtrando = Array.prototype.some.call(campos, function (c) { return c.dataset.f !== 'orden' && c.value && !porDefecto(c); });
    conteo.parentNode.hidden = !filtrando;
    conteo.textContent = visibles;
    conteo.nextSibling.textContent = visibles === 1 ? ' propiedad' : ' propiedades';
    vacio.hidden = visibles > 0;

    var q = new URLSearchParams();
    campos.forEach(function (c) { if (c.value && !porDefecto(c)) q.set(c.dataset.f, c.value); });
    var nueva = location.pathname + (q.toString() ? '?' + q : '') + location.hash;
    history.replaceState(null, '', nueva);
  }

  campos.forEach(function (c) { c.addEventListener(c.type === 'range' ? 'input' : 'change', aplicar); });
  aplicar();
})();
