// ok_tools/static/js/rental_dashboard.js

// Django i18n support
const gettext = window.gettext || function (str) { return str; };
const ngettext = window.ngettext || function (singular, plural, count) { return count === 1 ? singular : plural; };
const interpolate = window.interpolate || function (format, obj) {
    return format.replace(/%\((\w+)\)s/g, (match, key) => (
        Object.prototype.hasOwnProperty.call(obj, key) ? obj[key] : match
    ));
};

// Open a full-screen lightbox showing an enlarged image. Click or Esc closes.
function openImageLightbox(url) {
    if (!url) return;
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.8);' +
        'display:flex;align-items:center;justify-content:center;z-index:20000;' +
        'cursor:zoom-out;padding:24px;';
    const img = document.createElement('img');
    img.src = url;
    img.style.cssText = 'max-width:92vw;max-height:92vh;border-radius:8px;' +
        'box-shadow:0 8px 40px rgba(0,0,0,.5);';
    overlay.appendChild(img);
    const close = () => { overlay.remove(); document.removeEventListener('keydown', onKey); };
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    overlay.addEventListener('click', close);
    document.addEventListener('keydown', onKey);
    document.body.appendChild(overlay);
}

// Rental Dashboard JavaScript - English Translation
document.addEventListener('DOMContentLoaded', function() {
    class RentalDashboard {
        constructor() {
            this.selectedItems = [];
            this.selectedRooms = [];
            this.filterOptions = {};
            this.selectedSet = null;
            this.selectedRoom = null;
            this.equipmentSets = [];
            this.rooms = [];

            // Bind events
            this.bindEvents();

            // Bind stats events
            this.bindStatsEvents();

            // Load filter options
            this.loadFilterOptions();

            // Load active requests list
            this.loadUserActiveRequests();

            // Check if dates are already selected and load inventory
            if (this.isPeriodSelected()) {
                this.loadInventory();
            } else {
                // Show date selection hint if dates are not selected
                this.showSelectDatesHint();
            }

        }

        bindEvents() {
            const startDateField = document.querySelector('input[name="start_date"]');
            const endDateField = document.querySelector('input[name="end_date"]');

            if (startDateField) {
                this.setupDateFieldConstraints(startDateField, null);
                startDateField.addEventListener('change', this.debounce(() => {
                    this.ensureDateTimeDefaults();
                    this.updateWorkingHoursHint();
                    if (endDateField && startDateField.value) {
                        this.setupDateFieldConstraints(endDateField, startDateField.value);
                    }
                    this.loadInventoryIfPeriodSelected();
                }, 300));
            }

            if (endDateField) {
                this.setupDateFieldConstraints(endDateField, startDateField?.value || null);
                endDateField.addEventListener('change', this.debounce(() => {
                    this.ensureDateTimeDefaults();
                    this.updateWorkingHoursHint();
                    this.loadInventoryIfPeriodSelected();
                }, 300));
            }

            this.ensureDateTimeDefaults();
            this.updateWorkingHoursHint();

            // Filter event listeners
            const inventorySearch = document.getElementById('inventorySearch');
            if (inventorySearch) {
                inventorySearch.addEventListener('input', this.debounce(() => {
                    if (!this.isPeriodSelected()) return;
                    this.applyFilters();
                }, 300));
            }

            // const ownerFilter = document.getElementById('ownerFilter');
            // if (ownerFilter) {
            //     ownerFilter.addEventListener('change', () => {
            //         if (this.isPeriodSelected()) this.applyFilters();
            //     });
            // }

            const categoryFilter = document.getElementById('categoryFilter');
            if (categoryFilter) {
                categoryFilter.addEventListener('change', () => {
                    if (this.isPeriodSelected()) this.applyFilters();
                });
            }

            const locationFilter = document.getElementById('locationFilter');
            if (locationFilter) {
                locationFilter.addEventListener('change', () => {
                    if (this.isPeriodSelected()) this.applyFilters();
                });
            }

            // Button event listeners
            const clearFormBtn = document.getElementById('clearFormBtn');
            if (clearFormBtn) clearFormBtn.addEventListener('click', this.clearForm.bind(this));

            const showSetsBtn = document.getElementById('showSetsBtn');
            if (showSetsBtn) showSetsBtn.addEventListener('click', this.showEquipmentSets.bind(this));

            const reserveBtn = document.getElementById('reserveBtn');
            if (reserveBtn) {
                reserveBtn.addEventListener('click', () => {
                    const action = (typeof RENTAL_REQUIRES_APPROVAL !== 'undefined' && RENTAL_REQUIRES_APPROVAL)
                        ? 'draft'
                        : 'reserved';
                    this.createRental(action);
                });
            }

            const addSetToRentalBtn = document.getElementById('addSetToRentalBtn');
            if (addSetToRentalBtn) addSetToRentalBtn.addEventListener('click', this.addSetToRental.bind(this));

            const roomsFilterBtn = document.getElementById('roomsFilterBtn');
            if (roomsFilterBtn) roomsFilterBtn.addEventListener('click', this.showRooms.bind(this));

            const addRoomToRentalBtn = document.getElementById('addRoomToRentalBtn');
            if (addRoomToRentalBtn) addRoomToRentalBtn.addEventListener('click', this.addRoomToRental.bind(this));
        }

        addDaysToDateString(dateString, days) {
            if (!dateString) return '';
            const date = new Date(`${dateString}T00:00:00`);
            if (Number.isNaN(date.getTime())) return '';
            date.setDate(date.getDate() + days);
            return date.toISOString().slice(0, 10);
        }

        getCurrentTimeHHMM() {
            const now = new Date();
            return `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
        }

        buildDateTimeValue(datePart, defaultTime) {
            if (!datePart) return '';
            return `${datePart}T${defaultTime}`;
        }

        // Working hours of the day of a "YYYY-MM-DD" string, keyed like
        // RENTAL_WORKING_HOURS (0 = Monday). Null if unknown.
        getDayWorkingHours(datePart) {
            if (!datePart || typeof RENTAL_WORKING_HOURS === 'undefined') return null;
            const date = new Date(`${datePart.slice(0, 10)}T00:00:00`);
            if (Number.isNaN(date.getTime())) return null;
            return RENTAL_WORKING_HOURS[String((date.getDay() + 6) % 7)] || null;
        }

        getTodayDateString() {
            const now = new Date();
            return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
        }

        // Opening time of the day; for today the current time if already open.
        getDefaultStartTime(datePart) {
            const hours = this.getDayWorkingHours(datePart);
            const currentTime = this.getCurrentTimeHHMM();
            if (!hours || !hours.enabled) return currentTime;
            if (datePart.slice(0, 10) === this.getTodayDateString()
                    && currentTime > hours.start && currentTime < hours.end) {
                return currentTime;
            }
            return hours.start;
        }

        getDefaultEndTime(datePart) {
            const hours = this.getDayWorkingHours(datePart);
            return hours && hours.enabled ? hours.end : '18:00';
        }

        // Mirrors rental.working_hours.validate_working_hours_period, so the
        // user sees the problem before the server rejects the request.
        getWorkingHoursError(startValue, endValue) {
            if (!startValue || !endValue || typeof RENTAL_WORKING_HOURS === 'undefined') return null;
            const startHours = this.getDayWorkingHours(startValue);
            const endHours = this.getDayWorkingHours(endValue);
            if (!startHours || !endHours) return null;
            const startTime = startValue.slice(11, 16);
            const endTime = endValue.slice(11, 16);
            const describe = (hours) => interpolate(
                gettext('%(day)s: %(start)s–%(end)s'),
                { day: hours.label, start: hours.start, end: hours.end }, true);

            if (!startHours.enabled) {
                return interpolate(gettext('The rental is closed on %(day)s. Please choose another start day.'),
                    { day: startHours.label }, true);
            }
            if (!endHours.enabled) {
                return interpolate(gettext('The rental is closed on %(day)s. Please choose another return day.'),
                    { day: endHours.label }, true);
            }
            if (startTime < startHours.start || startTime >= startHours.end) {
                return interpolate(gettext('The start time is outside the working hours (%(hours)s).'),
                    { hours: describe(startHours) }, true);
            }
            if (endTime < endHours.start || endTime > endHours.end) {
                return interpolate(gettext('The end time is outside the working hours (%(hours)s).'),
                    { hours: describe(endHours) }, true);
            }
            return null;
        }

        // Show the hours of the chosen days below the period fields.
        updateWorkingHoursHint() {
            const hint = document.getElementById('workingHoursHint');
            if (!hint) return;
            const startValue = document.querySelector('input[name="start_date"]')?.value || '';
            const endValue = document.querySelector('input[name="end_date"]')?.value || '';
            const describeDay = (value) => {
                const hours = this.getDayWorkingHours(value);
                if (!hours) return '';
                return hours.enabled
                    ? `${hours.label} ${hours.start}–${hours.end}`
                    : interpolate(gettext('%(day)s closed'), { day: hours.label }, true);
            };
            const days = [...new Set([describeDay(startValue), describeDay(endValue)].filter(Boolean))];
            const error = this.getWorkingHoursError(startValue, endValue);

            hint.textContent = '';
            if (days.length) {
                hint.append(`${gettext('Working hours')}: ${days.join(', ')}`);
            }
            if (error) {
                const warning = document.createElement('div');
                warning.className = 'text-danger';
                warning.textContent = error;
                hint.append(warning);
            }
        }

        ensureDateTimeDefaults() {
            const startDateField = document.querySelector('input[name="start_date"]');
            const endDateField = document.querySelector('input[name="end_date"]');
            if (!startDateField || !endDateField) return;

            const startRaw = startDateField.value || '';
            const endRaw = endDateField.value || '';

            if (!startRaw && !endRaw) {
                return;
            }

            if (startRaw && !startRaw.includes('T')) {
                startDateField.value = this.buildDateTimeValue(startRaw, this.getDefaultStartTime(startRaw));
            }

            if (endRaw && !endRaw.includes('T')) {
                endDateField.value = this.buildDateTimeValue(endRaw, this.getDefaultEndTime(endRaw));
            }

            const startValue = startDateField.value;
            let endValue = endDateField.value;

            const computeDefaultEndFromStart = (startDateTimeValue, allowSameDayDefault = true) => {
                const startDate = new Date(startDateTimeValue);
                if (Number.isNaN(startDate.getTime())) return '';
                const startDatePart = startDateTimeValue.slice(0, 10);
                const afterWorkday = startDateTimeValue.slice(11, 16) >= this.getDefaultEndTime(startDatePart);
                if (afterWorkday && !allowSameDayDefault) {
                    return '';
                }
                const targetDate = afterWorkday ? this.addDaysToDateString(startDatePart, 1) : startDatePart;
                return this.buildDateTimeValue(targetDate, this.getDefaultEndTime(targetDate));
            };

            if (startValue && !endValue) {
                endValue = computeDefaultEndFromStart(startValue, false);
                if (endValue) {
                    endDateField.value = endValue;
                }
            }

            if (!startValue || !endDateField.value) {
                return;
            }

            const startDateTime = new Date(startDateField.value);
            const endDateTime = new Date(endDateField.value);
            if (Number.isNaN(startDateTime.getTime()) || Number.isNaN(endDateTime.getTime())) {
                return;
            }

            if (endDateTime <= startDateTime) {
                endDateField.value = computeDefaultEndFromStart(startDateField.value);

                // Safety fallback: if start is already after closing time, force next day end.
                const correctedEnd = new Date(endDateField.value);
                if (!Number.isNaN(correctedEnd.getTime()) && correctedEnd <= startDateTime) {
                    const nextDay = this.addDaysToDateString(startDateField.value.slice(0, 10), 1);
                    endDateField.value = this.buildDateTimeValue(nextDay, this.getDefaultEndTime(nextDay));
                }
            }
        }

        // Setup date field constraints (min date only)
        setupDateFieldConstraints(field, minStartDate) {
            if (!field) return;
            
            const now = new Date();
            const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
            
            // Set minimum date: today, or minStartDate if provided
            let minDate;
            if (minStartDate) {
                // For end_date: use start_date as minimum
                minDate = new Date(minStartDate);
            } else {
                // For start_date: use today
                minDate = new Date(today);
            }
            
            // Format as input-compatible string
            minDate.setHours(0, 0, 0, 0);
            const minDateString = field.type === 'date'
                ? minDate.toISOString().slice(0, 10)
                : minDate.toISOString().slice(0, 16);
            field.min = minDateString;
            
            // Clear max to allow any time selection (no time restrictions)
            field.max = '';
        }

        // Check if period is selected
        isPeriodSelected() {
            const startDate = document.querySelector('input[name="start_date"]')?.value;
            const endDate = document.querySelector('input[name="end_date"]')?.value;
            return Boolean(startDate && endDate);
        }

        // Load inventory only if period is selected
        loadInventoryIfPeriodSelected() {
            if (this.isPeriodSelected()) {
                this.ensureDateTimeDefaults();
                this.loadInventory();
            }
        }

        bindStatsEvents() {
            // Add click handlers to stats cards
            const statsCards = document.querySelectorAll('.stats-card[data-type]');
            statsCards.forEach(card => {
                card.addEventListener('click', () => {
                    const type = card.dataset.type;
                    this.showRentalDetails(type);
                });
            });
        }

        async loadUserActiveRequests() {
            const container = document.getElementById('userActiveRequests');
            if (!container) return;

            try {
                const resp = await fetch(`${URLS.userRentalDetails}?type=active`);
                if (!resp.ok) {
                    throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
                }

                const data = await resp.json();

                if (!data.success) {
                    throw new Error(data.error || gettext('Unknown error'));
                }

                const rentals = (data.rentals || []).filter(rental => {
const status = (rental.status || '').toLowerCase();
                    return status === 'draft' || status === 'reserved';
                });
                if (!rentals.length) {
                    container.innerHTML = `<div class="text-muted">${container.dataset.labelNoActive || gettext('No active rentals')}</div>`;
                    return;
                }

                const labelRequest = container.dataset.labelRequest || gettext('Request');
                const labelStatus = container.dataset.labelStatus || gettext('Status');
                const labelPeriod = container.dataset.labelPeriod || gettext('Period');
                const labelItems = container.dataset.labelItems || gettext('Items');
                const labelRooms = container.dataset.labelRooms || gettext('Rooms');

                const rows = rentals.map(rental => {
                    const status = rental.status_display || rental.status || '';
                    const start = rental.requested_start_date ? new Date(rental.requested_start_date).toLocaleString() : gettext('-');
                    const end = rental.requested_end_date ? new Date(rental.requested_end_date).toLocaleString() : gettext('-');
                    const itemsCount = (rental.items || []).length;
                    const roomsCount = (rental.room_rentals || []).length;
                    return `
                        <div class="border rounded p-2 mb-2 bg-light">
                            <div class="fw-semibold">
                                ${labelRequest} #${rental.id}: ${rental.project_name || ''}
                            </div>
                            <div>${labelStatus}: ${status}</div>
                            <div>${labelPeriod}: ${start} – ${end}</div>
                            <div>${labelItems}: ${itemsCount} • ${labelRooms}: ${roomsCount}</div>
                        </div>
                    `;
                }).join('');

                container.innerHTML = rows;
            } catch (error) {
                console.error('Error loading active requests:', error);
                container.innerHTML = `<div class="text-muted">${container.dataset.labelNoActive || gettext('No active rentals')}</div>`;
            }
        }

        async showRentalDetails(type) {
            try {
                // Show loading in the appropriate modal
                let modalId, contentId;
                switch (type) {
                    case 'active':
                        modalId = 'activeRentalsModal';
                        contentId = 'activeRentalsContent';
                        break;
                    case 'returned':
                        modalId = 'returnedRentalsModal';
                        contentId = 'returnedRentalsContent';
                        break;
                    case 'overdue':
                        modalId = 'overdueRentalsModal';
                        contentId = 'overdueRentalsContent';
                        break;
                    default:
                        console.error('Unknown rental type:', type);
                        return;
                }

                // Show modal
                const modal = new bootstrap.Modal(document.getElementById(modalId));
                modal.show();

                // Load data
                const resp = await fetch(`${URLS.userRentalDetails}?type=${type}`);
                if (!resp.ok) {
                    throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
                }

                const data = await resp.json();

                if (data.success) {
                    this.renderRentalDetails(contentId, data);
                } else {
                    throw new Error(data.error || gettext('Unknown error'));
                }

            } catch (error) {
                console.error('Error loading rental details:', error);

                // Show error in modal content instead of alert
                const contentId = this.getContentIdForType(type);
                if (contentId) {
                    const container = document.getElementById(contentId);
                    if (container) {
                        container.innerHTML = `
                            <div class="text-center p-4">
                                <div class="alert alert-danger">
                                    <i class="bi bi-exclamation-triangle me-2"></i>
                                    <strong>${gettext('Error loading data')}:</strong><br>
                                    ${error.message}
                                </div>
                                <button class="btn btn-primary mt-3" onclick="location.reload()">
                                    <i class="bi bi-arrow-clockwise me-1"></i>${gettext('Retry')}
                                </button>
                            </div>
                        `;
                    }
                } else {
                    alert(interpolate(gettext('Error loading data: %(message)s'), { message: error.message }, true));
                }
            }
        }

        getContentIdForType(type) {
            switch (type) {
                case 'active': return 'activeRentalsContent';
                case 'returned': return 'returnedRentalsContent';
                case 'overdue': return 'overdueRentalsContent';
                default: return null;
            }
        }

        renderRentalDetails(contentId, data) {
            const container = document.getElementById(contentId);
            if (!container) return;

            const rentals = data.rentals || [];
            const user = data.user || {};
            const type = data.type || 'active';

            if (rentals.length === 0) {
                container.innerHTML = `
                    <div class="rental-details-header">
                        <h5>${this.getTypeLabel(type)}</h5>
                        <div class="user-info">
                            <strong>${gettext('User')}:</strong> ${user.name || user.email}
                        </div>
                    </div>
                    <div class="rental-details-content">
                        <div class="empty-state">
                            <i class="bi bi-inbox"></i>
                            <h6>${gettext('No')} ${this.getTypeLabel(type)} ${gettext('found')}</h6>
                            <p>${gettext('No')} ${this.getTypeLabel(type).toLowerCase()} ${gettext('found for')} ${user.name || user.email}.</p>
                        </div>
                    </div>`;
                return;
            }

            // Create header section
            let html = `
                <div class="rental-details-header">
                    <h5>${this.getTypeLabel(type)}</h5>
                    <div class="user-info">
                        <strong>${gettext('User')}:</strong> ${user.name || user.email}
                    </div>
                </div>
                <div class="rental-details-content">`;

            rentals.forEach(rental => {
                    const startDate = rental.requested_start_date ?
                        new Date(rental.requested_start_date).toLocaleString('de-DE', {
                            year: 'numeric', month: '2-digit', day: '2-digit',
                            hour: '2-digit', minute: '2-digit'
                        }) : gettext('N/A');

                    const endDate = rental.requested_end_date ?
                        new Date(rental.requested_end_date).toLocaleString('de-DE', {
                            year: 'numeric', month: '2-digit', day: '2-digit',
                            hour: '2-digit', minute: '2-digit'
                        }) : gettext('N/A');

                    const actualEndDate = rental.actual_end_date ?
                        new Date(rental.actual_end_date).toLocaleString('de-DE', {
                            year: 'numeric', month: '2-digit', day: '2-digit',
                            hour: '2-digit', minute: '2-digit'
                        }) : gettext('N/A');

                html += `
                    <div class="rental-card">
                        <div class="rental-card-header d-flex justify-content-between align-items-center">
                            <div>
                                <h6 class="mb-0">${rental.project_name}</h6>
                                <small class="text-muted">${gettext('ID')}: ${rental.id}</small>
                            </div>
                            <div class="d-flex align-items-center gap-2">
                                <span class="badge ${this.getStatusBadgeClass(rental.status)}">${this.getStatusLabel(rental.status)}</span>
                                ${type === 'overdue' && rental.days_overdue > 0 ?
                                    `<span class="badge bg-danger ms-1">${rental.days_overdue} ${gettext('days overdue')}</span>` : ''}
                            </div>
                        </div>
                        <div class="rental-card-body">
                            <div class="rental-info-row">
                                <div class="rental-info-item">
                                    <div class="rental-info-label">${gettext('Purpose')}</div>
                                    <div class="rental-info-value">${rental.purpose || rental.project_name || gettext('N/A')}</div>
                                </div>
                                <div class="rental-info-item">
                                    <div class="rental-info-label">${gettext('Planned from')}</div>
                                    <div class="rental-info-value">${startDate}</div>
                                </div>
                                <div class="rental-info-item">
                                    <div class="rental-info-label">${gettext('Planned until')}</div>
                                    <div class="rental-info-value">${endDate}</div>
                                </div>
                                ${type === 'returned' ? `
                                <div class="rental-info-item">
                                    <div class="rental-info-label">${gettext('Returned')}</div>
                                    <div class="rental-info-value">${actualEndDate}</div>
                                </div>` : ''}
                            </div>`;

                // Equipment section
                if (rental.items && rental.items.length > 0) {
                    html += `
                        <div class="rental-section">
                            <div class="rental-section-title">
                                <i class="bi bi-tools"></i>
                                ${gettext('Equipment')} (${rental.items.length} ${gettext('items')})
                            </div>
                            <div class="table-responsive">
                                <table class="table table-sm">
                                    <thead>
                                        <tr>
                                            <th>${gettext('Item')}</th>
                                            <th>${gettext('Requested')}</th>
                                            <th>${gettext('Issued')}</th>
                                            <th>${gettext('Returned')}</th>
                                            ${type === 'active' ? `<th>${gettext('Outstanding')}</th>` : ''}
                                        </tr>
                                    </thead>
                                    <tbody>`;

                    rental.items.forEach(item => {
                        const itemInfo = item.inventory_item || item;
                        const description = itemInfo.description || itemInfo.inventory_number || gettext('Unknown item');
                    const inventoryNumber = itemInfo.inventory_number || gettext('N/A');

                        html += `
                            <tr>
                                <td>
                                    <strong>${description}</strong><br>
                                    <small class="text-muted">[${inventoryNumber}]</small>
                                </td>
                                <td>${item.quantity_requested}</td>
                                <td>${item.quantity_issued || 0}</td>
                                <td>${item.quantity_returned || 0}</td>
                                ${type === 'active' ?
                                    `<td><span class="badge ${item.outstanding > 0 ? 'bg-warning' : 'bg-success'}">${item.outstanding}</span></td>` : ''}
                            </tr>`;
                    });

                    html += `
                                    </tbody>
                                </table>
                            </div>
                        </div>`;
                }

                // Rooms section
                if (rental.room_rentals && rental.room_rentals.length > 0) {
                    html += `
                        <div class="rental-section">
                            <div class="rental-section-title">
                                <i class="bi bi-building"></i>
                                ${gettext('Rooms')} (${rental.room_rentals.length} ${gettext('rooms')})
                            </div>
                            <div class="table-responsive">
                                <table class="table table-sm">
                                    <thead>
                                        <tr>
                                            <th>${gettext('Room')}</th>
                                            <th>${gettext('Capacity')}</th>
                                            <th>${gettext('Booked people')}</th>
                                            <th>${gettext('Notes')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>`;

                    rental.room_rentals.forEach(roomRental => {
                        html += `
                            <tr>
                                <td>
                                    <strong>${roomRental.room.name}</strong><br>
                                    <small class="text-muted">[${roomRental.room.location}]</small>
                                </td>
                                <td>${roomRental.room.capacity} ${gettext('people')}</td>
                                <td>${roomRental.people_count} ${gettext('people')}</td>
                                <td>${roomRental.notes || gettext('-')}</td>
                            </tr>`;
                    });

                    html += `
                                    </tbody>
                                </table>
                            </div>
                        </div>`;
                }

                html += `
                        </div>
                    </div>`;
            });

            html += `</div>`;
            container.innerHTML = html;
        }

        getTypeLabel(type) {
            switch (type) {
                case 'active': return gettext('Current Rentals');
                case 'returned': return gettext('Returned Rentals');
                case 'overdue': return gettext('Expired Rentals');
                default: return gettext('Rentals');
            }
        }

        getStatusLabel(status) {
            switch (status) {
                case 'draft': return gettext('Draft');
                case 'reserved': return gettext('Reserved');
                case 'issued': return gettext('Issued');
                case 'returned': return gettext('Returned');
                case 'cancelled': return gettext('Cancelled');
                default: return status;
            }
        }

        getStatusBadgeClass(status) {
            switch (status) {
                case 'draft': return 'bg-secondary';
                case 'reserved': return 'bg-info';
                case 'issued': return 'bg-primary';
                case 'returned': return 'bg-success';
                case 'cancelled': return 'bg-danger';
                default: return 'bg-secondary';
            }
        }

        async loadFilterOptions() {
            try {
                const resp = await fetch(URLS.filterOptions);
                const data = await resp.json();
                this.filterOptions = data;
                this.populateFilterDropdowns(data);
            } catch (error) {
                console.error('Error loading filter options:', error);
            }
        }

        populateFilterDropdowns(options) {
            // Populate owner filter
            // const ownerSelect = document.getElementById('ownerFilter');
            // if (ownerSelect && options.owners) {
            //     ownerSelect.innerHTML = `<option value="all">${gettext('All Owners')}</option>`;
            //     options.owners.forEach(owner => {
            //         const option = document.createElement('option');
            //         option.value = owner.name;
            //         option.textContent = owner.name;
            //         ownerSelect.appendChild(option);
            //     });
            // }

            // Populate category filter
            const categorySelect = document.getElementById('categoryFilter');
            if (categorySelect && options.categories) {
                categorySelect.innerHTML = `<option value="all">${gettext('All Categories')}</option>`;
                options.categories.forEach(category => {
                    const option = document.createElement('option');
                    option.value = category.name;
                    option.textContent = category.name;
                    categorySelect.appendChild(option);
                });
            }

            // Populate location filter
            const locationSelect = document.getElementById('locationFilter');
            if (locationSelect && options.locations) {
                locationSelect.innerHTML = `<option value="all">${gettext('All Locations')}</option>`;

                const addLocationOptions = (locations, level = 0) => {
                    locations.forEach(location => {
                        const option = document.createElement('option');
                        option.value = location.full_path;

                        const indent = '&nbsp;'.repeat(level * 4);
                        option.innerHTML = indent + location.name;
                        option.dataset.level = level;
                        option.dataset.fullPath = location.full_path;

                        locationSelect.appendChild(option);

                        if (location.children && location.children.length > 0) {
                            addLocationOptions(location.children, level + 1);
                        }
                    });
                };

                addLocationOptions(options.locations);
            }
        }

        async loadInventory() {
            try {
                const startDate = document.querySelector('input[name="start_date"]')?.value;
                const endDate = document.querySelector('input[name="end_date"]')?.value;

                if (!startDate || !endDate) {
                    this.showSelectDatesHint();
                    return;
                }

                // Load inventory for current user using the rental API
                const userId = this.getCurrentUserId();
                if (!userId) {
                    console.error('User ID not found');
                    this.renderInventory([]);
                    return;
                }

                // Build URL with parameters
                const params = new URLSearchParams();
                params.append('start_date', startDate);
                params.append('end_date', endDate);

                // Use the simplified user inventory API endpoint
                const url = `/rental/api/user/${userId}/inventory-simple/?${params.toString()}`;

                const response = await fetch(url);
                if (!response.ok) {
                    const errorText = await response.text();
                    console.error('HTTP error response:', response.status, errorText);
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                const data = await response.json();

                if (data.inventory) {
                    this.renderInventory(data.inventory || []);
                } else {
                    console.error('API error:', data.error);
                    this.renderInventory([]);
                }

            } catch (error) {
                console.error('Error loading inventory:', error);
                this.renderInventory([]);
            }
        }

        getCurrentUserId() {
            // Use global USER_ID from Django template
            if (typeof USER_ID !== 'undefined' && USER_ID) {
                return USER_ID;
            }

            // Fallback: try to get from DOM
            const userIdElement = document.querySelector('[data-user-id]');
            if (userIdElement) {
                return userIdElement.dataset.userId;
            }

            // Alternative: try to get from any workflow step
            const workflowStep = document.querySelector('.workflow-step');
            if (workflowStep && workflowStep.dataset.userId) {
                return workflowStep.dataset.userId;
            }

            console.error('User ID not found');
            return null;
        }

        showSelectDatesHint() {
            const grid = document.getElementById('inventoryGrid');
            if (!grid) return;

            grid.innerHTML = `
                <div class="col-12">
                    <div class="text-center p-5">
                        <div class="workflow-step p-3 rounded mb-3 d-inline-block" style="max-width: 400px;">
                            <div class="d-flex align-items-center mb-2 justify-content-center">
                                <i class="bi bi-calendar-check text-secondary me-2"></i>
                                <strong>${gettext('3. Time Period')}</strong>
                            </div>
                            <div class="mb-2">
                                <label class="form-label form-label-sm">${gettext('From:')}</label>
                                <input name="start_date_hint" type="date" class="form-control form-control-sm" required>
                            </div>
                            <div class="mb-2">
                                <label class="form-label form-label-sm">${gettext('To:')}</label>
                                <input name="end_date_hint" type="date" class="form-control form-control-sm" required>
                            </div>
                        </div>
                        <p class="mt-3 text-muted">${gettext('Select dates above to view availability')}</p>
                    </div>
                </div>
            `;
            
            const startHintField = grid.querySelector('input[name="start_date_hint"]');
            const endHintField = grid.querySelector('input[name="end_date_hint"]');
            const startMainField = document.querySelector('input[name="start_date"]');
            const endMainField = document.querySelector('input[name="end_date"]');
            if (startHintField && startMainField) {
                startHintField.value = (startMainField.value || '').slice(0, 10);
                this.setupDateFieldConstraints(startHintField, null);
                startHintField.addEventListener('change', (e) => {
                    if (startMainField) {
                        if (e.target.value) {
                            startMainField.value = this.buildDateTimeValue(
                                e.target.value, this.getDefaultStartTime(e.target.value));
                        }
                        if (endMainField && e.target.value) {
                            this.setupDateFieldConstraints(endMainField, e.target.value);
                        }
                        if (endHintField && e.target.value) {
                            this.setupDateFieldConstraints(endHintField, e.target.value);
                        }
                        this.ensureDateTimeDefaults();
                        startMainField.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                });
            }
            
            if (endHintField && endMainField) {
                endHintField.value = (endMainField.value || '').slice(0, 10);
                const startDate = (startMainField?.value || '').slice(0, 10) || startHintField?.value;
                this.setupDateFieldConstraints(endHintField, startDate);
                endHintField.addEventListener('change', (e) => {
                    if (endMainField) {
                        if (e.target.value) {
                            endMainField.value = this.buildDateTimeValue(
                                e.target.value, this.getDefaultEndTime(e.target.value));
                        }
                        this.ensureDateTimeDefaults();
                        endMainField.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                });
            }
            
            if (startMainField && startHintField) {
                const syncStartHandler = () => {
                    if (startHintField) {
                        startHintField.value = (startMainField.value || '').slice(0, 10);
                        if (endHintField) {
                            this.setupDateFieldConstraints(endHintField, (startMainField.value || '').slice(0, 10));
                        }
                    }
                };
                startMainField.addEventListener('change', syncStartHandler);
            }
            
            if (endMainField && endHintField) {
                const syncEndHandler = () => {
                    if (endHintField) {
                        endHintField.value = (endMainField.value || '').slice(0, 10);
                    }
                };
                endMainField.addEventListener('change', syncEndHandler);
            }
        }

        async applyFilters() {
            if (!this.isPeriodSelected()) return;

            const searchQuery = document.getElementById('inventorySearch')?.value || '';
            // const ownerFilter = document.getElementById('ownerFilter')?.value || 'all';
            const categoryFilter = document.getElementById('categoryFilter')?.value || 'all';
            const locationFilter = document.getElementById('locationFilter')?.value || 'all';

            // Get dates from form fields
            const startDate = document.querySelector('[name="start_date"]')?.value;
            const endDate = document.querySelector('[name="end_date"]')?.value;

            if (!startDate || !endDate) {
                return;
            }

            const userId = this.getCurrentUserId();
            if (!userId) {
                console.error('User ID not found for filtering');
                return;
            }

            // Build filter parameters
            const params = new URLSearchParams();
            params.append('start_date', startDate);
            params.append('end_date', endDate);

            if (searchQuery) params.append('search', searchQuery);
            // if (ownerFilter !== 'all') params.append('owner', ownerFilter);
            if (categoryFilter !== 'all') params.append('category', categoryFilter);
            if (locationFilter !== 'all') params.append('location', locationFilter);

            try {
                // Use the same simplified user inventory API with filters
                const url = `/rental/api/user/${userId}/inventory-simple/?${params.toString()}`;

                const response = await fetch(url);
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                const data = await response.json();

                if (data.inventory) {
                    this.renderInventory(data.inventory || []);
                } else {
                    console.error('API error during filtering:', data.error);
                    this.renderInventory([]);
                }

            } catch (error) {
                console.error('Error applying filters:', error);
                this.renderInventory([]);
            }
        }

        renderInventory(items) {
            const grid = document.getElementById('inventoryGrid');
            if (!grid) {
                console.error('inventoryGrid element not found');
                return;
            }

            if (items.length === 0) {
                grid.innerHTML = `
                    <div class="col-12">
                        <div class="text-center p-5">
                            <i class="bi bi-inbox text-muted" style="font-size: 3rem;"></i>
                            <p class="mt-3 text-muted">${gettext('No available inventory for selected period')}</p>
                        </div>
                    </div>
                `;
                return;
            }

            this.renderInventoryFlat(items, grid);
        }

        renderInventoryFlat(items, grid) {
            // Clear existing content but keep the row structure
            while (grid.firstChild) {
                grid.removeChild(grid.firstChild);
            }
            
            items.forEach((item, index) => {
                const col = document.createElement('div');
                col.className = 'col-md-6 col-lg-4 mb-3 d-flex';
                
                // Ensure column has minimum height and is visible
                col.style.minHeight = '150px';
                col.style.display = 'flex';
                
                const cardHTML = this.createItemCardHTML(item);
                col.innerHTML = cardHTML;

                const card = col.querySelector('.item-card');
                if (card) {
                    // Ensure card is visible
                    card.style.display = 'flex';
                    card.style.flexDirection = 'column';
                    card.style.minHeight = '150px';
                    this.bindItemCardEvents(card, item);
                } else {
                    console.error('Item card not found for item', index);
                }

                grid.appendChild(col);
            });
            // Ensure grid and parent are visible
            // Grid is a Bootstrap row, so it should use default row display
            if (grid.parentElement) {
                const parent = grid.parentElement;
                parent.style.display = 'block';
                parent.style.minHeight = '200px';
                
                // Remove max-height restriction if exists (from admin_rental.css)
                const parentMaxHeight = window.getComputedStyle(parent).maxHeight;
                if (parentMaxHeight && parentMaxHeight !== 'none') {
                    const maxHeightValue = parseFloat(parentMaxHeight);
                    if (maxHeightValue < 1000) {
                        parent.style.maxHeight = 'none';
                    }
                }
                
                // Ensure overflow is visible or auto, not hidden
                const parentOverflow = window.getComputedStyle(parent).overflow;
                if (parentOverflow === 'hidden') {
                    parent.style.overflow = 'visible';
                }
            }
            
            // Ensure grid (row) is visible and uses Bootstrap row behavior
            if (grid.classList.contains('row')) {
                grid.style.display = 'flex';
                grid.style.flexWrap = 'wrap';
                grid.style.marginLeft = '-0.75rem';
                grid.style.marginRight = '-0.75rem';
            }
            
            // Scroll to first element if it's below viewport
            if (grid.children.length > 0) {
                const firstChildRect = grid.children[0].getBoundingClientRect();
                const viewportHeight = window.innerHeight;
                
                if (firstChildRect.top > viewportHeight) {
                    grid.children[0].scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            }
            
            // Force reflow to ensure rendering
            grid.offsetHeight;
        }

        renderInventoryGrouped(items, grid) {
            // Group items by location
            const locationGroups = {};

            items.forEach(item => {
                const locationPath = item.location_path || gettext('Unknown location');
                if (!locationGroups[locationPath]) {
                    locationGroups[locationPath] = [];
                }
                locationGroups[locationPath].push(item);
            });

            const sortedLocations = Object.keys(locationGroups).sort();

            grid.innerHTML = '';
            sortedLocations.forEach(locationPath => {
                const itemsInLocation = locationGroups[locationPath];

                // Create location header
                const locationHeader = document.createElement('div');
                locationHeader.className = 'col-12 mb-3';
                locationHeader.innerHTML = `
                    <div class="location-group-header p-3 bg-light border rounded">
                        <h6 class="mb-2">
                            <i class="bi bi-map-marker-alt me-2 text-primary"></i>
                            <span class="location-hierarchy">${this.formatLocationPath(locationPath)}</span>
                        </h6>
                        <small class="text-muted">${itemsInLocation.length} ${gettext('items')}</small>
                    </div>
                `;
                grid.appendChild(locationHeader);

                // Create items in this location
                const itemsRow = document.createElement('div');
                itemsRow.className = 'col-12 mb-3';
                const itemsContainer = document.createElement('div');
                itemsContainer.className = 'row';

                itemsInLocation.forEach(item => {
                    const col = document.createElement('div');
                    col.className = 'col-md-6 col-lg-4 mb-3 d-flex';
                    col.innerHTML = this.createItemCardHTML(item);

                    const card = col.querySelector('.item-card');
                    this.bindItemCardEvents(card, item);

                    itemsContainer.appendChild(col);
                });

                itemsRow.appendChild(itemsContainer);
                grid.appendChild(itemsRow);
            });
        }

        createItemCardHTML(item) {
            const html = `
                <div class="item-card p-3 w-100 h-100 d-flex flex-column border rounded" data-item-id="${item.id}" style="min-height: 150px;">
                    <div class="d-flex justify-content-between align-items-start mb-2">
                        <div class="d-flex align-items-center gap-2" style="min-width: 0;">
                            ${item.thumbnail_url ? `<img src="${item.thumbnail_url}" alt="" loading="lazy" class="item-thumb" title="${gettext('Click to enlarge')}" style="width: 40px; height: 40px; object-fit: cover; border-radius: 6px; border: 1px solid #dee2e6; flex-shrink: 0; cursor: zoom-in;">` : ''}
                            <h6 class="mb-1">${this.escapeHtml(item.description || item.inventory_number || gettext('Unknown'))}</h6>
                        </div>
                        <span class="badge bg-success status-badge">${gettext('Available')}</span>
                    </div>
                    <div class="d-flex align-items-center text-muted small mb-1">
                        <span class="me-3"><i class="bi bi-barcode me-1"></i>${this.escapeHtml(item.inventory_number || gettext('N/A'))}</span>
                        <span><i class="bi bi-tag me-1"></i>${this.escapeHtml(item.category || gettext('No category'))}</span>
                    </div>
                    <div class="d-flex justify-content-between align-items-center mt-auto">
                        <small class="text-muted">${gettext('Owner')}: ${this.escapeHtml(item.owner || gettext('-'))}</small>
                        ${(item.available_quantity || 1) > 1 ? `
                        <div class="quantity-controls">
                            <div class="input-group input-group-sm">
                                <button class="btn btn-outline-secondary qty-minus" type="button">-</button>
                                <input type="number" class="form-control text-center qty-input" value="1" min="1" max="${item.available_quantity}">
                                <button class="btn btn-outline-secondary qty-plus" type="button">+</button>
                            </div>
                        </div>` : ''}
                    </div>
                </div>`;
            return html;
        }

        escapeHtml(text) {
            if (!text) return '';
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        bindItemCardEvents(card, item) {
            card.addEventListener('click', (e) => {
                if (!e.target.closest('.quantity-controls') && !e.target.closest('.item-thumb')) {
                    this.toggleItem(item);
                }
            });

            // Enlarge photo on thumbnail click (without selecting the card)
            const thumb = card.querySelector('.item-thumb');
            if (thumb) {
                thumb.addEventListener('click', (e) => {
                    e.stopPropagation();
                    openImageLightbox(item.image_url || item.thumbnail_url);
                });
            }

            // Quantity controls
            const qtyMinus = card.querySelector('.qty-minus');
            const qtyPlus = card.querySelector('.qty-plus');
            const qtyInput = card.querySelector('.qty-input');

            if (qtyMinus) {
                qtyMinus.addEventListener('click', (e) => {
                    e.stopPropagation();
                    if (qtyInput.value > 1) qtyInput.value = parseInt(qtyInput.value) - 1;
                });
            }

            if (qtyPlus) {
                qtyPlus.addEventListener('click', (e) => {
                    e.stopPropagation();
                    if (qtyInput.value < item.available_quantity) qtyInput.value = parseInt(qtyInput.value) + 1;
                });
            }
        }

        toggleItem(item) {
            const card = document.querySelector(`[data-item-id="${item.id}"]`);
            if (!card) return;

            const idx = this.selectedItems.findIndex(x => x.inventory_id === item.id);
            const qtyInput = card.querySelector('.qty-input');
            const quantity = qtyInput ? (parseInt(qtyInput.value) || 1) : 1;

            if (idx >= 0) {
                this.selectedItems.splice(idx, 1);
                card.classList.remove('selected');
            } else {
                this.selectedItems.push({
                    inventory_id: item.id,
                    inventory_number: item.inventory_number,
                    description: item.description,
                    quantity: quantity,
                    location: item.location ? item.location.full_path : (item.location_name || gettext('Location not specified')),
                    category: item.category || gettext('No category')
                });
                card.classList.add('selected');
            }

            this.updateSelectedItemsUI();
            this.updateActionButtons();
        }

        updateSelectedItemsUI() {
            const box = document.getElementById('selectedItems');
            if (!box) return;

            if (this.selectedItems.length === 0 && this.selectedRooms.length === 0) {
                box.innerHTML = `<small class="text-muted">${gettext('Nothing selected')}</small>`;
                return;
            }

            let html = '';

            // Show selected items
            if (this.selectedItems.length > 0) {
                html += `
                    <div class="alert alert-info py-2 mb-2">
                        <small><i class="bi bi-check-circle me-1"></i>${this.selectedItems.length} ${gettext('items selected')}</small>
                    </div>`;

                html += '<div class="selected-items-list">';
                this.selectedItems.forEach((item, index) => {
                    html += `
                        <div class="selected-item p-2 mb-1 border rounded bg-light" data-item-index="${index}">
                            <div class="d-flex justify-content-between align-items-center">
                                <div>
                                    <strong>${item.description}</strong>
                                    <br><small class="text-muted">${item.inventory_number}</small>
                                    <br><small class="text-muted"><i class="bi bi-map-marker-alt me-1"></i>${item.location}</small>
                                    <br><small class="text-muted"><i class="bi bi-tag me-1"></i>${item.category}</small>
                                </div>
                                <div class="text-end">
                                    <span class="badge bg-primary">${item.quantity}x</span>
                                    <button type="button" class="btn btn-sm btn-outline-danger ms-1 remove-item-btn" data-item-index="${index}">
                                        <i class="bi bi-times"></i>
                                    </button>
                                </div>
                            </div>
                        </div>`;
                });
                html += '</div>';
            }

            // Show selected rooms
            if (this.selectedRooms.length > 0) {
                html += `
                    <div class="alert alert-success py-2 mb-2">
                        <small><i class="bi bi-building me-1"></i>${this.selectedRooms.length} ${gettext('rooms selected')}</small>
                    </div>`;

                html += '<div class="selected-rooms-list">';
                this.selectedRooms.forEach((room, index) => {
                    html += `
                        <div class="selected-room p-2 mb-1 border rounded bg-light" data-room-index="${index}">
                            <div class="d-flex justify-content-between align-items-center">
                                <div>
                                    <strong>${room.room_name}</strong>
                                    <br><small class="text-muted">${room.start_date} ${room.start_time} - ${room.end_date} ${room.end_time}</small>
                                    <br><small class="text-info"><i class="bi bi-info-circle me-1"></i>${gettext('Auto-return after scheduled time')}</small>
                                </div>
                                <div class="text-end">
                                    <button type="button" class="btn btn-sm btn-outline-danger ms-1 remove-room-btn" data-room-index="${index}">
                                        <i class="bi bi-times"></i>
                                    </button>
                                </div>
                            </div>
                        </div>`;
                });
                html += '</div>';
            }

            box.innerHTML = html;

            // Add event listeners to remove buttons
            this.bindRemoveItemEvents();
            this.bindRemoveRoomEvents();
        }

        bindRemoveItemEvents() {
            const removeButtons = document.querySelectorAll('.remove-item-btn');
            removeButtons.forEach(button => {
                button.addEventListener('click', (e) => {
                    e.preventDefault();
                    const index = parseInt(button.dataset.itemIndex);
                    this.removeSelectedItem(index);
                });
            });
        }

        bindRemoveRoomEvents() {
            const removeRoomButtons = document.querySelectorAll('.remove-room-btn');
            removeRoomButtons.forEach(button => {
                button.addEventListener('click', (e) => {
                    e.preventDefault();
                    const index = parseInt(button.dataset.roomIndex);
                    this.removeSelectedRoom(index);
                });
            });
        }

        removeSelectedItem(index) {
            if (index >= 0 && index < this.selectedItems.length) {
                const removedItem = this.selectedItems.splice(index, 1)[0];
                this.updateSelectedItemsUI();
                this.updateActionButtons();
            }
        }

        removeSelectedRoom(index) {
            if (index >= 0 && index < this.selectedRooms.length) {
                const removedRoom = this.selectedRooms.splice(index, 1)[0];
                this.updateSelectedRoomsUI();
                this.updateActionButtons();
            }
        }

        updateSelectedRoomsUI() {
            this.updateSelectedItemsUI(); // Reuse the same function
        }

        updateActionButtons() {
            const reserveBtn = document.getElementById('reserveBtn');
            if (!reserveBtn) return;

            if (this.selectedItems.length > 0 || this.selectedRooms.length > 0) {
                reserveBtn.disabled = false;
            } else {
                reserveBtn.disabled = true;
            }
        }

        async showEquipmentSets() {
            try {
                const resp = await fetch(URLS.equipmentSets);
                const data = await resp.json();

                if (data.success) {
                    this.equipmentSets = data.equipment_sets || [];
                } else {
                    this.equipmentSets = [];
                }

                this.renderEquipmentSets();

                // Show modal
                const modal = new bootstrap.Modal(document.getElementById('equipmentSetsModal'));
                modal.show();
            } catch (error) {
                console.error('Error loading equipment sets:', error);
                alert(gettext('Error loading equipment sets'));
                this.equipmentSets = [];
                this.renderEquipmentSets();
            }
        }

        renderEquipmentSets() {
            const container = document.getElementById('equipmentSetsList');
            if (!container) return;

            if (this.equipmentSets.length === 0) {
                container.innerHTML = `<div class="text-center p-3"><small class="text-muted">${gettext('No available sets')}</small></div>`;
                return;
            }

            container.innerHTML = '';
            this.equipmentSets.forEach(set => {
                const item = document.createElement('a');
                item.href = '#';
                item.className = 'list-group-item list-group-item-action';
                item.innerHTML = `
                    <div class="d-flex w-100 justify-content-between">
                        <div>
                            <h6 class="mb-1">${set.name}</h6>
                            <p class="mb-1 text-truncate" style="max-width: 200px;">${set.description || gettext('No description')}</p>
                            <small class="text-muted">${set.items_count} ${gettext('items')}</small>
                        </div>
                        <div class="text-end">
                            <span class="badge bg-success">${gettext('Available')}</span>
                        </div>
                    </div>`;

                item.addEventListener('click', (e) => {
                    e.preventDefault();
                    this.selectEquipmentSet(set);
                    container.querySelectorAll('.list-group-item').forEach(i => i.classList.remove('active'));
                    item.classList.add('active');
                });

                container.appendChild(item);
            });
        }

        async selectEquipmentSet(set) {
            this.selectedSet = set;

            try {
                const url = URLS.equipmentSetDetails.replace('{setId}', set.id);
                const resp = await fetch(url);
                const data = await resp.json();

                if (data.success) {
                    this.selectedSetDetails = data.equipment_set;
                    this.renderSetDetails(data.equipment_set);
                } else {
                    this.renderSetDetails(set);
                }
            } catch (error) {
                console.error('Error loading set details:', error);
                this.renderSetDetails(set);
            }

            document.getElementById('addSetToRentalBtn').disabled = false;
        }

        renderSetDetails(set) {
            const panel = document.getElementById('setDetailsPanel');
            if (!panel) return;

            let html = `
                <h6>${set.name}</h6>
                <p class="text-muted">${set.description || gettext('No description')}</p>`;

            if (set.items && set.items.length > 0) {
                html += `
                    <div class="table-responsive">
                        <table class="table table-sm">
                            <thead>
                                <tr>
                                    <th>${gettext('Item')}</th>
                                    <th>${gettext('Required')}</th>
                                    <th>${gettext('Available')}</th>
                                    <th>${gettext('Status')}</th>
                                    <th>${gettext('Location')}</th>
                                </tr>
                            </thead>
                            <tbody>`;

                set.items.forEach(item => {
                    const isAvailable = item.is_available && item.quantity_available >= item.quantity_needed;
                    html += `
                        <tr class="${isAvailable ? '' : 'table-warning'}">
                            <td>
                                <strong>${item.description || item.inventory_number}</strong><br>
                                <small class="text-muted">${item.inventory_number}</small>
                            </td>
                            <td>${item.quantity_needed}</td>
                            <td>${item.quantity_available}</td>
                            <td>
                                <span class="badge ${isAvailable ? 'bg-success' : 'bg-warning'}">
                                    ${isAvailable ? gettext('OK') : gettext('Missing')}
                                </span>
                            </td>
                            <td>
                                <small class="text-muted">${item.location}</small>
                            </td>
                        </tr>`;
                });

                html += `
                            </tbody>
                        </table>
                    </div>`;
            } else {
                html += `
                    <div class="alert alert-info">
                        <i class="bi bi-info-circle me-2"></i>
                        <strong>${set.items_count || 0}</strong> ${gettext('items in set')}
                    </div>`;
            }

            panel.innerHTML = html;
        }

        addSetToRental() {
            if (!this.selectedSet || !this.selectedSetDetails) {
                alert(gettext('Please select a set'));
                return;
            }

            if (this.selectedSetDetails.items) {
                this.selectedSetDetails.items.forEach(setItem => {
                    if (setItem.is_available && setItem.quantity_available > 0) {
                        const existingIndex = this.selectedItems.findIndex(item =>
                            item.inventory_id === setItem.inventory_item_id
                        );

                        const quantityToAdd = Math.min(setItem.quantity_available, setItem.quantity_needed);

                        if (existingIndex >= 0) {
                            this.selectedItems[existingIndex].quantity += quantityToAdd;
                        } else {
                            this.selectedItems.push({
                                inventory_id: setItem.inventory_item_id,
                                inventory_number: setItem.inventory_number,
                                description: setItem.description,
                                quantity: quantityToAdd,
                                location: setItem.location,
                                category: setItem.category
                            });
                        }
                    }
                });

                this.updateSelectedItemsUI();
                this.updateActionButtons();

                // Close modal
                const modal = bootstrap.Modal.getInstance(document.getElementById('equipmentSetsModal'));
                if (modal) modal.hide();

                alert(interpolate(gettext('Set "%(setName)s" added to rental'), { setName: this.selectedSet.name }, true));
            }
        }

        async showRooms() {
            try {
                // For rooms, we can show the modal first and let users select dates there
                // Load rooms without date filtering initially
                let url = URLS.rooms;

                const resp = await fetch(url);

                if (!resp.ok) {
                    throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
                }

                const data = await resp.json();

                if (data.success) {
                    this.rooms = data.rooms || [];
                    this.renderRooms();
                    this.populateRoomSelects();

                    // Show modal first
                    const modal = new bootstrap.Modal(document.getElementById('roomsModal'));
                    modal.show();

                    // Check availability for selected dates if they exist
                    const startDate = document.querySelector('[name="start_date"]')?.value;
                    const endDate = document.querySelector('[name="end_date"]')?.value;

                    if (startDate && endDate && this.selectedRoom) {
                        const startTime = document.getElementById('roomStartTime')?.value || '10:00';
                        const endTime = document.getElementById('roomEndTime')?.value || '10:30';
                        const availabilityStatus = document.getElementById('roomAvailabilityStatus');

                        if (availabilityStatus) {
                            this.checkRoomAvailability(this.selectedRoom.id, startDate, startTime, startDate, endTime, availabilityStatus);
                        }
                    }
                } else {
                    throw new Error(data.error || gettext('Unknown error'));
                }
            } catch (error) {
                console.error('Error loading rooms:', error);
                alert(gettext('Error loading rooms'));
            }
        }

        populateRoomSelects() {
            const calendarSelect = document.getElementById('calendarRoomSelect');
            const timelineSelect = document.getElementById('timelineRoomSelect');

            if (calendarSelect) {
                calendarSelect.innerHTML = `<option value="">${gettext('All rooms')}</option>`;
                this.rooms.forEach(room => {
                    const option = document.createElement('option');
                    option.value = room.id;
                    option.textContent = room.name;
                    calendarSelect.appendChild(option);
                });
            }

            if (timelineSelect) {
                timelineSelect.innerHTML = `<option value="">${gettext('All rooms')}</option>`;
                this.rooms.forEach(room => {
                    const option = document.createElement('option');
                    option.value = room.id;
                    option.textContent = room.name;
                    timelineSelect.appendChild(option);
                });
            }

            // Set current date
            const today = new Date().toISOString().split('T')[0];
            if (document.getElementById('calendarStartDate')) {
                document.getElementById('calendarStartDate').value = today;
            }
            if (document.getElementById('calendarEndDate')) {
                const endDate = new Date();
                endDate.setDate(endDate.getDate() + 6);
                document.getElementById('calendarEndDate').value = endDate.toISOString().split('T')[0];
            }

                    // Add event listeners for date changes to reload rooms with availability
        this.bindRoomDateEvents();

        // Bind calendar events
        this.bindCalendarEvents();
    }

    bindRoomDateEvents() {
        const startDateInput = document.getElementById('calendarStartDate');
        const endDateInput = document.getElementById('calendarEndDate');

        if (startDateInput) {
            startDateInput.addEventListener('change', () => this.reloadRoomsWithDates());
        }
        if (endDateInput) {
            endDateInput.addEventListener('change', () => this.reloadRoomsWithDates());
        }
    }

    async reloadRoomsWithDates() {
        const startDate = document.getElementById('calendarStartDate')?.value;
        const endDate = document.getElementById('calendarEndDate')?.value;

        if (!startDate || !endDate) return;

        try {
            let url = URLS.rooms;
            url += `?start_date=${encodeURIComponent(startDate + 'T10:00:00')}&end_date=${encodeURIComponent(endDate + 'T18:00:00')}`;

            const resp = await fetch(url);
            if (!resp.ok) {
                throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
            }

            const data = await resp.json();
            if (data.success) {
                this.rooms = data.rooms || [];
                this.renderRooms();
            }
        } catch (error) {
            console.error('Error reloading rooms with dates:', error);
        }
    }

    bindCalendarEvents() {
        // Handlers for calendar
        const calendarRoomSelect = document.getElementById('calendarRoomSelect');
        const calendarStartDate = document.getElementById('calendarStartDate');
        const calendarEndDate = document.getElementById('calendarEndDate');

        if (calendarRoomSelect) {
            calendarRoomSelect.addEventListener('change', () => this.loadRoomSchedule());
        }
        if (calendarStartDate) {
            calendarStartDate.addEventListener('change', () => this.loadRoomSchedule());
        }
        if (calendarEndDate) {
            calendarEndDate.addEventListener('change', () => this.loadRoomSchedule());
        }

        // Handlers for tabs
        const roomsTabs = document.getElementById('roomsTabs');
        if (roomsTabs) {
            roomsTabs.addEventListener('shown.bs.tab', (event) => {
                if (event.target.id === 'rooms-calendar-tab') {
                    this.loadRoomSchedule();
                }
            });
        }
    }

    async loadRoomSchedule() {
        try {
            const roomId = document.getElementById('calendarRoomSelect')?.value || '';
            const startDate = document.getElementById('calendarStartDate')?.value || '';
            const endDate = document.getElementById('calendarEndDate')?.value || '';

            if (!startDate || !endDate) {
                return;
            }

            // Show loading indicator
            const container = document.getElementById('calendarContainer');
            if (container) {
                container.innerHTML = `
                    <div class="text-center p-5">
                        <div class="spinner-border" role="status"></div>
                        <p class="mt-2">${gettext('Loading calendar...')}</p>
                    </div>
                `;
            }

            let url = URLS.roomSchedule;
            const params = new URLSearchParams();
            if (roomId) params.append('room_id', roomId);
            if (startDate) params.append('start_date', startDate);
            if (endDate) params.append('end_date', endDate);

            if (params.toString()) {
                url += '?' + params.toString();
            }

            const resp = await fetch(url);

            if (!resp.ok) {
                throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
            }

            const data = await resp.json();

            if (data.success) {
                this.renderCalendar(data.rooms, data.period);
            } else {
                throw new Error(data.error || gettext('Unknown error'));
            }
        } catch (error) {
            console.error('Error loading room schedule:', error);
            const container = document.getElementById('calendarContainer');
            if (container) {
                container.innerHTML = `
                    <div class="text-center p-5">
                        <div class="alert alert-danger">
                            <i class="bi bi-exclamation-triangle me-2"></i>
                            ${gettext('Error loading calendar')}: ${error.message}
                        </div>
                        <button class="btn btn-primary mt-3" id="retryCalendarBtn">
                            <i class="bi bi-arrow-clockwise me-1"></i>${gettext('Retry')}
                        </button>
                    </div>
                `;

                // Add handler for retry button
                const retryBtn = container.querySelector('#retryCalendarBtn');
                if (retryBtn) {
                    retryBtn.addEventListener('click', () => this.loadRoomSchedule());
                }
            }
        }
    }

    renderCalendar(rooms, period) {
        const container = document.getElementById('calendarContainer');
        if (!container) return;

        if (!rooms || rooms.length === 0) {
            container.innerHTML = `<div class="text-center p-3"><p class="text-muted">${gettext('No available rooms')}</p></div>`;
            return;
        }

        // Check if the first room has a schedule
        const firstRoom = rooms[0];
        if (!firstRoom.schedule || firstRoom.schedule.length === 0) {
            container.innerHTML = `<div class="text-center p-3"><p class="text-muted">${gettext('No schedule')}</p></div>`;
            return;
        }

        // If "All rooms" mode is selected, aggregate occupancy for all rooms
        const isAllRooms = rooms.length > 1;
        const scheduleToUse = isAllRooms
            ? firstRoom.schedule.map((day, dayIdx) => {
                const aggregatedSlots = day.slots.map((_, slotIdx) => {
                    const occupiedRooms = [];
                    for (const r of rooms) {
                        const rd = r.schedule && r.schedule[dayIdx];
                        if (rd && rd.slots && rd.slots[slotIdx] && rd.slots[slotIdx].status === 'occupied') {
                            occupiedRooms.push(r.name);
                        }
                    }
                    return occupiedRooms.length
                        ? { status: 'occupied', rooms: occupiedRooms }
                        : { status: 'available', rooms: [] };
                });
                return { ...day, slots: aggregatedSlots };
            })
            : firstRoom.schedule;

        const numDays = scheduleToUse.length;
        let html = `<div class="calendar-grid" style="grid-template-columns: 80px repeat(${numDays}, 1fr);">`;

        // Calendar header
        html += '<div class="calendar-header">';
        html += `<div class="calendar-cell header">${gettext('Time')}</div>`;
        // Days of the week
        scheduleToUse.forEach(day => {
            const dayClass = day.is_today ? 'today' : day.is_weekend ? 'weekend' : '';
            html += `<div class="calendar-cell header ${dayClass}">`;
            html += `<div class="day-name">${day.day_short}</div>`;
            html += `<div class="day-number">${day.day_number}</div>`;
            html += '</div>';
        });
        html += '</div>';

        // Time slots
        for (let i = 0; i < 16; i++) { // 10:00 - 18:00 (16 slots of 30 minutes)
            const hour = Math.floor(i / 2) + 10;
            const minute = (i % 2) * 30;
            const time = `${hour.toString().padStart(2, '0')}:${minute.toString().padStart(2, '0')}`;

            html += '<div class="calendar-row">';
            html += `<div class="calendar-cell time-slot">${time}</div>`;

            // Slots for each day
            scheduleToUse.forEach(day => {
                if (day.slots && day.slots[i]) {
                    const slot = day.slots[i];
                    const slotClass = slot.status === 'occupied' ? 'occupied' : 'available';
                    // Tooltip: for aggregated mode show list of rooms, otherwise normal slot tooltip
                    const title = isAllRooms
                        ? (slot.status === 'occupied' && slot.rooms ? slot.rooms.join(', ') : '')
                        : this.getSlotTooltip(slot);
                    html += `<div class="calendar-cell ${slotClass}" title="${title}">`;
                    if (slot.status === 'occupied') {
                        if (!isAllRooms && slot.info) {
                            html += `<div class="slot-info">`;
                            html += `<small class="d-block">${slot.info.user_name}</small>`;
                            html += `<small class="d-block text-muted">${slot.info.project}</small>`;
                            html += `<small class="badge bg-${this.getStatusColor(slot.info.status)} text-white">${this.getStatusText(slot.info.status)}</small>`;
                            if (slot.info.people_count > 1) {
                                html += `<small class="d-block text-muted"><i class="bi bi-people me-1"></i>${slot.info.people_count} ${gettext('people')}</small>`;
                            }
                            html += `</div>`;
                        } else if (isAllRooms && slot.rooms && slot.rooms.length) {
                            html += `<div class="slot-info"><small>${slot.rooms.join(', ')}</small></div>`;
                        }
                    }
                    html += '</div>';
                } else {
                    // If slot does not exist, add an empty cell
                    html += '<div class="calendar-cell available"></div>';
                }
            });
            html += '</div>';
        }

        // Add ending row with 18:00 label to visually show until 18:00
        html += '<div class="calendar-row">';
        html += `<div class="calendar-cell time-slot">18:00</div>`;
        scheduleToUse.forEach(() => {
            html += '<div class="calendar-cell available"></div>';
        });
        html += '</div>';

        html += '</div>';
        container.innerHTML = html;
    }

    getSlotTooltip(slot) {
        if (slot.status === 'available') {
            return gettext('Available');
        }
        if (slot.info) {
            const userName = slot.info.user_name || gettext('Unknown user');
            const project = slot.info.project || gettext('No project');
            const status = slot.info.status || gettext('Unknown');
            const peopleCount = slot.info.people_count || 1;
            const startTime = slot.info.start_time || '';
            const endTime = slot.info.end_time || '';

            let tooltip = `${userName} - ${project}`;
            if (startTime && endTime) {
                tooltip += ` (${startTime}-${endTime})`;
            }
            tooltip += ` - ${this.getStatusText(status)}`;
            if (peopleCount > 1) {
                tooltip += ` - ${peopleCount} ${gettext('people')}`;
            }
            return tooltip;
        }
        return gettext('Occupied');
    }

    getStatusColor(status) {
        switch (status) {
            case 'draft': return 'secondary';
            case 'reserved': return 'info';
            case 'issued': return 'primary';
            case 'returned': return 'success';
            case 'cancelled': return 'danger';
            default: return 'secondary';
        }
    }

    getStatusText(status) {
        switch (status) {
            case 'draft': return gettext('Draft');
            case 'reserved': return gettext('Reserved');
            case 'issued': return gettext('Issued');
            case 'returned': return gettext('Returned');
            case 'cancelled': return gettext('Cancelled');
            default: return status;
        }
    }

        renderRooms() {
            const container = document.getElementById('roomsList');
            if (!container) return;

            if (this.rooms.length === 0) {
                container.innerHTML = `
                    <div class="text-center p-3">
                        <i class="bi bi-building text-muted mb-2" style="font-size: 2rem;"></i>
                        <p class="text-muted mb-0">${gettext('No available rooms')}</p>
                    </div>`;
                return;
            }

            let html = '';
            this.rooms.forEach(room => {
                const availabilityClass = room.is_available ? 'list-group-item-action' : 'list-group-item-secondary';
                const availabilityIcon = room.is_available ? 'bi-check-circle text-success' : 'bi-times-circle text-danger';
                const availabilityText = room.is_available ? gettext('Available') : gettext('Unavailable');

                html += `
                    <div class="list-group-item ${availabilityClass} room-item ${!room.is_available ? 'disabled' : ''}"
                          data-room-id="${room.id}" ${!room.is_available ? 'style="opacity: 0.6;"' : ''}>
                        <div class="d-flex justify-content-between align-items-start">
                            <div>
                                <h6 class="mb-1">
                                    ${room.name}
                                    <i class="bi ${availabilityIcon} ms-2" title="${availabilityText}"></i>
                                </h6>
                            </div>
                            <span class="badge bg-primary">${room.capacity} ${gettext('people')}</span>
                        </div>
                        <small class="text-muted d-block mt-1">
                            <i class="bi bi-map-marker-alt me-1"></i>${room.location || gettext('Location not specified')}
                        </small>
                        ${!room.is_available ? `<small class="text-danger d-block mt-1"><i class="bi bi-info-circle me-1"></i>${room.availability_info}</small>` : ''}
                    </div>`;
            });

            container.innerHTML = html;

            // Add click event listeners only for available rooms
            container.querySelectorAll('.room-item:not(.disabled)').forEach(item => {
                item.addEventListener('click', (e) => {
                    container.querySelectorAll('.room-item').forEach(i => i.classList.remove('active'));
                    item.classList.add('active');

                    const roomId = item.dataset.roomId;
                    this.selectRoom(roomId);
                });
            });

            // Add disabled message for unavailable rooms
            container.querySelectorAll('.room-item.disabled').forEach(item => {
                item.addEventListener('click', (e) => {
                    e.preventDefault();
                    alert(gettext('This room is not available for the selected period.'));
                });
            });
        }

        selectRoom(roomId) {
            this.selectedRoom = this.rooms.find(room => room.id == roomId);
            if (this.selectedRoom) {
                this.renderRoomDetails(this.selectedRoom);
                // Button will be enabled/disabled based on availability check
                const addRoomBtn = document.getElementById('addRoomToRentalBtn');
                if (addRoomBtn) {
                    addRoomBtn.disabled = true;
                    addRoomBtn.classList.remove('btn-success');
                    addRoomBtn.classList.add('btn-secondary');
                }
            }
        }

        renderRoomDetails(room) {
            const panel = document.getElementById('roomDetailsPanel');
            if (!panel) return;

            // Smart date calculation function
            const getSmartStartDate = () => {
                return RentalWorkingHours.getSuggestedStartDate();
            };

            const smartStartDate = getSmartStartDate();
            const minDate = new Date().toISOString().split('T')[0];

            let html = `
                <h6>${room.name}</h6>
                <p class="text-muted">${room.description || gettext('No description')}</p>
                <div class="row mb-3">
                    <div class="col-6">
                        <strong>${gettext('Capacity')}:</strong><br>
                        <span class="badge bg-primary fs-6">${room.capacity} ${gettext('people')}</span>
                    </div>
                    <div class="col-6">
                        <strong>${gettext('Location')}:</strong><br>
                        <small class="text-muted">${room.location || gettext('Not specified')}</small>
                    </div>
                </div>
                <hr>
                <div class="room-time-section">
                    <div class="mb-3">
                        <label class="form-label"><strong>📅 ${gettext('Start date')}:</strong></label>
                        <input type="date" class="form-control date-input" id="roomStartDate"
                               min="${minDate}"
                               value="${smartStartDate}">
                    </div>
                    <div class="mb-3">
                        <label class="form-label"><strong>🕐 ${gettext('Start time')}:</strong></label>
                        <select class="form-select time-select" id="roomStartTime"></select>
                    </div>
                    <div class="mb-3">
                        <label class="form-label"><strong>📅 ${gettext('End date')} (${gettext('optional')}):</strong></label>
                        <div class="form-check mb-2">
                            <input class="form-check-input" type="checkbox" id="differentEndDate">
                            <label class="form-check-label" for="differentEndDate">
                                ${gettext('Select different end date')}
                            </label>
                        </div>
                        <input type="date" class="form-control date-input" id="roomEndDate"
                               min="${minDate}"
                               value="${smartStartDate}" disabled>
                    </div>
                    <div class="mb-3">
                        <label class="form-label"><strong>🕐 ${gettext('End time')}:</strong></label>
                        <select class="form-select time-select" id="roomEndTime"></select>
                    </div>
                </div>
                <div class="alert alert-info p-2">
                    <small><i class="fas fa-info-circle me-1"></i>${gettext('Working hours')}: ${RENTAL_WORKING_HOURS_SUMMARY}</small>
                </div>
                <div id="roomAvailabilityStatus" class="mt-3"></div>`;

            panel.innerHTML = html;

            // Wait for DOM to be ready, then set up time selectors
            setTimeout(() => {
                const startTimeSelect = document.getElementById('roomStartTime');
                const endTimeSelect = document.getElementById('roomEndTime');
                const startDateInput = document.getElementById('roomStartDate');
                const endDateInput = document.getElementById('roomEndDate');
                const differentEndDateCheckbox = document.getElementById('differentEndDate');
                const availabilityStatus = document.getElementById('roomAvailabilityStatus');

                if (startTimeSelect && endTimeSelect) {
                    if (startDateInput) {
                        startDateInput.value = smartStartDate;
                    }
                    const setAddRoomEnabled = (enabled) => {
                        const addRoomBtn = document.getElementById('addRoomToRentalBtn');
                        if (!addRoomBtn) return;
                        addRoomBtn.disabled = !enabled;
                        addRoomBtn.classList.toggle('btn-success', enabled);
                        addRoomBtn.classList.toggle('btn-secondary', !enabled);
                    };
                    const getEffectiveEndDate = () => differentEndDateCheckbox?.checked ? endDateInput.value : startDateInput.value;
                    const showInvalidSelection = (message) => {
                        availabilityStatus.innerHTML = `
                            <div class="alert alert-warning">
                                <i class="bi bi-exclamation-triangle me-2"></i>${message}
                            </div>
                        `;
                        setAddRoomEnabled(false);
                    };
                    const syncEndDate = () => {
                        if (endDateInput && !differentEndDateCheckbox?.checked) {
                            endDateInput.value = startDateInput.value;
                        }
                    };
                    const refreshStartTimes = () => {
                        const currentValue = startTimeSelect.value;
                        const options = RentalWorkingHours.buildOptions(startDateInput.value, 'start');
                        const suggestedValue = RentalWorkingHours.getSuggestedStartTime(startDateInput.value) || options[0] || '';
                        RentalWorkingHours.populateSelect(startTimeSelect, options, suggestedValue);
                        if (currentValue && options.includes(currentValue)) {
                            startTimeSelect.value = currentValue;
                        } else if (suggestedValue) {
                            startTimeSelect.value = suggestedValue;
                        }
                    };
                    const refreshEndTimes = () => {
                        const endDateValue = getEffectiveEndDate();
                        const currentValue = endTimeSelect.value;
                        const options = RentalWorkingHours.buildOptions(endDateValue, 'end', startTimeSelect.value);
                        const suggestedValue = RentalWorkingHours.getNextEndTime(endDateValue, startTimeSelect.value) || options[0] || '';
                        RentalWorkingHours.populateSelect(endTimeSelect, options, suggestedValue);
                        if (currentValue && options.includes(currentValue)) {
                            endTimeSelect.value = currentValue;
                        } else if (suggestedValue) {
                            endTimeSelect.value = suggestedValue;
                        }
                    };
                    const refreshAvailability = () => {
                        const endDateValue = getEffectiveEndDate();
                        if (RentalWorkingHours.isClosed(startDateInput.value)) {
                            showInvalidSelection(gettext('The selected start day is closed.'));
                            return;
                        }
                        if (RentalWorkingHours.isClosed(endDateValue)) {
                            showInvalidSelection(gettext('The selected end day is closed.'));
                            return;
                        }
                        if (!startTimeSelect.value || !endTimeSelect.value) {
                            showInvalidSelection(gettext('Please select a valid time within working hours.'));
                            return;
                        }
                        this.checkRoomAvailability(room.id, startDateInput.value, startTimeSelect.value, endDateValue, endTimeSelect.value, availabilityStatus);
                    };

                    syncEndDate();
                    refreshStartTimes();
                    refreshEndTimes();
                    refreshAvailability();

                    if (startDateInput) {
                        startDateInput.addEventListener('change', () => {
                            syncEndDate();
                            refreshStartTimes();
                            refreshEndTimes();
                            refreshAvailability();
                        });
                    }

                    startTimeSelect.addEventListener('change', () => {
                        refreshEndTimes();
                        refreshAvailability();
                    });

                    endTimeSelect.addEventListener('change', () => {
                        refreshAvailability();
                    });

                    if (differentEndDateCheckbox && endDateInput) {
                        differentEndDateCheckbox.addEventListener('change', () => {
                            endDateInput.disabled = !differentEndDateCheckbox.checked;
                            syncEndDate();
                            refreshEndTimes();
                            refreshAvailability();
                        });

                        endDateInput.addEventListener('change', () => {
                            refreshEndTimes();
                            refreshAvailability();
                        });
                    }
                }
            }, 100); // 100ms delay to ensure DOM is ready
        }

        async checkRoomAvailability(roomId, startDate, startTime, endDate, endTime, statusElement) {
            try {
                const url = `${URLS.checkRoomAvailability}?room_id=${roomId}&start_date=${startDate}&start_time=${startTime}&end_date=${endDate}&end_time=${endTime}`;

                const resp = await fetch(url);
                const data = await resp.json();

                if (data.success) {
                    const addRoomBtn = document.getElementById('addRoomToRentalBtn');

                    if (data.is_available) {
                        statusElement.innerHTML = `
                            <div class="alert alert-success">
                                <i class="bi bi-check-circle me-2"></i>
                                ${gettext('Room is available for the selected period.')}
                            </div>
                        `;
                        // Enable Add Room button
                        if (addRoomBtn) {
                            addRoomBtn.disabled = false;
                            addRoomBtn.classList.remove('btn-secondary');
                            addRoomBtn.classList.add('btn-success');
                        }
                    } else {
                        const unavailableMessage = data.message || gettext('Room is not available for the selected period.');
                        statusElement.innerHTML = `
                            <div class="alert alert-danger">
                                <i class="bi bi-x-circle me-2"></i>
                                ${unavailableMessage}
                                ${data.conflicts && data.conflicts.length > 0 ?
                                    `<br><small class="mt-2"><strong>${gettext('Conflicts:')}</strong><br>${data.conflicts.join('<br>')}</small>` : ''}
                            </div>
                        `;
                        // Disable Add Room button
                        if (addRoomBtn) {
                            addRoomBtn.disabled = true;
                            addRoomBtn.classList.remove('btn-success');
                            addRoomBtn.classList.add('btn-secondary');
                        }
                    }
                } else {
                    statusElement.innerHTML = `
                        <div class="alert alert-warning">
                            <i class="bi bi-exclamation-triangle me-2"></i>
                            ${interpolate(gettext('Error checking room availability: %(message)s'), { message: data.error }, true)}
                        </div>
                    `;
                    // Disable Add Room button on error
                    const addRoomBtn = document.getElementById('addRoomToRentalBtn');
                    if (addRoomBtn) {
                        addRoomBtn.disabled = true;
                        addRoomBtn.classList.remove('btn-success');
                        addRoomBtn.classList.add('btn-secondary');
                    }
                }
            } catch (error) {
                statusElement.innerHTML = `
                    <div class="alert alert-danger">
                        <i class="bi bi-exclamation-triangle me-2"></i>
                        ${interpolate(gettext('Error checking room availability: %(message)s'), { message: error.message }, true)}
                    </div>
                `;
                // Disable Add Room button on error
                const addRoomBtn = document.getElementById('addRoomToRentalBtn');
                if (addRoomBtn) {
                    addRoomBtn.disabled = true;
                    addRoomBtn.classList.remove('btn-success');
                    addRoomBtn.classList.add('btn-secondary');
                }
            }
        }

        addRoomToRental() {
            if (!this.selectedRoom) {
                alert(gettext('Please select a room'));
                return;
            }

            // Get selected date and time
            const startDate = document.getElementById('roomStartDate')?.value;
            const startTime = document.getElementById('roomStartTime')?.value;
            const endDate = document.getElementById('roomEndDate')?.value;
            const endTime = document.getElementById('roomEndTime')?.value;
            const differentEndDate = document.getElementById('differentEndDate')?.checked;

            if (!startDate || !startTime || !endTime) {
                alert(gettext('Please select start date and time'));
                return;
            }

            // Use start date for end date if different end date is not checked
            const finalEndDate = differentEndDate ? endDate : startDate;

            if (!finalEndDate) {
                alert(gettext('Please select end date'));
                return;
            }

            // Validate time range
            const startHour = parseInt(startTime.split(':')[0]);
            const startMinute = parseInt(startTime.split(':')[1]);
            const endHour = parseInt(endTime.split(':')[0]);
            const endMinute = parseInt(endTime.split(':')[1]);

            if (!RentalWorkingHours.isWithinDayHours(startDate, startTime, false)) {
                alert(gettext('Please select a start time within the configured working hours.'));
                return;
            }

            if (!RentalWorkingHours.isWithinDayHours(finalEndDate, endTime, true)) {
                alert(gettext('Please select an end time within the configured working hours.'));
                return;
            }

            const startDateTime = new Date(`${startDate}T${startTime}`);
            const endDateTime = new Date(`${finalEndDate}T${endTime}`);

            if (endDateTime <= startDateTime) {
                alert(gettext('End time must be after start time'));
                return;
            }

            // Check if time is in the past
            const now = new Date();

            if (startDateTime < now) {
                alert(interpolate(gettext('Start time cannot be in the past. Selected time: %(selected)s, Current time: %(current)s'), {
                    selected: startDateTime.toLocaleString('en-US'),
                    current: now.toLocaleString('en-US')
                }, true));
                return;
            }

            if (endDateTime < now) {
                alert(interpolate(gettext('End time cannot be in the past. Selected time: %(selected)s, Current time: %(current)s'), {
                    selected: endDateTime.toLocaleString('en-US'),
                    current: now.toLocaleString('en-US')
                }, true));
                return;
            }

            // Final availability check before adding room
            this.finalRoomAvailabilityCheck(this.selectedRoom.id, startDate, startTime, finalEndDate, endTime, () => {
                // Check if room is already selected
                const existingIndex = this.selectedRooms.findIndex(room => room.room_id === this.selectedRoom.id);

                if (existingIndex >= 0) {
                    // Update existing room
                    this.selectedRooms[existingIndex].start_date = startDate;
                    this.selectedRooms[existingIndex].end_date = finalEndDate;
                    this.selectedRooms[existingIndex].start_time = startTime;
                    this.selectedRooms[existingIndex].end_time = endTime;
                } else {
                    // Add new room
                    this.selectedRooms.push({
                        room_id: this.selectedRoom.id,
                        room_name: this.selectedRoom.name,
                        start_date: startDate,
                        end_date: finalEndDate,
                        start_time: startTime,
                        end_time: endTime
                    });
                }

                // Auto-fill time period fields on main page
                this.autoFillZeitraum(startDate, startTime, finalEndDate, endTime);

                // Update UI
                this.updateSelectedRoomsUI();
                this.updateActionButtons();

                // Update action buttons based on selection
                this.updateActionButtons();

                // Close modal
                const modal = bootstrap.Modal.getInstance(document.getElementById('roomsModal'));
                if (modal) modal.hide();

                alert(interpolate(gettext('Room "%(roomName)s" was added to the rental. Note: Rooms are automatically reserved and will return after the scheduled time.'), {
                    roomName: this.selectedRoom.name
                }, true));
            });
        }

        autoFillZeitraum(startDate, startTime, endDate, endTime) {
            // Check if time is in the past
            const startDateTime = new Date(`${startDate}T${startTime}`);
            const endDateTime = new Date(`${endDate}T${endTime}`);
            const now = new Date();

            if (startDateTime < now || endDateTime < now) {
                alert(gettext('Warning: The selected time is in the past. Please select a future time.'));
                return;
            }

            const startDateField = document.querySelector('[name="start_date"]');
            const endDateField = document.querySelector('[name="end_date"]');

            if (startDateField) startDateField.value = `${startDate}T${startTime}`;
            if (endDateField) {
                this.setupDateFieldConstraints(endDateField, `${startDate}T${startTime}`);
                endDateField.value = `${endDate}T${endTime}`;
            }

            this.ensureDateTimeDefaults();

            // Enable the fields
            if (startDateField) startDateField.disabled = false;
            if (endDateField) endDateField.disabled = false;
        }

        async createRental(action = 'reserved') {
            try {
                this.ensureDateTimeDefaults();

                // Validate project info
                const projectName = document.querySelector('[name="project_name"]').value.trim();
                if (!projectName) {
                    alert(gettext('Please enter project name'));
                    return;
                }

                // Validate purpose
                const purpose = document.querySelector('[name="purpose"]').value.trim();
                if (!purpose) {
                    alert(gettext('Please enter purpose of use'));
                    return;
                }

                // Validate dates
                const startDate = document.querySelector('[name="start_date"]').value;
                const endDate = document.querySelector('[name="end_date"]').value;

                if (!startDate || !endDate) {
                    alert(gettext('Please select start and end dates'));
                    return;
                }

                const workingHoursError = this.getWorkingHoursError(startDate, endDate);
                if (workingHoursError) {
                    this.updateWorkingHoursHint();
                    alert(workingHoursError);
                    return;
                }

                // Validate items or rooms selection
                if ((!this.selectedItems || this.selectedItems.length === 0) &&
                    (!this.selectedRooms || this.selectedRooms.length === 0)) {
                    alert(gettext('Please select at least one item or room'));
                    return;
                }

                // Prepare rental data
                const rentalData = {
                    user_id: parseInt(USER_ID), // Convert string to integer for Django comparison
                    project_name: projectName,
                    purpose: purpose,
                    start_date: startDate,
                    end_date: endDate,
                    action: action,
                    items: this.selectedItems || [],
                    rooms: this.selectedRooms || [],
                    rental_type: this.getRentalType()
                };

                // Send request
                const response = await fetch(URLS.createRental, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': CSRF_TOKEN
                    },
                    body: JSON.stringify(rentalData)
                });

                const result = await response.json();

                if (!response.ok) {
                    console.error('Rental creation failed:', {
                        status: response.status,
                        statusText: response.statusText,
                        error: result.error || result,
                        requestData: rentalData
                    });
                }

                if (result.success) {
                    if (action === 'draft') {
                        alert(interpolate(gettext('Request submitted for approval. ID: %(rentalId)s'), { rentalId: result.rental_id }, true));
                    } else {
                        alert(interpolate(gettext('Rental successfully booked! ID: %(rentalId)s'), { rentalId: result.rental_id }, true));
                    }
                    this.clearForm();
                } else {
                    const errorMessage = result.error || gettext('Unknown error occurred');
                    console.error('Rental creation error:', errorMessage);
                    alert(interpolate(gettext('Error: %(message)s'), { message: errorMessage }, true));
                }
            } catch (error) {
                console.error('Error creating rental:', error);
                console.error('Request data was:', rentalData);
                alert(interpolate(gettext('Error creating rental: %(message)s'), { message: error.message }, true));
            }
        }

        getRentalType() {
            if (this.selectedItems && this.selectedItems.length > 0 &&
                this.selectedRooms && this.selectedRooms.length > 0) {
                return 'mixed';
            } else if (this.selectedRooms && this.selectedRooms.length > 0) {
                return 'room';
            } else {
                return 'equipment';
            }
        }

        clearForm() {
            // Clear selected items and rooms
            this.selectedItems = [];
            this.selectedRooms = [];
            this.selectedSet = null;
            this.selectedRoom = null;

            // Update UI
            this.updateSelectedItemsUI();
            this.updateActionButtons();

            // Clear form fields
            document.querySelector('[name="project_name"]').value = '';
            document.querySelector('[name="purpose"]').value = '';
            document.querySelector('[name="start_date"]').value = '';
            document.querySelector('[name="end_date"]').value = '';

            // Remove selection from inventory cards
            document.querySelectorAll('.item-card.selected').forEach(card => {
                card.classList.remove('selected');
            });

            // Show hint
            this.showSelectDatesHint();

        }

        formatLocationPath(path) {
            if (!path) return '';

            const parts = path.split(' -> ');
            if (parts.length === 1) return parts[0];

            return parts.map((part, index) => {
                const indent = '&nbsp;'.repeat(index * 2);
                const separator = index < parts.length - 1 ? ' → ' : '';
                return `${indent}${part}${separator}`;
            }).join('');
        }

        debounce(fn, wait) {
            let t;
            return (...a) => {
                clearTimeout(t);
                t = setTimeout(() => fn(...a), wait);
            };
        }

        async finalRoomAvailabilityCheck(roomId, startDate, startTime, endDate, endTime, onSuccess) {
            try {
                const url = `${URLS.checkRoomAvailability}?room_id=${roomId}&start_date=${startDate}&start_time=${startTime}&end_date=${endDate}&end_time=${endTime}`;

                const resp = await fetch(url);
                const data = await resp.json();

                if (data.success) {
                    if (data.is_available) {
                        // Room is available, proceed with adding
                        onSuccess();
                    } else {
                        // Room is not available, show conflicts
                        let conflictMessage = gettext('Room is not available for the selected period.\n\nConflicts:\n');
                        if (data.conflicts && data.conflicts.length > 0) {
                            conflictMessage += data.conflicts.join('\n');
                        } else {
                            conflictMessage += gettext('Unknown conflict');
                        }
                        alert(conflictMessage);
                    }
                } else {
                    alert(interpolate(gettext('Error checking room availability: %(message)s'), {
                        message: data.error || gettext('Unknown error')
                    }, true));
                }
            } catch (error) {
                console.error('Error checking room availability:', error);
                alert(gettext('Error checking room availability. Please try again.'));
            }
        }
    }

    // Initialize rental dashboard
    new RentalDashboard();
});
