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
      this.groupByLocation = false;

      // Bind events
      this.bindEvents();

      // Bind calendar and timeline events
      this.bindCalendarEvents();

      // Load filter options for owners, categories and locations
      this.loadFilterOptions();

    }

    bindEvents() {
      const userSearch = document.getElementById('userSearch');
      if (userSearch) {
        userSearch.addEventListener('input', this.debounce(this.searchUsers.bind(this), 300));
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

      // Group by location button
      const groupByLocationBtn = document.getElementById('groupByLocationBtn');
      if (groupByLocationBtn) groupByLocationBtn.addEventListener('click', this.toggleLocationGrouping.bind(this));

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

      // Issue from Reservation modal button
      const processIssueFromReservationBtn = document.getElementById('processIssueFromReservationBtn');
      if (processIssueFromReservationBtn) processIssueFromReservationBtn.addEventListener('click', this.processIssueFromReservation.bind(this));
    }

    async searchUsers(e) {
      const q = e.target.value;
      if (!q || q.length < 2) return;

      try {
        const resp = await fetch(`${URLS.searchUsers}?q=${encodeURIComponent(q)}`);
        const data = await resp.json();
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

        // Update action buttons
        this.updateActionButtons();
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

      // Update right panel to show only selected user
      this.updateUserSelectionPanel(u);
    }

    updateUserSelectionPanel(u) {
      const container = document.getElementById('userResults');
      if (!container) return;

      // Clear the container and show only selected user
      container.innerHTML = `
        <div class="list-group-item list-group-item-success">
          <div class="d-flex w-100 justify-content-between">
            <div>
              <h6 class="mb-1">${u.name || gettext('Unknown')}</h6>
              <p class="mb-1">${u.email || ''}</p>
              <small class="text-muted">${gettext('Selected user')} | ${u.permissions || ''} ${gettext('authorized')}</small>
            </div>
            <div class="text-end">
              <span class="badge ${u.is_member ? 'bg-success':'bg-secondary'}">${u.member_status || gettext('User')}</span>
            </div>
          </div>
        </div>
        <div class="mt-3">
          <button class="btn btn-outline-secondary btn-sm w-100" id="changeUserBtn">
            <i class="fas fa-edit me-1"></i>${gettext('Change User')}
          </button>
        </div>
      `;

      // Add event listener for change user button
      const changeUserBtn = container.querySelector('#changeUserBtn');
      if (changeUserBtn) {
        changeUserBtn.addEventListener('click', () => {
          this.resetUserSelection();
        });
      }
    }

    resetUserSelection() {
      // Clear selected user
      this.selectedUser = null;

      // Reset left panel
      const selectedUserBox = document.getElementById('selectedUser');
      if (selectedUserBox) {
        selectedUserBox.innerHTML = `
          <div class="alert alert-info py-2 mb-0">
            <small><i class="fas fa-info-circle me-1"></i>${gettext('Select user')}</small>
          </div>`;
      }

      // Reset right panel to show search
      const container = document.getElementById('userResults');
      if (container) {
        container.innerHTML = `
          <div class="list-group-item">
            <small class="text-muted">
              <i class="fas fa-search me-1"></i>${gettext('Start typing in the search field above to find users')}
            </small>
          </div>
        `;
      }

      // Disable steps that require user selection
      this.disableStep(3);
      this.disableStep(4);
      this.disableStep(5);

      // Clear inventory panel
      const inventoryPanel = document.querySelector('.inventory-selection-panel');
      if (inventoryPanel) {
        inventoryPanel.classList.add('d-none');
      }

      // Clear selected items
      this.selectedItems = [];
      this.updateSelectedItemsUI();

      // Update action buttons
      this.updateActionButtons();
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

      // Populate location filter with hierarchical structure
      const locationSelect = document.getElementById('locationFilter');
      if (locationSelect && options.locations) {
        locationSelect.innerHTML = '<option value="all">' + gettext('All Locations') + '</option>';

        // Recursive function to add location options with proper indentation
        const addLocationOptions = (locations, level = 0) => {
          locations.forEach(location => {
            const option = document.createElement('option');
            option.value = location.full_path;

            // Create indentation based on level
            const indent = '&nbsp;'.repeat(level * 4);
            option.innerHTML = indent + location.name;
            option.dataset.level = level;
            option.dataset.fullPath = location.full_path;

            locationSelect.appendChild(option);

            // Add children recursively
            if (location.children && location.children.length > 0) {
              addLocationOptions(location.children, level + 1);
            }
          });
        };

        addLocationOptions(options.locations);
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

        const resp = await fetch(finalUrl);
        const data = await resp.json();
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
        this.renderInventory(data.inventory || []);
      } catch (error) {
        console.error('Error applying filters:', error);
      }
    }

    formatLocationPath(path) {
      if (!path) return '';

      // Split path by ' -> ' and format with visual hierarchy
      const parts = path.split(' -> ');
      if (parts.length === 1) return parts[0];

      return parts.map((part, index) => {
        const indent = '&nbsp;'.repeat(index * 2);
        const separator = index < parts.length - 1 ? ' → ' : '';
        return `${indent}${part}${separator}`;
      }).join('');
    }

    toggleLocationGrouping() {
      this.groupByLocation = !this.groupByLocation;
      const btn = document.getElementById('groupByLocationBtn');
      if (btn) {
        if (this.groupByLocation) {
          btn.classList.remove('btn-outline-info');
          btn.classList.add('btn-info');
          btn.innerHTML = '<i class="fas fa-sitemap me-1"></i>' + gettext('Ungroup');
        } else {
          btn.classList.remove('btn-info');
          btn.classList.add('btn-outline-info');
          btn.innerHTML = '<i class="fas fa-sitemap me-1"></i>' + gettext('Group by Location');
        }
      }

      // Re-render inventory if we have items
      if (this.selectedUser) {
        this.loadUserInventory(this.selectedUser.id);
      }
    }

    renderInventory(items) {
      const grid = document.getElementById('inventoryGrid');
      if (!grid) return;

      grid.innerHTML = '';

      if (items.length === 0) {
        grid.innerHTML = '<div class="col-12"><div class="alert alert-info">' + gettext('No available inventory for this user') + '</div></div>';
        return;
      }

      if (this.groupByLocation) {
        this.renderInventoryGrouped(items, grid);
      } else {
        this.renderInventoryFlat(items, grid);
      }
    }

    renderInventoryFlat(items, grid) {
      items.forEach(it => {
        const col = document.createElement('div');
        col.className = 'col-md-6 col-lg-4 mb-3 d-flex';

        // Create item card with location path
        const cardHTML = this.createItemCardHTML(it);
        const locationPathHTML = `
          <div class="location-path mb-2">
            <i class="fas fa-map-marker-alt me-1"></i>
            <span class="location-hierarchy">${this.formatLocationPath(it.location_path || '')}</span>
          </div>
        `;

        // Insert location path after the category line
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = cardHTML;
        const categoryLine = tempDiv.querySelector('.d-flex.align-items-center.text-muted.small.mb-1');
        if (categoryLine) {
          categoryLine.insertAdjacentHTML('afterend', locationPathHTML);
        }

        col.innerHTML = tempDiv.innerHTML;

        const card = col.querySelector('.item-card');
        this.bindItemCardEvents(card, it);

        grid.appendChild(col);
      });
    }

    renderInventoryGrouped(items, grid) {
      // Group items by location
      const locationGroups = {};

      items.forEach(item => {
        const locationPath = item.location_path || gettext('Unknown Location');
        if (!locationGroups[locationPath]) {
          locationGroups[locationPath] = [];
        }
        locationGroups[locationPath].push(item);
      });

      // Sort locations by path
      const sortedLocations = Object.keys(locationGroups).sort();

      sortedLocations.forEach(locationPath => {
        const itemsInLocation = locationGroups[locationPath];

        // Create location header
        const locationHeader = document.createElement('div');
        locationHeader.className = 'col-12 mb-3';
        locationHeader.innerHTML = `
          <div class="location-group-header p-3 bg-light border rounded">
            <h6 class="mb-2">
              <i class="fas fa-map-marker-alt me-2 text-primary"></i>
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
      return `
        <div class="item-card p-3 w-100 h-100 d-flex flex-column" data-item-id="${item.id}">
          <div class="d-flex justify-content-between align-items-start mb-2">
            <h6 class="mb-1">${item.description || item.inventory_number}</h6>
            <span class="badge bg-success status-badge">${gettext('Available')}</span>
          </div>
          <div class="d-flex align-items-center text-muted small mb-1">
            <span class="me-3"><i class="fas fa-barcode me-1"></i>${item.inventory_number}</span>
            <span><i class="fas fa-tag me-1"></i>${item.category || gettext('No category')}</span>
          </div>
          <div class="d-flex justify-content-between align-items-center mt-auto">
            <small class="text-muted">${gettext('Owner')}: ${item.owner || '-'}</small>
            <div class="quantity-controls">
              <div class="input-group input-group-sm">
                <button class="btn btn-outline-secondary qty-minus" type="button">-</button>
                <input type="number" class="form-control text-center qty-input" value="1" min="1" max="${item.available_quantity}">
                <button class="btn btn-outline-secondary qty-plus" type="button">+</button>
              </div>
            </div>
          </div>
        </div>`;
    }

    bindItemCardEvents(card, item) {
      card.addEventListener('click', (e) => {
        if (!e.target.closest('.quantity-controls')) {
          this.toggleItem(item);
        }
      });

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

      // Update action buttons based on selection
      this.updateActionButtons();
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

      // Update action buttons based on selection
      this.updateActionButtons();
    }

    bindRemoveItemEvents() {
      // Add event listeners to all remove buttons
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
      // Add event listeners to all remove room buttons
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

        // If no items left, disable step 5
        if (this.selectedItems.length === 0) {
          this.disableStep(5);
        }

        // Update action buttons based on selection
        this.updateActionButtons();
      } else {
        console.error('Invalid index for removeSelectedItem:', index);
      }
    }

    removeSelectedRoom(index) {
      if (index >= 0 && index < this.selectedRooms.length) {
        const removedRoom = this.selectedRooms.splice(index, 1)[0];
        this.updateSelectedRoomsUI();

        // If no items and no rooms left, disable step 5
        if (this.selectedItems.length === 0 && this.selectedRooms.length === 0) {
          this.disableStep(5);
        }

        // Update action buttons based on selection
        this.updateActionButtons();
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
                  <br><small class="text-info"><i class="fas fa-info-circle me-1"></i>${gettext('Auto-return after scheduled time')}</small>
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

      // Update action buttons based on selection
      this.updateActionButtons();
    }

    updateActionButtons() {
      const reserveBtn = document.getElementById('reserveBtn');
      const issueBtn = document.getElementById('issueBtn');

      if (!reserveBtn || !issueBtn) return;

      // If only rooms are selected, disable issue button
      if (this.selectedRooms.length > 0 && this.selectedItems.length === 0) {
        issueBtn.disabled = true;
        issueBtn.title = gettext('Rooms can only be reserved, not issued');
        issueBtn.classList.add('btn-secondary');
        issueBtn.classList.remove('btn-outline-success');
      } else {
        issueBtn.disabled = false;
        issueBtn.title = gettext('Issue Immediately');
        issueBtn.classList.remove('btn-secondary');
        issueBtn.classList.add('btn-outline-success');
      }

      // Always enable reserve button
      reserveBtn.disabled = false;
    }

    async loadUserStats(uid) {
      try {
        const url = URLS.getUserStats.replace('{userId}', uid);

        const resp = await fetch(url);

        if (!resp.ok) {
          throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
        }

        const d = await resp.json();

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

        const resp = await fetch(url);

        if (!resp.ok) {
          throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
        }

        const data = await resp.json();
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

        // For rooms, always use 'reserved' status since they auto-return
        let finalAction = action;
        if (this.selectedRooms && this.selectedRooms.length > 0) {
          finalAction = 'reserved';
          if (action === 'issued') {
            alert(gettext('Rooms can only be reserved, not issued. They will automatically return after the scheduled time.'));
          }
        }

        // Prepare rental data
        const rentalData = {
          user_id: this.selectedUser.id,
          project_name: projectName,
          purpose: purpose,
          start_date: startDate,
          end_date: endDate,
          action: finalAction,
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

        if (result.success) {
          const actionText = finalAction === 'issued' ? 'issued' : 'reserved';
          const roomNote = this.selectedRooms && this.selectedRooms.length > 0 ?
            gettext(' Rooms will automatically return after the scheduled time.') : '';
          alert(gettext(`Rental successfully ${actionText}! ID: ${result.rental_id}${roomNote}`));
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

      // Clear selected items, rooms, and sets
      this.selectedItems = [];
      this.selectedRooms = [];
      this.selectedSet = null;
      this.selectedSetDetails = null;
      this.selectedRoom = null;

      // Update UI for all sections
      this.updateSelectedItemsUI();
      this.updateSelectedRoomsUI();

      // Update action buttons
      this.updateActionButtons();

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

    disableStep(n) {
      const steps = document.querySelectorAll('.workflow-step');

      // Disable step n and all future steps
      for (let i = n-1; i < steps.length; i++) {
        if (steps[i]) {
          steps[i].classList.remove('active', 'completed');
          steps[i].querySelectorAll('input,textarea,button').forEach(el => el.disabled = true);
        }
      }

      // Mark step n-1 as active if it exists
      if (n > 1 && steps[n-2]) {
        steps[n-2].classList.remove('completed');
        steps[n-2].classList.add('active');
      }
    }

    clearForm() {
      if (confirm(gettext('Do you really want to reset the entire form?'))) {

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

        // Update action buttons
        this.updateActionButtons();

        // Clear user selection
        this.resetUserSelection();
        document.getElementById('userStats').innerHTML = '';

        // Clear form fields
        document.querySelector('[name="project_name"]').value = '';
        document.querySelector('[name="purpose"]').value = '';
        document.querySelector('[name="start_date"]').value = '';
        document.querySelector('[name="end_date"]').value = '';

        // Clear inventory
        document.getElementById('inventoryGrid').innerHTML = '';
        const inventoryPanel = document.querySelector('.inventory-selection-panel');
        if (inventoryPanel) {
          inventoryPanel.classList.add('d-none');
        }

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

      }
    }

    async showEquipmentSets() {
      try {
        const resp = await fetch(URLS.equipmentSets);
        const data = await resp.json();

        if (data.success) {
          this.equipmentSets = data.equipment_sets || [];
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

        const resp = await fetch(url);
        const data = await resp.json();

        if (data.success) {
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

      // Check if we have detailed information about the set
      if (this.selectedSetDetails && this.selectedSetDetails.items) {

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
            }
          } else {
            console.log(`Skipping unavailable item: ${setItem.description} (available: ${setItem.quantity_available})`);
          }
        });

      } else {
        console.warn('No detailed set information available, cannot add items');
        alert(gettext('Error: Detailed information about the set is not available'));
        return;
      }

      // Update UI
      this.updateSelectedItemsUI();
      this.enableStep(5);

      // Update action buttons based on selection
      this.updateActionButtons();

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

        // Get selected dates for availability check
        const startDateInput = document.querySelector('[name="start_date"]');
        const endDateInput = document.querySelector('[name="end_date"]');

        if (!startDateInput || !endDateInput) {
          return;
        }

        const startDate = startDateInput.value;
        const endDate = endDateInput.value;

        // Form URL with time parameters
        let url = URLS.rooms;
        if (startDate && endDate) {
          try {
            // Check if dates are valid
            const startDateObj = new Date(startDate);
            const endDateObj = new Date(endDate);

            if (isNaN(startDateObj.getTime()) || isNaN(endDateObj.getTime())) {
            } else {
              // Create dates for filtering (10:00 - 18:00)
              const startDateTime = new Date(startDate + 'T10:00:00');
              const endDateTime = new Date(endDate + 'T18:00:00');

              if (!isNaN(startDateTime.getTime()) && !isNaN(endDateTime.getTime())) {
                url += `?start_date=${encodeURIComponent(startDateTime.toISOString())}&end_date=${encodeURIComponent(endDateTime.toISOString())}`;
              }
            }
          } catch (dateError) {
            // Continue without date filter
          }
        }

        const resp = await fetch(url);

        if (!resp.ok) {
          throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
        }

        const data = await resp.json();

        if (data.success) {
          this.rooms = data.rooms || [];
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
    }

    renderTimeline(rooms, date) {
      const container = document.getElementById('timelineContainer');
      if (!container) return;

      if (!rooms || rooms.length === 0) {
        container.innerHTML = '<div class="text-center p-3"><p class="text-muted">' + gettext('No rooms available') + '</p></div>';
        return;
      }

      let html = '<div class="timeline-container">';

      rooms.forEach(room => {
        if (!room.schedule) {
          return;
        }

        const daySchedule = room.schedule.find(day => day.date === date);
        if (!daySchedule) {
          return;
        }

        if (!daySchedule.slots) {
          return;
        }

        html += `<div class="timeline-room mb-4">`;
        html += `<h6 class="mb-3">${room.name}</h6>`;
        // 16 half-hour slots + right marker 18:00 = 17 columns in one row
        html += `<div class="timeline-slots" style="grid-template-columns: repeat(17, 1fr);">`;

        // Group consecutive occupied slots for the same user
        const groupedSlots = this.groupConsecutiveSlots(daySchedule.slots);

        groupedSlots.forEach(group => {
          if (group.type === 'occupied') {
            // Render grouped occupied slots
            const gridColumn = group.startIndex + 1; // +1 because grid starts from 1
            const gridSpan = group.slots.length;

            html += `<div class="timeline-slot occupied grouped" style="grid-column: ${gridColumn} / span ${gridSpan};" title="${this.getGroupedSlotTooltip(group)}">`;
            html += `<div class="slot-details">`;
            const userName = group.userName || gettext('Unknown user');
            const project = group.project || gettext('No project');
            const status = group.status || 'unknown';
            const peopleCount = group.peopleCount || 1;
            const startTime = group.startTime || '';
            const endTime = group.endTime || '';

            html += `<div class="user-name">${userName}</div>`;
            html += `<div class="project-name">${project}</div>`;
            html += `<div class="status-badge ${status}">${this.getStatusText(status)}</div>`;
            if (peopleCount > 1) {
              html += `<div class="people-count"><i class="fas fa-users me-1"></i>${peopleCount} ${gettext('people')}</div>`;
            }
            if (startTime && endTime) {
              html += `<div class="time-range"><i class="fas fa-clock me-1"></i>${startTime}-${endTime}</div>`;
            }
            html += `</div>`;
            html += '</div>';
          } else {
            // Render individual available slots
            group.slots.forEach(slot => {
              html += `<div class="timeline-slot available" title="${gettext('Available')}">`;
              html += `<div class="slot-time">${slot.time}</div>`;
              html += '</div>';
            });
          }
        });

        // Add right marker 18:00 in the same row
        html += `<div class="timeline-slot available end-marker" title="18:00"><div class="slot-time">18:00</div></div>`; // TODO: gettext('18:00')

        html += '</div></div>';
      });

      html += '</div>';
      container.innerHTML = html;
    }

    groupConsecutiveSlots(slots) {
      if (!slots || slots.length === 0) return [];

      const groups = [];
      let currentGroup = null;

      slots.forEach((slot, index) => {
        if (slot.status === 'occupied' && slot.info) {
          // Check if this slot can be grouped with the current group
          if (currentGroup &&
              currentGroup.type === 'occupied' &&
              currentGroup.userName === slot.info.user_name &&
              currentGroup.project === slot.info.project &&
              currentGroup.status === slot.info.status) {
            // Add to current group
            currentGroup.slots.push(slot);
            currentGroup.endTime = slot.info.end_time;
          } else {
            // Start new group
            if (currentGroup) {
              groups.push(currentGroup);
            }
            currentGroup = {
              type: 'occupied',
              startIndex: index,
              slots: [slot],
              userName: slot.info.user_name,
              project: slot.info.project,
              status: slot.info.status,
              peopleCount: slot.info.people_count,
              startTime: slot.info.start_time,
              endTime: slot.info.end_time
            };
          }
        } else {
          // Available slot
          if (currentGroup) {
            groups.push(currentGroup);
            currentGroup = null;
          }
          // Group consecutive available slots
          if (groups.length > 0 && groups[groups.length - 1].type === 'available') {
            groups[groups.length - 1].slots.push(slot);
          } else {
            groups.push({
              type: 'available',
              startIndex: index,
              slots: [slot]
            });
          }
        }
      });

      // Add the last group if exists
      if (currentGroup) {
        groups.push(currentGroup);
      }

      return groups;
    }

    getGroupedSlotTooltip(group) {
      if (group.type === 'available') {
        return gettext('Available');
      }

      const userName = group.userName || gettext('Unknown user');
      const project = group.project || gettext('No project');
      const status = group.status || 'unknown';
      const peopleCount = group.peopleCount || 1;
      const startTime = group.startTime || '';
      const endTime = group.endTime || '';

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
        const now = new Date();
        const currentHour = now.getHours();

        // If current time is after 18:00, suggest next day
        if (currentHour >= 18) {
          const tomorrow = new Date(now);
          tomorrow.setDate(tomorrow.getDate() + 1);
          return tomorrow.getFullYear() + '-' +
                 String(tomorrow.getMonth() + 1).padStart(2, '0') + '-' +
                 String(tomorrow.getDate()).padStart(2, '0');
        }

        // If it's during working hours, use today
        return now.getFullYear() + '-' +
               String(now.getMonth() + 1).padStart(2, '0') + '-' +
               String(now.getDate()).padStart(2, '0');
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
                   min="${minDate}"
                   value="${smartStartDate}" disabled>
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
        </div>
        <div id="roomAvailabilityStatus" class="mt-3"></div>`;

      panel.innerHTML = html;

      // Wait for DOM to be ready, then set up time selectors
      setTimeout(() => {
        const startTimeSelect = document.getElementById('roomStartTime');
        const endTimeSelect = document.getElementById('roomEndTime');
        const differentEndDateCheckbox = document.getElementById('differentEndDate');
        const endDateInput = document.getElementById('roomEndDate');
        const startDateInput = document.getElementById('roomStartDate');
        const availabilityStatus = document.getElementById('roomAvailabilityStatus');

        // Smart time calculation function
        const getSmartStartTime = (date) => {
          const now = new Date();
          const today = now.getFullYear() + '-' +
                       String(now.getMonth() + 1).padStart(2, '0') + '-' +
                       String(now.getDate()).padStart(2, '0');

          if (date === today) {
            const currentHour = now.getHours();
            const currentMinute = now.getMinutes();

            // If current time is after 18:00, suggest tomorrow
            if (currentHour >= 18) {
              return null; // Will be handled by date logic
            }

            // Round up to next 30-minute slot
            let suggestedHour = currentHour;
            let suggestedMinute = currentMinute <= 30 ? 30 : 0;

            if (suggestedMinute === 0) {
              suggestedHour += 1;
            }

            // Ensure time is within working hours (10:00-18:00)
            if (suggestedHour < 10) {
              suggestedHour = 10;
              suggestedMinute = 0;
            } else if (suggestedHour >= 18) {
              return null; // Will be handled by date logic
            }

            const suggestedTime = `${suggestedHour.toString().padStart(2, '0')}:${suggestedMinute.toString().padStart(2, '0')}`;
            return suggestedTime;
          }

          return '10:00'; // Default for future dates
        };



        if (startTimeSelect && endTimeSelect) {

          // Set smart initial values (use already calculated date)
          const smartStartTime = getSmartStartTime(smartStartDate);

          if (startDateInput) {
            startDateInput.value = smartStartDate;
          }

          if (smartStartTime) {
            startTimeSelect.value = smartStartTime;
          } else {
            startTimeSelect.value = '10:00';
          }

          // Calculate and set end time
          const startTime = startTimeSelect.value;
          const startHour = parseInt(startTime.split(':')[0]);
          const startMinute = parseInt(startTime.split(':')[1]);

          let endHour = startHour;
          let endMinute = startMinute + 30;

          if (endMinute >= 60) {
            endMinute = 0;
            endHour += 1;
          }

          if (endHour > 18) {
            endHour = 18;
            endMinute = 0;
          }

          const initialEndTime = `${endHour.toString().padStart(2, '0')}:${endMinute.toString().padStart(2, '0')}`;
          endTimeSelect.value = initialEndTime;

                  // Also update end date to match start date initially
        if (endDateInput && !differentEndDateCheckbox?.checked) {
          endDateInput.value = smartStartDate;
        }

        // Add change event listener for end date
        if (endDateInput) {
          endDateInput.addEventListener('change', () => {
            // Check availability after end date change
            setTimeout(() => {
              this.checkRoomAvailability(room.id, startDateInput.value, startTimeSelect.value, endDateInput.value, endTimeSelect.value, availabilityStatus);
            }, 300);
          });
        }

          // Add change event listener for start date
          if (startDateInput) {
            startDateInput.addEventListener('change', () => {
              // Auto-update end date to match start date
              if (endDateInput && !differentEndDateCheckbox?.checked) {
                endDateInput.value = startDateInput.value;
              }

              // Update start time based on new date
              const smartStartTime = getSmartStartTime(startDateInput.value);
              if (smartStartTime && smartStartTime !== startTimeSelect.value) {
                startTimeSelect.value = smartStartTime;

                // Recalculate end time
                const startHour = parseInt(smartStartTime.split(':')[0]);
                const startMinute = parseInt(smartStartTime.split(':')[1]);

                let endHour = startHour;
                let endMinute = startMinute + 30;

                if (endMinute >= 60) {
                  endMinute = 0;
                  endHour += 1;
                }

                if (endHour > 18) {
                  endHour = 18;
                  endMinute = 0;
                }

                const newEndTime = `${endHour.toString().padStart(2, '0')}:${endMinute.toString().padStart(2, '0')}`;
                endTimeSelect.value = newEndTime;
              }

              // Check availability after date change
              setTimeout(() => {
                this.checkRoomAvailability(room.id, startDateInput.value, startTimeSelect.value, startDateInput.value, endTimeSelect.value, availabilityStatus);
              }, 300);
            });
          }

          // Add change event listener for start time
          startTimeSelect.addEventListener('change', () => {
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

            // Check availability after time change
            setTimeout(() => {
              this.checkRoomAvailability(room.id, startDateInput.value, startTimeSelect.value, startDateInput.value, newEndTime, availabilityStatus);
            }, 300);
          });

                  // Add change event listener for end time
        endTimeSelect.addEventListener('change', () => {

          // Check availability after end time change
          setTimeout(() => {
            this.checkRoomAvailability(room.id, startDateInput.value, startTimeSelect.value, startDateInput.value, endTimeSelect.value, availabilityStatus);
          }, 300);
        });
        }

        // Handle different end date checkbox
        if (differentEndDateCheckbox && endDateInput) {
          differentEndDateCheckbox.addEventListener('change', () => {
            endDateInput.disabled = !differentEndDateCheckbox.checked;
            if (!differentEndDateCheckbox.checked) {
              endDateInput.value = document.getElementById('roomStartDate').value;
            }

            // Check availability after checkbox change
            setTimeout(() => {
              this.checkRoomAvailability(room.id, startDateInput.value, startTimeSelect.value, startDateInput.value, endTimeSelect.value, availabilityStatus);
            }, 300);
          });
        }

        // Initial availability check
        setTimeout(() => {
          this.checkRoomAvailability(room.id, startDateInput.value, startTimeSelect.value, startDateInput.value, endTimeSelect.value, availabilityStatus);
        }, 300);
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

      // Auto-fill Zeitraum fields on main page
      this.autoFillZeitraum(startDate, startTime, finalEndDate, endTime);

      // Update UI
      this.updateSelectedRoomsUI();
      this.enableStep(5);

      // Update action buttons based on selection
      this.updateActionButtons();

      // Close modal
      const modal = bootstrap.Modal.getInstance(document.getElementById('roomsModal'));
      if (modal) modal.hide();

      alert(gettext(`Room "${this.selectedRoom.name}" was added to the rental. Note: Rooms are automatically reserved and will return after the scheduled time.`));
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

        if (!resp.ok) {
          throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
        }

        const data = await resp.json();

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

        // Show error in the appropriate modal content
        let contentId;
        switch (type) {
          case 'active':
            contentId = 'activeRentalsContent';
            break;
          case 'returned':
            contentId = 'returnedRentalsContent';
            break;
          case 'overdue':
            contentId = 'overdueRentalsContent';
            break;
          default:
            return;
        }

        const container = document.getElementById(contentId);
        if (container) {
          container.innerHTML = `
            <div class="text-center p-4">
              <i class="fas fa-exclamation-triangle fa-3x text-danger mb-3"></i>
              <h6>${gettext('Error loading data')}</h6>
              <p class="text-danger">${error.message}</p>
              <button class="btn btn-primary btn-sm" onclick="location.reload()">
                <i class="fas fa-sync-alt me-1"></i>${gettext('Retry')}
              </button>
            </div>`;
        }

        // Still show the modal to display the error
        let modalId;
        switch (type) {
          case 'active':
            modalId = 'activeRentalsModal';
            break;
          case 'returned':
            modalId = 'returnedRentalsModal';
            break;
          case 'overdue':
            modalId = 'overdueRentalsModal';
            break;
          default:
            return;
        }

        const modal = new bootstrap.Modal(document.getElementById(modalId));
        modal.show();
      }
    }

    renderRentalDetails(contentId, data) {
      const container = document.getElementById(contentId);
      if (!container) return;

      // Check if data is valid
      if (!data || typeof data !== 'object') {
        container.innerHTML = `
          <div class="text-center p-4">
            <i class="fas fa-exclamation-triangle fa-3x text-danger mb-3"></i>
            <h6>${gettext('Invalid data received')}</h6>
            <p class="text-danger">${gettext('The server returned invalid data. Please try again.')}</p>
          </div>`;
        return;
      }

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
            <div class="text-center p-4">
              <i class="fas fa-inbox fa-3x text-muted mb-3"></i>
              <h6>${gettext('No')} ${this.getTypeLabel(type)} ${gettext('found')}</h6>
              <p class="text-muted">${gettext('No')} ${this.getTypeLabel(type).toLowerCase()} ${gettext('found for')} ${user.name || user.email}.</p>
            </div>
          </div>`;
        return;
      }

      let html = `
        <div class="rental-details-header">
          <h5>${this.getTypeLabel(type)}</h5>
          <div class="user-info">
            <strong>${gettext('User')}:</strong> ${user.name} (${user.email})
          </div>
        </div>
        <div class="rental-details-content">`;

      rentals.forEach(rental => {
        // Debug: log rental object to see what fields are available

        // Safe date parsing with fallbacks
        let startDate = 'N/A';
        let endDate = 'N/A';
        let actualEndDate = 'N/A';

        try {
          if (rental.requested_start_date) {
            const startDateObj = new Date(rental.requested_start_date);
            if (!isNaN(startDateObj.getTime())) {
              startDate = startDateObj.toLocaleString('de-DE', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
              });
            }
          }
        } catch (e) {
          console.warn('Error parsing start date:', e);
        }

        try {
          if (rental.requested_end_date) {
            const endDateObj = new Date(rental.requested_end_date);
            if (!isNaN(endDateObj.getTime())) {
              endDate = endDateObj.toLocaleString('de-DE', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
              });
            }
          }
        } catch (e) {
          console.warn('Error parsing end date:', e);
        }

        try {
          if (rental.actual_end_date) {
            const actualEndDateObj = new Date(rental.actual_end_date);
            if (!isNaN(actualEndDateObj.getTime())) {
              actualEndDate = actualEndDateObj.toLocaleString('de-DE', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
              });
            }
          }
        } catch (e) {
          console.warn('Error parsing actual end date:', e);
        }

        // Safe field access with fallbacks
        const projectName = rental.project_name || rental.id || gettext('Unnamed rental');
        const rentalId = rental.id || 'N/A';
        const purpose = rental.purpose && rental.purpose.trim() ? rental.purpose : (rental.project_name || gettext('No purpose specified'));
        const createdBy = rental.created_by || gettext('Not specified');
        const daysOverdue = rental.days_overdue || 0;

        html += `
          <div class="rental-card">
            <div class="card-header d-flex justify-content-between align-items-center">
              <div>
                <h6 class="mb-0">${projectName}</h6>
                <small class="text-muted">ID: ${rentalId}</small>
              </div>
              <div class="d-flex align-items-center gap-2">
                <span class="badge ${this.getStatusBadgeClass(rental.status)}">${this.getStatusLabelForRental(rental)}</span>
                ${type === 'overdue' && daysOverdue > 0 ? `<span class="badge bg-danger ms-1">${daysOverdue} ${gettext('days overdue')} (${gettext('expected')} ${endDate})</span>` : ''}
                ${this.getRentalActionButtons(rental, type)}
                <a href="/rental/rental/${rentalId}/" class="btn btn-sm btn-outline-primary ms-1" title="${gettext('Show details')}">
                  <i class="fas fa-eye"></i>
                </a>
              </div>
            </div>
            <div class="card-body">
              <div class="rental-info-row">
                <div class="rental-info-item">
                  <strong>${gettext('Purpose')}:</strong>
                  <span>${purpose}</span>
                </div>
                <div class="rental-info-item">
                  <strong>${gettext('Created by')}:</strong>
                  <span>${createdBy}</span>
                </div>
              </div>
              <div class="rental-info-row">
                <div class="rental-info-item">
                  <strong>${gettext('Planned from')}:</strong>
                  <span>${startDate}</span>
                </div>
                <div class="rental-info-item">
                  <strong>${gettext('Planned until')}:</strong>
                  <span>${endDate}</span>
                </div>
              </div>
              ${type === 'returned' ? `
              <div class="rental-info-row">
                <div class="rental-info-item">
                  <strong>${gettext('Returned')}:</strong>
                  <span>${actualEndDate}</span>
                </div>
              </div>` : ''}

              ${rental.items && rental.items.length > 0 ? `
              <div class="rental-section">
                <h6><i class="fas fa-boxes"></i>${gettext('Equipment')} (${rental.items.length} ${gettext('items')})</h6>
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

        if (rental.items && Array.isArray(rental.items) && rental.items.length > 0) {
          rental.items.forEach(item => {
            try {
              // Handle both old and new data structure for inventory item info
              const itemInfo = item.inventory_item || item;
              const description = itemInfo.description || itemInfo.inventory_number || gettext('Unknown item');
              const inventoryNumber = itemInfo.inventory_number || gettext('N/A');
              const quantityRequested = item.quantity_requested || 0;
              const quantityIssued = item.quantity_issued || 0;
              const quantityReturned = item.quantity_returned || 0;
              const outstanding = item.outstanding || 0;

              html += `
                <tr>
                  <td>
                    <strong>${description}</strong><br>
                    <small class="text-muted">[${inventoryNumber}]</small>
                  </td>
                  <td>${quantityRequested}</td>
                  <td>${quantityIssued}</td>
                  <td>${quantityReturned}</td>
                  ${type === 'active' ? `<td><span class="badge ${outstanding > 0 ? 'bg-warning' : 'bg-success'}">${outstanding}</span></td>` : ''}
                </tr>`;
            } catch (e) {
              console.warn('Error rendering item:', e, item);
              html += `
                <tr class="table-warning">
                  <td colspan="${type === 'active' ? '5' : '4'}">
                    <small class="text-muted">${gettext('Error rendering item')}</small>
                  </td>
                </tr>`;
            }
          });

          html += `
                  </tbody>
                </table>
              </div>
            </div>`;
        }

        // Add rooms section if there are rooms
        if (rental.room_rentals && Array.isArray(rental.room_rentals) && rental.room_rentals.length > 0) {
          html += `
            <div class="rental-section">
              <h6><i class="fas fa-building"></i>${gettext('Rooms')} (${rental.room_rentals.length} ${gettext('rooms')})</h6>
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
            try {
              const roomName = roomRental.room && roomRental.room.name ? roomRental.room.name : gettext('Unknown room');
              const roomLocation = roomRental.room && roomRental.room.location ? roomRental.room.location : gettext('Location not specified');
              const roomCapacity = roomRental.room && roomRental.room.capacity ? roomRental.room.capacity : gettext('Unknown');
              const peopleCount = roomRental.people_count || 0;
              const notes = roomRental.notes || '-';

              html += `
                <tr>
                  <td>
                    <strong>${roomName}</strong><br>
                    <small class="text-muted">[${roomLocation}]</small>
                  </td>
                  <td>${roomCapacity} ${gettext('people')}</td>
                  <td>${peopleCount} ${gettext('people')}</td>
                  <td>${notes}</td>
                </tr>`;
            } catch (e) {
              console.warn('Error rendering room rental:', e, roomRental);
              html += `
                <tr class="table-warning">
                  <td colspan="4">
                    <small class="text-muted">${gettext('Error rendering room')}</small>
                  </td>
                </tr>`;
            }
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

      container.querySelectorAll('.issue-from-reservation-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const rentalId = e.currentTarget.dataset.rentalId;
          this.showIssueFromReservationModal(rentalId);
        });
      });
    }

    getRentalActionButtons(rental, type) {
      if (type !== 'active') return '';

      let buttons = '';

      // Issue from Reservation button for reserved rentals with equipment
      if (rental.status === 'reserved' && rental.items && rental.items.length > 0) {
        buttons += `
          <button class="btn btn-sm btn-outline-warning issue-from-reservation-btn me-1"
                  data-rental-id="${rental.id}"
                  title="${gettext('Issue Equipment from Reservation')}">
              <i class="fas fa-box-open"></i>
          </button>`;
      }

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

        const formattedCurrentDate = currentEndDate.toLocaleString('de-DE', {
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit'
        });

        const currentEndDateElement = document.getElementById('extendCurrentEndDate');

        if (currentEndDateElement) {
          currentEndDateElement.innerHTML = `<strong>${formattedCurrentDate}</strong>`;
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
                            <i class="fas fa-check-circle me-2"></i>
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
                    statusElement.innerHTML = `
                        <div class="alert alert-danger">
                            <i class="fas fa-times-circle me-2"></i>
                            ${gettext('Room is not available for the selected period.')}
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
                        <i class="fas fa-exclamation-triangle me-2"></i>
                        ${gettext('Error checking room availability:')} ${data.error}
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
                    <i class="fas fa-exclamation-triangle me-2"></i>
                    ${gettext('Error checking room availability:')} ${error.message}
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

    async finalRoomAvailabilityCheck(roomId, startDate, startTime, endDate, endTime, onSuccess) {
        try {
            const url = `${URLS.checkRoomAvailability}?room_id=${roomId}&start_date=${startDate}&start_time=${startTime}&end_date=${endDate}&end_time=${endTime}`;

            const resp = await fetch(url);
            const data = await resp.json();

            if (data.success && data.is_available) {
                // Room is available, execute success callback
                onSuccess();
            } else {
                // Room is not available, show error
                const conflicts = data.conflicts && data.conflicts.length > 0 ?
                    `<br><small class="mt-2"><strong>${gettext('Conflicts:')}</strong><br>${data.conflicts.join('<br>')}</small>` : '';

                alert(gettext('Room is not available for the selected period.') + conflicts);
            }
        } catch (error) {
            console.error('Error checking room availability:', error);
            alert(gettext('Error checking room availability. Please try again.'));
        }
    }

    // Issue from Reservation functionality
    async showIssueFromReservationModal(rentalId) {
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
            const rental = data.rentals && data.rentals.find(r => r.id == rentalId);

            if (!rental) {
                alert(gettext('Rental not found'));
                return;
            }

            // Store rental data for processing
            this.currentIssueRental = rental;

            // Check if rental has equipment items
            if (!rental.items || rental.items.length === 0) {
                alert(gettext('This rental has no equipment items. Only equipment can be issued from reservation.'));
                return;
            }

            // Load staff users for dropdown
            await this.loadStaffUsers();

            // Render items in the modal
            this.renderIssueItems(rental);

            // Set default dates and times
            const startDate = new Date(rental.requested_start_date);
            const endDate = new Date(rental.requested_end_date);

            document.getElementById('issueStartDate').value = startDate.toISOString().split('T')[0];
            document.getElementById('issueEndDate').value = endDate.toISOString().split('T')[0];
            document.getElementById('issueStartTime').value = '10:00';
            document.getElementById('issueEndTime').value = '18:00';

            // Show modal
            const modal = new bootstrap.Modal(document.getElementById('issueFromReservationModal'));
            modal.show();

        } catch (error) {
            console.error('Error showing issue from reservation modal:', error);
            alert(gettext('Error loading rental details'));
        }
    }

    async loadStaffUsers() {
        try {
            const resp = await fetch(URLS.getStaffUsers);
            if (!resp.ok) {
                throw new Error(`HTTP error! status: ${resp.status}`);
            }

            const data = await resp.json();
            if (!data.success) {
                throw new Error(data.error || 'Failed to load staff users');
            }

            const select = document.getElementById('issueCreatedBy');
            if (!select) return;

            // Clear existing options except the first one
            select.innerHTML = '<option value="">' + gettext('Select staff member') + '</option>';

            // Add staff users
            data.users.forEach(user => {
                const option = document.createElement('option');
                option.value = user.id;
                option.textContent = `${user.name} (${user.email})`;
                select.appendChild(option);
            });

        } catch (error) {
            console.error('Error loading staff users:', error);
        }
    }

    renderIssueItems(rental) {
        const container = document.getElementById('issueItemsList');
        if (!container) return;

        if (!rental.items || rental.items.length === 0) {
            container.innerHTML = '<p class="text-muted">No equipment items in this rental.</p>';
            return;
        }

        let html = '';
        rental.items.forEach(item => {
            const itemInfo = item.inventory_item || item;
            const description = itemInfo.description || itemInfo.inventory_number || gettext('Unknown item');
            const inventoryNumber = itemInfo.inventory_number || gettext('N/A');
            const quantityRequested = item.quantity_requested || 0;
            const quantityIssued = item.quantity_issued || 0;

            html += `
                <div class="card mb-2">
                    <div class="card-body p-2">
                        <div class="row align-items-center">
                            <div class="col-md-6">
                                <strong>${description}</strong><br>
                                <small class="text-muted">[${inventoryNumber}]</small>
                            </div>
                            <div class="col-md-3">
                                <label class="form-label form-label-sm">${gettext('Requested')}:</label>
                                <input type="number" class="form-control form-control-sm issue-quantity"
                                       data-item-id="${item.id}" data-requested="${quantityRequested}"
                                       value="${quantityIssued || quantityRequested}" min="0" max="${quantityRequested}">
                            </div>
                            <div class="col-md-3">
                                <label class="form-label form-label-sm">${gettext('Issued')}:</label>
                                <span class="badge ${quantityIssued > 0 ? 'bg-success' : 'bg-warning'}">${quantityIssued || 0}</span>
                            </div>
                        </div>
                    </div>
                </div>`;
        });

        container.innerHTML = html;
    }

    renderIssueRooms(rental) {
        const container = document.getElementById('issueRoomsList');
        if (!container) return;

        if (!rental.room_rentals || rental.room_rentals.length === 0) {
            container.innerHTML = '<p class="text-muted">No rooms in this rental.</p>';
            return;
        }

        let html = '';
        rental.room_rentals.forEach(roomRental => {
            const room = roomRental.room || roomRental;
            const roomName = room.name || room.description || gettext('Unknown room');
            const roomNumber = room.room_number || gettext('N/A');

            html += `
                <div class="card mb-2">
                    <div class="card-body p-2">
                        <div class="row align-items-center">
                            <div class="col-md-8">
                                <strong>${roomName}</strong><br>
                                <small class="text-muted">[${roomNumber}]</small>
                            </div>
                            <div class="col-md-4">
                                <label class="form-label form-label-sm">${gettext('Status')}:</label>
                                <span class="badge bg-info">${gettext('Reserved')}</span>
                            </div>
                        </div>
                    </div>
                </div>`;
        });

        container.innerHTML = html;
    }

    async processIssueFromReservation() {
        try {
            if (!this.currentIssueRental) {
                alert(gettext('No rental selected for processing'));
                return;
            }

            // Collect form data
            const startDate = document.getElementById('issueStartDate').value;
            const endDate = document.getElementById('issueEndDate').value;
            const startTime = document.getElementById('issueStartTime').value;
            const endTime = document.getElementById('issueEndTime').value;
            const createdBy = document.getElementById('issueCreatedBy').value;
            const notes = document.getElementById('issueNotes').value;

            if (!startDate || !endDate || !startTime || !endTime || !createdBy) {
                alert(gettext('Please fill in all required fields'));
                return;
            }

            // Collect item quantities
            const itemQuantities = {};
            const quantityInputs = document.querySelectorAll('.issue-quantity');
            quantityInputs.forEach(input => {
                const itemId = input.dataset.itemId;
                const quantity = parseInt(input.value) || 0;
                itemQuantities[itemId] = quantity;
            });

            // Prepare data for API
            const issueData = {
                rental_id: this.currentIssueRental.id,
                start_date: `${startDate}T${startTime}`,
                end_date: `${endDate}T${endTime}`,
                created_by: createdBy,
                notes: notes,
                item_quantities: itemQuantities
            };

            // Send request to API
            const resp = await fetch(URLS.issueFromReservation, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': CSRF_TOKEN,
                },
                body: JSON.stringify(issueData)
            });

            const data = await resp.json();

            if (data.success) {
                alert(gettext('Rental successfully issued from reservation'));

                // Close modal
                const modal = bootstrap.Modal.getInstance(document.getElementById('issueFromReservationModal'));
                modal.hide();

                // Refresh rental details
                if (this.selectedUser) {
                    this.showRentalDetails(this.selectedUser.id, 'active');
                    this.loadUserStats(this.selectedUser.id);
                    this.loadActiveItems(this.selectedUser.id);
                }

                // Clear current rental
                this.currentIssueRental = null;
            } else {
                alert(data.error || gettext('Error issuing rental from reservation'));
            }
        } catch (error) {
            console.error('Error processing issue from reservation:', error);
            alert(gettext('Network error processing issue from reservation'));
        }
    }
  }

  // Check if URLS are defined
  if (typeof URLS === 'undefined') {
    console.error('URLS not defined - check template');
  } else {
    console.log('URLS available:', URLS); // TODO: remove
  }

  new RentalProcess();
});
