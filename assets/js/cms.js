/* Phireworx CMS loader
   Fills page content from the JSON files edited at /admin.
     data-cms="file:path"       -> text (prices, headlines, stats)
     data-cms-list="file:path"  -> replaces the <li> items of a list
     data-cms-img="file:path"   -> swaps a photo ({image, alt})
     data-cms-num="file:path"   -> the number in a stat (keeps its suffix)
     data-cms-tpl="file|text ${path} text" -> text with values filled in
   "file" is a path under /data without .json (e.g. prices, photos/home).
   The HTML already holds the current content, so nothing changes until
   a value saved in /admin differs from what's on the page. */
(function () {
  var nodes = document.querySelectorAll('[data-cms],[data-cms-list],[data-cms-img],[data-cms-num],[data-cms-tpl]');
  if (!nodes.length) return;

  var ATTRS = ['data-cms', 'data-cms-list', 'data-cms-img', 'data-cms-num'];
  var files = {};
  nodes.forEach(function (el) {
    ATTRS.forEach(function (a) {
      var v = el.getAttribute(a);
      if (v) files[v.split(':')[0]] = true;
    });
    var tp = el.getAttribute('data-cms-tpl');
    if (tp) files[tp.split('|')[0]] = true;
  });

  function get(obj, path) {
    return path.split('.').reduce(function (o, k) {
      if (o == null) return undefined;
      var m = k.match(/^(\w+)\[(\d+)\]$/);
      return m ? (o[m[1]] || [])[+m[2]] : o[k];
    }, obj);
  }

  var onNetlify = /phireworxphoto\.com$|netlify\.app$/.test(location.hostname);
  function imageUrl(path, width) {
    if (!onNetlify || !/^\/?assets\/images\//.test(path)) return path;
    var p = path.charAt(0) === '/' ? path : '/' + path;
    return '/.netlify/images?url=' + encodeURIComponent(p) + '&w=' + width + '&q=82';
  }
  function plain(src) { // '/.netlify/images?url=%2Fassets%2F...' -> 'assets/...'
    var m = String(src || '').match(/[?&]url=([^&]+)/);
    return (m ? decodeURIComponent(m[1]) : String(src || '')).replace(/^\//, '');
  }
  function samePath(a, b) {
    return plain(a) === plain(b);
  }

  function apply(file, data) {
    nodes.forEach(function (el) {
      var t = el.getAttribute('data-cms');
      if (t && t.split(':')[0] === file) {
        var v = get(data, t.split(':')[1]);
        if (typeof v === 'number') v = String(v);
        if (typeof v === 'string' && v.indexOf('*') !== -1) {
          // *word* in a CMS headline = Amber accent word
          var safe = v.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
          var h = safe.replace(/\*([^*]+)\*/g, '<span class="hl-accent">$1</span>');
          if (el.innerHTML !== h) el.innerHTML = h;
        } else if (typeof v === 'string' && v.trim() !== '' && el.textContent !== v) el.textContent = v;
      }
      var n = el.getAttribute('data-cms-num');
      if (n && n.split(':')[0] === file) {
        var nv = get(data, n.split(':')[1]);
        if (nv != null && String(nv).trim() !== '') {
          nv = String(nv).trim();
          el.setAttribute('data-final', nv);
          for (var i = 0; i < el.childNodes.length; i++) {
            if (el.childNodes[i].nodeType === 3 && el.childNodes[i].textContent.trim()) {
              if (el.childNodes[i].textContent.trim() !== nv) el.childNodes[i].textContent = nv;
              break;
            }
          }
        }
      }
      var tp = el.getAttribute('data-cms-tpl');
      if (tp && tp.split('|')[0] === file) {
        var out = tp.slice(tp.indexOf('|') + 1).replace(/\$\{([^}]+)\}/g, function (m, k) {
          var x = get(data, k); return x == null || x === '' ? m : String(x);
        });
        if (out.indexOf('${') === -1 && el.textContent !== out) el.textContent = out;
      }
      var l = el.getAttribute('data-cms-list');
      if (l && l.split(':')[0] === file) {
        var items = get(data, l.split(':')[1]);
        if (Array.isArray(items) && items.length) {
          el.innerHTML = '';
          items.forEach(function (it) {
            var li = document.createElement('li');
            li.textContent = typeof it === 'string' ? it : (it && it.item) || '';
            el.appendChild(li);
          });
        }
      }
      var im = el.getAttribute('data-cms-img');
      if (im && im.split(':')[0] === file) {
        var slot = get(data, im.split(':')[1]);
        var src = slot && (typeof slot === 'string' ? slot : slot.image);
        if (slot && slot.alt) el.setAttribute('alt', slot.alt);
        if (src && !samePath(src, el.getAttribute('src'))) {
          var w = el.getAttribute('data-cms-w') || '1800';
          el.removeAttribute('width');
          el.removeAttribute('height');
          el.addEventListener('load', function onload() {
            el.removeEventListener('load', onload);
            if (el.style.getPropertyValue('--ar') && el.naturalHeight) {
              el.style.setProperty('--ar', (el.naturalWidth / el.naturalHeight).toFixed(4));
            }
          });
          el.setAttribute('src', imageUrl(src, w));
        }
      }
    });
  }

  var cb = Math.floor(Date.now() / 60000);
  Object.keys(files).forEach(function (file) {
    fetch('/data/' + file + '.json?cb=' + cb)
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d) apply(file, d); })
      .catch(function () {});
  });
})();
