(()=>{
  const passwordList = ['B1g_tony', 'Minecrsft_pro'];
  const authKey = 'cdb-admin-auth';
  const editKey = 'cdb-admin-editing';
  const pageName = location.pathname.split('/').pop() || 'index.html';
  const storageKey = `cdb-page-edits-v1:${pageName}`;
  const selector = 'main h1,main h2,main h3,main p,main li,main .eyebrow,main .card-link,.footer-inner p,.footer-links a';
  const nodes = [...document.querySelectorAll(selector)].filter(node => !node.closest('form') && !node.matches('#player-status'));
  nodes.forEach((node, index) => { node.dataset.cdbEditTarget = String(index); });

  const css = document.createElement('style');
  css.id = 'cdb-admin-style';
  css.textContent = `.cdb-admin-launch{position:fixed;right:20px;bottom:20px;z-index:1200;border:1px solid #6ce6ef80;border-radius:999px;padding:13px 18px;background:linear-gradient(135deg,#20dce8,#9d70ff);color:#07111a;font:800 13px system-ui,sans-serif;box-shadow:0 10px 34px #0008;cursor:pointer}.cdb-admin-dialog{width:min(620px,calc(100vw - 28px));max-height:85vh;overflow:auto;border:1px solid #33415c;border-radius:22px;background:#0d1221;color:#eff3ff;padding:26px;box-shadow:0 25px 100px #000b}.cdb-admin-dialog::backdrop{background:#030610bb;backdrop-filter:blur(6px)}.cdb-admin-dialog h2{margin:0 35px 8px 0;font-size:25px}.cdb-admin-dialog p{color:#aebbd2;line-height:1.6}.cdb-admin-actions{display:flex;flex-wrap:wrap;gap:10px;margin:20px 0 12px}.cdb-admin-actions button,.cdb-admin-close{border:1px solid #394964;border-radius:12px;background:#151d30;color:#eff3ff;padding:11px 14px;font:700 13px system-ui,sans-serif;cursor:pointer}.cdb-admin-actions .cdb-admin-save{background:#35d9d9;color:#061019;border:0}.cdb-admin-close{float:right;font-size:20px;padding:5px 11px}.cdb-admin-note{padding:13px;border:1px solid #364665;border-radius:12px;background:#111a2c;font-size:13px}.cdb-admin-status{min-height:22px;color:#75eeee;font-size:13px}.cdb-admin-error{min-height:22px;color:#ff7d9f;font-size:13px}.cdb-admin-form{display:flex;align-items:center;flex-wrap:wrap;gap:10px;margin:18px 0}.cdb-admin-form label{width:100%;font-size:13px;color:#aebbd2}.cdb-admin-form input{flex:1;min-width:180px;border:1px solid #394964;border-radius:10px;background:#080d18;color:#eff3ff;padding:12px;font:inherit}.cdb-admin-editing [data-cdb-edit-target]{outline:2px dashed #36dfec;outline-offset:4px;border-radius:3px;cursor:text}.cdb-admin-editing [data-cdb-edit-target]:focus{outline-style:solid}[hidden]{display:none!important}`;
  document.head.append(css);
  document.body.insertAdjacentHTML('beforeend', `<button class="cdb-admin-launch cdb-admin-ui" id="cdb-admin-open" type="button">⚙️ Website bearbeiten</button><dialog class="cdb-admin-dialog cdb-admin-ui" id="cdb-admin-dialog"><button class="cdb-admin-close" id="cdb-admin-close" type="button" aria-label="Schließen">×</button><section id="cdb-admin-login"><h2>Admin-Anmeldung</h2><p>Gib eines der Admin-Passwörter ein, um den Editor auf dieser Seite zu öffnen.</p><form class="cdb-admin-form" id="cdb-admin-form"><label for="cdb-admin-password">Passwort</label><input id="cdb-admin-password" type="password" autocomplete="current-password" required><button class="cdb-admin-save" type="submit">Anmelden</button></form><div class="cdb-admin-error" id="cdb-admin-error" role="alert"></div></section><section id="cdb-admin-editor" hidden><h2>Website-Editor</h2><p>Aktiviere den Bearbeitungsmodus und klicke auf markierte Texte auf dieser Seite.</p><div class="cdb-admin-actions"><button id="cdb-admin-toggle" type="button">Bearbeitungsmodus starten</button><button class="cdb-admin-save" id="cdb-admin-save" type="button">Änderungen speichern</button><button id="cdb-admin-export" type="button">Diese Seite herunterladen</button><button id="cdb-admin-reset" type="button">Seite zurücksetzen</button><button id="cdb-admin-logout" type="button">Abmelden</button></div><p class="cdb-admin-note">Änderungen werden in diesem Browser für diese Seite gespeichert. Zum Veröffentlichen für alle Besucher lade die bearbeitete HTML-Seite herunter, ersetze die passende Datei im Ordner public und veröffentliche die Website erneut.</p><div class="cdb-admin-status" id="cdb-admin-status" role="status" aria-live="polite"></div></section></dialog>`);

  const dialog = document.getElementById('cdb-admin-dialog');
  const login = document.getElementById('cdb-admin-login');
  const editor = document.getElementById('cdb-admin-editor');
  const input = document.getElementById('cdb-admin-password');
  const status = document.getElementById('cdb-admin-status');
  let editing = sessionStorage.getItem(editKey) === '1';
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || '{}');
    nodes.forEach(node => { if (typeof saved[node.dataset.cdbEditTarget] === 'string') node.innerHTML = saved[node.dataset.cdbEditTarget]; });
  } catch {}

  const setEditing = on => {
    editing = on;
    sessionStorage.setItem(editKey, on ? '1' : '0');
    document.body.classList.toggle('cdb-admin-editing', on);
    nodes.forEach(node => { node.contentEditable = on ? 'true' : 'false'; });
    document.getElementById('cdb-admin-toggle').textContent = on ? 'Bearbeitungsmodus beenden' : 'Bearbeitungsmodus starten';
    status.textContent = on ? 'Bearbeite die türkis markierten Texte direkt auf der Seite.' : 'Bearbeitungsmodus beendet.';
  };
  if (editing) setEditing(true);

  document.getElementById('cdb-admin-open').addEventListener('click', () => {
    const authorized = sessionStorage.getItem(authKey) === '1';
    login.hidden = authorized;
    editor.hidden = !authorized;
    dialog.showModal();
    if (!authorized) input.focus();
  });
  document.getElementById('cdb-admin-form').addEventListener('submit', event => {
    event.preventDefault();
    if (!passwordList.includes(input.value)) {
      document.getElementById('cdb-admin-error').textContent = 'Das Passwort stimmt nicht.';
      input.select();
      return;
    }
    sessionStorage.setItem(authKey, '1');
    input.value = '';
    document.getElementById('cdb-admin-error').textContent = '';
    login.hidden = true;
    editor.hidden = false;
  });
  document.getElementById('cdb-admin-toggle').addEventListener('click', () => setEditing(!editing));
  document.getElementById('cdb-admin-save').addEventListener('click', () => {
    const data = {};
    nodes.forEach(node => { data[node.dataset.cdbEditTarget] = node.innerHTML; });
    localStorage.setItem(storageKey, JSON.stringify(data));
    status.textContent = editing ? 'Änderungen gespeichert. Bearbeitungsmodus bleibt aktiv.' : 'Änderungen in diesem Browser gespeichert.';
  });
  document.getElementById('cdb-admin-reset').addEventListener('click', () => {
    if (confirm('Die gespeicherten Änderungen dieser Seite löschen?')) { localStorage.removeItem(storageKey); location.reload(); }
  });
  document.getElementById('cdb-admin-export').addEventListener('click', () => {
    const copy = document.documentElement.cloneNode(true);
    copy.querySelectorAll('.cdb-admin-ui,#cdb-admin-style').forEach(node => node.remove());
    copy.querySelectorAll('[contenteditable],[data-cdb-edit-target]').forEach(node => { node.removeAttribute('contenteditable'); node.removeAttribute('data-cdb-edit-target'); });
    copy.body.classList.remove('cdb-admin-editing');
    const file = new Blob(['<!doctype html>\n' + copy.outerHTML], { type: 'text/html;charset=utf-8' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(file);
    link.download = pageName;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    status.textContent = `${pageName} wurde heruntergeladen.`;
  });
  document.getElementById('cdb-admin-logout').addEventListener('click', () => {
    sessionStorage.removeItem(authKey);
    setEditing(false);
    dialog.close();
  });
  document.getElementById('cdb-admin-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
})();
