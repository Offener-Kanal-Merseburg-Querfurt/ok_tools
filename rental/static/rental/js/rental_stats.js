// Rental Statistics Page JavaScript

// Django i18n support
const gettext = window.gettext || function(str) { return str; };
const ngettext = window.ngettext || function(singular, plural, count) { return count === 1 ? singular : plural; };

document.addEventListener('DOMContentLoaded', function() {
    let rentalStats; // Global variable for access from onclick handlers

    class RentalStats {
        constructor() {
            console.log('🚀 RentalStats constructor started');
            this.currentPage = 1;
            this.currentAction = null;

            console.log('🔗 Binding events...');
            this.bindEvents();

            console.log('📊 Loading rental data...');
            this.loadRentalsData();

            console.log('✅ RentalStats fully initialized');
        }

        bindEvents() {
            // Tab change events
            document.getElementById('inventory-tab').addEventListener('click', () => {
                this.loadInventoryData();
            });

            document.getElementById('sets-tab').addEventListener('click', () => {
                this.loadSetsData();
            });

            // Filter events
            document.getElementById('statusFilter').addEventListener('change', () => {
                this.currentPage = 1;
                this.loadRentalsData();
            });

            document.getElementById('typeFilter').addEventListener('change', () => {
                this.currentPage = 1;
                this.loadRentalsData();
            });

            document.getElementById('userFilter').addEventListener('input',
                this.debounce(() => {
                    this.currentPage = 1;
                    this.loadRentalsData();
                }, 500)
            );

            document.getElementById('ownerFilter').addEventListener('change', () => {
                this.loadInventoryData();
            });

            document.getElementById('inventoryStatusFilter').addEventListener('change', () => {
                this.loadInventoryData();
            });

            // Equipment Sets events
            document.getElementById('createSetBtn').addEventListener('click', () => {
                this.showCreateSetModal();
            });

            document.getElementById('saveSetBtn').addEventListener('click', () => {
                this.saveEquipmentSet();
            });

            document.getElementById('itemSearch').addEventListener('input',
                this.debounce(() => {
                    this.searchInventoryItems();
                }, 300)
            );

            // Confirmation modal
            document.getElementById('confirmResetBtn').addEventListener('click', () => {
                this.executeReset();
            });

            // Room expiration
            const expireRoomsBtn = document.getElementById('expireRoomsBtn');
            if (expireRoomsBtn) {
                console.log('✅ Button expireRoomsBtn found, adding handler');
                expireRoomsBtn.addEventListener('click', () => {
                    console.log('🖱️ Button expireRoomsBtn clicked');
                    this.expireRoomRentals();
                });
            } else {
                console.error('❌ Button expireRoomsBtn not found!');
            }
        }

        debounce(func, wait) {
            let timeout;
            return function executedFunction(...args) {
                const later = () => {
                    clearTimeout(timeout);
                    func(...args);
                };
                clearTimeout(timeout);
                timeout = setTimeout(later, wait);
            };
        }

        async loadRentalsData() {
            const tbody = document.getElementById('rentalsTableBody');
            const info = document.getElementById('rentalsInfo');
            const pagination = document.getElementById('rentalsPagination');

            try {
                // Show loading
                tbody.innerHTML = '<tr><td colspan="7" class="text-center"><div class="spinner-border spinner-border-sm me-2"></div>' + gettext('Loading data...') + '</td></tr>';

                const params = new URLSearchParams({
                    page: this.currentPage,
                    status: document.getElementById('statusFilter').value,
                    type: document.getElementById('typeFilter').value,
                    user: document.getElementById('userFilter').value
                });

                const resp = await fetch(`${URLS.getAllRentals}?${params}`);
                const data = await resp.json();

                if (data.error) {
                    throw new Error(data.error);
                }

                this.renderRentalsTable(data.rentals);
                this.updateRentalsInfo(data);
                this.updateRentalsPagination(data);

            } catch (error) {
                console.error('Error loading rentals:', error);
                tbody.innerHTML = `<tr><td colspan="8" class="text-center text-danger">${gettext('Error loading')}: ${error.message}</td></tr>`;
                info.textContent = gettext('Error loading');
            }
        }

        renderRentalsTable(rentals) {
            const tbody = document.getElementById('rentalsTableBody');

            if (rentals.length === 0) {
                tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted">' + gettext('No rentals found') + '</td></tr>';
                return;
            }

            let html = '';
            rentals.forEach(rental => {
                const statusClass = this.getStatusClass(rental.status);
                const itemsSummary = rental.items_summary.map(item =>
                    `${item.description} (${item.quantity}x)`
                ).join(', ');
                const moreItems = rental.items_count > 3 ? ` ${gettext('and')} ${rental.items_count - 3} ${gettext('more')}...` : '';

                // Generate rooms summary
                const roomsSummary = rental.rooms_summary ? rental.rooms_summary.map(room =>
                    `${room.name} (${room.people_count} ${gettext('people')})`
                ).join(', ') : '';
                const moreRooms = rental.rooms_count > 3 ? ` ${gettext('and')} ${rental.rooms_count - 3} ${gettext('more')}...` : '';

                // Generate return status information
                const returnInfo = this.getReturnStatusInfo(rental);

                // Create combined summary for items and rooms
                let combinedSummary = '';
                if (rental.items_count > 0 && rental.rooms_count > 0) {
                    combinedSummary = `
                        <span class="badge bg-secondary me-1">${rental.items_count} ${gettext('items')}</span>
                        <span class="badge bg-success me-1">${rental.rooms_count} ${gettext('rooms')}</span>
                        <br><small class="text-muted">
                            ${itemsSummary ? `${gettext('Items')}: ${itemsSummary}${moreItems}` : ''}
                            ${roomsSummary ? `${itemsSummary ? ' | ' : ''}${gettext('Rooms')}: ${roomsSummary}${moreRooms}` : ''}
                        </small>`;
                } else if (rental.items_count > 0) {
                    combinedSummary = `
                        <span class="badge bg-secondary">${rental.items_count} ${gettext('items')}</span>
                        ${itemsSummary ? `<br><small class="text-muted">${itemsSummary}${moreItems}</small>` : ''}`;
                } else if (rental.rooms_count > 0) {
                    combinedSummary = `
                        <span class="badge bg-success">${rental.rooms_count} ${gettext('rooms')}</span>
                        ${roomsSummary ? `<br><small class="text-muted">${roomsSummary}${moreRooms}</small>` : ''}`;
                }

                html += `
                    <tr>
                        <td class="col-id"><a href="/rental/rental/${rental.id}/" class="text-decoration-none fw-bold">${rental.id}</a></td>
                        <td class="col-project">
                            <div class="project-name">${rental.project_name}</div>
                            <div class="project-meta">${gettext('Created by')}: ${rental.created_by_name}</div>
                            ${rental.rental_type ? `<div class="project-meta text-info">${gettext('Type')}: ${this.getRentalTypeLabel(rental.rental_type)}</div>` : ''}
                        </td>
                        <td class="col-user">
                            <div class="user-name">${rental.user_name}</div>
                            <div class="user-email">${rental.user_email}</div>
                        </td>
                        <td class="col-status text-center">
                            <span class="status-badge ${statusClass}">${this.getStatusLabelForRental(rental)}</span>
                        </td>
                        <td class="col-created">
                            <div class="date-info">${this.formatDisplayDate(rental.created_at)}</div>
                        </td>
                        <td class="col-period">
                            <div class="date-info">${this.formatDisplayDate(rental.requested_start_date)}</div>
                            <div class="time-info">${gettext('until')} ${this.formatDisplayDate(rental.requested_end_date)}</div>
                        </td>
                        <td class="col-return">
                            <div class="return-status">${returnInfo}</div>
                        </td>
                        <td class="col-items">
                            ${this.renderItemsSummary(rental)}
                        </td>
                    </tr>`;
            });

            tbody.innerHTML = html;
        }

        updateRentalsInfo(data) {
            const info = document.getElementById('rentalsInfo');
            info.textContent = `${data.total_count} ${gettext('rentals total')}`;
        }

        updateRentalsPagination(data) {
            const pagination = document.getElementById('rentalsPagination');

            if (data.total_pages <= 1) {
                pagination.innerHTML = '';
                return;
            }

            let html = '';

            // Previous button
            if (data.has_previous) {
                html += `<li class="page-item"><a class="page-link" href="#" onclick="rentalStats.changePage(${data.current_page - 1})">${gettext('Previous')}</a></li>`;
            }

            // Page numbers
            for (let i = Math.max(1, data.current_page - 2); i <= Math.min(data.total_pages, data.current_page + 2); i++) {
                const active = i === data.current_page ? 'active' : '';
                html += `<li class="page-item ${active}"><a class="page-link" href="#" onclick="rentalStats.changePage(${i})">${i}</a></li>`;
            }

            // Next button
            if (data.has_next) {
                html += `<li class="page-link" href="#" onclick="rentalStats.changePage(${data.current_page + 1})">${gettext('Next')}</a></li>`;
            }

            pagination.innerHTML = html;
        }

        changePage(page) {
            this.currentPage = page;
            this.loadRentalsData();
        }

        async loadInventoryData() {
            const tbody = document.getElementById('inventoryTableBody');
            const info = document.getElementById('inventoryInfo');

            try {
                // Show loading
                tbody.innerHTML = '<tr><td colspan="8" class="text-center"><div class="spinner-border spinner-border-sm me-2"></div>' + gettext('Loading data...') + '</td></tr>';

                const params = new URLSearchParams({
                    owner: document.getElementById('ownerFilter').value,
                    status: document.getElementById('inventoryStatusFilter').value
                });

                const resp = await fetch(`${URLS.getInventoryStatus}?${params}`);
                const data = await resp.json();

                if (data.error) {
                    throw new Error(data.error);
                }

                this.renderInventoryTable(data.items);
                info.textContent = `${data.total_count} ${gettext('items found')}`;

            } catch (error) {
                console.error('Error loading inventory:', error);
                tbody.innerHTML = `<tr><td colspan="8" class="text-center text-danger">${gettext('Error loading')}: ${error.message}</td></tr>`;
                info.textContent = gettext('Error loading');
            }
        }

        renderInventoryTable(items) {
            const tbody = document.getElementById('inventoryTableBody');

            if (items.length === 0) {
                tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted">' + gettext('No items found') + '</td></tr>';
                return;
            }

            let html = '';
            items.forEach(item => {
                const statusClass = this.getInventoryStatusClass(item.reserved_quantity, item.rented_quantity);
                const statusText = this.getInventoryStatusText(item.reserved_quantity, item.rented_quantity);

                html += `
                    <tr>
                        <td><code>${item.inventory_number}</code></td>
                        <td>${item.description}</td>
                        <td>${item.owner}</td>
                        <td>${item.location}</td>
                        <td>${item.category}</td>
                        <td>${item.reserved_quantity}</td>
                        <td>${item.rented_quantity}</td>
                        <td><span class="badge ${statusClass}">${statusText}</span></td>
                        <td>
                            <button class="btn btn-sm btn-outline-primary" onclick="window.rentalStats.showInventorySchedule('${item.inventory_number}', '${item.description.replace(/'/g, "\\'")}')">
                                <i class="fas fa-calendar"></i>
                            </button>
                        </td>
                    </tr>`;
            });

            tbody.innerHTML = html;
        }

        async showInventorySchedule(invNumber, description) {
            document.getElementById('invScheduleTitle').textContent = `[${invNumber}] ${description}`;
            const modal = new bootstrap.Modal(document.getElementById('inventoryScheduleModal'));
            modal.show();

            // default dates = current week
            const startInput = document.getElementById('invCalStart');
            const endInput = document.getElementById('invCalEnd');
            const today = new Date();
            const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
            const end = new Date(start); end.setDate(end.getDate() + 6);
            startInput.value = start.toISOString().split('T')[0];
            endInput.value = end.toISOString().split('T')[0];

            const load = async () => {
                const base = (typeof URLS !== 'undefined' && URLS.inventorySchedule) ? URLS.inventorySchedule : '/rental/api/inventory-schedule/';
                const url = `${base}?inv=${encodeURIComponent(invNumber)}&start_date=${startInput.value}&end_date=${endInput.value}`;
                console.log('Loading inventory schedule from:', url);
                const container = document.getElementById('invCalendarContainer');
                container.innerHTML = '<div class="text-center p-5"><div class="spinner-border" role="status"></div><p class="mt-2">' + gettext('Loading calendar...') + '</p></div>';

                try {
                    // First, test if the server is responding at all
                    console.log('🧪 Testing server response...');
                    const testResp = await fetch('/rental/api/get-all-inventory-status/', { signal: AbortSignal.timeout(5000) });
                    console.log('✅ Server test successful:', testResp.status);

                    console.log('🔄 Fetching inventory schedule from:', url);

                    // Add timeout to prevent hanging
                    const controller = new AbortController();
                    const timeoutId = setTimeout(() => {
                        console.log('⏰ Request timeout, aborting...');
                        controller.abort();
                    }, 10000); // 10 second timeout

                    const resp = await fetch(url, {
                        signal: controller.signal
                    });

                    clearTimeout(timeoutId);
                    console.log('📡 Response received:', resp.status, resp.statusText);

                    if (!resp.ok) {
                        throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
                    }

                    const text = await resp.text();
                    console.log('📄 Response text length:', text.length);
                    console.log('📄 Response text preview:', text.substring(0, 200));

                    if (!text.trim()) {
                        throw new Error('Empty response from server');
                    }

                    let data;
                    try {
                        data = JSON.parse(text);
                        console.log('✅ Parsed data successfully:', data);
                    } catch(e){
                        console.error('❌ JSON parse error:', e);
                        console.error('❌ Raw text that failed to parse:', text);
                        throw new Error('Invalid server response - not valid JSON');
                    }

                    if (!data.success) {
                        console.error('❌ API returned error:', data);
                        throw new Error(data.error || 'API request failed');
                    }

                    console.log('🎯 Rendering calendar with schedule:', data.schedule);
                    this.renderInventoryCalendar(data.schedule);

                } catch (e) {
                    console.error('❌ Error in loadInventorySchedule:', e);

                    let errorMessage = e.message;
                    if (e.name === 'AbortError') {
                        errorMessage = 'Request timeout - server is not responding';
                    } else if (e.name === 'TypeError' && e.message.includes('fetch')) {
                        errorMessage = 'Network error - check server connection';
                    }

                    container.innerHTML = `<div class="alert alert-danger">${gettext('Error loading')}: ${errorMessage}</div>`;
                }
            };

            startInput.onchange = load;
            endInput.onchange = load;
            await load();
        }

                getStatusColor(status) {
            const colors = {
                'reserved': 'warning',
                'issued': 'primary',
                'returned': 'success',
                'cancelled': 'danger'
            };
            return colors[status] || 'secondary';
        }

        getStatusText(status) {
            const texts = {
                'reserved': gettext('Reserved'),
                'issued': gettext('Issued'),
                'returned': gettext('Returned'),
                'cancelled': gettext('Cancelled')
            };
            return texts[status] || status;
        }

        renderInventoryCalendar(days) {
            const container = document.getElementById('invCalendarContainer');
            if (!days || days.length === 0) {
                container.innerHTML = '<div class="text-center text-muted p-3">' + gettext('No schedule available') + '</div>';
                return;
            }

            const numDays = days.length;
            let html = `<div class="calendar-grid" style="grid-template-columns: 80px repeat(${numDays}, 1fr);">`;

            // Calendar header
            html += '<div class="calendar-header">';
            html += '<div class="calendar-cell header">' + gettext('Time') + '</div>';

            // Days of the week
            days.forEach(day => {
                const dayClass = day.is_today ? 'today' : day.is_weekend ? 'weekend' : '';
                html += `<div class="calendar-cell header ${dayClass}">`;
                html += `<div class="day-name">${day.day_short}</div>`;
                html += `<div class="day-number">${day.day_number}</div>`;
                html += '</div>';
            });
            html += '</div>';

            // Time slots (24 hours)
            for (let i = 0; i < 24; i++) {
                const hour = i;
                const time = `${hour.toString().padStart(2, '0')}:00`;

                html += '<div class="calendar-row">';
                html += `<div class="calendar-cell time-slot">${time}</div>`;

                // Slots for each day
                days.forEach(day => {
                    if (day.slots && day.slots[i]) {
                        const slot = day.slots[i];
                        const slotClass = slot.status === 'occupied' ? 'occupied' : 'available';
                        const title = slot.info ? `${slot.info.user_name} (${slot.info.start_time}-${slot.info.end_time})` : '';

                        html += `<div class="calendar-cell ${slotClass}" title="${title}">`;
                        if (slot.status === 'occupied' && slot.info) {
                            html += `<div class="slot-info">`;
                            html += `<small class="d-block">${slot.info.user_name}</small>`;
                            html += `<small class="d-block text-muted">${slot.info.project || ''}</small>`;
                            html += `<small class="badge bg-${this.getStatusColor(slot.info.status)} text-white">${this.getStatusText(slot.info.status)}</small>`;
                            html += `</div>`;
                        }
                        html += '</div>';
                    } else {
                        html += '<div class="calendar-cell available"></div>';
                    }
                });
                html += '</div>';
            }

            html += '</div>';
            container.innerHTML = html;
        }

        renderItemsSummary(rental) {
            const itemsSummary = rental.items_summary ? rental.items_summary.map(item =>
                `${item.description} (${item.quantity}x)`
            ).join(', ') : '';
            const moreItems = rental.items_count > 3 ? ` ${gettext('and')} ${rental.items_count - 3} ${gettext('more')}...` : '';

            // Generate rooms summary
            const roomsSummary = rental.rooms_summary ? rental.rooms_summary.map(room =>
                `${room.name} (${room.people_count} ${gettext('people')})`
            ).join(', ') : '';
            const moreRooms = rental.rooms_count > 3 ? ` ${gettext('and')} ${rental.rooms_count - 3} ${gettext('more')}...` : '';

            // Create combined summary for items and rooms
            let combinedSummary = '';
            if (rental.items_count > 0 && rental.rooms_count > 0) {
                combinedSummary = `
                    <span class="items-count">${rental.items_count} ${gettext('items')}</span>
                    <span class="items-count">${rental.rooms_count} ${gettext('rooms')}</span>
                    <div class="items-details">
                        ${itemsSummary ? `${gettext('Items')}: ${itemsSummary}${moreItems}` : ''}
                        ${roomsSummary ? `${itemsSummary ? ' | ' : ''}${gettext('Rooms')}: ${roomsSummary}${moreRooms}` : ''}
                    </div>`;
            } else if (rental.items_count > 0) {
                combinedSummary = `
                    <span class="items-count">${rental.items_count} ${gettext('items')}</span>
                    ${itemsSummary ? `<div class="items-details">${itemsSummary}${moreItems}</div>` : ''}`;
            } else if (rental.rooms_count > 0) {
                combinedSummary = `
                    <span class="items-count">${rental.rooms_count} ${gettext('rooms')}</span>
                    ${roomsSummary ? `<div class="items-details">${roomsSummary}${moreRooms}</div>` : ''}`;
            }

            return combinedSummary;
        }

        getStatusClass(status) {
            switch (status) {
                case 'reserved': return 'status-reserved';
                case 'issued': return 'status-issued';
                case 'returned': return 'status-returned';
                case 'cancelled': return 'status-cancelled';
                case 'draft': return 'status-draft';
                default: return 'status-draft';
            }
        }

        getStatusLabel(status) {
            switch (status) {
                case 'reserved': return gettext('Reserved');
                case 'issued': return gettext('Issued');
                case 'returned': return gettext('Returned');
                case 'cancelled': return gettext('Cancelled');
                default: return status;
            }
        }

        getStatusLabelForRental(rental) {
            // For rooms, show special status if they have room_rentals
            if (rental.room_rentals && rental.room_rentals.length > 0) {
                if (rental.status === 'reserved') {
                    return gettext('Reserved (Auto-return)');
                } else if (rental.status === 'returned') {
                    return gettext('Returned (Auto)');
                }
            }
            return this.getStatusLabel(rental.status);
        }

        formatDisplayDate(dateString) {
            if (!dateString) return '';

            try {
                const date = new Date(dateString);
                if (isNaN(date.getTime())) return dateString; // Return original if invalid

                return date.toLocaleDateString('de-DE', {
                    day: '2-digit',
                    month: '2-digit',
                    year: 'numeric'
                });
            } catch (error) {
                console.warn('Error formatting date:', dateString, error);
                return dateString; // Return original if error
            }
        }

        getReturnStatusInfo(rental) {
            const now = new Date();
            const plannedEndDate = new Date(rental.requested_end_date);

            if (rental.status === 'returned' && rental.actual_end_date) {
                const actualReturnDate = new Date(rental.actual_end_date);
                const isOverdue = actualReturnDate > plannedEndDate;

                const formatDate = (date) => {
                    return date.toLocaleDateString('de-DE', {
                        day: '2-digit',
                        month: '2-digit',
                        year: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit'
                    });
                };

                if (isOverdue) {
                    const daysDiff = Math.ceil((actualReturnDate - plannedEndDate) / (1000 * 60 * 60 * 24));
                    return `
                        <div class="return-overdue rounded px-2 py-1">
                            <small class="d-block"><i class="fas fa-calendar-check me-1"></i><strong>${gettext('Returned')}:</strong></small>
                            <small>${formatDate(actualReturnDate)}</small>
                            <br><small class="fw-bold"><i class="fas fa-exclamation-triangle me-1"></i>${daysDiff} ${daysDiff > 1 ? gettext('days') : gettext('day')} ${gettext('overdue')}</small>
                        </div>
                    `;
                } else {
                    return `
                        <div class="return-ontime rounded px-2 py-1">
                            <small class="d-block"><i class="fas fa-calendar-check me-1"></i><strong>${gettext('Returned')}:</strong></small>
                            <small>${formatDate(actualReturnDate)}</small>
                            <br><small class="fw-bold"><i class="fas fa-check me-1"></i>${gettext('On time')}</small>
                        </div>
                    `;
                }
            } else if (rental.status === 'issued') {
                const isOverdue = now > plannedEndDate;

                if (isOverdue) {
                    const daysDiff = Math.ceil((now - plannedEndDate) / (1000 * 60 * 60 * 24));
                    return `
                        <div class="return-pending rounded px-2 py-1">
                            <small class="d-block"><i class="fas fa-clock me-1"></i><strong>${gettext('Overdue')}:</strong></small>
                            <small class="fw-bold text-warning">${daysDiff} ${daysDiff > 1 ? gettext('days') : gettext('day')}</small>
                        </div>
                    `;
                } else {
                    return `
                        <div class="return-active rounded px-2 py-1">
                            <small class="d-block"><i class="fas fa-hourglass-half me-1"></i><strong>${gettext('Pending')}</strong></small>
                            <small>${gettext('Until')} ${plannedEndDate.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' })}</small>
                        </div>
                    `;
                }
            } else if (rental.status === 'reserved') {
                return `
                    <div class="return-active rounded px-2 py-1">
                        <small class="d-block"><i class="fas fa-calendar-alt me-1"></i><strong>${gettext('Reserved')}</strong></small>
                        <small>${gettext('Until')} ${plannedEndDate.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' })}</small>
                    </div>
                `;
            } else if (rental.status === 'cancelled') {
                return `
                    <div class="rounded px-2 py-1 bg-light text-muted">
                        <small class="d-block"><i class="fas fa-times me-1"></i><strong>${gettext('Cancelled')}</strong></small>
                    </div>
                `;
            }

            return '<small class="text-muted">-</small>';
        }

        getInventoryStatusClass(reserved, rented) {
            if (rented > 0) return 'inventory-rented';
            if (reserved > 0) return 'inventory-reserved';
            return 'inventory-available';
        }

        getInventoryStatusText(reserved, rented) {
            if (rented > 0) return gettext('Rented');
            if (reserved > 0) return gettext('Reserved');
            return gettext('Available');
        }

        getRentalTypeLabel(rentalType) {
            switch (rentalType) {
                case 'equipment': return gettext('Equipment');
                case 'room': return gettext('Rooms');
                case 'mixed': return gettext('Mixed');
                default: return rentalType;
            }
        }

        async executeReset() {
            const confirmationCode = document.getElementById('confirmationCode').value;

            if (confirmationCode !== 'RESET_ALL_DATA') {
                alert(gettext('Wrong confirmation code'));
                return;
            }

            try {
                const resp = await fetch(URLS.resetSystem, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': CSRF_TOKEN,
                    },
                    body: JSON.stringify({
                        action: this.currentAction,
                        confirm_code: confirmationCode
                    })
                });

                const data = await resp.json();

                if (data.success) {
                    alert(data.message);

                    // Close modal and refresh page
                    bootstrap.Modal.getInstance(document.getElementById('confirmationModal')).hide();
                    location.reload();
                } else {
                    alert(data.error || gettext('Error executing action'));
                }
            } catch (error) {
                console.error('Reset error:', error);
                alert(gettext('Network error'));
            }
        }

    // Equipment Sets Methods
    async loadSetsData() {
        const tbody = document.getElementById('setsTableBody');

        try {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center"><div class="spinner-border spinner-border-sm me-2"></div>' + gettext('Loading sets...') + '</td></tr>';

            const resp = await fetch(URLS.getAllSets);
            const data = await resp.json();

            if (data.error) {
                throw new Error(data.error);
            }

            this.renderSetsTable(data.sets);

                    } catch (error) {
                console.error('Error loading sets:', error);
                tbody.innerHTML = `<tr><td colspan="6" class="text-center text-danger">${gettext('Error loading')}: ${error.message}</td></tr>`;
            }
    }

    renderSetsTable(sets) {
        const tbody = document.getElementById('setsTableBody');

                    if (sets.length === 0) {
                tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">' + gettext('No equipment sets found') + '</td></tr>';
                return;
            }

        let html = '';
        sets.forEach(set => {
            const statusBadge = set.is_active ?
                '<span class="badge bg-success">' + gettext('Active') + '</span>' :
                '<span class="badge bg-secondary">' + gettext('Inactive') + '</span>';

            html += `
                <tr>
                    <td><strong>${set.name}</strong></td>
                    <td>${set.description || '-'}</td>
                    <td><span class="badge bg-info">${set.items_count}</span></td>
                    <td>${statusBadge}</td>
                    <td>${set.created_at}<br><small class="text-muted">${set.created_by}</small></td>
                    <td>
                        <button class="btn btn-sm btn-outline-info me-1" onclick="rentalStats.showSetDetails(${set.id})">
                            <i class="fas fa-eye"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-danger" onclick="rentalStats.deleteSet(${set.id}, '${set.name}')">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                </tr>`;
        });

        tbody.innerHTML = html;
        this.allSets = sets; // Store for later use
    }

    showSetDetails(setId) {
        const set = this.allSets.find(s => s.id === setId);
        if (!set) return;

        const detailsPanel = document.getElementById('setDetailsPanel');

                    let html = `
                <h6>${set.name}</h6>
                <p class="text-muted">${set.description || gettext('No description')}</p>
                <p><strong>${gettext('Status')}:</strong> ${set.is_active ? gettext('Active') : gettext('Inactive')}</p>
                <p><strong>${gettext('Created')}:</strong> ${set.created_at}</p>
                <p><strong>${gettext('Created by')}:</strong> ${set.created_by}</p>

                <h6>${gettext('Items')} (${set.items.length}):</h6>
                <div class="list-group">`;

        set.items.forEach(item => {
            html += `
                <div class="list-group-item list-group-item-action p-2">
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            <strong>${item.inventory_item.description}</strong><br>
                            <small class="text-muted">[${item.inventory_item.inventory_number}]</small>
                        </div>
                        <span class="badge bg-secondary">${item.quantity}x</span>
                    </div>
                </div>`;
        });

        html += '</div>';
        detailsPanel.innerHTML = html;
    }

    showCreateSetModal() {
        document.getElementById('setModalLabel').innerHTML = '<i class="fas fa-layer-group me-2"></i>' + gettext('Create Equipment Set');
        document.getElementById('setName').value = '';
        document.getElementById('setDescription').value = '';
        document.getElementById('setIsActive').checked = true;

        // Clear items list
        this.currentSetItems = [];
        this.renderSetItemsList();

        // Clear search
        document.getElementById('itemSearch').value = '';
        document.getElementById('searchResults').innerHTML = '<small class="text-muted">' + gettext('Enter a search term...') + '</small>';

        const modal = new bootstrap.Modal(document.getElementById('setModal'));
        modal.show();
    }

    async searchInventoryItems() {
        const query = document.getElementById('itemSearch').value;
        const resultsDiv = document.getElementById('searchResults');

        if (query.length < 2) {
            resultsDiv.innerHTML = '<small class="text-muted">' + gettext('Enter at least 2 characters...') + '</small>';
            return;
        }

        try {
            const resp = await fetch(`${URLS.searchInventory}?q=${encodeURIComponent(query)}`);
            const data = await resp.json();

            if (data.error) {
                throw new Error(data.error);
            }

            this.renderSearchResults(data.items);

        } catch (error) {
            console.error('Search error:', error);
            resultsDiv.innerHTML = '<small class="text-danger">' + gettext('Search error') + '</small>';
        }
    }

    renderSearchResults(items) {
        const resultsDiv = document.getElementById('searchResults');

        if (items.length === 0) {
            resultsDiv.innerHTML = '<small class="text-muted">' + gettext('No items found') + '</small>';
            return;
        }

        let html = '';
        items.forEach(item => {
            // Escape quotes for onclick
            const desc = item.description.replace(/'/g, "\\'");
            const invNum = item.inventory_number.replace(/'/g, "\\'");

            html += `
                <div class="border-bottom p-2" style="cursor: pointer;" onclick="rentalStats.addItemToSet(${item.id}, '${desc}', '${invNum}')">
                    <strong>${item.description}</strong><br>
                    <small class="text-muted">[${item.inventory_number}] • ${item.category} • ${item.owner}</small>
                </div>`;
        });

        resultsDiv.innerHTML = html;
    }

    addItemToSet(itemId, description, inventoryNumber) {
        // Check if item already exists
        if (this.currentSetItems && this.currentSetItems.some(item => item.inventory_item_id === itemId)) {
            alert(gettext('This item is already in the set'));
            return;
        }

        if (!this.currentSetItems) {
            this.currentSetItems = [];
        }

        this.currentSetItems.push({
            inventory_item_id: itemId,
            description: description,
            inventory_number: inventoryNumber,
            quantity: 1
        });

        this.renderSetItemsList();
    }

    renderSetItemsList() {
        const tbody = document.getElementById('setItemsList');

        if (!this.currentSetItems || this.currentSetItems.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" class="text-center text-muted">' + gettext('No items added') + '</td></tr>';
            return;
        }

        let html = '';
        this.currentSetItems.forEach((item, index) => {
            html += `
                <tr>
                    <td>
                        <strong>${item.description}</strong><br>
                        <small class="text-muted">[${item.inventory_number}]</small>
                    </td>
                    <td>
                        <input type="number" class="form-control form-control-sm" value="${item.quantity}" min="1"
                               onchange="rentalStats.updateItemQuantity(${index}, this.value)">
                    </td>
                    <td>
                        <button class="btn btn-sm btn-outline-danger" onclick="rentalStats.removeItemFromSet(${index})">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                </tr>`;
        });

        tbody.innerHTML = html;
    }

    updateItemQuantity(index, quantity) {
        this.currentSetItems[index].quantity = parseInt(quantity) || 1;
    }

    removeItemFromSet(index) {
        this.currentSetItems.splice(index, 1);
        this.renderSetItemsList();
    }

    async saveEquipmentSet() {
        const name = document.getElementById('setName').value.trim();
        const description = document.getElementById('setDescription').value.trim();
        const isActive = document.getElementById('setIsActive').checked;

        if (!name) {
            alert(gettext('Name is required'));
            return;
        }

        if (!this.currentSetItems || this.currentSetItems.length === 0) {
            alert(gettext('At least one item must be added'));
            return;
        }

        try {
            const resp = await fetch(URLS.createSet, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': CSRF_TOKEN,
                },
                body: JSON.stringify({
                    name: name,
                    description: description,
                    is_active: isActive,
                    items: this.currentSetItems
                })
            });

            const data = await resp.json();

            if (data.success) {
                alert(data.message);
                bootstrap.Modal.getInstance(document.getElementById('setModal')).hide();
                this.loadSetsData(); // Refresh table
                            } else {
                    alert(data.error || gettext('Error saving'));
                }

        } catch (error) {
            console.error('Save error:', error);
            alert(gettext('Network error'));
        }
    }

    async deleteSet(setId, setName) {
        if (!confirm(gettext('Are you sure you want to delete the set') + ` "${setName}"?`)) {
            return;
        }

        try {
            const resp = await fetch(URLS.deleteSet.replace('{setId}', setId), {
                method: 'DELETE',
                headers: {
                    'X-CSRFToken': CSRF_TOKEN,
                }
            });

            const data = await resp.json();

            if (data.success) {
                alert(data.message);
                this.loadSetsData(); // Refresh table
                // Clear details panel
                document.getElementById('setDetailsPanel').innerHTML = '<p class="text-muted text-center">' + gettext('Select a set to see details') + '</p>';
                            } else {
                    alert(data.error || gettext('Error deleting'));
                }

        } catch (error) {
            console.error('Delete error:', error);
            alert(gettext('Network error'));
        }
    }

    async expireRoomRentals() {
        console.log('🚀 Method expireRoomRentals called');

        if (!confirm(gettext('Are you sure you want to automatically expire all expired room reservations and rentals?'))) {
            console.log('❌ User cancelled operation');
            return;
        }

        console.log('✅ User confirmed operation');

        const button = document.getElementById('expireRoomsBtn');
        const resultDiv = document.getElementById('expireRoomsResult');

        console.log('🔍 Searching for elements:', {
            button: button,
            resultDiv: resultDiv
        });

        if (!button) {
            console.error('❌ Button expireRoomsBtn not found!');
            return;
        }

        if (!resultDiv) {
            console.error('❌ resultDiv not found!');
            return;
        }

        try {
            console.log('🔄 Starting API request...');

            // Disable button and show loading
            button.disabled = true;
            button.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>' + gettext('Processing...');
            resultDiv.style.display = 'none';

            const url = '/rental/api/expire-room-rentals/';
            console.log('🌐 Sending request to:', url);

            const resp = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': CSRF_TOKEN,
                }
            });

            console.log('📡 Response received:', resp.status, resp.statusText);

            const data = await resp.json();
            console.log('📊 Response data:', data);

            if (data.success) {
                console.log('✅ API request successful');

                // Show success result
                resultDiv.innerHTML = `
                    <div class="alert alert-success p-2 mb-0">
                        <i class="fas fa-check-circle me-1"></i>
                        <strong>${gettext('Successfully expired')}:</strong><br>
                        <small>
                            ${gettext('Total')}: ${data.statistics.total_expired}<br>
                            ${gettext('Auto-returned reservations')}: ${data.statistics.reserved_expired}<br>
                            ${gettext('Returned rentals')}: ${data.statistics.issued_expired}
                        </small>
                    </div>
                `;
                resultDiv.style.display = 'block';

                // Refresh data
                this.loadRentalsData();
                this.loadInventoryData();

                console.log('Room expiration result:', data);
            } else {
                console.error('❌ API returned error:', data.error);
                throw new Error(data.error || gettext('Unknown error'));
            }

        } catch (error) {
            console.error('❌ Error in expireRoomRentals:', error);

            // Show error result
            resultDiv.innerHTML = `
                <div class="alert alert-danger p-2 mb-0">
                    <i class="fas fa-exclamation-triangle me-1"></i>
                    <strong>${gettext('Error')}:</strong> ${error.message}
                </div>
            `;
            resultDiv.style.display = 'block';

        } finally {
            console.log('🔄 Restoring button');
            // Re-enable button
            button.disabled = false;
            button.innerHTML = '<i class="fas fa-sync-alt me-1"></i>' + gettext('Expire rooms');
        }
    }
}

    // Global functions
    window.rentalStats = new RentalStats();

    window.resetAction = function(action) {
        rentalStats.currentAction = action;

        let message = '';
        switch (action) {
            case 'reset_inventory_quantities':
                message = gettext('All inventory quantities (reserved/rented) will be set to 0. This action cannot be undone.');
                break;
            case 'cancel_active_rentals':
                message = gettext('All active rentals will be cancelled and inventory quantities reset. This action cannot be undone.');
                break;
            case 'reset_all':
                message = gettext('ALL rental data will be deleted and inventory reset. This action CANNOT be undone!');
                break;
        }

        document.getElementById('confirmationMessage').textContent = message;
        document.getElementById('confirmationCode').value = '';

        const modal = new bootstrap.Modal(document.getElementById('confirmationModal'));
        modal.show();
    };
});
