/* =========================================================
   rental/static/rental/js/return.jsx
   React island for rental_return.html.
   Depends on: shared.jsx (cls, fmtDateShort, apiPost, t, Avatar, beep)
   ========================================================= */

function ReturnScreen({ rental, items, urls, consumables = [] }) {
  const [returns, setReturns] = React.useState(() =>
    items.map(i => ({
      id: i.id,
      name: i.name,
      num: i.num,
      issuedAt: i.issued_at,
      total: i.qty_issued,
      qtyReturned: 0,
      condition: null,
      issue: '',
      charge: false,
      holdOut: true,
    }))
  );
  // Consumables (cables, cards, ...) not kept in inventory. Whatever is not
  // ticked off here is stored as missing and reminded about later; it does
  // not block completing the return.
  const [consumableReturns, setConsumableReturns] = React.useState(() =>
    consumables.map(c => ({ id: c.id, name: c.name, total: c.quantity, qtyReturned: 0, note: '' }))
  );
  const setCons = (id, patch) => setConsumableReturns(xs => xs.map(x => x.id === id ? { ...x, ...patch } : x));
  const [showIssueFor, setShowIssueFor] = React.useState(null);
  const [note, setNote] = React.useState('');
  const [emailReceipt, setEmailReceipt] = React.useState(true);
  const [closeRental, setCloseRental] = React.useState(true);
  const [flagAudit, setFlagAudit] = React.useState(false);
  const [submitting, setSubmitting] = React.useState(false);

  const [scanValue, setScanValue] = React.useState('');
  const [scanBusy, setScanBusy] = React.useState(false);
  const [scanFeedback, setScanFeedback] = React.useState(null);
  const [scanError, setScanError] = React.useState('');
  const scanDebounce = React.useRef(null);
  const scanInputRef = React.useRef(null);

  // The input is disabled while a scan is in flight, which drops the focus.
  // Put it back as soon as the request settles so the next scan just works.
  React.useEffect(() => {
    if (!scanBusy && scanInputRef.current) scanInputRef.current.focus();
  }, [scanBusy]);

  const setRet = (id, patch) => setReturns(xs => xs.map(x => x.id === id ? { ...x, ...patch } : x));
  const checkAll = () => {
    setReturns(xs => xs.map(x => ({ ...x, qtyReturned: x.total, condition: x.condition || 'ok' })));
    setConsumableReturns(xs => xs.map(x => ({ ...x, qtyReturned: x.total })));
  };
  const clearAll = () => {
    setReturns(xs => xs.map(x => ({ ...x, qtyReturned: 0, condition: null, issue: '' })));
    setConsumableReturns(xs => xs.map(x => ({ ...x, qtyReturned: 0, note: '' })));
  };

  const handleScan = async () => {
    if (!scanValue.trim() || scanDebounce.current) return;
    scanDebounce.current = setTimeout(() => { scanDebounce.current = null; }, 300);
    setScanBusy(true);
    try {
      // rental.pk is the numeric primary key; rental.id is the human-readable
      // code (R-2608-0284) the backend cannot look up.
      const data = await apiPost(urls.scan_return, {
        rental_id: rental.pk,
        inventory_number: scanValue.trim(),
      });
      const idx = returns.findIndex(r => r.id === data.rental_item_id);
      if (idx >= 0) {
        setRet(data.rental_item_id, { qtyReturned: data.quantity_returned });
      }
      beep(800, 100);
      setScanError('');
      setScanFeedback('success');
      setTimeout(() => setScanFeedback(null), 500);
    } catch (e) {
      beep(300, 200);
      setScanError(e.message || t('ret.scan_failed', 'Scan failed.'));
      setScanFeedback('error');
      setTimeout(() => setScanFeedback(null), 500);
    }
    setScanValue('');
    setScanBusy(false);
  };

  const checkedCount = returns.filter(x => x.qtyReturned >= x.total).length;
  const totalCount = returns.length;
  const issueCount = returns.filter(x => x.condition === 'warn' || x.condition === 'bad' || x.issue).length;
  const missingConsumables = consumableReturns.filter(x => x.qtyReturned < x.total);

  const submit = async () => {
    if (missingConsumables.length > 0) {
      const names = missingConsumables.map(x => `${x.name} (${x.total - x.qtyReturned})`).join(', ');
      const ok = window.confirm(
        t('ret.cons_confirm', 'These consumables are not returned and will be kept as missing: {names}. Continue?')
          .replace('{names}', names));
      if (!ok) return;
    }
    setSubmitting(true);
    try {
      await apiPost(urls.submit_return, {
        items: returns.map(r => ({
          id: r.id,
          qty_returned: r.qtyReturned,
          condition: r.condition,
          issue: r.issue,
          charge: r.charge,
          hold_out: r.holdOut,
        })),
        consumables: consumableReturns.map(c => ({
          id: c.id,
          qty_returned: c.qtyReturned,
          note: c.note,
        })),
        note,
        email_receipt: emailReceipt,
        close_rental: closeRental,
        flag_audit: flagAudit,
      });
      window.location = urls.detail;
    } catch (e) {
      alert(t('err.return', 'Could not submit return: ') + e.message);
      setSubmitting(false);
    }
  };

  return (
    <>
      {/* Scan panel: the border flashes green/red so the operator gets
          feedback without looking away from the counter. */}
      <div className="surface p-3 mb-3"
           style={{
             border: `2px solid ${scanFeedback === 'success' ? 'oklch(0.65 0.18 145)' : scanFeedback === 'error' ? 'oklch(0.55 0.18 28)' : 'var(--line)'}`,
             transition: 'border-color 0.2s ease',
           }}>
        <div className="d-flex align-items-center" style={{gap: 12, flexWrap: 'wrap'}}>
          <div style={{flex: 1, minWidth: 220}}>
            <label className="form-label mb-1" style={{fontSize: 12, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.04em'}}>
              {t('ret.scan_barcode', 'Scan Barcode')}
            </label>
            <div className="input-group input-group-sm">
              <span className="input-group-text"><i className="fas fa-barcode"></i></span>
              <input type="text" className="form-control"
                     autoFocus
                     ref={scanInputRef}
                     disabled={scanBusy}
                     value={scanValue}
                     onChange={e => { setScanValue(e.target.value); if (e.target.value.includes('\n') || e.target.value.includes('\r')) handleScan(); }}
                     onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleScan(); } }}
                     placeholder={t('ret.scan_ph', 'Scan or type inventory number…')} />
            </div>
            {scanError && (
              <div className="tiny mt-1" style={{color: 'oklch(0.55 0.18 28)', fontWeight: 500}}>
                <i className="fas fa-triangle-exclamation me-1"></i>{scanError}
              </div>
            )}
          </div>
          <div className="text-end" style={{minWidth: 120}}>
            <div className="muted tiny" style={{textTransform: 'uppercase', letterSpacing: '.04em', fontWeight: 600}}>
              {t('ret.progress', 'Progress')}
            </div>
            <div style={{fontWeight: 600, fontVariantNumeric: 'tabular-nums', fontSize: 16}}>
              {checkedCount}/{totalCount} {t('ret.returned', 'returned')}
            </div>
          </div>
        </div>
      </div>

      {/* Summary bar */}
      <div className="action-bar" style={{background: 'oklch(0.97 0.03 240)', borderColor: 'oklch(0.88 0.06 240)'}}>
        <div className="primary-cta">
          <Avatar user={rental.user} size={32} />
          <div>
            <div style={{fontWeight: 600, fontSize: 13}}>{rental.user.name}</div>
            <div className="muted tiny">{rental.user.org} · {t('ret.returning','returning')} {totalCount} {t('ret.items','items')}</div>
          </div>
        </div>
        <div className="secondary" style={{gap: 12, fontSize: 13}}>
          <div>
            <div className="muted tiny" style={{textTransform: 'uppercase', letterSpacing: '.04em', fontWeight: 600}}>
              {t('ret.progress', 'Progress')}
            </div>
            <div style={{fontWeight: 600, fontVariantNumeric: 'tabular-nums'}}>
              {checkedCount}/{totalCount} {t('ret.checked', 'checked')}
            </div>
          </div>
          <div>
            <div className="muted tiny" style={{textTransform: 'uppercase', letterSpacing: '.04em', fontWeight: 600}}>
              {t('ret.issues', 'Issues')}
            </div>
            <div style={{fontWeight: 600, color: issueCount > 0 ? 'oklch(0.45 0.14 28)' : 'var(--ink)'}}>
              {issueCount}
            </div>
          </div>
          <div>
            <div className="muted tiny" style={{textTransform: 'uppercase', letterSpacing: '.04em', fontWeight: 600}}>
              {t('ret.due_by', 'Due by')}
            </div>
            <div style={{fontWeight: 600}}>{fmtDateShort(rental.to_at)}</div>
          </div>
          <a className="btn btn-ghost btn-sm" href={urls.detail}>{t('btn.cancel', 'Cancel')}</a>
          <button className="btn btn-primary btn-sm" disabled={submitting} onClick={submit}>
            <i className="fas fa-check me-1"></i>{t('btn.complete_return', 'Complete return')}
          </button>
        </div>
      </div>

      <div className="d-flex align-items-center mb-2" style={{gap: 8}}>
        <strong style={{fontSize: 13}}>{t('ret.heading', 'Equipment returning')}</strong>
        <span className="muted tiny">
          {t('ret.sub', "Tick off items as the user hands them back. Mark condition if something's not right.")}
        </span>
        <div className="ms-auto d-flex" style={{gap: 6}}>
          <button className="btn btn-ghost btn-sm" onClick={clearAll}>
            <i className="fas fa-rotate-left me-1"></i>{t('btn.reset', 'Reset')}
          </button>
          <button className="btn btn-ghost btn-sm" onClick={checkAll}>
            <i className="fas fa-check-double me-1"></i>{t('btn.all_ok', 'All returned, all OK')}
          </button>
        </div>
      </div>

      <div className="return-list">
        <div className="return-list-head">
          <div></div>
          <div>{t('ret.col.item', 'Item')}</div>
          <div>{t('ret.col.returned', 'Returned')}</div>
          <div>{t('ret.col.condition', 'Condition')}</div>
          <div>{t('ret.col.note', 'Issue note')}</div>
        </div>

        {returns.map(ret => {
          const done = ret.qtyReturned >= ret.total;
          const hasIssue = ret.condition === 'warn' || ret.condition === 'bad';
          return (
            <React.Fragment key={ret.id}>
              <div className={cls('return-row', done && 'checked')}>
                <input type="checkbox" className="form-check-input"
                       checked={done}
                       onChange={e => setRet(ret.id, {
                         qtyReturned: e.target.checked ? ret.total : 0,
                         condition: e.target.checked ? (ret.condition || 'ok') : null,
                       })} />
                <div>
                  <div className="name">{ret.name}</div>
                  <div className="sub">
                    <span className="mono">{ret.num}</span> · {t('ret.issued','issued')} {fmtDateShort(ret.issuedAt)}
                  </div>
                </div>
                <div>
                  {ret.total > 1 ? (
                    <div className="input-group input-group-sm" style={{maxWidth: 100}}>
                      <button className="btn btn-ghost"
                              onClick={() => setRet(ret.id, { qtyReturned: Math.max(0, ret.qtyReturned - 1) })}>−</button>
                      <input className="form-control text-center" readOnly
                             value={`${ret.qtyReturned}/${ret.total}`} />
                      <button className="btn btn-ghost"
                              onClick={() => setRet(ret.id, {
                                qtyReturned: Math.min(ret.total, ret.qtyReturned + 1),
                                condition: ret.condition || 'ok',
                              })}>+</button>
                    </div>
                  ) : (
                    <span className={cls('tag', done ? 'tag-ok' : 'tag-neutral')}>
                      {done ? `1/1 ${t('ret.back','back')}` : '0/1'}
                    </span>
                  )}
                </div>
                <div>
                  <div className="condition-pick">
                    <button className={cls(ret.condition === 'ok' && 'sel-ok')}
                            onClick={() => setRet(ret.id, { condition: 'ok', qtyReturned: ret.total })}>
                      {t('ret.ok', 'OK')}
                    </button>
                    <button className={cls(ret.condition === 'warn' && 'sel-warn')}
                            onClick={() => { setRet(ret.id, { condition: 'warn', qtyReturned: ret.total }); setShowIssueFor(ret.id); }}>
                      {t('ret.minor', 'Minor')}
                    </button>
                    <button className={cls(ret.condition === 'bad' && 'sel-bad')}
                            onClick={() => { setRet(ret.id, { condition: 'bad', qtyReturned: ret.total }); setShowIssueFor(ret.id); }}>
                      {t('ret.damage', 'Damage')}
                    </button>
                  </div>
                </div>
                <div>
                  {hasIssue ? (
                    <button className="btn btn-sm btn-ghost" style={{width: '100%'}}
                            onClick={() => setShowIssueFor(showIssueFor === ret.id ? null : ret.id)}>
                      {ret.issue
                        ? <><i className="fas fa-check-circle me-1" style={{color: 'oklch(0.55 0.12 145)'}}></i>{t('ret.logged','Logged')}</>
                        : <><i className="fas fa-plus me-1"></i>{t('ret.add_note','Add note')}</>}
                    </button>
                  ) : <span className="muted tiny">—</span>}
                </div>
              </div>

              {showIssueFor === ret.id && hasIssue && (
                <div style={{padding: '12px 20px 14px 60px', background: 'oklch(0.98 0.02 28)',
                                borderBottom: '1px solid var(--line)'}}>
                  <div className="d-flex" style={{gap: 10, alignItems: 'center', marginBottom: 8}}>
                    <i className="fas fa-triangle-exclamation" style={{color: 'oklch(0.55 0.14 45)'}}></i>
                    <strong style={{fontSize: 12.5}}>
                      {t('ret.log_for', 'Log issue for')} {ret.name}
                    </strong>
                  </div>
                  <div style={{display: 'grid', gridTemplateColumns: '1fr 220px', gap: 10}}>
                    <textarea className="form-control form-control-sm" rows={2}
                              value={ret.issue}
                              onChange={e => setRet(ret.id, { issue: e.target.value })}
                              placeholder={t('ret.desc_ph', "Describe what's wrong…")} />
                    <div>
                      <div className="form-check tiny">
                        <input className="form-check-input" type="checkbox" id={`charge-${ret.id}`}
                               checked={ret.charge} onChange={e => setRet(ret.id, {charge: e.target.checked})} />
                        <label className="form-check-label" htmlFor={`charge-${ret.id}`}>
                          {t('ret.charge','Charge user (recoverable damage)')}
                        </label>
                      </div>
                      <div className="form-check tiny">
                        <input className="form-check-input" type="checkbox" id={`holdout-${ret.id}`}
                               checked={ret.holdOut} onChange={e => setRet(ret.id, {holdOut: e.target.checked})} />
                        <label className="form-check-label" htmlFor={`holdout-${ret.id}`}>
                          {t('ret.hold_out','Hold item out of pool until reviewed')}
                        </label>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>

      {consumableReturns.length > 0 && (
        <div className="surface p-3 mt-3">
          <div className="d-flex align-items-center mb-2" style={{gap: 8}}>
            <strong style={{fontSize: 13}}>{t('ret.cons_heading', 'Consumables')}</strong>
            <span className="muted tiny">
              {t('ret.cons_sub', 'Not in inventory. What is not ticked off stays open as missing and the user is reminded.')}
            </span>
          </div>
          {consumableReturns.map(c => {
            const done = c.qtyReturned >= c.total;
            return (
              <div key={c.id} className={cls('return-row', done && 'checked')}
                   style={{gridTemplateColumns: '28px 1fr 120px 1fr'}}>
                <button type="button" className="cons-check" aria-pressed={done}
                        style={done ? {background: 'oklch(0.62 0.14 145)', borderColor: 'oklch(0.62 0.14 145)'} : undefined}
                        onClick={() => setCons(c.id, { qtyReturned: done ? 0 : c.total })}>
                  {done && <i className="fas fa-check" style={{fontSize: 11}}></i>}
                </button>
                <div className="name" style={done ? {textDecoration: 'line-through', color: 'var(--ink-3)'} : undefined}>
                  {c.name} <span className="muted">- {c.total}</span>
                </div>
                <div>
                  {c.total > 1 ? (
                    <div className="input-group input-group-sm" style={{maxWidth: 110}}>
                      <button className="btn btn-ghost"
                              onClick={() => setCons(c.id, { qtyReturned: Math.max(0, c.qtyReturned - 1) })}>−</button>
                      <input className="form-control text-center" readOnly value={`${c.qtyReturned}/${c.total}`} />
                      <button className="btn btn-ghost"
                              onClick={() => setCons(c.id, { qtyReturned: Math.min(c.total, c.qtyReturned + 1) })}>+</button>
                    </div>
                  ) : (
                    <span className={cls('tag', done ? 'tag-ok' : 'tag-neutral')}>
                      {done ? `1/1 ${t('ret.back','back')}` : '0/1'}
                    </span>
                  )}
                </div>
                <input type="text" className="form-control form-control-sm"
                       value={c.note} onChange={e => setCons(c.id, { note: e.target.value })}
                       placeholder={done ? t('ret.cons_note_ph', 'Note (optional)') : t('ret.cons_missing_ph', 'Why missing? (optional)')} />
              </div>
            );
          })}
        </div>
      )}

      {/* Bottom — internal note + final toggles */}
      <div className="surface p-3 mt-3">
        {rental.internal_note && (
          <div className="mb-3">
            <strong style={{fontSize: 13}}>{t('ret.rental_note', 'Internal note of the rental')}</strong>
            <div className="tiny mt-1" style={{whiteSpace: 'pre-line', color: 'var(--ink-2)'}}>{rental.internal_note}</div>
          </div>
        )}
        <strong style={{fontSize: 13}}>{t('ret.int_note', 'Return note (internal)')}</strong>
        <textarea className="form-control mt-2" rows={2}
                  value={note} onChange={e => setNote(e.target.value)}
                  placeholder={t('ret.int_note_ph', 'Anything to remember for next time?')} />
        <div className="return-options mt-3">
          <div className="return-options-title">{t('ret.options_explain', 'What these options do')}</div>
          <div className="form-check return-option">
            <input className="form-check-input" type="checkbox" id="emailRet"
                   checked={emailReceipt} onChange={e => setEmailReceipt(e.target.checked)} />
            <div>
              <label className="form-check-label" htmlFor="emailRet">
                {t('ret.email_receipt', 'Email return receipt to user')}
              </label>
              <div className="return-option-help">
                {emailReceipt ? t('ret.email_help_on', 'Checked: the user receives a return receipt by email.') : t('ret.email_help_off', 'Unchecked: the return is saved without sending a receipt email.')}
              </div>
            </div>
          </div>
          <div className="form-check return-option">
            <input className="form-check-input" type="checkbox" id="closeRet"
                   checked={closeRental} onChange={e => setCloseRental(e.target.checked)} />
            <div>
              <label className="form-check-label" htmlFor="closeRet">
                {t('ret.close', 'Close rental after return')}
              </label>
              <div className="return-option-help">
                {closeRental ? t('ret.close_help_on', 'Checked: after all issued items are back, the rental is closed immediately and no separate Close rental step is needed.') : t('ret.close_help_off', 'Unchecked: the rental stays returned, so staff can review it and close it later.')}
              </div>
            </div>
          </div>
          <div className="form-check return-option">
            <input className="form-check-input" type="checkbox" id="auditRet"
                   checked={flagAudit} onChange={e => setFlagAudit(e.target.checked)} />
            <div>
              <label className="form-check-label" htmlFor="auditRet">
                {t('ret.audit', 'Flag for inventory audit')}
              </label>
              <div className="return-option-help">
                {flagAudit ? t('ret.audit_help_on', 'Checked: an inventory audit issue is created for each returned item.') : t('ret.audit_help_off', 'Unchecked: no audit issue is created unless an item condition note is entered.')}
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

Object.assign(window, { ReturnScreen });
