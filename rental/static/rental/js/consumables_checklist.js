/* =========================================================
   rental/static/rental/js/consumables_checklist.js
   Checklist of consumables on the rental detail page, like a notes app:
   one line per consumable ("XLR cable 3 m - 3"), a circle to tick it off
   as returned (struck through), an empty last line to add more. Pasting
   several lines adds them all. Plain script, no build step.
   ========================================================= */

(function () {
  const root = document.getElementById('consumables-checklist');
  if (!root) return;

  const items = JSON.parse(document.getElementById('consumables-data').textContent);
  const config = JSON.parse(document.getElementById('consumables-config').textContent);
  const i18n = config.i18n;
  const csrfToken = root.dataset.csrf;

  const list = document.createElement('div');
  list.className = 'cons-list';
  const error = document.createElement('div');
  error.className = 'cons-error';
  root.append(list, error);

  const urlFor = (template, id) => template.replace(/\/0\/([a-z]+)\/$/, `/${id}/$1/`);
  const lineOf = item => `${item.name} - ${item.quantity}`;
  const format = (text, values) => text.replace(/%\((\w+)\)s/g, (_, key) => values[key]);

  async function post(url, body) {
    error.textContent = '';
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
      credentials: 'same-origin',
      body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      error.textContent = data.error || i18n.error;
      throw new Error(error.textContent);
    }
    return data;
  }

  function replaceItem(updated) {
    const index = items.findIndex(item => item.id === updated.id);
    if (index >= 0) items[index] = updated;
  }

  function checkIcon() {
    return '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
      + 'stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
      + '<polyline points="20 6 9 17 4 12"></polyline></svg>';
  }

  function itemRow(item) {
    const row = document.createElement('div');
    const done = item.status === 'returned';
    const off = item.status === 'written_off';
    const missing = item.status === 'missing';
    row.className = 'cons-row' + (done ? ' done' : '') + (off ? ' off' : '') + (missing ? ' missing' : '');

    const check = document.createElement('button');
    check.type = 'button';
    check.className = 'cons-check';
    check.disabled = off;
    check.setAttribute('aria-pressed', done ? 'true' : 'false');
    check.title = done ? i18n.untick : i18n.tick;
    check.innerHTML = done ? checkIcon() : '';
    check.addEventListener('click', async () => {
      try {
        const data = await post(urlFor(config.urls.update, item.id), { checked: !done });
        replaceItem(data.item);
        render();
      } catch (e) { /* message already shown */ }
    });

    const body = document.createElement('div');
    const text = document.createElement('input');
    text.type = 'text';
    text.className = 'cons-text';
    text.value = lineOf(item);
    // Only lines still handed out can be edited; the rest is history.
    text.readOnly = !(config.can_add && item.status === 'out');
    text.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        text.dataset.next = '1';
        text.blur();
        const newLine = list.querySelector('.cons-row.new .cons-text');
        if (newLine) newLine.focus();
      } else if (event.key === 'Backspace' && !text.readOnly && text.value === '') {
        event.preventDefault();
        text.blur();
      }
    });
    text.addEventListener('change', async () => {
      if (text.readOnly) return;
      try {
        if (!text.value.trim()) {
          await post(urlFor(config.urls.delete, item.id), {});
          items.splice(items.indexOf(item), 1);
        } else {
          const data = await post(urlFor(config.urls.update, item.id), { line: text.value });
          replaceItem(data.item);
        }
      } catch (e) { /* message already shown */ }
      render();
      // Enter moves on to the empty line, like in a notes app.
      const newLine = text.dataset.next && list.querySelector('.cons-row.new .cons-text');
      if (newLine) newLine.focus();
    });
    body.append(text);

    if (missing) {
      const meta = document.createElement('div');
      meta.className = 'cons-meta';
      const label = document.createElement('span');
      label.textContent = format(i18n.missing, { missing: item.quantity_missing, total: item.quantity })
        + (item.reminder_count ? ` · ${format(i18n.reminders, { count: item.reminder_count })}` : '');
      const writeOff = document.createElement('button');
      writeOff.type = 'button';
      writeOff.textContent = i18n.write_off;
      writeOff.addEventListener('click', async () => {
        if (!window.confirm(i18n.write_off_confirm)) return;
        try {
          const data = await post(urlFor(config.urls.update, item.id), { write_off: true });
          replaceItem(data.item);
          render();
        } catch (e) { /* message already shown */ }
      });
      meta.append(label, writeOff);
      body.append(meta);
    } else if (off) {
      const meta = document.createElement('div');
      meta.className = 'cons-meta';
      meta.style.color = 'var(--ink-3)';
      meta.textContent = i18n.written_off;
      body.append(meta);
    }
    if (item.notes) {
      const notes = document.createElement('div');
      notes.className = 'tiny muted';
      notes.style.whiteSpace = 'pre-line';
      notes.textContent = item.notes;
      body.append(notes);
    }

    row.append(check, body);
    return row;
  }

  function newRow() {
    const row = document.createElement('div');
    row.className = 'cons-row new';
    const check = document.createElement('button');
    check.type = 'button';
    check.className = 'cons-check';
    check.disabled = true;
    const text = document.createElement('input');
    text.type = 'text';
    text.className = 'cons-text';
    text.placeholder = i18n.new_line;

    // Clear the field before the request: re-rendering removes the focused
    // input, which fires "blur" and would otherwise add the same line twice.
    const add = async lines => {
      if (!lines.trim()) return;
      text.value = '';
      try {
        const data = await post(config.urls.add, { lines });
        items.push(...data.items);
        render();
        list.querySelector('.cons-row.new .cons-text').focus();
      } catch (e) {
        text.value = lines;
      }
    };
    text.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        add(text.value);
      }
    });
    text.addEventListener('blur', () => add(text.value));
    // A pasted list (e.g. from a notes app) becomes one line per consumable.
    text.addEventListener('paste', event => {
      const pasted = (event.clipboardData || window.clipboardData).getData('text');
      if (pasted.includes('\n')) {
        event.preventDefault();
        add(pasted);
      }
    });
    row.append(check, text);
    return row;
  }

  function render() {
    list.replaceChildren(...items.map(itemRow));
    if (config.can_add) {
      list.append(newRow());
    } else if (!items.length) {
      const empty = document.createElement('div');
      empty.className = 'tiny muted';
      empty.textContent = i18n.empty;
      list.append(empty);
    }
  }

  render();
})();
