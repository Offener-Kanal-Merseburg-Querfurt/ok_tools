/* =========================================================
   rental/static/rental/js/wizard.jsx
   4-step rental creation wizard + Quick mode.
   Adapted from prototype screen-wizard.jsx — all mock data
   now comes from Django via props (`initial`).
   Depends on: shared.jsx (cls, fmtDate, apiPost, apiGet, t, Avatar)
   ========================================================= */

/* ===== Helpers ===== */

// Open the shared carousel lightbox (rental/js/lightbox.js). Accepts a single
// URL or a list of URLs; falls back to a no-op if the script is not loaded.
// Named differently from the global it calls: this file is a classic script,
// so a top-level ``openImageLightbox`` would replace ``window.openImageLightbox``
// and recurse into itself.
function openPhotoLightbox(images) {
  if (window.openImageLightbox) window.openImageLightbox(images);
}

// Round a date up to the next :00 or :30
function _roundUp(d) {
  const m = d.getMinutes();
  if (m === 0 || m === 30) return d;
  if (m < 30) { d.setMinutes(30, 0, 0); }
  else { d.setHours(d.getHours() + 1, 0, 0, 0); }
  return d;
}

function _fmtDT(d) {
  const y = d.getFullYear();
  const mo = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  const h = String(d.getHours()).padStart(2, '0');
  const mi = String(d.getMinutes()).padStart(2, '0');
  return `${y}-${mo}-${dd}T${h}:${mi}`;
}

// Get working-hours config for a specific date (null if closed/missing)
function _whForDate(date, wh) {
  const dayIdx = date.getDay() === 0 ? 6 : date.getDay() - 1;
  return wh?.[String(dayIdx)] || null;
}

// Snap a date forward to the next valid working-hours slot.
// Returns a new Date (never mutates the input).
function snapToWorkingHours(date, workingHours) {
  const d = new Date(date);
  for (let attempt = 0; attempt < 14; attempt++) {
    const dayHours = _whForDate(d, workingHours);
    if (!dayHours || !dayHours.enabled) {
      d.setDate(d.getDate() + 1);
      d.setHours(0, 0, 0, 0);
      continue;
    }
    const [sh, sm] = (dayHours.start || '00:00').split(':').map(Number);
    const [eh, em] = (dayHours.end   || '00:00').split(':').map(Number);
    const startMins = sh * 60 + sm;
    const endMins   = eh * 60 + em;
    const curMins   = d.getHours() * 60 + d.getMinutes();

    if (curMins < startMins) {
      d.setHours(sh, sm, 0, 0);
      return d;
    }
    if (curMins >= endMins) {
      d.setDate(d.getDate() + 1);
      d.setHours(0, 0, 0, 0);
      continue;
    }
    // Within working hours → round up to next slot
    _roundUp(d);
    const snappedMins = d.getHours() * 60 + d.getMinutes();
    if (snappedMins > endMins) {
      d.setDate(d.getDate() + 1);
      d.setHours(0, 0, 0, 0);
      continue;
    }
    return d;
  }
  return d;
}

/* ===== Root ===== */
function WizardScreen({ initial }) {
  // initial = {
  //   categories:  [{id, label, icon, count}, ...],
  //   users:       [{id, name, org, role, initials, past, warn?}, ...],
  //   rooms:       [{id, name, sub, free}, ...],
  //   urls: { create, quick_issue, inventory_search, availability_check, users_search },
  //   defaults: { from, to, project, purpose }
  // }

  const [mode, setMode] = React.useState('wizard');
  const [step, setStep] = React.useState(0);
  const [submitting, setSubmitting] = React.useState(false);

  const [cart, setCart]   = React.useState([]);
  const [rooms, setRooms] = React.useState([]);
  const [user, setUser]   = React.useState(null);
  const [period, setPeriod] = React.useState({
    from: initial.defaults?.from || '',
    to:   initial.defaults?.to   || '',
  });
  const [project, setProject] = React.useState(initial.defaults?.project || '');
  const [purpose, setPurpose] = React.useState(initial.defaults?.purpose || '');
  const [notifyEmail, setNotifyEmail] = React.useState(false);

  const hasOnlyRooms = rooms.length > 0 && cart.length === 0;

  const steps = [
    { title: t('wiz.step1', 'User'),               hint: user ? user.name : t('wiz.no_user', 'Not selected') },
    { title: t('wiz.step2', 'Time & conflicts'),   hint: hasOnlyRooms
      ? t('wiz.skipped_rooms', 'Skipped (rooms only)')
      : (period.from ? period.from.slice(0,10) + ' → ' + period.to.slice(0,10) : '—') },
    { title: t('wiz.step3', 'Items & rooms'),      hint: `${cart.length} ${t('wiz.items','items')} · ${rooms.length} ${t('wiz.rooms','rooms')}` },
    { title: t('wiz.step4', 'Review & confirm'),   hint: t('wiz.send_confirm', 'Send confirmation') },
  ];

  // Validation per step — block "Next" until required fields are set
  const canNext = () => {
    if (step === 0) return !!user;
    if (step === 1) {
      if (hasOnlyRooms) return true;
      const f = new Date(period.from), tt = new Date(period.to);
      return !isNaN(f) && !isNaN(tt) && f < tt;
    }
    if (step === 2) {
      if (rooms.length > 0) {
        const allRoomsHaveDates = rooms.every(r => r.start_date && r.start_time && r.end_date && r.end_time);
        if (!allRoomsHaveDates) return false;
      }
      return cart.length > 0 || rooms.length > 0;
    }
    return true;
  };

  const submit = async () => {
    if (!project.trim()) {
      alert(t('wiz.project_req', 'Please enter a project name.'));
      return;
    }
    if (hasOnlyRooms && rooms.length === 0) {
      alert(t('wiz.no_items_rooms', 'Please select at least one item or room.'));
      return;
    }
    setSubmitting(true);
    try {
      const payload = {
        user_id: user?.id,
        from: period.from,
        to: period.to,
        project, purpose,
        items: cart.map(c => ({ id: c.id, qty: c.qty })),
        rooms: rooms.map(r => ({
          id: r.id,
          start_date: r.start_date || '',
          start_time: r.start_time || '',
          end_date: r.end_date || '',
          end_time: r.end_time || '',
        })),
        notify: { email: notifyEmail },
      };
      const res = await apiPost(initial.urls.create, payload);
      window.location = res.detail_url;
    } catch (e) {
      alert(t('err.create', 'Could not create rental: ') + e.message);
      setSubmitting(false);
    }
  };

  return (
    <>
      <div className="page-title">
        <h1>{t('wiz.title', 'Create rental')}</h1>
        <span className="sub">{t('wiz.sub', 'Reserve items and rooms for a user')}</span>
        <div className="page-actions">
          <div className="btn-group" role="group">
            <button type="button" className={cls('btn btn-sm', mode === 'wizard' ? 'btn-primary' : 'btn-ghost')}
                    onClick={() => setMode('wizard')}>
              <i className="fas fa-list-ol me-1"></i>{t('wiz.guided', 'Guided')}
            </button>
            <button type="button" className={cls('btn btn-sm', mode === 'quick' ? 'btn-primary' : 'btn-ghost')}
                    onClick={() => setMode('quick')}>
              <i className="fas fa-bolt me-1"></i>{t('wiz.quick', 'Quick')}
            </button>
          </div>
        </div>
      </div>

      {mode === 'quick'
        ? <QuickRental initial={initial} cart={cart} setCart={setCart}
                       user={user} setUser={setUser} period={period} setPeriod={setPeriod} />
        : <>
            <Stepper steps={steps} active={step} setActive={setStep} />

            <div className="wizard-body">
              {step === 0 && <StepUser initial={initial} selected={user} setSelected={setUser} />}
              {step === 1 && (hasOnlyRooms
                ? <div className="surface" style={{padding: 20, textAlign: 'center'}}>
                    <i className="fas fa-door-open muted" style={{fontSize: 24, marginBottom: 8}}></i>
                    <div style={{fontSize: 14, fontWeight: 600}}>{t('wiz.rooms_skip_title', 'Room-only rental')}</div>
                    <div className="muted tiny" style={{marginTop: 4}}>
                      {t('wiz.rooms_skip_hint', 'Each room has its own time slot. You can skip this step.')}
                    </div>
                  </div>
                : <StepTime initial={initial} period={period} setPeriod={setPeriod} cart={cart} />)}
              {step === 2 && <StepItems initial={initial} cart={cart} setCart={setCart}
                                        rooms={rooms} setRooms={setRooms}
                                        user={user} period={period} />}
              {step === 3 && <StepReview user={user} period={period} cart={cart} rooms={rooms}
                                         project={project} setProject={setProject}
                                         purpose={purpose} setPurpose={setPurpose}
                                         notifyEmail={notifyEmail} setNotifyEmail={setNotifyEmail} />}
            </div>

            <div className="wizard-foot">
              <button className="btn btn-ghost btn-sm" disabled={step === 0} onClick={() => setStep(step - 1)}>
                <i className="fas fa-arrow-left me-1"></i>{t('btn.back', 'Back')}
              </button>
              <div className="progress-text">
                {t('wiz.step', 'Step')} {step + 1} {t('wiz.of', 'of')} {steps.length}
              </div>
              {step < steps.length - 1
                ? <button className="btn btn-primary btn-sm" disabled={!canNext()}
                          onClick={() => setStep(step + 1)}>
                    {t('btn.next', 'Next')} <i className="fas fa-arrow-right ms-1"></i>
                  </button>
                : <button className="btn btn-primary btn-sm" disabled={submitting} onClick={submit}>
                    <i className="fas fa-check me-1"></i>
                    {submitting ? t('btn.sending', 'Sending…') : t('btn.confirm_send', 'Confirm & send')}
                  </button>}
            </div>
          </>
      }
    </>
  );
}

/* ===== Stepper ===== */
function Stepper({ steps, active, setActive }) {
  return (
    <div className="stepper">
      {steps.map((s, i) => (
        <div key={i}
             className={cls('step', i === active && 'active', i < active && 'done')}
             onClick={() => setActive(i)}>
          <div className="step-num">
            {i < active ? <i className="fas fa-check" style={{fontSize: 11}}></i> : i + 1}
          </div>
          <div className="step-body">
            <div className="step-title">{s.title}</div>
            <div className="step-hint">{s.hint}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

/* Availability badge shared by the guided catalog and the quick-scan list.
   `stock` is the serializer's qty block ({avail, total, reserved, issued});
   the backend also sends a ready-made `status_label` for unavailable items. */
function availabilityLabel(stock, conflict, statusLabel) {
  if (statusLabel) return statusLabel;
  const q = stock || {};
  if (conflict && q.issued) return t('tag.issued', 'Issued');
  if (conflict && q.reserved) return t('tag.reserved', 'Reserved');
  if (conflict) return t('tag.booked', 'Booked');
  return q.avail > 0 ? t('tag.in_stock', 'In stock') : t('tag.out', 'Out');
}

function ItemStatusTag({ stock, conflict, statusLabel, showCounts = true }) {
  const q = stock || {};
  const label = availabilityLabel(stock, conflict, statusLabel);
  const free = !conflict && q.avail > 0;
  // Reserved/issued counts are shown even when the item is still available, so
  // an item wrongly left in "issued" state is visible at scan time.
  const notes = [];
  if (showCounts && q.reserved) notes.push(`${q.reserved} ${t('wiz.reserved', 'reserved')}`);
  if (showCounts && q.issued) notes.push(`${q.issued} ${t('wiz.issued_count', 'issued')}`);
  return (
    <div>
      <span className={cls('tag', free ? 'tag-ok' : 'tag-hold')}>
        {!free && <i className="fas fa-lock" style={{fontSize: 9}}></i>}{label}
      </span>
      {notes.length > 0 && <div className="muted tiny mt-1">{notes.join(' · ')}</div>}
    </div>
  );
}

/* ===== STEP 1 — Items & rooms ===== */
function StepItems({ initial, cart, setCart, rooms, setRooms, user, period }) {
  const [activeTab, setActiveTab] = React.useState(initial.categories[0]?.id || '');
  const [mode, setMode] = React.useState('items');
  const [search, setSearch] = React.useState('');
  const [items, setItems] = React.useState([]);
  const [categories, setCategories] = React.useState(initial.categories || []);
  const [loading, setLoading] = React.useState(false);
  const [sets, setSets] = React.useState([]);
  const [setsLoading, setSetsLoading] = React.useState(false);
  const [setsError, setSetsError] = React.useState('');
  const [addingSetId, setAddingSetId] = React.useState(null);

  React.useEffect(() => {
    if (mode !== 'items' || activeTab == null) return;
    setLoading(true);
    const timer = setTimeout(() => {
      const params = { cat: activeTab, q: search };
      if (user && user.id) params.user_id = user.id;
      if (period && period.from) params.from = period.from;
      if (period && period.to) params.to = period.to;
      const q = new URLSearchParams(params);
      apiGet(`${initial.urls.inventory_search}?${q}`)
        .then(data => {
          setItems(data.items || []);
          if (Array.isArray(data.categories)) {
            setCategories(data.categories);
          }
        })
        .catch(() => setItems([]))
        .finally(() => setLoading(false));
    }, search ? 250 : 0);
    return () => clearTimeout(timer);
  }, [activeTab, search, mode, user, period]);

  React.useEffect(() => {
    if (mode !== 'sets') return;
    setSetsLoading(true);
    setSetsError('');
    apiGet(initial.urls.equipment_sets)
      .then(data => {
        setSets(data.equipment_sets || []);
      })
      .catch(err => {
        setSets([]);
        setSetsError(err.message || t('wiz.sets_error', 'Could not load equipment sets.'));
      })
      .finally(() => setSetsLoading(false));
  }, [mode, initial.urls.equipment_sets]);

  const inCart = id => cart.some(c => c.id === id);
  const addItem = it => !inCart(it.id) && setCart(c => [...c, { id: it.id, name: it.name, num: it.num, qty: 1, cat: it.cat }]);
  const setQty = (id, qty) => setCart(c => c.map(x => x.id === id ? { ...x, qty } : x));
  const removeItem = id => setCart(c => c.filter(x => x.id !== id));

  const addSetToCart = async (setId) => {
    if (addingSetId) return;
    setAddingSetId(setId);
    try {
      const url = initial.urls.equipment_set_details.replace('/0/', `/${setId}/`);
      const data = await apiGet(url);
      const setItems = data.equipment_set?.items || [];
      if (setItems.length === 0) return;
      setCart(prevCart => {
        const nextCart = prevCart.slice();
        for (const si of setItems) {
          const invId = si.inventory_item_id;
          const existing = nextCart.find(c => c.id === invId);
          if (existing) {
            existing.qty += si.quantity_needed || 1;
          } else {
            nextCart.push({
              id: invId,
              name: si.description || '',
              num: si.inventory_number || '',
              qty: si.quantity_needed || 1,
              cat: si.category || '',
            });
          }
        }
        return nextCart;
      });
    } catch (err) {
      setSetsError(err.message || t('wiz.set_add_error', 'Could not add equipment set.'));
    } finally {
      setAddingSetId(null);
    }
  };

  const visibleCategories = React.useMemo(() => categories.filter(c => c.count > 0 || c.id === ''), [categories]);

  React.useEffect(() => {
    if (!visibleCategories.some(c => c.id === activeTab)) {
      setActiveTab(visibleCategories[0]?.id || '');
    }
  }, [visibleCategories, activeTab]);

  return (
    <div>
      <div className="d-flex align-items-center mb-3" style={{gap: 12}}>
        <h2 style={{fontSize: 16, fontWeight: 600, margin: 0}}>
          {t('wiz.what_need', 'What do you need?')}
        </h2>
        <div className="muted tiny">{t('wiz.tap_to_add', 'Tap to add. Then set quantities on the right.')}</div>
        <div className="ms-auto d-flex" style={{gap: 4}}>
          <button className={cls('btn btn-sm', mode === 'items' ? 'btn-primary' : 'btn-ghost')}
                  onClick={() => setMode('items')}
                  disabled={rooms.length > 0}
                  title={rooms.length > 0 ? t('wiz.rooms_only_hint', 'Equipment must be rented separately — create a new rental for equipment') : ''}
                  style={{opacity: rooms.length > 0 ? 0.5 : 1, pointerEvents: rooms.length > 0 ? 'none' : 'auto'}}>
            <i className="fas fa-toolbox me-1"></i>{t('wiz.equipment', 'Equipment')}
          </button>
          <button className={cls('btn btn-sm', mode === 'sets' ? 'btn-primary' : 'btn-ghost')}
                  onClick={() => setMode('sets')}
                  disabled={rooms.length > 0}
                  title={rooms.length > 0 ? t('wiz.rooms_only_hint', 'Equipment must be rented separately — create a new rental for equipment') : ''}
                  style={{opacity: rooms.length > 0 ? 0.5 : 1, pointerEvents: rooms.length > 0 ? 'none' : 'auto'}}>
            <i className="fas fa-layer-group me-1"></i>{t('wiz.sets', 'Sets')}
          </button>
          <button className={cls('btn btn-sm', mode === 'rooms' ? 'btn-primary' : 'btn-ghost')}
                  onClick={() => setMode('rooms')}
                  disabled={cart.length > 0}
                  title={cart.length > 0 ? t('wiz.equipment_only_hint', 'Rooms must be rented separately — create a new rental for rooms') : ''}
                  style={{opacity: cart.length > 0 ? 0.5 : 1, pointerEvents: cart.length > 0 ? 'none' : 'auto'}}>
            <i className="fas fa-door-open me-1"></i>{t('wiz.rooms', 'Reserve rooms')}
          </button>
        </div>
      </div>

      <CartSummary cart={cart} setQty={setQty} removeItem={removeItem} rooms={rooms} />

      {mode === 'items' ? (
        <div className="catalog" style={{border: '1px solid var(--line)', borderRadius: 12, overflow: 'hidden', background: '#fff'}}>
          <div className="catalog-tabs">
            {visibleCategories.map(c => (
              <div key={c.id} className={cls('t', activeTab === c.id && 'active')}
                   onClick={() => setActiveTab(c.id)}>
                <i className={`fas ${c.icon}`}></i>
                <span>{c.label}</span>
                <span className="count">{c.count}</span>
              </div>
            ))}
          </div>
          <div className="catalog-body">
            <div className="filters">
              <div className="search">
                <i className="fas fa-search"></i>
                <input type="text" className="form-control" placeholder={t('wiz.search_items', 'Search items…')}
                       value={search} onChange={e => setSearch(e.target.value)} />
              </div>
              <div className="ms-auto muted tiny">
                {loading ? t('loading', 'Loading…') : `${items.length} ${t('wiz.in_cat', 'in category')}`}
              </div>
            </div>

            {items.map(item => {
              const chosen = inCart(item.id);
              const canChoose = item.qty.avail > 0 && !item.conflict;
              return (
                <div key={item.id}
                     className={cls('item-row', chosen && 'selected', !canChoose && !chosen && 'unavailable')}
                     onClick={() => canChoose && addItem(item)}>
                  <input type="checkbox" className="form-check-input" checked={chosen} readOnly disabled={!canChoose && !chosen} />
                  <div style={{display: 'flex', alignItems: 'center', gap: 8, minWidth: 0}}>
                    {item.thumbnail_url && (
                      <img src={item.thumbnail_url} alt="" loading="lazy"
                           title={t('wiz.enlarge_photo', 'Click to enlarge')}
                           onClick={e => { e.stopPropagation(); openPhotoLightbox(item.image_urls && item.image_urls.length ? item.image_urls : (item.image_url || item.thumbnail_url)); }}
                           style={{width: 34, height: 34, objectFit: 'cover', borderRadius: 6,
                                   border: '1px solid var(--line)', flexShrink: 0, cursor: 'zoom-in'}} />
                    )}
                    <div style={{minWidth: 0}}>
                      <div className="name">{item.name}</div>
                      <div className="num">{item.num} · <span className="muted">{item.loc}</span></div>
                    </div>
                  </div>
                  <div className="meta">{item.qty.avail}/{item.qty.total} {t('wiz.available', 'available')}</div>
                  <div>
                    <ItemStatusTag stock={item.qty} conflict={item.conflict}
                                   statusLabel={item.status_label} showCounts={false} />
                  </div>
                  <div className="meta" style={{textAlign: 'right'}}>
                    {item.qty.reserved ? `${item.qty.reserved} ${t('wiz.reserved','reserved')}` : t('wiz.free','Free')}
                  </div>
                  <div style={{textAlign: 'right'}}>
                    <button className="btn btn-sm btn-ghost" disabled={!canChoose && !chosen}
                            onClick={e => { e.stopPropagation(); chosen ? removeItem(item.id) : addItem(item); }}>
                      <i className={`fas fa-${chosen ? 'minus' : 'plus'}`}></i>
                    </button>
                  </div>
                </div>
              );
            })}
            {!loading && items.length === 0 && (
              <div className="muted p-3">{t('wiz.no_items', 'No items match.')}</div>
            )}
          </div>
        </div>
      ) : mode === 'sets' ? (
        <div className="catalog" style={{border: '1px solid var(--line)', borderRadius: 12, overflow: 'hidden', background: '#fff'}}>
          <div className="catalog-body">
            <div className="filters">
              <div className="ms-auto muted tiny">
                {setsLoading ? t('loading', 'Loading…') : `${sets.length} ${t('wiz.sets_count', 'sets')}`}
              </div>
            </div>

            {setsError && (
              <div className="alert alert-warning" style={{fontSize: 13, padding: '10px 12px', marginBottom: 10}}>
                <i className="fas fa-exclamation-triangle me-1"></i>{setsError}
              </div>
            )}

            {sets.map(set => (
              <div key={set.id} className="item-row" style={{cursor: 'default'}}>
                <div></div>
                <div>
                  <div className="name">{set.name}</div>
                  <div className="num">{set.description || ''}</div>
                </div>
                <div className="meta">{set.items_count} {t('wiz.items', 'items')}</div>
                <div></div>
                <div></div>
                <div style={{textAlign: 'right'}}>
                  <button className="btn btn-sm btn-ghost" disabled={addingSetId === set.id}
                          onClick={() => addSetToCart(set.id)}>
                    <i className={`fas fa-${addingSetId === set.id ? 'spinner fa-spin' : 'plus'}`}></i>
                    {addingSetId === set.id ? t('wiz.adding', 'Adding…') : t('wiz.add_set', 'Add set')}
                  </button>
                </div>
              </div>
            ))}

            {!setsLoading && sets.length === 0 && !setsError && (
              <div className="muted p-3">{t('wiz.no_sets', 'No equipment sets available.')}</div>
            )}
          </div>
        </div>
      ) : (
        <RoomPicker rooms={rooms} setRooms={setRooms} options={initial.rooms || []} initial={initial} period={period} />
      )}
    </div>
  );
}

function RoomPicker({ rooms, setRooms, options, initial, period }) {
  const [expandedRoom, setExpandedRoom] = React.useState(null);
  const [checking, setChecking] = React.useState({});
  const [availResult, setAvailResult] = React.useState({});
  const wh = initial?.working_hours || {};

  const getTimeSlots = (dateStr) => {
    if (!dateStr) return [];
    const d = new Date(dateStr + 'T00:00:00');
    const dayIdx = d.getDay() === 0 ? 6 : d.getDay() - 1;
    const dayHours = wh[String(dayIdx)];
    if (!dayHours || !dayHours.enabled) return [];
    const [sh, sm] = (dayHours.start || '00:00').split(':').map(Number);
    const [eh, em] = (dayHours.end || '00:00').split(':').map(Number);
    const slots = [];
    let mins = sh * 60 + sm;
    const endMins = eh * 60 + em;
    while (mins < endMins) {
      const h = String(Math.floor(mins / 60)).padStart(2, '0');
      const m = String(mins % 60).padStart(2, '0');
      const time = `${h}:${m}`;
      const slotStart = new Date(`${dateStr}T${time}:00`);
      if (slotStart >= new Date()) slots.push(time);
      mins += 30;
    }
    return slots;
  };

  const getDefaultTimes = (dateStr) => {
    const slots = getTimeSlots(dateStr);
    return { start: slots[0] || '', end: slots[slots.length - 1] || '' };
  };

  const checkAvailability = async (roomId, sd, st, ed, et) => {
    if (!sd || !st || !ed || !et) return;
    setChecking(c => ({ ...c, [roomId]: true }));
    setAvailResult(r => ({ ...r, [roomId]: null }));
    try {
      const params = new URLSearchParams({
        room_id: roomId, start_date: sd, start_time: st,
        end_date: ed, end_time: et,
      });
      const data = await apiGet(`${initial.urls.room_availability_check}?${params}`);
      setAvailResult(r => ({ ...r, [roomId]: data }));
    } catch {
      setAvailResult(r => ({ ...r, [roomId]: { success: false, is_available: false, message: t('room.check_error', 'Could not check availability') } }));
    }
    setChecking(c => ({ ...c, [roomId]: false }));
  };

  const toggleExpand = (r) => {
    if (expandedRoom === r.id) {
      setExpandedRoom(null);
    } else {
      setExpandedRoom(r.id);
    }
  };

  const confirmRoom = (roomId, name, sd, st, ed, et) => {
    setRooms(rs => {
      const exists = rs.find(x => x.id === roomId);
      const entry = { id: roomId, name, start_date: sd, start_time: st, end_date: ed, end_time: et };
      return exists ? rs.map(x => x.id === roomId ? entry : x) : [...rs, entry];
    });
    setExpandedRoom(null);
  };

  const removeRoom = (roomId) => {
    setRooms(rs => rs.filter(x => x.id !== roomId));
    setExpandedRoom(null);
    setAvailResult(r => { const copy = { ...r }; delete copy[roomId]; return copy; });
  };

  return (
    <div className="surface" style={{padding: 14}}>
      <div className="row g-2">
        {options.map(r => {
          const booked = rooms.find(x => x.id === r.id);
          const isExpanded = expandedRoom === r.id;
          const result = availResult[r.id];
          return (
            <div key={r.id} className="col-md-6">
              <div className={cls('user-card', booked && 'selected')}
                   style={{gridTemplateColumns: '36px 1fr auto', cursor: 'pointer'}}>
                <span className="av" style={{width: 36, height: 36, fontSize: 14, overflow: 'hidden', padding: 0}} onClick={() => toggleExpand(r)}>
                  {r.image_url
                    ? <img src={r.image_url} alt="" loading="lazy"
                           title={t('wiz.enlarge_photo', 'Click to enlarge')}
                           onClick={e => { e.stopPropagation(); openPhotoLightbox(r.image_urls && r.image_urls.length ? r.image_urls : (r.image_full_url || r.image_url)); }}
                           style={{width: '100%', height: '100%', objectFit: 'cover', cursor: 'zoom-in'}} />
                    : <i className="fas fa-door-open"></i>}
                </span>
                <div onClick={() => toggleExpand(r)}>
                  <div className="name">{r.name}</div>
                  <div className="org">{r.sub}</div>
                  {booked && (
                    <div className="tiny" style={{color: 'var(--brand)', marginTop: 2}}>
                      {booked.start_date} {booked.start_time} – {booked.end_date} {booked.end_time}
                    </div>
                  )}
                </div>
                {!r.free
                  ? <span className="tag tag-warn">{t('room.restricted','Restricted')}</span>
                  : booked
                    ? <span className="tag tag-hold" style={{cursor: 'pointer'}} onClick={(e) => { e.stopPropagation(); removeRoom(r.id); }}>
                        <i className="fas fa-times" style={{fontSize: 9, marginRight: 4}}></i>{t('room.remove','Remove')}
                      </span>
                    : <span className="tag tag-ok">{t('room.open','Open')}</span>}
              </div>

              {isExpanded && !booked && (
                <RoomDateTimeForm
                  room={r}
                  wh={wh}
                  initial={initial}
                  period={period}
                  getTimeSlots={getTimeSlots}
                  getDefaultTimes={getDefaultTimes}
                  checking={checking[r.id]}
                  result={result}
                  onCheck={(sd, st, ed, et) => checkAvailability(r.id, sd, st, ed, et)}
                  onConfirm={(sd, st, ed, et) => confirmRoom(r.id, r.name, sd, st, ed, et)}
                  onCancel={() => setExpandedRoom(null)}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* Day strip for one room: shows which slots are taken and which are free, so
   a free window can be picked without trial and error. Reuses the room
   schedule API that also backs the Raumkalender page. */
function RoomDayStrip({ initial, roomId, date, startTime, endTime }) {
  const [slots, setSlots] = React.useState([]);
  const [loading, setLoading] = React.useState(false);

  React.useEffect(() => {
    if (!date) { setSlots([]); return; }
    let cancelled = false;
    setLoading(true);
    apiGet(`${initial.urls.room_schedule}?start_date=${date}&end_date=${date}`)
      .then(d => {
        if (cancelled) return;
        const room = (d.rooms || []).find(r => r.id === roomId);
        setSlots(room?.schedule?.[0]?.slots || []);
      })
      .catch(() => { if (!cancelled) setSlots([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [roomId, date]);

  if (!date || (!loading && slots.length === 0)) return null;

  const inSelection = (time) =>
    startTime && endTime && time >= startTime && time < endTime;

  return (
    <div style={{marginTop: 10}}>
      <div className="tiny muted" style={{marginBottom: 4}}>
        {t('room.day_overview', 'Day overview')}
        {loading && <span className="ms-2">{t('loading', 'Loading…')}</span>}
      </div>
      <div style={{display: 'flex', gap: 1, height: 20, borderRadius: 4, overflow: 'hidden'}}>
        {slots.map((s, i) => {
          const busy = s.status === 'occupied';
          const past = s.status === 'past';
          const picked = inSelection(s.time);
          const tip = busy
            ? `${s.time} · ${s.info?.start_time}–${s.info?.end_time} · ${s.info?.user_name || ''} ${s.info?.project ? '(' + s.info.project + ')' : ''}`.trim()
            : past
              ? `${s.time} · ${t('room.past', 'past')}`
              : `${s.time} · ${t('room.free', 'free')}`;
          return (
            <div key={i} title={tip}
                 style={{
                   flex: 1,
                   background: busy
                     ? 'oklch(0.72 0.15 28)'
                     : past
                       ? 'oklch(0.82 0.02 250)'
                       : 'oklch(0.88 0.09 145)',
                   outline: picked && !past ? '2px solid var(--ink-2, #333)' : 'none',
                   outlineOffset: -2,
                 }} />
          );
        })}
      </div>
      <div style={{display: 'flex', justifyContent: 'space-between', marginTop: 2}} className="tiny muted">
        <span>{slots[0]?.time}</span>
        <span>{slots[slots.length - 1]?.time}</span>
      </div>
      <div className="tiny muted" style={{marginTop: 4, display: 'flex', gap: 12}}>
        <span><span style={{display: 'inline-block', width: 9, height: 9, borderRadius: 2, background: 'oklch(0.88 0.09 145)', marginRight: 4}}></span>{t('room.free', 'free')}</span>
        <span><span style={{display: 'inline-block', width: 9, height: 9, borderRadius: 2, background: 'oklch(0.72 0.15 28)', marginRight: 4}}></span>{t('room.busy', 'booked')}</span>
        <span><span style={{display: 'inline-block', width: 9, height: 9, borderRadius: 2, background: 'oklch(0.82 0.02 250)', marginRight: 4}}></span>{t('room.past', 'past')}</span>
      </div>
    </div>
  );
}

function RoomDateTimeForm({ room, wh, period, getTimeSlots, getDefaultTimes, checking, result, onCheck, onConfirm, onCancel, initial }) {
  const today = _fmtDT(new Date()).slice(0, 10);
  const periodStart = period?.from ? period.from.slice(0, 10) : today;
  const periodEnd = period?.to ? period.to.slice(0, 10) : today;
  const periodStartTime = period?.from ? period.from.slice(11, 16) : '';
  const periodEndTime = period?.to ? period.to.slice(11, 16) : '';
  const [startDate, setStartDate] = React.useState(periodStart);
  const [endDate, setEndDate] = React.useState(periodEnd);
  const startSlots = getTimeSlots(startDate);
  const endSlots = getTimeSlots(endDate);
  const defaults = getDefaultTimes(startDate);
  const [startTime, setStartTime] = React.useState(periodStartTime || defaults.start);
  const [endTime, setEndTime] = React.useState(periodEndTime || defaults.end);

  React.useEffect(() => {
    const d = getDefaultTimes(startDate);
    if (!startSlots.includes(startTime)) setStartTime(d.start);
  }, [startDate]);
  React.useEffect(() => {
    const d = getDefaultTimes(endDate);
    if (!endSlots.includes(endTime)) setEndTime(d.end);
  }, [endDate]);

  const startDayIdx = startDate ? (new Date(startDate + 'T00:00:00').getDay() === 0 ? 6 : new Date(startDate + 'T00:00:00').getDay() - 1) : -1;
  const startDayHours = wh[String(startDayIdx)];
  const dayClosed = startDayHours && !startDayHours.enabled;
  const endDayIdx = endDate ? (new Date(endDate + 'T00:00:00').getDay() === 0 ? 6 : new Date(endDate + 'T00:00:00').getDay() - 1) : -1;
  const endDayHours = wh[String(endDayIdx)];
  const noFutureSlots = (
    (startDayHours?.enabled && startSlots.length === 0)
    || (endDayHours?.enabled && endSlots.length === 0)
  );

  const canCheck = startDate && startTime && endDate && endTime && !dayClosed && !noFutureSlots;
  const canConfirm = result && result.is_available;

  return (
    <div style={{padding: '10px 12px', borderTop: '1px solid var(--line)', background: 'var(--bg-sub, #f8f9fa)', borderRadius: '0 0 8px 8px'}}>
      <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: 12}}>
        <div>
          <label className="muted tiny" style={{display: 'block', marginBottom: 2}}>{t('room.start_date', 'Start date')}</label>
          <input type="date" className="form-control form-control-sm" value={startDate}
                  onChange={e => { setStartDate(e.target.value); setEndDate(e.target.value); }} min={today} />
        </div>
        <div>
          <label className="muted tiny" style={{display: 'block', marginBottom: 2}}>{t('room.start_time', 'Start time')}</label>
          {startDayHours?.enabled ? (
            <select className="form-select form-select-sm" value={startTime} disabled={startSlots.length === 0} onChange={e => setStartTime(e.target.value)}>
              {startSlots.length === 0 && <option value="">—</option>}
              {startSlots.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          ) : (
            <input type="time" className="form-control form-control-sm" value={startTime} step="1800"
                   onChange={e => setStartTime(e.target.value)} />
          )}
        </div>
        <div>
          <label className="muted tiny" style={{display: 'block', marginBottom: 2}}>{t('room.end_date', 'End date')}</label>
          <input type="date" className="form-control form-control-sm" value={endDate}
                 onChange={e => setEndDate(e.target.value)} min={startDate || today} />
        </div>
        <div>
          <label className="muted tiny" style={{display: 'block', marginBottom: 2}}>{t('room.end_time', 'End time')}</label>
          {endDayHours?.enabled ? (
            <select className="form-select form-select-sm" value={endTime} disabled={endSlots.length === 0} onChange={e => setEndTime(e.target.value)}>
              {endSlots.length === 0 && <option value="">—</option>}
              {endSlots.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          ) : (
            <input type="time" className="form-control form-control-sm" value={endTime} step="1800"
                   onChange={e => setEndTime(e.target.value)} />
          )}
        </div>
      </div>

      {dayClosed && (
        <div className="tiny" style={{color: 'oklch(0.45 0.14 28)', marginTop: 6}}>
          <i className="fas fa-triangle-exclamation me-1"></i>{t('room.day_closed', 'Selected day is closed.')}
        </div>
      )}

      {!dayClosed && noFutureSlots && (
        <div className="tiny" style={{color: 'oklch(0.45 0.14 28)', marginTop: 6}}>
          <i className="fas fa-clock me-1"></i>{t('room.no_future_slots', 'No reservable time remains on this day.')}
        </div>
      )}

      {!dayClosed && (
        <RoomDayStrip initial={initial} roomId={room.id} date={startDate}
                      startTime={startTime} endTime={endTime} />
      )}

      {result && !result.is_available && (
        <div className="tiny" style={{color: 'oklch(0.45 0.14 28)', marginTop: 6}}>
          <i className="fas fa-triangle-exclamation me-1"></i>{result.message || t('room.not_available', 'Room is not available for this period.')}
          {result.conflicts && result.conflicts.length > 0 && (
            <div style={{marginTop: 4}}>
              <strong>{t('room.booked_at', 'Already booked:')}</strong>
              <ul style={{margin: '2px 0 0', paddingLeft: 18}}>
                {result.conflicts.map((c, i) => <li key={i}>{c}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}
      {result && result.is_available && (
        <div className="tiny" style={{color: 'oklch(0.45 0.12 145)', marginTop: 6}}>
          <i className="fas fa-check-circle me-1"></i>{t('room.available', 'Room is available!')}
        </div>
      )}

      <div style={{display: 'flex', gap: 6, marginTop: 8, justifyContent: 'flex-end'}}>
        <button className="btn btn-ghost btn-sm" onClick={onCancel}>{t('btn.cancel', 'Cancel')}</button>
        <button className="btn btn-ghost btn-sm" disabled={!canCheck || checking}
                onClick={() => onCheck(startDate, startTime, endDate, endTime)}>
          {checking ? t('loading', 'Loading…') : <><i className="fas fa-search me-1"></i>{t('room.check', 'Check')}</>}
        </button>
        <button className="btn btn-primary btn-sm" disabled={!canConfirm}
                onClick={() => onConfirm(startDate, startTime, endDate, endTime)}>
          <i className="fas fa-plus me-1"></i>{t('room.reserve', 'Reserve')}
        </button>
      </div>
    </div>
  );
}

function CartSummary({ cart, setQty, removeItem, rooms }) {
  if (cart.length === 0 && rooms.length === 0) return null;
  return (
    <div className="surface" style={{marginTop: 14, padding: '12px 14px'}}>
      <div className="d-flex align-items-center mb-2" style={{gap: 8}}>
        <strong style={{fontSize: 13}}>{t('cart.title', 'In this rental')}</strong>
        <span className="muted tiny">{cart.length} {t('wiz.items', 'items')} · {rooms.length} {t('wiz.rooms', 'rooms')}</span>
      </div>
      {cart.map(c => (
        <div key={c.id} style={{display: 'grid', gridTemplateColumns: '1fr 120px 34px', gap: 10, alignItems: 'center',
                                   padding: '8px 0', borderBottom: '1px solid var(--line)', fontSize: 13}}>
          <div>
            <div style={{fontWeight: 500}}>{c.name}</div>
            <div className="muted mono" style={{fontSize: 11}}>{c.num} · {c.cat}</div>
          </div>
          <div className="input-group input-group-sm" style={{maxWidth: 110}}>
            <button className="btn btn-ghost" onClick={() => setQty(c.id, Math.max(1, c.qty - 1))}>−</button>
            <input className="form-control text-center" value={c.qty} readOnly />
            <button className="btn btn-ghost" onClick={() => setQty(c.id, c.qty + 1)}>+</button>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={() => removeItem(c.id)}>
            <i className="fas fa-times muted"></i>
          </button>
        </div>
      ))}
      {rooms.map(r => (
        <div key={r.id} style={{display: 'flex', gap: 10, alignItems: 'center', padding: '8px 0',
                                   borderBottom: '1px solid var(--line)', fontSize: 13}}>
          <i className="fas fa-door-open muted"></i>
          <div>
            <div style={{fontWeight: 500}}>{r.name}</div>
            <div className="muted tiny">{r.start_date} {r.start_time} – {r.end_date} {r.end_time}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ===== STEP 2 — User ===== */
/* User lookup shared by the guided user step and the quick-mode picker:
   the preloaded list is filtered in the browser and merged with a debounced
   remote search so users outside that list are findable too. */
function useUserSearch(initial, q) {
  const [remoteUsers, setRemoteUsers] = React.useState([]);
  const [loading, setLoading] = React.useState(false);

  React.useEffect(() => {
    if (!q || q.length < 2) { setRemoteUsers([]); setLoading(false); return; }
    setLoading(true);
    const timer = setTimeout(() => {
      apiGet(initial.urls.users_search + '?q=' + encodeURIComponent(q))
        .then(data => setRemoteUsers(data.users || []))
        .catch(() => setRemoteUsers([]))
        .finally(() => setLoading(false));
    }, 300);
    return () => clearTimeout(timer);
  }, [q]);

  const needle = (q || '').toLowerCase();
  const localFiltered = (initial.users || []).filter(u =>
    !needle || u.name.toLowerCase().includes(needle) || u.org.toLowerCase().includes(needle)
  );
  const seen = new Set(localFiltered.map(u => u.id));
  return {
    users: [...localFiltered, ...(remoteUsers || []).filter(u => !seen.has(u.id))],
    loading,
  };
}

function StepUser({ initial, selected, setSelected }) {
  const [q, setQ] = React.useState('');
  const { users: merged, loading } = useUserSearch(initial, q);

  return (
    <div>
      <h2 style={{fontSize: 16, fontWeight: 600, margin: '0 0 4px'}}>
        {t('wiz.who', 'Who is this rental for?')}
      </h2>
      <div className="muted tiny" style={{marginBottom: 14}}>
        {t('wiz.who_sub', 'Pick an existing user or create a new account.')}
      </div>
      <div className="filters" style={{marginBottom: 12}}>
        <div className="search" style={{maxWidth: 420}}>
          <i className="fas fa-search"></i>
          <input type="text" className="form-control"
                 placeholder={t('wiz.search_user', 'Search by name, email, student ID…')}
                 value={q} onChange={e => setQ(e.target.value)} />
        </div>
        <a className="btn btn-ghost btn-sm" href={initial.urls.new_user} target="_blank">
          <i className="fas fa-user-plus me-1"></i>{t('wiz.new_user', 'New user')}
        </a>
      </div>
      {loading && <div className="muted tiny" style={{marginBottom: 8}}>{t('loading', 'Searching…')}</div>}
      <div className="row g-2">
        {merged.map(u => (
          <div key={u.id} className="col-md-6">
            <div className={cls('user-card', selected?.id === u.id && 'selected')}
                 onClick={() => setSelected(u)}>
              <Avatar user={u} size={32} />
              <div style={{minWidth: 0}}>
                <div className="name">{u.name}</div>
                <div className="org">{u.org} · <RoleBadge role={u.role} roleKey={u.role_key} /> · {u.past || 0} {t('user.past_rentals','past rentals')}</div>
                {u.warn && <div className="mt-1 tiny" style={{color: 'oklch(0.45 0.14 28)'}}>
                  <i className="fas fa-triangle-exclamation me-1"></i>{u.warn}
                </div>}
              </div>
              {selected?.id === u.id && <i className="fas fa-check" style={{color: 'var(--brand)'}}></i>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ===== Quick Pick presets ===== */
function QuickPick({ period, setPeriod, workingHours }) {
  const applyQuickPick = (preset) => {
    const now = new Date();
    let from, to;

    switch (preset) {
      case 'today-tomorrow': {
        from = snapToWorkingHours(now, workingHours);
        to = new Date(from);
        to.setDate(to.getDate() + 1);
        break;
      }
      case 'afternoon': {
        // Start at 14:00 today, snap forward to valid hours if needed
        from = snapToWorkingHours(
          new Date(now.getFullYear(), now.getMonth(), now.getDate(), 14, 0, 0, 0),
          workingHours,
        );
        // End at closing time of whatever day "from" landed on
        const fromDayHours = _whForDate(from, workingHours);
        const [eh, em] = fromDayHours?.enabled
          ? fromDayHours.end.split(':').map(Number)
          : [18, 0];
        to = new Date(from);
        to.setHours(eh, em, 0, 0);
        break;
      }
      case 'weekend': {
        const dow = now.getDay();
        const daysUntilFri = dow <= 5 ? 5 - dow : 5 + (7 - dow);
        const fri = new Date(now);
        fri.setDate(fri.getDate() + daysUntilFri);
        const friHours = _whForDate(fri, workingHours);
        if (friHours?.enabled) {
          const [fh, fm] = friHours.start.split(':').map(Number);
          fri.setHours(fh, fm, 0, 0);
        } else {
          fri.setHours(10, 0, 0, 0);
        }
        from = fri;

        const mon = new Date(fri);
        mon.setDate(mon.getDate() + 3);
        const monHours = _whForDate(mon, workingHours);
        if (monHours?.enabled) {
          const [mh, mm] = monHours.end.split(':').map(Number);
          mon.setHours(mh, mm, 0, 0);
        } else {
          mon.setHours(18, 0, 0, 0);
        }
        to = mon;
        break;
      }
      case '7days': {
        from = snapToWorkingHours(now, workingHours);
        to = new Date(from);
        to.setDate(to.getDate() + 7);
        break;
      }
    }

    setPeriod({ from: _fmtDT(from), to: _fmtDT(to) });
  };

  const presets = [
    { key: 'today-tomorrow', label: t('quick.today_tomorrow', 'Today → tomorrow') },
    { key: 'afternoon',      label: t('quick.afternoon', 'This afternoon') },
    { key: 'weekend',        label: t('quick.weekend', 'Fri — Mon (weekend)') },
    { key: '7days',          label: t('quick.7days', 'Next 7 days') },
  ];

  return (
    <div className="t-card surface p-3" style={{marginBottom: 14}}>
      <div className="muted tiny" style={{textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.04em'}}>
        {t('quick.title', 'Quick pick')}
      </div>
      <div className="mt-2" style={{display: 'flex', flexWrap: 'wrap', gap: 6}}>
        {presets.map(p => (
          <button key={p.key} className="btn btn-sm btn-ghost" onClick={() => applyQuickPick(p.key)}>
            {p.label}
          </button>
        ))}
      </div>
    </div>
  );
}

/* ===== STEP 3 — Time & conflicts ===== */
function StepTime({ initial, period, setPeriod, cart }) {
  const [conflicts, setConflicts] = React.useState([]);
  const [loading, setLoading] = React.useState(false);

  // Earliest valid pickup time (snapped to working hours)
  const earliestFrom = React.useMemo(() => {
    return _fmtDT(snapToWorkingHours(new Date(), initial.working_hours));
  }, [initial.working_hours]);

  // Snap a field value to working hours on blur
  const snapInput = (field, raw) => {
    const snapped = snapToWorkingHours(new Date(raw), initial.working_hours);
    const snappedStr = _fmtDT(snapped);
    if (snappedStr !== raw) {
      setPeriod(p => ({...p, [field]: snappedStr}));
    }
  };

  // Pull real conflict data whenever period or cart changes. Rooms are not
  // covered here: each room carries its own time slot, picked inline in the
  // room step, so this step is skipped for room-only rentals.
  React.useEffect(() => {
    if (!period.from || !period.to || cart.length === 0) { setConflicts([]); return; }
    setLoading(true);
    const timer = setTimeout(() => {
      apiPost(initial.urls.availability_check, {
        from: period.from, to: period.to, items: cart.map(c => c.id),
      }).then(d => setConflicts(d.rows || []))
        .catch(() => setConflicts([]))
        .finally(() => setLoading(false));
    }, 300);
    return () => clearTimeout(timer);
  }, [period.from, period.to, cart]);

  const from = new Date(period.from), to = new Date(period.to);
  const warnings = [];
  if (period.from && period.to && from >= to) warnings.push(t('wiz.warn.reversed', 'End time is before start time.'));

  // Check against configured working hours
  const wh = initial.working_hours || {};
  if (period.from) {
    const dayKey = String(from.getDay() === 0 ? 6 : from.getDay() - 1); // JS getDay: 0=Sun, config: 0=Mon
    const dayHours = wh[dayKey];
    if (dayHours && !dayHours.enabled) {
      warnings.push(t('wiz.warn.closed', 'Selected day is closed.'));
    } else if (dayHours && dayHours.enabled) {
      const h = from.getHours();
      const m = from.getMinutes();
      const startParts = (dayHours.start || '00:00').split(':').map(Number);
      const endParts = (dayHours.end || '00:00').split(':').map(Number);
      const startMins = startParts[0] * 60 + startParts[1];
      const endMins = endParts[0] * 60 + endParts[1];
      const pickMins = h * 60 + m;
      if (pickMins < startMins || pickMins >= endMins) {
        warnings.push(t('wiz.warn.hours', 'Pickup is outside working hours ({start} – {end}).').replace('{start}', dayHours.start).replace('{end}', dayHours.end));
      }
    }
  }
  const duration = period.from && period.to ? Math.round((to - from) / 36e5) : 0;
  const hasConflict = conflicts.some(c => c.ranges && c.ranges.some(r => r.conflict));

  return (
    <div>
      <h2 style={{fontSize: 16, fontWeight: 600, margin: '0 0 4px'}}>
        {t('wiz.when', 'When is the equipment needed?')}
      </h2>
      <div className="muted tiny" style={{marginBottom: 14}}>
        {(() => {
          const wh = initial.working_hours || {};
          const days = [];
          for (let i = 0; i < 7; i++) {
            const d = wh[String(i)];
            if (d && d.enabled) days.push(d.short_label);
          }
          const hours = Object.values(wh).filter(d => d.enabled).map(d => d.start + '–' + d.end);
          const uniqueHours = [...new Set(hours)].join(', ');
          return t('wiz.hours', 'Working hours: {days} {hours}').replace('{days}', days.join('–')).replace('{hours}', uniqueHours);
        })()}
      </div>

      <div className="time-grid" style={{marginBottom: 14}}>
        <div className="t-card">
          <label>{t('wiz.pickup', 'Pickup')}</label>
          <input type="datetime-local" className="form-control" value={period.from} step="1800"
                 min={earliestFrom}
                 onChange={e => setPeriod(p => ({...p, from: e.target.value}))}
                 onBlur={e => { if (e.target.value) snapInput('from', e.target.value); }} />
        </div>
        <div className="t-card">
          <label>{t('wiz.return_by', 'Return by')}</label>
          <input type="datetime-local" className="form-control" value={period.to} step="1800"
                 min={period.from || earliestFrom}
                 onChange={e => setPeriod(p => ({...p, to: e.target.value}))}
                 onBlur={e => { if (e.target.value) snapInput('to', e.target.value); }} />
          <div className="tiny muted mt-1">
            <i className="fas fa-clock me-1"></i>{duration > 0 ? `${duration}h` : '—'}
          </div>
        </div>
      </div>

      <QuickPick period={period} setPeriod={setPeriod} workingHours={initial.working_hours} />

      {warnings.length > 0 && (
        <div className="inline-extend" style={{background: 'oklch(0.97 0.04 28)', borderColor: 'oklch(0.85 0.09 28)'}}>
          <i className="fas fa-triangle-exclamation" style={{color: 'oklch(0.55 0.16 28)'}}></i>
          <ul style={{margin: 0, paddingLeft: 16, color: 'oklch(0.35 0.12 28)'}}>
            {warnings.map((w, i) => <li key={i} style={{fontSize: 12}}>{w}</li>)}
          </ul>
        </div>
      )}

      {conflicts.length > 0 && (
        <div className="availability">
          <div className="d-flex align-items-center" style={{gap: 10, marginBottom: 10}}>
            <strong style={{fontSize: 13}}>{t('wiz.availability', 'Availability — selected period')}</strong>
            {hasConflict
              ? <span className="tag tag-bad"><i className="fas fa-exclamation"></i>{t('wiz.conflicts', 'Conflicts')}</span>
              : <span className="tag tag-ok">{t('wiz.clear', 'All clear')}</span>}
            {loading && <span className="muted tiny ms-auto">{t('loading', 'Loading…')}</span>}
          </div>
          <div style={{display: 'grid', gridTemplateColumns: '180px 1fr', gap: 10, alignItems: 'center', fontSize: 12}}>
            {conflicts.map((row, i) => (
              <React.Fragment key={i}>
                <div style={{fontSize: 12.5, color: 'var(--ink-2)', fontWeight: 500}}>{row.item}</div>
                <div className="timeline-track">
                  {row.selection && (
                    <div className="timeline-block selection"
                         style={{left: `${row.selection.left}%`, width: `${row.selection.width}%`}}>
                      {t('wiz.your_booking', 'Your booking')}
                    </div>
                  )}
                  {(row.ranges || []).map((r, j) => (
                    <div key={j} className="timeline-block"
                         style={{left: `${r.left}%`, width: `${r.width}%`}}
                         title={r.title || r.label}>{r.label}</div>
                  ))}
                </div>
              </React.Fragment>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ===== STEP 4 — Review + email preview ===== */
function StepReview({ user, period, cart, rooms, project, setProject, purpose, setPurpose,
                     notifyEmail, setNotifyEmail }) {
  if (!user) return <div className="muted">{t('wiz.need_user','Select a user first.')}</div>;
  return (
    <div className="col-lg-12">
        <h2 style={{fontSize: 16, fontWeight: 600, margin: '0 0 10px'}}>
          {t('wiz.confirm', 'Confirm details')}
        </h2>

        <div className="surface p-3 mb-3">
          <div className="muted tiny" style={{textTransform: 'uppercase', fontWeight: 600, letterSpacing: '.04em', marginBottom: 6}}>
            {t('wiz.project', 'Project')}
          </div>
          <input className="form-control" value={project} onChange={e => setProject(e.target.value)}
                 placeholder={t('wiz.project_ph', 'Project name')}
                 required style={{fontSize: 15, fontWeight: 600}} />
          {!project.trim() && <div className="muted tiny" style={{marginTop: 4}}>
            <span style={{color: 'oklch(0.50 0.16 28)'}}>*</span> {t('wiz.project_req', 'Required — please enter a project name')}
          </div>}
          <textarea className="form-control mt-2" rows={2} value={purpose}
                    onChange={e => setPurpose(e.target.value)}
                    placeholder={t('wiz.purpose_ph', 'Short description of purpose')} />
        </div>

        <div className="surface p-3 mb-3">
          <strong style={{fontSize: 13}}>{t('wiz.user', 'User')}</strong>
          <div className="d-flex mt-2" style={{gap: 10, alignItems: 'center'}}>
            <Avatar user={user} size={36} />
            <div>
              <div style={{fontWeight: 600, fontSize: 13}}>{user.name}</div>
              <div className="muted tiny">{user.org} · {user.role}</div>
            </div>
          </div>
        </div>

        <div className="surface p-3 mb-3">
          <strong style={{fontSize: 13}}>{t('wiz.period', 'Period')}</strong>
          {cart.length > 0 && period.from && period.to ? (
            <div style={{display: 'grid', gridTemplateColumns: '1fr auto 1fr', gap: 10, alignItems: 'center',
                          fontSize: 13, marginTop: 8}}>
              <div>
                <div className="muted tiny">{t('wiz.pickup', 'Pickup')}</div>
                <div style={{fontWeight: 600}}>{fmtDate(period.from.replace('T', ' '))}</div>
              </div>
              <i className="fas fa-arrow-right muted"></i>
              <div>
                <div className="muted tiny">{t('wiz.return', 'Return')}</div>
                <div style={{fontWeight: 600}}>{fmtDate(period.to.replace('T', ' '))}</div>
              </div>
            </div>
          ) : rooms.length > 0 ? (
            <div className="muted tiny" style={{marginTop: 6}}>
              {t('wiz.per_room', 'Time slots are set per room (see below).')}
            </div>
          ) : null}
        </div>

        <div className="surface p-3 mb-3">
          <strong style={{fontSize: 13}}>{t('wiz.items_rooms', 'Items & rooms')}</strong>
          <ul style={{margin: 8, paddingLeft: 0, listStyle: 'none', fontSize: 13}}>
            {cart.map(c => (
              <li key={c.id} style={{display: 'flex', justifyContent: 'space-between', padding: '4px 0',
                                        borderBottom: '1px solid var(--line)'}}>
                <span>{c.name}</span><span className="muted">× {c.qty}</span>
              </li>
            ))}
            {rooms.map(r => (
              <li key={r.id} style={{display: 'flex', justifyContent: 'space-between', padding: '4px 0',
                                        borderBottom: '1px solid var(--line)'}}>
                <span><i className="fas fa-door-open me-2 muted"></i>{r.name}</span>
                <span className="muted">{r.start_date} {r.start_time} – {r.end_date} {r.end_time}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="surface p-3">
          <strong style={{fontSize: 13}}>{t('wiz.notifications', 'Notifications')}</strong>
          <div className="form-check mt-2">
            <input className="form-check-input" type="checkbox" checked={notifyEmail}
                   onChange={e => setNotifyEmail(e.target.checked)} id="nEmail" />
            <label className="form-check-label tiny" htmlFor="nEmail">
              {t('wiz.notify_email', 'Send confirmation email to')} <strong>{user.email}</strong>
            </label>
          </div>
        </div>
    </div>
  );
}

/* Compact type-ahead user picker for quick mode. A plain <select> listing every
   user is unusable once the account list grows, so search the same way the
   guided step does and show the pick inline. */
function QuickUserPicker({ initial, user, setUser, onPicked }) {
  const [q, setQ] = React.useState('');
  const [open, setOpen] = React.useState(false);
  const { users, loading } = useUserSearch(initial, q);
  const boxRef = React.useRef(null);

  // Close the menu when the operator clicks anywhere else.
  React.useEffect(() => {
    if (!open) return;
    const onPointerDown = e => {
      if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', onPointerDown);
    return () => document.removeEventListener('mousedown', onPointerDown);
  }, [open]);

  const pick = u => { setUser(u); setQ(''); setOpen(false); if (onPicked) onPicked(u); };

  if (user) {
    return (
      <div className="d-flex align-items-center" style={{gap: 8, minWidth: 0}}>
        <Avatar user={user} size={26} />
        <div style={{minWidth: 0}}>
          <div className="text-truncate" style={{fontWeight: 500, fontSize: 13}}>{user.name}</div>
          <div className="tiny text-truncate d-flex align-items-center" style={{gap: 4}}>
            <RoleBadge role={user.role} roleKey={user.role_key} />
            <span className="muted text-truncate">{user.org}</span>
          </div>
        </div>
        <button className="btn btn-ghost btn-sm ms-auto" type="button"
                title={t('wiz.clear', 'Clear')}
                onClick={() => { setUser(null); setQ(''); setOpen(true); }}>
          <i className="fas fa-times muted"></i>
        </button>
      </div>
    );
  }

  const options = users.slice(0, 20);
  return (
    <div ref={boxRef} style={{position: 'relative'}}>
      <div className="input-group input-group-sm">
        <span className="input-group-text"><i className="fas fa-search"></i></span>
        <input type="text" className="form-control"
               placeholder={t('wiz.search_user', 'Search by name, email, student ID…')}
               value={q}
               onFocus={() => setOpen(true)}
               onChange={e => { setQ(e.target.value); setOpen(true); }}
               onKeyDown={e => {
                 if (e.key === 'Escape') setOpen(false);
                 // Enter picks the only remaining match, so a keyboard-only
                 // operator never has to reach for the mouse.
                 if (e.key === 'Enter' && options.length === 1) {
                   e.preventDefault();
                   pick(options[0]);
                 }
               }} />
      </div>
      {open && (
        <div className="quick-user-menu">
          {loading && <div className="muted tiny p-2">{t('loading', 'Loading…')}</div>}
          {!loading && options.length === 0 && (
            <div className="muted tiny p-2">{t('wiz.no_users', 'No users match your search.')}</div>
          )}
          {options.map(u => (
            <div key={u.id} className="quick-user-option" onClick={() => pick(u)}>
              <Avatar user={u} size={26} />
              <div style={{minWidth: 0}}>
                <div className="text-truncate" style={{fontWeight: 500, fontSize: 13}}>{u.name}</div>
                <div className="tiny text-truncate d-flex align-items-center" style={{gap: 4}}>
                  <RoleBadge role={u.role} roleKey={u.role_key} />
                  <span className="muted text-truncate">{u.org}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ===== Quick mode ===== */
function QuickRental({ initial, cart, setCart, user, setUser, period, setPeriod }) {
  const [scan, setScan] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [feedback, setFeedback] = React.useState(null);
  const debounceRef = React.useRef(null);
  const scanRef = React.useRef(null);

  // The scan field is disabled while the lookup runs, which makes the browser
  // drop focus. Restore it as soon as the request settles so the operator can
  // keep scanning without touching the mouse.
  React.useEffect(() => {
    if (!busy && scanRef.current) scanRef.current.focus();
  }, [busy]);

  const setQty = (id, qty) => setCart(cc => cc.map(x => x.id === id ? { ...x, qty } : x));

  // Quick mode used to accept any typed value, including dates in the past or
  // outside the opening hours -- the backend then refused the issue with an
  // error the operator only saw after scanning everything. Correct the value
  // as soon as the field is left instead.
  const workingHours = initial.working_hours;
  const nowInput = _fmtDT(new Date());

  const normalize = (raw, notBefore) => {
    if (!raw) return '';
    const parsed = new Date(raw);
    if (isNaN(parsed)) return '';
    const floor = notBefore ? new Date(notBefore) : new Date();
    const snapped = snapToWorkingHours(parsed < floor ? floor : parsed,
                                       workingHours);
    return _fmtDT(snapped);
  };

  // The return has to stay strictly after the pickup: snapping both to the
  // same opening time would otherwise produce a rental of zero length.
  const normalizeReturn = (raw, from) => {
    const candidate = normalize(raw, from);
    if (!from) return candidate;
    if (candidate && new Date(candidate) > new Date(from)) return candidate;
    const nextDay = new Date(from);
    nextDay.setDate(nextDay.getDate() + 1);
    return _fmtDT(snapToWorkingHours(nextDay, workingHours));
  };

  const normalizeFrom = () => setPeriod(p => {
    const from = normalize(p.from);
    if (!from) return p;
    return { ...p, from, to: normalizeReturn(p.to, from) };
  });

  const normalizeTo = () => setPeriod(p => {
    const to = normalizeReturn(p.to, p.from);
    return to === p.to ? p : { ...p, to };
  });

  // Start from a usable period instead of two empty fields: quick mode exists
  // to hand something over right now.
  React.useEffect(() => {
    setPeriod(p => {
      if (p.from && p.to) return p;
      const from = snapToWorkingHours(new Date(), workingHours);
      const to = new Date(from);
      to.setDate(to.getDate() + 1);
      return {
        ...p,
        from: p.from || _fmtDT(from),
        to: p.to || _fmtDT(snapToWorkingHours(to, workingHours)),
      };
    });
  }, []);

  const addByScan = async () => {
    if (!scan.trim()) return;
    if (debounceRef.current) return;
    debounceRef.current = setTimeout(() => { debounceRef.current = null; }, 300);
    setBusy(true);
    try {
      const params = new URLSearchParams({ num: scan.trim() });
      if (user && user.id) params.append('user_id', user.id);
      if (period && period.from) params.append('from', period.from);
      if (period && period.to) params.append('to', period.to);
      const data = await apiGet(`${initial.urls.inventory_search}?${params}`);
      const hit = data.items?.[0];
      if (hit) {
        // `qty` on a cart entry is the requested count, so move the serializer's
        // availability block to `stock` before it gets overwritten.
        setCart(c => c.some(x => x.id === hit.id) ? c : [...c, { ...hit, stock: hit.qty, qty: 1 }]);
        beep(800, 100);
        setFeedback('success');
        setTimeout(() => setFeedback(null), 500);
      } else {
        beep(300, 200);
        setFeedback('error');
        setTimeout(() => setFeedback(null), 500);
        alert(t('err.scan_not_found', 'Inventory code not found: ') + scan);
      }
    } catch (e) {
      beep(300, 200);
      setFeedback('error');
      setTimeout(() => setFeedback(null), 500);
      alert(e.message);
    } finally {
      setBusy(false);
      setScan('');
    }
  };

  // The rental exists before it is signed, so the modal gets the real
  // per-rental endpoints and the QR flow works exactly as on the detail page.
  const [signFor, setSignFor] = React.useState(null);

  const issueNow = async () => {
    if (!user || cart.length === 0) return;
    // The operator can press the button without ever leaving a date field, so
    // correct the period here too rather than letting the backend refuse it.
    const from = normalize(period.from);
    const to = normalizeReturn(period.to, from);
    if (!from || !to) {
      alert(t('wiz.need_period', 'Please set the pickup and return time.'));
      return;
    }
    if (from !== period.from || to !== period.to) {
      setPeriod(p => ({ ...p, from, to }));
    }
    setBusy(true);
    try {
      const r = await apiPost(initial.urls.quick_issue, {
        user_id: user.id, from, to,
        items: cart.map(c => ({ id: c.id, qty: c.qty })),
      });
      if (r.has_signature || !r.signature_urls) {
        window.location = r.detail_url;
        return;
      }
      setSignFor({ urls: r.signature_urls, detailUrl: r.detail_url });
    } catch (e) { alert(e.message); setBusy(false); }
  };

  const scanInputStyle = feedback === 'success'
    ? { borderColor: 'oklch(0.7 0.2 140)', boxShadow: '0 0 0 2px oklch(0.7 0.2 140 / 0.3)' }
    : feedback === 'error'
    ? { borderColor: 'oklch(0.6 0.2 25)', boxShadow: '0 0 0 2px oklch(0.6 0.2 25 / 0.3)' }
    : {};

  return (
    <div>
      {signFor && (
        <SignatureModal
          urls={signFor.urls}
          onSigned={() => { window.location = signFor.detailUrl; }}
          onClose={() => { window.location = signFor.detailUrl; }}
        />
      )}
      <div className="quick-panel">
        <div className="quick-row">
          <div>
            <div className="muted tiny mb-1" style={{textTransform: 'uppercase', fontWeight: 600}}>{t('wiz.user','User')}</div>
            <QuickUserPicker initial={initial} user={user} setUser={setUser}
                             onPicked={() => scanRef.current && scanRef.current.focus()} />
          </div>
          <div>
            <div className="muted tiny mb-1" style={{textTransform: 'uppercase', fontWeight: 600}}>{t('wiz.pickup','Pickup')}</div>
            <input type="datetime-local" className="form-control form-control-sm"
                   min={nowInput}
                   value={period.from} onBlur={normalizeFrom}
                   onChange={e => setPeriod(p => ({...p, from: e.target.value}))} />
          </div>
          <div>
            <div className="muted tiny mb-1" style={{textTransform: 'uppercase', fontWeight: 600}}>{t('wiz.return_by','Return by')}</div>
            <input type="datetime-local" className="form-control form-control-sm"
                   min={period.from || nowInput}
                   value={period.to} onBlur={normalizeTo}
                   onChange={e => setPeriod(p => ({...p, to: e.target.value}))} />
          </div>
          <div>
            <div className="muted tiny mb-1" style={{textTransform: 'uppercase', fontWeight: 600}}>{t('wiz.scan','Scan')}</div>
            <div className="input-group input-group-sm">
              <span className="input-group-text"><i className="fas fa-barcode"></i></span>
              <input className="form-control" placeholder="INV-…" autoFocus
                     ref={scanRef}
                     style={scanInputStyle}
                     disabled={busy}
                     value={scan} onChange={e => setScan(e.target.value)}
                     onKeyDown={e => e.key === 'Enter' && addByScan()} />
            </div>
          </div>
          <div>
            <button className="btn btn-primary btn-sm" disabled={busy || !user || cart.length === 0} onClick={issueNow}>
              <i className="fas fa-check me-1"></i>{t('btn.issue_now', 'Issue now')}
            </button>
          </div>
        </div>
      </div>

      <div className="surface p-0">
        {cart.map((c, i) => {
          const qty = c.qty || 0;
          const total = c.stock && c.stock.total;
          const max = total > 0 ? total : Infinity;
          return (
          <div key={c.id} style={{display: 'grid', gridTemplateColumns: '28px 1fr 150px 108px 44px', gap: 10,
                                     padding: '10px 14px', borderBottom: '1px solid var(--line)', alignItems: 'center',
                                     fontSize: 13}}>
            <div className="muted mono">{i + 1}</div>
            <div>
              <div style={{fontWeight: 500}}>{c.name}</div>
              <div className="muted tiny mono">{c.num}</div>
            </div>
            <div>
              <ItemStatusTag stock={c.stock} conflict={c.conflict} statusLabel={c.status_label} />
            </div>
            <div className="input-group input-group-sm" style={{maxWidth: 108}}>
              <button className="btn btn-ghost" type="button"
                      disabled={qty <= 1}
                      onClick={() => setQty(c.id, Math.max(1, qty - 1))}>−</button>
              <input className="form-control text-center mono" readOnly
                     value={total > 0 ? `${qty}/${total}` : qty} />
              <button className="btn btn-ghost" type="button"
                      disabled={qty >= max}
                      onClick={() => setQty(c.id, Math.min(max, qty + 1))}>+</button>
            </div>
            <button className="btn btn-ghost btn-sm"
                    onClick={() => setCart(cc => cc.filter(x => x.id !== c.id))}>
              <i className="fas fa-times muted"></i>
            </button>
          </div>
          );
        })}
        {cart.length === 0 && (
          <div className="muted p-3 text-center">
            {t('wiz.scan_hint', 'Scan or enter an inventory code above to add items.')}
          </div>
        )}
      </div>
    </div>
  );
}

Object.assign(window, { WizardScreen });
