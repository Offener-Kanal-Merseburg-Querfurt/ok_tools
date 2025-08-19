// admin rental process JS

// Django i18n support
const gettext = window.gettext || function(str) { return str; };
const ngettext = window.ngettext || function(singular, plural, count) { return count === 1 ? singular : plural; };

document.addEventListener('DOMContentLoaded', function() {
  class RentalProcess {
    constructor() {
      this.selectedUser = null;
      this.selectedItems = [];
      this.selectedRooms = [];
      this.activeItems = [];
      this.filterOptions = {};
      this.selectedSet = null;
      this.selectedRoom = null;
      this.equipmentSets = [];
      this.rooms = [];

      // Bind events
      this.bindEvents();

      // Bind calendar and timeline events
      this.bindCalendarEvents();

      // Load filter options for owners, categories and locations
      this.loadFilterOptions();

      console.log('RentalProcess initialized');
    }

    bindEvents() {
      const userSearch = document.getElementById('userSearch');
      if (userSearch) {
        userSearch.addEventListener('input', this.debounce(this.searchUsers.bind(this), 300));
        console.log('User search bound');
      }

      const nextBtn = document.getElementById('nextStepBtn');
      if (nextBtn) nextBtn.addEventListener('click', () => this.nextStep());

      const reserveBtn = document.getElementById('reserveBtn');
      if (reserveBtn) reserveBtn.addEventListener('click', () => this.createRental('reserved'));

      const issueBtn = document.getElementById('issueBtn');
      if (issueBtn) issueBtn.addEventListener('click', () => this.createRental('issued'));

      // Filter event listeners
      const inventorySearch = document.getElementById('inventorySearch');
      if (inventorySearch) inventorySearch.addEventListener('input', this.debounce(() => {
        if (!this.isPeriodSelected()) return;
        this.applyFilters();
      }, 300));

      const ownerFilter = document.getElementById('ownerFilter');
      if (ownerFilter) ownerFilter.addEventListener('change', () => { if (this.isPeriodSelected()) this.applyFilters(); });

      const categoryFilter = document.getElementById('categoryFilter');
      if (categoryFilter) categoryFilter.addEventListener('change', () => { if (this.isPeriodSelected()) this.applyFilters(); });

      const locationFilter = document.getElementById('locationFilter');
      if (locationFilter) locationFilter.addEventListener('change', () => { if (this.isPeriodSelected()) this.applyFilters(); });

      // Date field event listeners - reload inventory when dates change (only when both dates selected)
      const startDateField = document.querySelector('input[name="start_date"]');
      if (startDateField) {
        startDateField.disabled = false;
        startDateField.addEventListener('change', this.debounce(() => {
          this.loadInventoryIfPeriodSelected();
        }, 300));
      }

      const endDateField = document.querySelector('input[name="end_date"]');
      if (endDateField) {
        endDateField.disabled = false;
        endDateField.addEventListener('change', this.debounce(() => {
          this.loadInventoryIfPeriodSelected();
        }, 300));
      }

      // New button event listeners
      const clearFormBtn = document.getElementById('clearFormBtn');
      if (clearFormBtn) clearFormBtn.addEventListener('click', this.clearForm.bind(this));

      const showSetsBtn = document.getElementById('showSetsBtn');
      if (showSetsBtn) showSetsBtn.addEventListener('click', this.showEquipmentSets.bind(this));

      const saveDraftBtn = document.getElementById('saveDraftBtn');
      if (saveDraftBtn) saveDraftBtn.addEventListener('click', () => this.createRental('draft'));

      const addSetToRentalBtn = document.getElementById('addSetToRentalBtn');
      if (addSetToRentalBtn) addSetToRentalBtn.addEventListener('click', this.addSetToRental.bind(this));

      // Modal buttons for return and extend
      const processReturnBtn = document.getElementById('processReturnBtn');
      if (processReturnBtn) processReturnBtn.addEventListener('click', this.processDetailedReturn.bind(this));

      const confirmExtendBtn = document.getElementById('confirmExtendBtn');
      if (confirmExtendBtn) confirmExtendBtn.addEventListener('click', this.processExtendRental.bind(this));

      // Sets filter button (same functionality as showSetsBtn)
      const setsFilterBtn = document.getElementById('setsFilterBtn');
      if (setsFilterBtn) setsFilterBtn.addEventListener('click', this.showEquipmentSets.bind(this));

      // Rooms filter button
      const roomsFilterBtn = document.getElementById('roomsFilterBtn');
      if (roomsFilterBtn) roomsFilterBtn.addEventListener('click', this.showRooms.bind(this));

      // Room modal buttons
      const addRoomToRentalBtn = document.getElementById('addRoomToRentalBtn');
      if (addRoomToRentalBtn) addRoomToRentalBtn.addEventListener('click', this.addRoomToRental.bind(this));
    }

    async searchUsers(e) {
      const q = e.target.value;
      console.log('Searching for:', q);
      if (!q || q.length < 2) return;

      try {
        const resp = await fetch(`${URLS.searchUsers}?q=${encodeURIComponent(q)}`);
        console.log('Search response status:', resp.status);
        const data = await resp.json();
        console.log('Search data:', data);
        this.renderUsers(data.users || []);
      } catch (error) {
        console.error('Search error:', error);
      }
    }

    renderUsers(users) {
      const container = document.getElementById('userResults');
      if (!container) {
        console.error('userResults container not found');
        return;
      }

      console.log('Rendering users:', users.length);
      container.innerHTML = '';

      if (users.length === 0) {
        container.innerHTML = '<div class="list-group-item"><small class="text-muted">' + gettext('No users found') + '</small></div>';
        return;
      }

      users.forEach(u => {
        const a = document.createElement('a');
        a.href = '#';
        a.className = 'list-group-item list-group-item-action user-result-card';
        a.innerHTML = `
          <div class="d-flex w-100 justify-content-between">
            <div>
              <h6 class="mb-1">${u.name || gettext('Unknown')}</h6>
              <p class="mb-1">${u.email || ''}</p>
              <small class="text-muted">${u.permissions || ''} ${gettext('authorized')}</small>
            </div>
            <div class="text-end">
              <span class="badge ${u.is_member ? 'bg-success':'bg-secondary'}">${u.member_status || gettext('User')}</span>
            </div>
          </div>`;
        a.addEventListener('click', ev => {
          ev.preventDefault();
          this.selectUser(u);
        });
        container.appendChild(a);
      });
    }

    async selectUser(u) {
      console.log('Selected user:', u);
      this.selectedUser = u;
      // Enable step 3 (Period) so dates can be selected manually
      this.enableStep(3);
      this.updateSelectedUserUI(u);
      // Do not fill dates automatically — user must select period manually
      this.clearDateFields();
      // Show hint in inventory block until period is selected
      this.showSelectDatesHint();

      try {
        await Promise.all([
          this.loadUserStats(u.id),
          this.loadActiveItems(u.id)
        ]);
        // Load inventory immediately (without dates), overlay is enabled until period is selected
        this.loadUserInventory(u.id);
        // Check if overlay is removed when period is selected
        this.loadInventoryIfPeriodSelected();
      } catch (error) {
        console.error('Error loading user data:', error);
      }
    }

    updateSelectedUserUI(u) {
      const box = document.getElementById('selectedUser');
      if (!box) return;
      box.innerHTML = `
        <div class="alert alert-success py-2 mb-0">
          <strong>${u.name || gettext('Unknown')}</strong><br>
          <small>${gettext('Status')}: ${u.member_status || gettext('User')} | ${gettext('Authorized')}: ${u.permissions || 'MSA'}</small>
        </div>`;
    }

    // Clear period fields — user must select period manually
    clearDateFields() {
      const startDate = document.querySelector('[name="start_date"]');
      if (startDate) startDate.value = '';
      const endDate = document.querySelector('[name="end_date"]');
      if (endDate) endDate.value = '';
    }

    // Check if period is selected
    isPeriodSelected() {
      const startDate = document.querySelector('[name="start_date"]')?.value;
      const endDate = document.querySelector('[name="end_date"]')?.value;
      return Boolean(startDate && endDate);
    }

    // Show hint instead of inventory list
    showSelectDatesHint() {
      const grid = document.getElementById('inventoryGrid');
      if (!grid) return;
      const wrapper = grid.parentElement; // .inventory-grid
      if (wrapper) {
        wrapper.classList.add('overlay-active');
        // Inject overlay message if not exists
        if (!wrapper.querySelector('.overlay-message')) {
          const overlay = document.createElement('div');
          overlay.className = 'overlay-message';
          overlay.innerHTML = `${gettext('Please select start and end dates to see accurate availability')}`;
          wrapper.appendChild(overlay);
        }
      }
    }

    // Load inventory only if period is selected
    loadInventoryIfPeriodSelected() {
      const grid = document.getElementById('inventoryGrid');
      const wrapper = grid ? grid.parentElement : null;
      if (this.selectedUser) {
        if (this.isPeriodSelected()) {
          if (wrapper) {
            wrapper.classList.remove('overlay-active');
            const overlay = wrapper.querySelector('.overlay-message');
            if (overlay) overlay.remove();
          }
          // Reload inventory with selected dates
          this.loadUserInventory(this.selectedUser.id);
        } else if (wrapper) {
          this.showSelectDatesHint();
        }
      }
    }

    async loadFilterOptions() {
      try {
        const resp = await fetch(URLS.filterOptions);
        const data = await resp.json();
        console.log('Filter options:', data);
        this.filterOptions = data;
        this.populateFilterDropdowns(data);
      } catch (error) {
        console.error('Error loading filter options:', error);
      }
    }

    populateFilterDropdowns(options) {
      // Populate owner filter
      const ownerSelect = document.getElementById('ownerFilter');
      if (ownerSelect && options.owners) {
        ownerSelect.innerHTML = '<option value="all">' + gettext('All owners') + '</option>';
        options.owners.forEach(owner => {
          const option = document.createElement('option');
          option.value = owner.name;
          option.textContent = owner.name;
          ownerSelect.appendChild(option);
        });
      }

      // Populate category filter (manufacturers)
      const categorySelect = document.getElementById('categoryFilter');
      if (categorySelect && options.categories) {
        categorySelect.innerHTML = '<option value="all">' + gettext('All categories') + '</option>';
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
        locationSelect.innerHTML = '<option value="all">' + gettext('All locations') + '</option>';
        options.locations.forEach(location => {
          const option = document.createElement('option');
          option.value = location.name;
          option.textContent = location.name;
          locationSelect.appendChild(option);
        });
      }
    }

    async loadUserInventory(uid) {
      try {
        const url = URLS.getUserInventory.replace('{userId}', uid);

        // Get dates from form fields
        const startDate = document.querySelector('input[name="start_date"]')?.value;
        const endDate = document.querySelector('input[name="end_date"]')?.value;

        // Add date parameters if available
        const params = new URLSearchParams();
        if (startDate) params.append('start_date', startDate);
        if (endDate) params.append('end_date', endDate);

        const finalUrl = params.toString() ? `${url}?${params.toString()}` : url;
        console.log('Loading inventory from:', finalUrl);

        const resp = await fetch(finalUrl);
        const data = await resp.json();
        console.log('Inventory data:', data);
        this.renderInventory(data.inventory || []);
        const panel = document.querySelector('.inventory-selection-panel');
        if (panel) panel.classList.remove('d-none');
      } catch (error) {
        console.error('Error loading inventory:', error);
      }
    }

    async applyFilters() {
      if (!this.selectedUser) return;

      const searchQuery = document.getElementById('inventorySearch')?.value || '';
      const ownerFilter = document.getElementById('ownerFilter')?.value || 'all';
      const categoryFilter = document.getElementById('categoryFilter')?.value || 'all';
      const locationFilter = document.getElementById('locationFilter')?.value || 'all';

      // Get dates from form fields
      const startDate = document.querySelector('input[name="start_date"]')?.value;
      const endDate = document.querySelector('input[name="end_date"]')?.value;

      const params = new URLSearchParams();
      if (searchQuery) params.append('search', searchQuery);
      if (ownerFilter !== 'all') params.append('owner', ownerFilter);
      if (locationFilter !== 'all') params.append('location', locationFilter);
      if (categoryFilter !== 'all') params.append('category', categoryFilter);
      if (startDate) params.append('start_date', startDate);
      if (endDate) params.append('end_date', endDate);

      try {
        const url = URLS.getUserInventory.replace('{userId}', this.selectedUser.id);
        const resp = await fetch(`${url}?${params.toString()}`);
        const data = await resp.json();
        console.log('Filtered inventory data:', data);
        this.renderInventory(data.inventory || []);
      } catch (error) {
        console.error('Error applying filters:', error);
      }
    }

    renderInventory(items) {
      const grid = document.getElementById('inventoryGrid');
      if (!grid) return;

      console.log('Rendering inventory:', items.length);
      grid.innerHTML = '';

      if (items.length === 0) {
        grid.innerHTML = '<div class="col-12"><div class="alert alert-info">' + gettext('No available inventory for this user') + '</div></div>';
        return;
      }

      items.forEach(it => {
        const col = document.createElement('div');
        col.className = 'col-md-6 col-lg-4 mb-3 d-flex';
        col.innerHTML = `
          <div class="item-card p-3 w-100 h-100 d-flex flex-column" data-item-id="${it.id}">
            <div class="d-flex justify-content-between align-items-start mb-2">
              <h6 class="mb-1">${it.description || it.inventory_number}</h6>
              <span class="badge bg-success status-badge">${gettext('Available')}</span>
            </div>
            <div class="d-flex align-items-center text-muted small mb-1">
              <span class="me-3"><i class="fas fa-barcode me-1"></i>${it.inventory_number}</span>
              <span><i class="fas fa-tag me-1"></i>${it.category || gettext('No category')}</span>
            </div>
            <div class="location-path mb-2">
              <i class="fas fa-map-marker-alt me-1"></i>${it.location_path || ''}
            </div>
            <div class="d-flex justify-content-between align-items-center mt-auto">
              <small class="text-muted">${gettext('Owner')}: ${it.owner || '-'}</small>
              <div class="quantity-controls">
                <div class="input-group input-group-sm">
                  <button class="btn btn-outline-secondary qty-minus" type="button">-</button>
                  <input type="number" class="form-control text-center qty-input" value="1" min="1" max="${it.available_quantity}">
                  <button class="btn btn-outline-secondary qty-plus" type="button">+</button>
                </div>
              </div>
            </div>
          </div>`;

        const card = col.querySelector('.item-card');
        card.addEventListener('click', (e) => {
          if (!e.target.closest('.quantity-controls')) {
            this.toggleItem(it);
          }
        });

        // Quantity controls
        col.querySelector('.qty-minus').addEventListener('click', (e) => {
          e.stopPropagation();
          const input = col.querySelector('.qty-input');
          if (input.value > 1) input.value = parseInt(input.value) - 1;
        });

        col.querySelector('.qty-plus').addEventListener('click', (e) => {
          e.stopPropagation();
          const input = col.querySelector('.qty-input');
          if (input.value < it.available_quantity) input.value = parseInt(input.value) + 1;
        });

        grid.appendChild(col);
      });
    }

    toggleItem(it) {
      const card = document.querySelector(`[data-item-id="${it.id}"]`);
      if (!card) return;

      const idx = this.selectedItems.findIndex(x => x.inventory_id === it.id);
      const qtyInput = card.querySelector('.qty-input');
      const quantity = parseInt(qtyInput.value) || 1;

      if (idx >= 0) {
        this.selectedItems.splice(idx, 1);
        card.classList.remove('selected');
      } else {
        // Add item with full information structure
        this.selectedItems.push({
          inventory_id: it.id,
          inventory_number: it.inventory_number,
          description: it.description,
          quantity: quantity,
          location: it.location ? it.location.full_path : (it.location_name || gettext('Location not specified')),
          category: it.category || gettext('No category')
        });
        card.classList.add('selected');
      }

      this.updateSelectedItemsUI();
      if (this.selectedItems.length > 0) {
        this.enableStep(5);
      } else {
        this.enableStep(4);
      }
    }

    updateSelectedItemsUI() {
      const box = document.getElementById('selectedItems');
      if (!box) return;

      if (this.selectedItems.length === 0) {
        box.innerHTML = '<small class="text-muted">' + gettext('No items selected') + '</small>';
        return;
      }

      let html = `
        <div class="alert alert-info py-2 mb-2">
          <small><i class="fas fa-check-circle me-1"></i>${this.selectedItems.length} ${gettext('items selected')}</small>
        </div>`;

      // Show detailed list of selected items
      html += '<div class="selected-items-list">';
      this.selectedItems.forEach((item, index) => {
        // Ensure all fields have fallback values
        const description = item.description || item.inventory_number || gettext('Unknown item');
        const inventoryNumber = item.inventory_number || gettext('No number');
        const location = item.location || gettext('Location not specified');
        const category = item.category || gettext('No category');
        const quantity = item.quantity || 1;

        html += `
          <div class="selected-item p-2 mb-1 border rounded bg-light" data-item-index="${index}">
            <div class="d-flex justify-content-between align-items-center">
              <div>
                <strong>${description}</strong>
                <br><small class="text-muted">${inventoryNumber}</small>
                <br><small class="text-muted"><i class="fas fa-map-marker-alt me-1"></i>${location}</small>
                <br><small class="text-muted"><i class="fas fa-tag me-1"></i>${category}</small>
              </div>
              <div class="text-end">
                <span class="badge bg-primary">${quantity}x</span>
                <button type="button" class="btn btn-sm btn-outline-danger ms-1 remove-item-btn" data-item-index="${index}">
                  <i class="fas fa-times"></i>
                </button>
              </div>
            </div>
          </div>`;
      });
      html += '</div>';

      box.innerHTML = html;

      // Add event listeners to remove buttons
      this.bindRemoveItemEvents();
    }

    bindRemoveItemEvents() {
      // Add event listeners to all remove buttons
      const removeButtons = document.querySelectorAll('.remove-item-btn');
      removeButtons.forEach(button => {
        button.addEventListener('click', (e) => {
          e.preventDefault();
          const index = parseInt(button.dataset.itemIndex);
          console.log('Remove button clicked for index:', index);
          this.removeSelectedItem(index);
        });
      });
    }

    bindRemoveRoomEvents() {
      // Add event listeners to all remove room buttons
      const removeRoomButtons = document.querySelectorAll('.remove-room-btn');
      removeRoomButtons.forEach(button => {
        button.addEventListener('click', (e) => {
          e.preventDefault();
          const index = parseInt(button.dataset.roomIndex);
          console.log('Remove room button clicked for index:', index);
          this.removeSelectedRoom(index);
        });
      });
    }

    removeSelectedItem(index) {
      console.log('removeSelectedItem called with index:', index);
      console.log('Current selectedItems:', this.selectedItems);

      if (index >= 0 && index < this.selectedItems.length) {
        const removedItem = this.selectedItems.splice(index, 1)[0];
        console.log(`Removed item: ${removedItem.description || removedItem.inventory_number}`);
        this.updateSelectedItemsUI();

        // If no items left, disable step 5
        if (this.selectedItems.length === 0) {
          this.disableStep(5);
        }
      } else {
        console.error('Invalid index for removeSelectedItem:', index);
      }
    }

    removeSelectedRoom(index) {
      console.log('removeSelectedRoom called with index:', index);
      console.log('Current selectedRooms:', this.selectedRooms);

      if (index >= 0 && index < this.selectedRooms.length) {
        const removedRoom = this.selectedRooms.splice(index, 1)[0];
        console.log(`Removed room: ${removedRoom.room_name}`);
        this.updateSelectedRoomsUI();

        // If no items and no rooms left, disable step 5
        if (this.selectedItems.length === 0 && this.selectedRooms.length === 0) {
          this.disableStep(5);
        }
      } else {
        console.error('Invalid index for removeSelectedRoom:', index);
      }
    }

    updateSelectedRoomsUI() {
      const box = document.getElementById('selectedItems');
      if (!box) return;

      let html = '';

      // Show selected items
      if (this.selectedItems.length > 0) {
        html += `
          <div class="alert alert-info py-2 mb-2">
            <small><i class="fas fa-check-circle me-1"></i>${this.selectedItems.length} ${gettext('items selected')}</small>
          </div>`;
      }

      // Show selected rooms
      if (this.selectedRooms.length > 0) {
        html += `
          <div class="alert alert-success py-2 mb-2">
            <small><i class="fas fa-building me-1"></i>${this.selectedRooms.length} ${gettext('rooms selected')}</small>
          </div>`;

        // Show detailed list of selected rooms
        html += '<div class="selected-rooms-list">';
        this.selectedRooms.forEach((room, index) => {
          html += `
            <div class="selected-room p-2 mb-1 border rounded bg-light" data-room-index="${index}">
              <div class="d-flex justify-content-between align-items-center">
                <div>
                  <strong>${room.room_name}</strong>
                  <br><small class="text-muted">${room.start_date} ${room.start_time} - ${room.end_date} ${room.end_time}</small>
                </div>
                <div class="text-end">
                  <button type="button" class="btn btn-sm btn-outline-danger ms-1 remove-room-btn" data-room-index="${index}">
                    <i class="fas fa-times"></i>
                  </button>
                </div>
              </div>
            </div>`;
        });
        html += '</div>';
      }

      if (html === '') {
        html = '<small class="text-muted">' + gettext('No items or rooms selected') + '</small>';
      }

      box.innerHTML = html;

      // Add event listeners to remove buttons
      this.bindRemoveItemEvents();
      this.bindRemoveRoomEvents();
    }

    async loadUserStats(uid) {
      try {
        const url = URLS.getUserStats.replace('{userId}', uid);
        console.log('Loading user stats from:', url);

        const resp = await fetch(url);

        if (!resp.ok) {
          throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
        }

        const d = await resp.json();
        console.log('User stats:', d);

        const stats = document.getElementById('userStats');
        if (!stats) return;

        stats.innerHTML = `
          <div class="row text-center">
            <div class="col-4">
              <div class="card bg-primary text-white stats-card" data-type="active" style="cursor: pointer;">
                <div class="card-body py-2">
                  <h5 class="mb-0">${d.active_rentals || 0}</h5>
                  <small>${gettext('Active')}</small>
                </div>
              </div>
            </div>
            <div class="col-4">
              <div class="card bg-success text-white stats-card" data-type="returned" style="cursor: pointer;">
                <div class="card-body py-2">
                  <h5 class="mb-0">${d.completed_rentals || 0}</h5>
                  <small>${gettext('Returned')}</small>
                </div>
              </div>
            </div>
            <div class="col-4">
              <div class="card bg-warning text-white stats-card" data-type="overdue" style="cursor: pointer;">
                <div class="card-body py-2">
                  <h5 class="mb-0">${d.overdue_rentals || 0}</h5>
                  <small>${gettext('Overdue')}</small>
                </div>
              </div>
            </div>
          </div>`;

        // Add click handlers to stats cards
        stats.querySelectorAll('.stats-card').forEach(card => {
          card.addEventListener('click', () => {
            const type = card.dataset.type;
            this.showRentalDetails(uid, type);
          });
        });
      } catch (error) {
        console.error('Error loading stats:', error);
        // Show error in interface
        const stats = document.getElementById('userStats');
        if (stats) {
          stats.innerHTML = `
            <div class="alert alert-warning">
              <i class="fas fa-exclamation-triangle me-2"></i>
              ${gettext('Error loading statistics:')} ${error.message}
            </div>`;
        }
      }
    }

    async loadActiveItems(uid) {
      try {
        const url = URLS.getUserActiveItems.replace('{userId}', uid);
        console.log('Loading active items from:', url);

        const resp = await fetch(url);

        if (!resp.ok) {
          throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
        }

        const data = await resp.json();
        console.log('Active items for return:', data.items);
        this.activeItems = data.items || [];
        this.renderReturnSection();
      } catch (error) {
        console.error('Error loading active items:', error);
        this.activeItems = [];
        this.renderReturnSection();
      }
    }

    renderReturnSection() {
      let returnSection = document.getElementById('returnSection');
      if (!returnSection) {
        const userStats = document.getElementById('userStats').parentElement;
        returnSection = document.createElement('div');
        returnSection.id = 'returnSection';
        returnSection.className = 'return-section';
        userStats.appendChild(returnSection);
      }

      if (this.activeItems.length === 0) {
        returnSection.innerHTML = '<h6>' + gettext('Return') + '</h6><p class="text-muted">' + gettext('No active rentals') + '</p>';
        return;
      }

      let html = '<h6>' + gettext('Return') + '</h6><div class="list-group">';
      this.activeItems.forEach(item => {
        html += `
          <div class="list-group-item">
            <div class="d-flex justify-content-between align-items-center">
              <div>
                <strong>${item.description || item.inventory_number}</strong><br>
                <small class="text-muted">${gettext('Outstanding:')} ${item.outstanding}</small>
              </div>
              <div class="d-flex gap-1">
                <button class="btn btn-sm btn-outline-success return-btn" data-item-id="${item.rental_item_id}" data-max="${item.outstanding}">
                  <i class="fas fa-undo me-1"></i>${gettext('Quick')}
                </button>
                <button class="btn btn-sm btn-outline-warning detailed-return-btn"
                        data-rental-id="${item.rental_request_id}"
                        data-item-id="${item.rental_item_id}"
                        title="${gettext('Detailed return with condition assessment')}">
                  <i class="fas fa-clipboard-check me-1"></i>${gettext('Detailed')}
                </button>
              </div>
            </div>
          </div>`;
      });
      html += '</div>';
      returnSection.innerHTML = html;

      // Bind return buttons
      returnSection.querySelectorAll('.return-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const el = e.currentTarget;
          const itemId = el.dataset.itemId;
          const max = parseInt(el.dataset.max, 10);
          this.returnItem(itemId, max);
        });
      });

      // Bind detailed return buttons
      returnSection.querySelectorAll('.detailed-return-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const el = e.currentTarget;
          const rentalId = el.dataset.rentalId;
          const itemId = el.dataset.itemId;
          this.showDetailedReturnModal(rentalId, itemId);
        });
      });
    }

    async returnItem(rentalItemId, maxQty) {
      if (!Number.isFinite(maxQty) || maxQty <= 0) {
        alert(gettext('No items to return selected'));
        return;
      }
      const defaultQty = String(Math.max(1, Math.min(1, maxQty)));
      const input = prompt(`${gettext('How many items to return?')} (max: ${maxQty})`, String(maxQty));
      const qty = parseInt(input, 10);
      if (!Number.isFinite(qty) || qty <= 0 || qty > maxQty) {
        alert(gettext('Invalid quantity'));
        return;
      }

      try {
        const resp = await fetch(URLS.returnItems, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
          body: JSON.stringify({ items: [{ rental_item_id: rentalItemId, quantity: parseInt(qty) }] })
        });
        const data = await resp.json();

        if (data.success) {
          alert(gettext('Return successful'));
          await this.loadActiveItems(this.selectedUser.id);
          await this.loadUserStats(this.selectedUser.id);
        } else {
          alert(data.error || gettext('Return error'));
        }
              } catch (error) {
          console.error('Return error:', error);
          alert(gettext('Network error'));
        }
      }

    async createRental(action='reserved') {
      try {
        // Validate user selection
        if (!this.selectedUser) {
          alert(gettext('Please select a user first'));
          return;
        }

        // Validate project info
        const projectName = document.querySelector('[name="project_name"]').value.trim();
        const purpose = document.querySelector('[name="purpose"]').value.trim();

        if (!projectName) {
          alert(gettext('Please enter a project name'));
          return;
        }

        // Purpose is optional

        // Validate dates
        const startDate = document.querySelector('[name="start_date"]').value;
        const endDate = document.querySelector('[name="end_date"]').value;

        if (!startDate || !endDate) {
          alert(gettext('Please select start and end dates'));
          return;
        }

        // Client-side validation for past dates
        const start = new Date(startDate);
        const end = new Date(endDate);
        const now = new Date();
        if (start < now) {
          alert(gettext(`Start time cannot be in the past. Selected time: ${start.toLocaleString('en-US')}, Current time: ${now.toLocaleString('en-US')}`));
          return;
        }
        if (end < now) {
          alert(gettext(`End time cannot be in the past. Selected time: ${end.toLocaleString('en-US')}, Current time: ${now.toLocaleString('en-US')}`));
          return;
        }
        if (end <= start) {
          alert(gettext('End date must be after start date'));
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
          user_id: this.selectedUser.id,
          project_name: projectName,
          purpose: purpose,
          start_date: startDate,
          end_date: endDate,
          action: action,
          items: this.selectedItems || [],
          rooms: this.selectedRooms || [],
          rental_type: this.getRentalType()
        };

        console.log('Creating rental:', rentalData);

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

        if (result.success) {
          alert(gettext(`Rental successfully ${action === 'issued' ? 'issued' : 'reserved'}! ID: ${result.rental_id}`));
          this.resetForm();
          if (this.selectedUser && this.selectedUser.id) {
            this.loadUserStats(this.selectedUser.id);
          }
        } else {
          alert(gettext(`Error: ${result.error}`));
        }
      } catch (error) {
        console.error('Error creating rental:', error);
        alert(gettext('Error creating rental'));
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

    resetForm() {
      console.log('Resetting form...');

      // Clear selected items, rooms, and sets
      this.selectedItems = [];
      this.selectedRooms = [];
      this.selectedSet = null;
      this.selectedSetDetails = null;
      this.selectedRoom = null;

      // Update UI for all sections
      this.updateSelectedItemsUI();
      this.updateSelectedRoomsUI();

      // Clear form fields
      document.querySelector('[name="project_name"]').value = '';
      document.querySelector('[name="purpose"]').value = '';

      // Reset date fields (require manual selection again)
      this.clearDateFields();
      this.showSelectDatesHint();
      this.enableStep(3);

      // Remove selection from inventory cards
      document.querySelectorAll('.item-card.selected').forEach(card => {
        card.classList.remove('selected');
      });

      // Clear equipment sets modal if open
      const equipmentSetsModal = bootstrap.Modal.getInstance(document.getElementById('equipmentSetsModal'));
      if (equipmentSetsModal) {
        equipmentSetsModal.hide();
      }

      // Clear rooms modal if open
      const roomsModal = bootstrap.Modal.getInstance(document.getElementById('roomsModal'));
      if (roomsModal) {
        roomsModal.hide();
      }

      // Reset to step 4 (equipment selection)
      this.enableStep(4);

      console.log('Form reset completed');
    }

    nextStep() {
      // Future implementation
    }

    enableStep(n) {
      const steps = document.querySelectorAll('.workflow-step');

      // Enable steps up to n
      for (let i = 0; i < n; i++) {
        if (steps[i]) {
          steps[i].classList.remove('completed');
          steps[i].classList.add('active');
          steps[i].querySelectorAll('input,textarea,button').forEach(el => el.disabled = false);
        }
      }

      // Mark previous steps as completed
      for (let i = 0; i < n-1; i++) {
        if (steps[i]) {
          steps[i].classList.remove('active');
          steps[i].classList.add('completed');
        }
      }

      // Disable future steps
      for (let i = n; i < steps.length; i++) {
        if (steps[i]) {
          steps[i].classList.remove('active', 'completed');
          steps[i].querySelectorAll('input,textarea,button').forEach(el => el.disabled = true);
        }
      }
    }

    clearForm() {
      if (confirm(gettext('Do you really want to reset the entire form?'))) {
        console.log('Clearing entire form...');

        this.selectedUser = null;
        this.selectedItems = [];
        this.selectedRooms = [];
        this.selectedSet = null;
        this.selectedSetDetails = null;
        this.selectedRoom = null;
        this.activeItems = [];

        // Update UI for all sections
        this.updateSelectedItemsUI();
        this.updateSelectedRoomsUI();

        // Clear user selection
        document.getElementById('selectedUser').innerHTML = '<div class="alert alert-info py-2 mb-0"><small><i class="fas fa-info-circle me-1"></i>' + gettext('Select user') + '</small></div>';
        document.getElementById('userResults').innerHTML = '';
        document.getElementById('userStats').innerHTML = '';

        // Clear form fields
        document.querySelector('[name="project_name"]').value = '';
        document.querySelector('[name="purpose"]').value = '';
        document.querySelector('[name="start_date"]').value = '';
        document.querySelector('[name="end_date"]').value = '';

        // Clear inventory
        document.getElementById('inventoryGrid').innerHTML = '';
        document.querySelector('.inventory-selection-panel')?.classList.add('d-none');

        // Close any open modals
        const equipmentSetsModal = bootstrap.Modal.getInstance(document.getElementById('equipmentSetsModal'));
        if (equipmentSetsModal) {
          equipmentSetsModal.hide();
        }

        const roomsModal = bootstrap.Modal.getInstance(document.getElementById('roomsModal'));
        if (roomsModal) {
          roomsModal.hide();
        }

        // Reset to step 1
        this.enableStep(1);

        // Clear search
        document.getElementById('userSearch').value = '';

        console.log('Entire form cleared');
      }
    }

    async showEquipmentSets() {
      try {
        console.log('Loading equipment sets from:', URLS.equipmentSets);
        const resp = await fetch(URLS.equipmentSets);
        const data = await resp.json();
        console.log('Equipment sets response:', data);

        if (data.success) {
          this.equipmentSets = data.equipment_sets || [];
          console.log('Loaded equipment sets:', this.equipmentSets);
        } else {
          console.error('API error:', data.error);
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

      console.log('Rendering equipment sets:', this.equipmentSets);

      if (this.equipmentSets.length === 0) {
        container.innerHTML = '<div class="text-center p-3"><small class="text-muted">' + gettext('No sets available') + '</small></div>';
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
          // Update selection
          container.querySelectorAll('.list-group-item').forEach(i => i.classList.remove('active'));
          item.classList.add('active');
        });

        container.appendChild(item);
      });
    }

    async selectEquipmentSet(set) {
      this.selectedSet = set;

      try {
        // Load detailed information about the set
        const url = URLS.equipmentSetDetails.replace('{setId}', set.id);
        console.log('Loading set details from:', url);

        const resp = await fetch(url);
        const data = await resp.json();

        if (data.success) {
          console.log('Set details loaded:', data.equipment_set);
          this.selectedSetDetails = data.equipment_set;
          this.renderSetDetails(data.equipment_set);
        } else {
          console.error('Failed to load set details:', data.error);
          this.renderSetDetails(set); // Fallback to basic info
        }
      } catch (error) {
        console.error('Error loading set details:', error);
        this.renderSetDetails(set); // Fallback to basic info
      }

      // Enable add button
      document.getElementById('addSetToRentalBtn').disabled = false;
    }

    renderSetDetails(set) {
      const panel = document.getElementById('setDetailsPanel');
      if (!panel) return;

      console.log('Rendering set details for:', set);

      let html = `
        <h6>${set.name}</h6>
        <p class="text-muted">${set.description || gettext('No description')}</p>`;

      // Check if we have detailed information
      if (set.items && set.items.length > 0) {
        html += `
          <div class="table-responsive">
            <table class="table table-sm">
              <thead>
                <tr>
                  <th>${gettext('Item')}</th>
                  <th>${gettext('Needed')}</th>
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
        // Fallback for basic info
        html += `
          <div class="alert alert-info">
            <i class="fas fa-info-circle me-2"></i>
            <strong>${set.items_count || 0}</strong> ${gettext('items in set')}
          </div>
          <div class="text-center">
            <small class="text-muted">${gettext('Detailed information is loading...')}</small>
          </div>`;
      }

      panel.innerHTML = html;
    }

    addSetToRental() {
      if (!this.selectedSet || !this.selectedUser) {
        alert(gettext('Please select a user and a set first'));
        return;
      }

      console.log('Adding set to rental:', this.selectedSet);

      // Check if we have detailed information about the set
      if (this.selectedSetDetails && this.selectedSetDetails.items) {
        console.log('Adding set items to rental:', this.selectedSetDetails.items);

        // Add all available items from the set to selected items
        this.selectedSetDetails.items.forEach(setItem => {
          if (setItem.is_available && setItem.quantity_available > 0) {
            // Check if item is already selected
            const existingIndex = this.selectedItems.findIndex(item =>
              item.inventory_id === setItem.inventory_item_id
            );

            const quantityToAdd = Math.min(setItem.quantity_available, setItem.quantity_needed);

            if (existingIndex >= 0) {
              // Update existing item quantity
              this.selectedItems[existingIndex].quantity += quantityToAdd;
              console.log(`Updated existing item ${setItem.description}, new quantity: ${this.selectedItems[existingIndex].quantity}`);
            } else {
              // Add new item
              this.selectedItems.push({
                inventory_id: setItem.inventory_item_id,
                inventory_number: setItem.inventory_number,
                description: setItem.description,
                quantity: quantityToAdd,
                location: setItem.location,
                category: setItem.category
              });
              console.log(`Added new item ${setItem.description} with quantity: ${quantityToAdd}`);
            }
          } else {
            console.log(`Skipping unavailable item: ${setItem.description} (available: ${setItem.quantity_available})`);
          }
        });

        console.log('Updated selectedItems:', this.selectedItems);
      } else {
        console.warn('No detailed set information available, cannot add items');
        alert(gettext('Error: Detailed information about the set is not available'));
        return;
      }

      // Update UI
      this.updateSelectedItemsUI();
      this.enableStep(5);

      // Refresh inventory display to show selection
      if (this.selectedUser) {
        this.loadUserInventory(this.selectedUser.id);
      }

      // Close modal
      const modal = bootstrap.Modal.getInstance(document.getElementById('equipmentSetsModal'));
      if (modal) modal.hide();

              alert(gettext(`Set "${this.selectedSet.name}" was added to the rental`));
    }

    async showRooms() {
      try {
        console.log('Loading rooms...');

        // Get selected dates for availability check
        const startDateInput = document.querySelector('[name="start_date"]');
        const endDateInput = document.querySelector('[name="end_date"]');

        if (!startDateInput || !endDateInput) {
          console.log('Date inputs not found');
          return;
        }

        const startDate = startDateInput.value;
        const endDate = endDateInput.value;

        console.log('Start date:', startDate, 'End date:', endDate);

        // Form URL with time parameters
        let url = URLS.rooms;
        if (startDate && endDate) {
          try {
            // Check if dates are valid
            const startDateObj = new Date(startDate);
            const endDateObj = new Date(endDate);

            if (isNaN(startDateObj.getTime()) || isNaN(endDateObj.getTime())) {
              console.log('Invalid date format, loading rooms without date filter');
            } else {
              // Create dates for filtering (10:00 - 18:00)
              const startDateTime = new Date(startDate + 'T10:00:00');
              const endDateTime = new Date(endDate + 'T18:00:00');

              if (!isNaN(startDateTime.getTime()) && !isNaN(endDateTime.getTime())) {
                url += `?start_date=${encodeURIComponent(startDateTime.toISOString())}&end_date=${encodeURIComponent(endDateTime.toISOString())}`;
                console.log('Added date filter to URL:', url);
              }
            }
          } catch (dateError) {
            console.log('Error creating date filter:', dateError);
            // Continue without date filter
          }
        }

        console.log('Fetching rooms from:', url);
        const resp = await fetch(url);

        if (!resp.ok) {
          throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
        }

        const data = await resp.json();

        if (data.success) {
          this.rooms = data.rooms || [];
          console.log('Loaded rooms:', this.rooms.length);
          this.renderRooms();

          // Populate selects for calendar and timeline
          this.populateRoomSelects();

          // Show modal
          const modal = new bootstrap.Modal(document.getElementById('roomsModal'));
          modal.show();
        } else {
          throw new Error(data.error || gettext('Unknown error'));
        }
      } catch (error) {
        console.error('Error loading rooms:', error);
        alert(gettext('Error loading rooms'));
      }
    }

    populateRoomSelects() {
      // Populate selects for calendar and timeline
      const calendarSelect = document.getElementById('calendarRoomSelect');
      const timelineSelect = document.getElementById('timelineRoomSelect');

      if (calendarSelect) {
        calendarSelect.innerHTML = '<option value="">' + gettext('All rooms') + '</option>';
        this.rooms.forEach(room => {
          const option = document.createElement('option');
          option.value = room.id;
          option.textContent = room.name;
          calendarSelect.appendChild(option);
        });
      }

      if (timelineSelect) {
        timelineSelect.innerHTML = '<option value="">' + gettext('All rooms') + '</option>';
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
      if (document.getElementById('timelineDate')) {
        document.getElementById('timelineDate').value = today;
      }
    }

    async loadRoomSchedule() {
      try {
        const roomId = document.getElementById('calendarRoomSelect')?.value || '';
        const startDate = document.getElementById('calendarStartDate')?.value || '';
        const endDate = document.getElementById('calendarEndDate')?.value || '';

        if (!startDate || !endDate) {
          console.log('No dates for calendar');
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

        console.log('Loading room schedule from:', url);
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
                <i class="fas fa-exclamation-triangle me-2"></i>
                ${gettext('Error loading calendar')}: ${error.message}
              </div>
              <button class="btn btn-primary mt-3" id="retryCalendarBtn">
                <i class="fas fa-sync-alt me-1"></i>${gettext('Retry')}
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

    async loadRoomTimeline() {
      try {
        const roomId = document.getElementById('timelineRoomSelect')?.value || '';
        const date = document.getElementById('timelineDate')?.value || '';

        if (!date) {
          console.log('No date for timeline');
          return;
        }

        // Show loading indicator
        const container = document.getElementById('timelineContainer');
        if (container) {
          container.innerHTML = `
            <div class="text-center p-5">
              <div class="spinner-border" role="status"></div>
              <p class="mt-2">${gettext('Loading timeline...')}</p>
            </div>
          `;
        }

        let url = URLS.roomSchedule;
        const params = new URLSearchParams();
        if (roomId) params.append('room_id', roomId);
        params.append('start_date', date);
        params.append('end_date', date);

        url += '?' + params.toString();

        console.log('Loading room timeline from:', url);
        const resp = await fetch(url);

        if (!resp.ok) {
          throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
        }

        const data = await resp.json();

        if (data.success) {
          this.renderTimeline(data.rooms, date);
        } else {
          throw new Error(data.error || gettext('Unknown error'));
        }
      } catch (error) {
        console.error('Error loading room timeline:', error);
        const container = document.getElementById('timelineContainer');
        if (container) {
          container.innerHTML = `
            <div class="text-center p-5">
              <div class="alert alert-danger">
                <i class="fas fa-exclamation-triangle me-2"></i>
                ${gettext('Error loading timeline')}: ${error.message}
              </div>
              <button class="btn btn-primary mt-3" id="retryTimelineBtn">
                <i class="fas fa-sync-alt me-1"></i>${gettext('Retry')}
              </button>
            </div>
          `;

          // Add handler for retry button
          const retryBtn = container.querySelector('#retryTimelineBtn');
          if (retryBtn) {
            retryBtn.addEventListener('click', () => this.loadRoomTimeline());
          }
        }
      }
    }

    renderCalendar(rooms, period) {
      const container = document.getElementById('calendarContainer');
      if (!container) return;

      if (!rooms || rooms.length === 0) {
        container.innerHTML = '<div class="text-center p-3"><p class="text-muted">' + gettext('No rooms available') + '</p></div>';
        return;
      }

      // Check if the first room has a schedule
      const firstRoom = rooms[0];
      if (!firstRoom.schedule || firstRoom.schedule.length === 0) {
        container.innerHTML = '<div class="text-center p-3"><p class="text-muted">' + gettext('No schedule available') + '</p></div>';
        return;
      }

      console.log('Rendering calendar for rooms:', rooms.length);
      console.log('First room schedule days:', firstRoom.schedule.length);

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
                  html += `<small class="d-block text-muted"><i class="fas fa-users me-1"></i>${slot.info.people_count} ${gettext('people')}</small>`;
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
      html += `<div class="calendar-cell time-slot">18:00</div>`; // TODO: gettext('18:00')
      scheduleToUse.forEach(() => {
        html += '<div class="calendar-cell available"></div>';
      });
      html += '</div>';

      html += '</div>';
      container.innerHTML = html;
      console.log('Calendar rendered successfully');
    }

    renderTimeline(rooms, date) {
      const container = document.getElementById('timelineContainer');
      if (!container) return;

      if (!rooms || rooms.length === 0) {
        container.innerHTML = '<div class="text-center p-3"><p class="text-muted">' + gettext('No rooms available') + '</p></div>';
        return;
      }

      console.log('Rendering timeline for rooms:', rooms.length, 'date:', date);

      let html = '<div class="timeline-container">';

      rooms.forEach(room => {
        if (!room.schedule) {
          console.log('Room has no schedule:', room.name);
          return;
        }

        const daySchedule = room.schedule.find(day => day.date === date);
        if (!daySchedule) {
          console.log('No schedule found for date:', date, 'in room:', room.name);
          return;
        }

        if (!daySchedule.slots) {
          console.log('Day schedule has no slots for room:', room.name);
          return;
        }

        html += `<div class="timeline-room mb-4">`;
        html += `<h6 class="mb-3">${room.name}</h6>`;
        // 16 half-hour slots + right marker 18:00 = 17 columns in one row
        html += `<div class="timeline-slots" style="grid-template-columns: repeat(17, 1fr);">`;

        daySchedule.slots.forEach(slot => {
          const slotClass = slot.status === 'occupied' ? 'occupied' : 'available';
          html += `<div class="timeline-slot ${slotClass}" title="${this.getSlotTooltip(slot)}">`;
          html += `<div class="slot-time">${slot.time}</div>`;
          if (slot.status === 'occupied' && slot.info) {
            html += `<div class="slot-details">`;
            const userName = slot.info.user_name || 'Unknown user';
            const project = slot.info.project || 'No project';
            const status = slot.info.status || 'unknown';
            const peopleCount = slot.info.people_count || 1;

            html += `<div class="user-name">${userName}</div>`;
            html += `<div class="project-name">${project}</div>`;
            html += `<div class="status-badge ${status}">${this.getStatusText(status)}</div>`;
            if (peopleCount > 1) {
              html += `<div class="people-count"><i class="fas fa-users me-1"></i>${peopleCount} people</div>`;
            }
            html += `</div>`;
          }
          html += '</div>';
        });

        // Add right marker 18:00 in the same row
        html += `<div class="timeline-slot available end-marker" title="18:00"><div class="slot-time">18:00</div></div>`; // TODO: gettext('18:00')

        html += '</div></div>';
      });

      html += '</div>';
      container.innerHTML = html;
      console.log('Timeline rendered successfully');
    }

    getSlotTooltip(slot) {
      if (slot.status === 'available') {
        return gettext('Available');
      }
      if (slot.info) {
        const userName = slot.info.user_name || gettext('Unknown user');
        const project = slot.info.project || gettext('No project');
        const status = slot.info.status || 'unknown';
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

    renderRooms() {
      const container = document.getElementById('roomsList');
      if (!container) return;

      if (this.rooms.length === 0) {
        container.innerHTML = `
          <div class="text-center p-3">
            <i class="fas fa-building fa-2x text-muted mb-2"></i>
            <p class="text-muted mb-0">${gettext('No rooms available')}</p>
          </div>`;
        return;
      }

      let html = '';
      this.rooms.forEach(room => {
        const availabilityClass = room.is_available ? 'list-group-item-action' : 'list-group-item-secondary';
        const availabilityIcon = room.is_available ? 'fa-check-circle text-success' : 'fa-times-circle text-danger';
        const availabilityText = room.is_available ? gettext('Available') : gettext('Not available');

        html += `
          <div class="list-group-item ${availabilityClass} room-item ${!room.is_available ? 'disabled' : ''}"
                data-room-id="${room.id}" ${!room.is_available ? 'style="opacity: 0.6;"' : ''}>
            <div class="d-flex justify-content-between align-items-start">
              <div>
                <h6 class="mb-1">
                  ${room.name}
                  <i class="fas ${availabilityIcon} ms-2" title="${availabilityText}"></i>
                </h6>
                <small class="text-muted">${room.description || gettext('No description')}</small>
              </div>
              <span class="badge bg-primary">${room.capacity} ${gettext('people')}</span>
            </div>
            <small class="text-muted d-block mt-1">
              <i class="fas fa-map-marker-alt me-1"></i>${room.location || gettext('Location not specified') || ''}
            </small>
            ${!room.is_available ? `<small class="text-danger d-block mt-1"><i class="fas fa-info-circle me-1"></i>${room.availability_info}</small>` : ''}
          </div>`;
      });

      container.innerHTML = html;

      // Add click event listeners only for available rooms
      container.querySelectorAll('.room-item:not(.disabled)').forEach(item => {
        item.addEventListener('click', (e) => {
          // Remove active class from all items
          container.querySelectorAll('.room-item').forEach(i => i.classList.remove('active'));
          // Add active class to clicked item
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
        document.getElementById('addRoomToRentalBtn').disabled = false;
      }
    }

        renderRoomDetails(room) {
      const panel = document.getElementById('roomDetailsPanel');
      if (!panel) return;

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
                   min="${new Date().toISOString().split('T')[0]}"
                   value="${new Date().toISOString().split('T')[0]}">
          </div>
          <div class="mb-3">
            <label class="form-label"><strong>🕐 ${gettext('Start time')}:</strong></label>
            <select class="form-select time-select" id="roomStartTime">
              <option value="10:00" selected>10:00</option>
              <option value="10:30">10:30</option>
              <option value="11:00">11:00</option>
              <option value="11:30">11:30</option>
              <option value="12:00">12:00</option>
              <option value="12:30">12:30</option>
              <option value="13:00">13:00</option>
              <option value="13:30">13:30</option>
              <option value="14:00">14:00</option>
              <option value="14:30">14:30</option>
              <option value="15:00">15:00</option>
              <option value="15:30">15:30</option>
              <option value="16:00">16:00</option>
              <option value="16:30">16:30</option>
              <option value="17:00">17:00</option>
              <option value="17:30">17:30</option>
              <option value="18:00">18:00</option>
            </select>
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
                   min="${new Date().toISOString().split('T')[0]}"
                   value="${new Date().toISOString().split('T')[0]}" disabled>
          </div>
          <div class="mb-3">
            <label class="form-label"><strong>🕐 ${gettext('End time')}:</strong></label>
            <select class="form-select time-select" id="roomEndTime">
              <option value="10:30" selected>10:30</option>
              <option value="11:00">11:00</option>
              <option value="11:30">11:30</option>
              <option value="12:00">12:00</option>
              <option value="12:30">12:30</option>
              <option value="13:00">13:00</option>
              <option value="13:30">13:30</option>
              <option value="14:00">14:00</option>
              <option value="14:30">14:30</option>
              <option value="15:00">15:00</option>
              <option value="15:30">15:30</option>
              <option value="16:00">16:00</option>
              <option value="16:30">16:30</option>
              <option value="17:00">17:00</option>
              <option value="17:30">17:30</option>
              <option value="18:00">18:00</option>
            </select>
          </div>
        </div>
        <div class="alert alert-info p-2">
            <small><i class="fas fa-info-circle me-1"></i>${gettext('Working hours')}: ${gettext('Mo-Fr, 10:00-18:00')} ${gettext('(except for holidays)')}</small>
        </div>`;

      panel.innerHTML = html;

      // Wait for DOM to be ready, then set up time selectors
      setTimeout(() => {
        const startTimeSelect = document.getElementById('roomStartTime');
        const endTimeSelect = document.getElementById('roomEndTime');
        const differentEndDateCheckbox = document.getElementById('differentEndDate');
        const endDateInput = document.getElementById('roomEndDate');

        if (startTimeSelect && endTimeSelect) {
          console.log('Setting up time selectors for room modal...');

          // Force set initial values
          startTimeSelect.value = '10:00';
          endTimeSelect.value = '10:30';

          console.log('Initial start time set to:', startTimeSelect.value);
          console.log('Initial end time set to:', endTimeSelect.value);

          // Add change event listener for start time
          startTimeSelect.addEventListener('change', () => {
            console.log('Start time changed to:', startTimeSelect.value);

            const startTime = startTimeSelect.value;
            const startHour = parseInt(startTime.split(':')[0]);
            const startMinute = parseInt(startTime.split(':')[1]);

            // Calculate end time (start time + 30 minutes)
            let endHour = startHour;
            let endMinute = startMinute + 30;

            if (endMinute >= 60) {
              endMinute = 0;
              endHour += 1;
            }

            // Ensure end time doesn't exceed 18:00
            if (endHour > 18) {
              endHour = 18;
              endMinute = 0;
            }

            const newEndTime = `${endHour.toString().padStart(2, '0')}:${endMinute.toString().padStart(2, '0')}`;
            endTimeSelect.value = newEndTime;

            console.log('End time automatically set to:', newEndTime);
          });

          // Add change event listener for end time
          endTimeSelect.addEventListener('change', () => {
            console.log('End time manually changed to:', endTimeSelect.value);
          });
        }

        // Handle different end date checkbox
        if (differentEndDateCheckbox && endDateInput) {
          differentEndDateCheckbox.addEventListener('change', () => {
            endDateInput.disabled = !differentEndDateCheckbox.checked;
            if (!differentEndDateCheckbox.checked) {
              endDateInput.value = document.getElementById('roomStartDate').value;
            }
          });
        }
      }, 100); // 100ms delay to ensure DOM is ready
    }

    addRoomToRental() {
      if (!this.selectedRoom || !this.selectedUser) {
        alert(gettext('Please select a user and a room first'));
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

              if (startHour < 10 || startHour > 18 || endHour < 10 || endHour > 18) {
          alert(gettext('Please select time between 10:00 and 18:00'));
          return;
        }

      // Convert to minutes for easier comparison
      const startTotalMinutes = startHour * 60 + startMinute;
      const endTotalMinutes = endHour * 60 + endMinute;

              if (endTotalMinutes <= startTotalMinutes) {
          alert(gettext('End time must be after start time'));
          return;
        }

      // Check if time is in the past
      const startDateTime = new Date(`${startDate}T${startTime}`);
      const endDateTime = new Date(`${finalEndDate}T${endTime}`);
      const now = new Date();

              if (startDateTime < now) {
          alert(gettext(`Start time cannot be in the past. Selected time: ${startDateTime.toLocaleString('en-US')}, Current time: ${now.toLocaleString('en-US')}`));
          return;
        }

              if (endDateTime < now) {
          alert(gettext(`End time cannot be in the past. Selected time: ${endDateTime.toLocaleString('en-US')}, Current time: ${now.toLocaleString('en-US')}`));
          return;
        }

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

      // Auto-fill Zeitraum fields on main page
      this.autoFillZeitraum(startDate, startTime, finalEndDate, endTime);

      // Update UI
      this.updateSelectedRoomsUI();
      this.enableStep(5);

      // Close modal
      const modal = bootstrap.Modal.getInstance(document.getElementById('roomsModal'));
      if (modal) modal.hide();

              alert(gettext(`Room "${this.selectedRoom.name}" was added to the rental`));
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

      // Fill start date and time
      const startDateField = document.querySelector('input[name="start_date"]');
      if (startDateField) {
        const startDateTime = `${startDate}T${startTime}`;
        startDateField.value = startDateTime;
      }

      // Fill end date and time
      const endDateField = document.querySelector('input[name="end_date"]');
      if (endDateField) {
        const endDateTime = `${endDate}T${endTime}`;
        endDateField.value = endDateTime;
      }

      // Enable the fields
      if (startDateField) startDateField.disabled = false;
      if (endDateField) endDateField.disabled = false;
    }

    async showRentalDetails(userId, type) {
      try {
        const url = URLS.userRentalDetails.replace('{userId}', userId);
        const resp = await fetch(`${url}?type=${type}`);
        const data = await resp.json();

        console.log('Rental details:', data);

        // Show appropriate modal based on type
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
            return;
        }

        this.renderRentalDetails(contentId, data);

        // Show modal
        const modal = new bootstrap.Modal(document.getElementById(modalId));
        modal.show();

      } catch (error) {
        console.error('Error loading rental details:', error);
        alert(gettext('Error loading rental details'));
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
          <div class="text-center p-4">
            <i class="fas fa-inbox fa-3x text-muted mb-3"></i>
            <h6>${gettext('No')} ${this.getTypeLabel(type)} ${gettext('found')}</h6>
            <p class="text-muted">${gettext('No')} ${this.getTypeLabel(type).toLowerCase()} ${gettext('found for')} ${user.name || user.email}.</p>
          </div>`;
        return;
      }

      let html = `
        <div class="mb-3">
          <strong>${gettext('User')}:</strong> ${user.name} (${user.email})
        </div>`;

      rentals.forEach(rental => {
        // Debug: log rental object to see what fields are available
        console.log('Rental object:', rental);

        const startDate = rental.requested_start_date ? new Date(rental.requested_start_date).toLocaleString('de-DE', {
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit'
        }) : 'N/A';
        const endDate = rental.requested_end_date ? new Date(rental.requested_end_date).toLocaleString('de-DE', {
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit'
        }) : 'N/A';
        const actualEndDate = rental.actual_end_date ? new Date(rental.actual_end_date).toLocaleString('de-DE', {
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit'
        }) : 'N/A';

        html += `
          <div class="card mb-3">
            <div class="card-header d-flex justify-content-between align-items-center">
              <div>
                <h6 class="mb-0">${rental.project_name}</h6>
                <small class="text-muted">ID: ${rental.id}</small>
              </div>
              <div class="d-flex align-items-center gap-2">
                <span class="badge ${this.getStatusBadgeClass(rental.status)}">${this.getStatusLabel(rental.status)}</span>
                ${type === 'overdue' && rental.days_overdue > 0 ? `<span class="badge bg-danger ms-1">${rental.days_overdue} ${gettext('days overdue')} (${gettext('expected')} ${rental.requested_end_date})</span>` : ''}
                ${this.getRentalActionButtons(rental, type)}
                <a href="/rental/rental/${rental.id}/" class="btn btn-sm btn-outline-primary ms-1" title="${gettext('Show details')}">
                  <i class="fas fa-eye"></i>
                </a>
              </div>
            </div>
            <div class="card-body">
              <div class="row mb-2">
                <div class="col-md-6">
                  <strong>${gettext('Purpose')}:</strong> ${rental.purpose && rental.purpose.trim() ? rental.purpose : (rental.project_name || 'N/A')}<br>
                  <strong>${gettext('Planned from')}:</strong> ${startDate}
                </div>
                <div class="col-md-6">
                  <strong>${gettext('Created by')}:</strong> ${rental.created_by || 'N/A'}<br>
                  <strong>${gettext('Planned until')}:</strong> ${endDate}
                </div>
              </div>
              ${type === 'returned' ? `
              <div class="row mb-3">
                <div class="col-md-6">
                  <strong>${gettext('Returned')}:</strong> ${actualEndDate}
                </div>
              </div>` : ''}

              ${rental.items && rental.items.length > 0 ? `
              <h6>${gettext('Equipment')} (${rental.items.length} ${gettext('items')}):</h6>
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
                  <tbody>` : ''}`;

        if (rental.items && rental.items.length > 0) {
          rental.items.forEach(item => {
            // Handle both old and new data structure for inventory item info
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
                ${type === 'active' ? `<td><span class="badge ${item.outstanding > 0 ? 'bg-warning' : 'bg-success'}">${item.outstanding}</span></td>` : ''}
              </tr>`;
          });

          html += `
                  </tbody>
                </table>
              </div>`;
        }

        // Add rooms section if there are rooms
        if (rental.room_rentals && rental.room_rentals.length > 0) {
          html += `
            <h6 class="mt-3">${gettext('Rooms')} (${rental.room_rentals.length} ${gettext('rooms')}):</h6>
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
                  <small class="text-muted">[${roomRental.room.location || gettext('Location not specified')}]</small>
                </td>
                <td>${roomRental.room.capacity} ${gettext('people')}</td>
                <td>${roomRental.people_count} ${gettext('people')}</td>
                <td>${roomRental.notes || '-'}</td>
              </tr>`;
          });

          html += `
                </tbody>
              </table>
            </div>`;
        }

        html += `
            </div>
          </div>`;
      });

      container.innerHTML = html;

      // Bind action button events
      container.querySelectorAll('.cancel-rental-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const rentalId = e.target.dataset.rentalId;
          this.cancelRental(rentalId, contentId);
        });
      });

      container.querySelectorAll('.extend-rental-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const rentalId = e.currentTarget.dataset.rentalId;
          this.showExtendRentalModal(rentalId);
        });
      });

      container.querySelectorAll('.print-rental-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const rentalId = e.currentTarget.dataset.rentalId;
          this.showPrintModal(rentalId);
        });
      });
    }

        getRentalActionButtons(rental, type) {
      if (type !== 'active') return '';

      let buttons = '';

      // Print button for issued rentals
      if (rental.status === 'issued') {
        buttons += `
          <button class="btn btn-sm btn-outline-success print-rental-btn me-1"
                  data-rental-id="${rental.id}"
                  title="${gettext('Print rental')}">
              <i class="fas fa-print"></i>
          </button>`;
      }

              // Extend button for reserved or issued rentals
        if (rental.status === 'reserved' || rental.status === 'issued') {
            buttons += `
                <button class="btn btn-sm btn-outline-info extend-rental-btn me-1"
                        data-rental-id="${rental.id}"
                        title="${gettext('Extend rental')}">
                    <i class="fas fa-calendar-plus"></i>
                </button>`;
        }

        // Cancel button for reserved or issued rentals
        if (rental.status === 'reserved' || rental.status === 'issued') {
            buttons += `
                <button class="btn btn-sm btn-outline-danger cancel-rental-btn"
                        data-rental-id="${rental.id}"
                        title="${gettext('Cancel rental')}">
                    <i class="fas fa-times"></i>
                </button>`;
        }

        return buttons;
    }

    async cancelRental(rentalId, contentId) {
      if (!confirm(gettext('Are you sure you want to cancel this rental? This action cannot be undone.'))) {
        return;
      }

      try {
        const resp = await fetch(URLS.cancelRental, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': CSRF_TOKEN,
          },
          body: JSON.stringify({ rental_id: rentalId })
        });

        const data = await resp.json();

        if (data.success) {
          alert(gettext('Rental was successfully cancelled'));

          // Refresh the modal content
          if (this.selectedUser) {
            this.showRentalDetails(this.selectedUser.id, 'active');
            // Also refresh user stats and active items
            this.loadUserStats(this.selectedUser.id);
            this.loadActiveItems(this.selectedUser.id);
          }
        } else {
          alert(data.error || gettext('Error cancelling rental'));
        }
      } catch (error) {
        console.error('Cancel rental error:', error);
        alert(gettext('Network error cancelling rental'));
      }
    }

    async showDetailedReturnModal(rentalId, itemId = null) {
      try {
        if (!this.selectedUser) {
          alert(gettext('Please select a user first'));
          return;
        }

        // Get rental details for the modal
        const resp = await fetch(URLS.userRentalDetails.replace('{userId}', this.selectedUser.id) + `?type=active&rental_id=${rentalId}`);
        if (!resp.ok) {
          throw new Error(`HTTP error! status: ${resp.status}`);
        }

        const data = await resp.json();
        console.log('Rental details data:', data);

        const rental = data.rentals && data.rentals.find(r => r.id == rentalId);
        if (!rental) {
          alert(gettext('Rental not found'));
          return;
        }

        // Build return form
        let html = `
          <div class="mb-3">
            <h6>${rental.project_name}</h6>
            <small class="text-muted">ID: ${rental.id} | ${rental.requested_start_date} - ${rental.requested_end_date}</small>
          </div>`;

        rental.items.forEach(item => {
          const outstanding = item.outstanding || ((item.quantity_issued || 0) - (item.quantity_returned || 0));
          if (outstanding <= 0) return;

          // Handle both old and new data structure
          const itemInfo = item.inventory_item || item;
          const description = itemInfo.description || itemInfo.inventory_number || gettext('Unknown item');
          const inventoryNumber = itemInfo.inventory_number || gettext('N/A');

          html += `
            <div class="card mb-3" data-item-id="${item.id}">
              <div class="card-body">
                <h6>${description} [${inventoryNumber}]</h6>
                <small class="text-muted">${gettext('Outstanding')}: ${outstanding}</small>

                <div class="row mt-2">
                  <div class="col-md-3">
                    <label class="form-label form-label-sm">${gettext('Quantity')}:</label>
                    <input type="number" class="form-control form-control-sm return-quantity"
                           min="1" max="${outstanding}" value="${outstanding}">
                  </div>
                  <div class="col-md-3">
                    <label class="form-label form-label-sm">${gettext('Condition')}:</label>
                    <select class="form-select form-select-sm return-condition">
                      <option value="excellent">${gettext('Excellent')}</option>
                      <option value="good" selected>${gettext('Good')}</option>
                      <option value="fair">${gettext('Fair')}</option>
                      <option value="poor">${gettext('Poor')}</option>
                    </select>
                  </div>
                  <div class="col-md-6">
                    <label class="form-label form-label-sm">${gettext('Notes')}:</label>
                    <input type="text" class="form-control form-control-sm return-notes"
                           placeholder="${gettext('Notes about the condition...')}">
                  </div>
                </div>

                <div class="mt-2">
                  <button type="button" class="btn btn-sm btn-outline-warning add-issue-btn"
                          data-item-id="${item.id}">
                    <i class="fas fa-plus me-1"></i>${gettext('Add problem')}
                  </button>
                  <div class="issues-container mt-2"></div>
                </div>
              </div>
            </div>`;
        });

        document.getElementById('returnItemsContent').innerHTML = html;

        // Bind add issue buttons
        document.querySelectorAll('.add-issue-btn').forEach(btn => {
          btn.addEventListener('click', (e) => {
            this.addIssueToReturn(e.target);
          });
        });

        // Store rental ID for processing
        this.currentReturnRentalId = rentalId;

        // Show modal
        const modal = new bootstrap.Modal(document.getElementById('returnItemsModal'));
        modal.show();

      } catch (error) {
        console.error('Error loading return modal:', error);
        alert(gettext('Error loading return modal'));
      }
    }

    addIssueToReturn(button) {
      const container = button.parentElement.querySelector('.issues-container');
      const issueForm = document.createElement('div');
      issueForm.className = 'issue-form border rounded p-2 mb-2';
      issueForm.innerHTML = `
        <div class="row">
          <div class="col-md-4 mb-2">
            <select class="form-select form-select-sm issue-type">
              <option value="">${gettext('Select problem')}</option>
              <option value="damaged">${gettext('Damaged')}</option>
              <option value="missing">${gettext('Missing')}</option>
              <option value="late_return">${gettext('Late return')}</option>
              <option value="other">${gettext('Other')}</option>
            </select>
          </div>
          <div class="col-md-4 mb-2">
            <select class="form-select form-select-sm issue-severity">
              <option value="minor">${gettext('Minor')}</option>
              <option value="major">${gettext('Major')}</option>
              <option value="critical">${gettext('Critical')}</option>
            </select>
          </div>
          <div class="col-md-4 mb-2">
            <button type="button" class="btn btn-sm btn-outline-danger remove-issue-btn">
              <i class="fas fa-trash"></i>
            </button>
          </div>
        </div>
        <div class="mb-2">
          <textarea class="form-control form-control-sm issue-description"
                    placeholder="${gettext('Description of the problem')}" rows="2"></textarea>
        </div>
      `;

      container.appendChild(issueForm);

      // Bind remove button
      issueForm.querySelector('.remove-issue-btn').addEventListener('click', () => {
        issueForm.remove();
      });
    }

    async processDetailedReturn() {
      const items = [];
      const itemCards = document.querySelectorAll('#returnItemsContent .card[data-item-id]');

      itemCards.forEach(card => {
        const itemId = card.dataset.itemId;
        const quantity = parseInt(card.querySelector('.return-quantity').value) || 0;
        const condition = card.querySelector('.return-condition').value;
        const notes = card.querySelector('.return-notes').value;

        const issues = [];
        card.querySelectorAll('.issue-form').forEach(issueForm => {
          const issueType = issueForm.querySelector('.issue-type').value;
          const description = issueForm.querySelector('.issue-description').value;
          const severity = issueForm.querySelector('.issue-severity').value;

          if (issueType && description) {
            issues.push({
              issue_type: issueType,
              description: description,
              severity: severity
            });
          }
        });

        if (quantity > 0) {
          items.push({
            rental_item_id: itemId,
            quantity: quantity,
            condition: condition,
            notes: notes,
            issues: issues
          });
        }
      });

              if (items.length === 0) {
          alert(gettext('No items to return selected'));
          return;
        }

      try {
        const resp = await fetch(URLS.returnRentalItems, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': CSRF_TOKEN,
          },
          body: JSON.stringify({
            rental_id: this.currentReturnRentalId,
            items: items
          })
        });

        const data = await resp.json();

        if (data.success) {
          alert(data.message);
          if (data.rental_completed) {
            alert(gettext('All items were returned. The rental is completed.'));
          }

          // Close modal and refresh
          bootstrap.Modal.getInstance(document.getElementById('returnItemsModal')).hide();
          this.loadUserStats(this.selectedUser.id);
          this.loadActiveItems(this.selectedUser.id);
        } else {
          alert(data.error || gettext('Error returning items'));
        }
      } catch (error) {
        console.error('Return error:', error);
        alert(gettext('Network error'));
      }
    }

    async showExtendRentalModal(rentalId) {
      try {
        if (!this.selectedUser) {
          alert(gettext('Please select a user first'));
          return;
        }

        // Get rental details
        const resp = await fetch(URLS.userRentalDetails.replace('{userId}', this.selectedUser.id) + `?type=active&rental_id=${rentalId}`);
        if (!resp.ok) {
          throw new Error(`HTTP error! status: ${resp.status}`);
        }

        const data = await resp.json();
        console.log('Extend rental data:', data);

        const rental = data.rentals && data.rentals.find(r => r.id == rentalId);
        if (!rental) {
          alert(gettext('Rental not found'));
          return;
        }

        // Fill rental info
        document.getElementById('extendRentalInfo').innerHTML = `
          <strong>${rental.project_name}</strong><br>
          <small class="text-muted">
            ID: ${rental.id}
          </small>
        `;

        // Fill current end date in readable format
        const currentEndDate = new Date(rental.requested_end_date);
        console.log('Current end date:', rental.requested_end_date);
        console.log('Parsed date:', currentEndDate);

        const formattedCurrentDate = currentEndDate.toLocaleString('de-DE', {
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit'
        });
        console.log('Formatted date:', formattedCurrentDate);

        const currentEndDateElement = document.getElementById('extendCurrentEndDate');
        console.log('Current end date element:', currentEndDateElement);

        if (currentEndDateElement) {
          currentEndDateElement.innerHTML = `<strong>${formattedCurrentDate}</strong>`;
          console.log('Date set successfully');
        } else {
          console.error('extendCurrentEndDate element not found!');
        }

        // Set minimum date to current end date + 1 hour
        currentEndDate.setHours(currentEndDate.getHours() + 1);
        const minDate = currentEndDate.toISOString().slice(0, 16);
        document.getElementById('extendNewEndDate').min = minDate;
        document.getElementById('extendNewEndDate').value = minDate;

        // Clear reason
        document.getElementById('extendReason').value = '';

        // Store rental ID
        this.currentExtendRentalId = rentalId;

        // Show modal
        const modal = new bootstrap.Modal(document.getElementById('extendRentalModal'));
        modal.show();

      } catch (error) {
        console.error('Error loading extend modal:', error);
        alert(gettext('Error loading extension modal'));
      }
    }

    async processExtendRental() {
      const newEndDate = document.getElementById('extendNewEndDate').value;
      const reason = document.getElementById('extendReason').value;

      if (!newEndDate) {
        alert(gettext('Please select a new end date'));
        return;
      }

      try {
        // Convert datetime-local format to ISO format
        const dateObj = new Date(newEndDate);
        if (isNaN(dateObj.getTime())) {
          alert(gettext('Invalid date format'));
          return;
        }
        const isoDate = dateObj.toISOString();

        console.log('Extending rental:', this.currentExtendRentalId, 'to:', isoDate);

        const resp = await fetch(URLS.extendRental, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': CSRF_TOKEN,
          },
          body: JSON.stringify({
            rental_id: this.currentExtendRentalId,
            new_end_date: isoDate,
            reason: reason
          })
        });

        const data = await resp.json();

        if (data.success) {
          alert(data.message);

          // Close modal and refresh
          bootstrap.Modal.getInstance(document.getElementById('extendRentalModal')).hide();
          this.loadUserStats(this.selectedUser.id);
          this.loadActiveItems(this.selectedUser.id);
        } else {
          alert(data.error || gettext('Error extending rental'));
        }
      } catch (error) {
        console.error('Extend error:', error);
        alert(gettext('Network error'));
      }
    }

    async showPrintModal(rentalId) {
      try {
        // Get rental print info
        const resp = await fetch(URLS.rentalPrintInfo.replace('{rentalId}', rentalId));
        if (!resp.ok) {
          throw new Error(`HTTP error! status: ${resp.status}`);
        }

        const data = await resp.json();
        console.log('Print info:', data);

        if (!data.success) {
          alert(gettext('Error loading print information: ') + (data.error || gettext('Unknown error')));
          return;
        }

        // Show print options based on available items
        let printOptions = '';

        if (data.has_msa_items) {
          printOptions += `
            <div class="mb-3">
              <button class="btn btn-outline-primary w-100" onclick="window.open('${URLS.printFormMSA.replace('{rentalId}', rentalId)}', '_blank')">
                <i class="fas fa-print me-2"></i>
                Print MSA rental form (${data.msa_items_count} items)
              </button>
            </div>`;
        }

        if (data.has_okmq_items) {
          printOptions += `
            <div class="mb-3">
              <button class="btn btn-outline-success w-100" onclick="window.open('${URLS.printFormOKMQ.replace('{rentalId}', rentalId)}', '_blank')">
                <i class="fas fa-print me-2"></i>
                Print OKMQ rental form (${data.okmq_items_count} items)
              </button>
            </div>`;
        }

        if (!data.has_msa_items && !data.has_okmq_items) {
          printOptions = `<p class="text-muted">${gettext('No printable items in this rental found.')}</p>`;
        }

        // Show modal with print options
        const modalHtml = `
          <div class="modal fade" id="printModal" tabindex="-1" aria-labelledby="printModalLabel" aria-hidden="true">
            <div class="modal-dialog">
              <div class="modal-content">
                <div class="modal-header">
                  <h5 class="modal-title" id="printModalLabel">
                    <i class="fas fa-print me-2"></i>${gettext('Print rental forms')}
                  </h5>
                  <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                </div>
                <div class="modal-body">
                  <div class="mb-3">
                    <h6>Rental: ${data.project_name}</h6>
                    <small class="text-muted"><b>${gettext('User')}: ${data.user_name}</b></small>
                  </div>
                  <div class="print-options">
                    ${printOptions}
                  </div>
                  <div class="alert alert-info">
                    <i class="fas fa-info-circle me-2"></i>
                    <small>${gettext('Rental forms will be opened in separate windows. Use the print function of the browser (Ctrl+P).')}</small>
                  </div>
                </div>
                <div class="modal-footer">
                  <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">${gettext('Close')}</button>
                </div>
              </div>
            </div>
          </div>`;

        // Remove existing modal if any
        const existingModal = document.getElementById('printModal');
        if (existingModal) {
          existingModal.remove();
        }

        // Add modal to body
        document.body.insertAdjacentHTML('beforeend', modalHtml);

        // Show modal
        const modal = new bootstrap.Modal(document.getElementById('printModal'));
        modal.show();

        // Clean up modal after hide
        document.getElementById('printModal').addEventListener('hidden.bs.modal', function() {
          this.remove();
        });

      } catch (error) {
        console.error('Error showing print modal:', error);
        alert(gettext('Error loading print options'));
      }
    }

    getTypeLabel(type) {
      switch (type) {
        case 'active': return gettext('Active rentals');
        case 'returned': return gettext('Returned rentals');
        case 'overdue': return gettext('Overdue rentals');
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

    debounce(fn, wait) {
      let t;
      return (...a) => {
        clearTimeout(t);
        t = setTimeout(() => fn(...a), wait);
      };
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

      // Handlers for timeline
      const timelineRoomSelect = document.getElementById('timelineRoomSelect');
      const timelineDate = document.getElementById('timelineDate');
      const refreshTimelineBtn = document.getElementById('refreshTimelineBtn');

      if (timelineRoomSelect) {
        timelineRoomSelect.addEventListener('change', () => this.loadRoomTimeline());
      }
      if (timelineDate) {
        timelineDate.addEventListener('change', () => this.loadRoomTimeline());
      }
      if (refreshTimelineBtn) {
        refreshTimelineBtn.addEventListener('click', () => this.loadRoomTimeline());
      }

      // Handlers for tabs
      const roomsTabs = document.getElementById('roomsTabs');
      if (roomsTabs) {
        roomsTabs.addEventListener('shown.bs.tab', (event) => {
          if (event.target.id === 'rooms-calendar-tab') {
            this.loadRoomSchedule();
          } else if (event.target.id === 'rooms-timeline-tab') {
            this.loadRoomTimeline();
          }
        });
      }
    }
  }

  // Check if URLS are defined
  if (typeof URLS === 'undefined') {
    console.error('URLS not defined - check template');
  } else {
    console.log('URLS available:', URLS);
  }

  new RentalProcess();
});
