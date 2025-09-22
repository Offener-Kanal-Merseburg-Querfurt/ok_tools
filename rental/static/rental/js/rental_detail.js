// Rental Detail Page JavaScript

// Django i18n support
const gettext = window.gettext || function(str) { return str; };
const ngettext = window.ngettext || function(singular, plural, count) { return count === 1 ? singular : plural; };

document.addEventListener('DOMContentLoaded', function() {
    class RentalDetailManager {
        constructor() {
            this.initializeData();
            this.bindEvents();
            this.initializeReturnState();
            console.log('RentalDetailManager initialized for rental:', this.rentalId);
        }

        initializeData() {
            const dataElement = document.getElementById('rental-data');
            if (dataElement) {
                this.rentalId = parseInt(dataElement.dataset.rentalId) || 0;
                this.csrfToken = dataElement.dataset.csrfToken || '';
                this.urls = {
                    extendRental: dataElement.dataset.extendUrl || '',
                    returnItems: dataElement.dataset.returnUrl || '',
                    cancelRental: dataElement.dataset.cancelUrl || '',
                    issueFromReservation: dataElement.dataset.issueFromReservationUrl || '',
                    getStaffUsers: dataElement.dataset.getStaffUsersUrl || '',
                    searchInventory: dataElement.dataset.searchInventoryUrl || ''
                };
            } else {
                this.rentalId = 0;
                this.csrfToken = '';
                this.urls = {};
            }
        }

        initializeReturnState() {
            // Initially disable all checkboxes and hide return forms
            const checkboxes = document.querySelectorAll('.item-return-checkbox');
            checkboxes.forEach(checkbox => {
                checkbox.disabled = false; // Enable checkboxes by default
                checkbox.checked = false;
            });

            // Hide all return forms initially
            const returnForms = document.querySelectorAll('.return-form');
            returnForms.forEach(form => {
                form.classList.add('d-none');
            });

            // Set initial button state only if return button exists
            this.updateReturnButtonState();
        }

        bindEvents() {
            // Extend button
            const extendBtn = document.getElementById('extendBtn');
            if (extendBtn) extendBtn.addEventListener('click', this.showExtendModal.bind(this));

            // Return button
            const returnBtn = document.getElementById('returnBtn');
            if (returnBtn) {
                returnBtn.addEventListener('click', (e) => {
                    if (returnBtn.classList.contains('btn-success') && returnBtn.classList.contains('btn-outline-success') === false) {
                        // Solid green button - process returns
                        this.processReturns();
                    } else {
                        // Outline button - toggle return mode
                        this.toggleReturnForms();
                    }
                });
            }

            // Cancel button
            const cancelBtn = document.getElementById('cancelBtn');
            if (cancelBtn) cancelBtn.addEventListener('click', this.cancelRental.bind(this));

            // Issue from Reservation button
            const issueFromReservationBtn = document.getElementById('issueFromReservationBtn');
            if (issueFromReservationBtn) issueFromReservationBtn.addEventListener('click', this.showIssueFromReservationModal.bind(this));

            // Extend modal confirm
            const confirmExtend = document.getElementById('confirmExtend');
            if (confirmExtend) confirmExtend.addEventListener('click', this.extendRental.bind(this));

            // Add issue buttons
            document.addEventListener('click', (e) => {
                if (e.target.classList.contains('add-issue-btn')) {
                    this.addIssueForm(e.target);
                }
            });

            // Process Issue from Reservation button
            const processIssueFromReservationBtn = document.getElementById('processIssueFromReservationBtn');
            if (processIssueFromReservationBtn) processIssueFromReservationBtn.addEventListener('click', this.processIssueFromReservation.bind(this));

            // Item return checkboxes
            document.addEventListener('change', (e) => {
                if (e.target.classList.contains('item-return-checkbox')) {
                    this.handleItemSelection(e.target);
                }
            });
        }

        handleItemSelection(checkbox) {
            const itemCard = checkbox.closest('.item-card');
            const itemId = checkbox.dataset.itemId;
            const isChecked = checkbox.checked;

            if (isChecked) {
                itemCard.classList.add('selected-for-return');
                // Show return form for this item
                const returnForm = itemCard.querySelector('.return-form');
                if (returnForm) {
                    returnForm.classList.remove('d-none');
                }
            } else {
                itemCard.classList.remove('selected-for-return');
                // Hide return form for this item
                const returnForm = itemCard.querySelector('.return-form');
                if (returnForm) {
                    returnForm.classList.add('d-none');
                }
            }

            // Update return button state
            this.updateReturnButtonState();
        }

        updateReturnButtonState() {
            const selectedItems = document.querySelectorAll('.item-return-checkbox:checked');
            const returnBtn = document.getElementById('returnBtn');

            // Check if return button exists (it might not be rendered if can_return is False)
            if (!returnBtn) {
                return;
            }

            if (selectedItems.length > 0) {
                returnBtn.disabled = false;
                returnBtn.className = 'btn btn-success';
                returnBtn.innerHTML = '<i class="fas fa-save me-1"></i>' + gettext('Save return');
            } else {
                returnBtn.disabled = false; // Allow clicking even without selection
                returnBtn.className = 'btn btn-outline-success';
                returnBtn.innerHTML = '<i class="fas fa-save me-1"></i>' + gettext('Save return');
            }
        }

        showExtendModal() {
            const modal = new bootstrap.Modal(document.getElementById('extendModal'));

            // Get current end date from the page data
            const currentEndDateText = document.querySelector('[data-rental-id]').dataset.currentEndDate;
            if (currentEndDateText) {
                const currentEndDate = new Date(currentEndDateText);
                const formattedCurrentDate = currentEndDate.toLocaleString('de-DE', {
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit'
                });

                document.getElementById('currentEndDateDisplay').innerHTML = `<strong>${formattedCurrentDate}</strong>`;
            }

            // Set minimum date to current end date + 1 hour
            const currentEndDate = new Date(document.querySelector('[data-rental-id]').dataset.currentEndDate);
            currentEndDate.setHours(currentEndDate.getHours() + 1);
            const minDate = currentEndDate.toISOString().slice(0, 16);
            document.getElementById('newEndDate').min = minDate;
            document.getElementById('newEndDate').value = minDate;

            modal.show();
        }

        async extendRental() {
            const newEndDate = document.getElementById('newEndDate').value;
            if (!newEndDate) {
                alert(gettext('Please select a new end date'));
                return;
            }

            try {
                console.log('Extending rental:', this.rentalId, 'with date:', newEndDate);

                // First, try sending the date as-is (datetime-local format)
                let resp = await fetch(this.urls.extendRental, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({
                        rental_id: this.rentalId,
                        new_end_date: newEndDate
                    })
                });

                let data = await resp.json();

                // If datetime-local format failed, try ISO format
                if (!data.success && data.error && data.error.includes('Invalid date format')) {
                    console.log('Datetime-local format failed, trying ISO format...');

                    const dateObj = new Date(newEndDate);
                    if (isNaN(dateObj.getTime())) {
                        alert(gettext('Invalid date format'));
                        return;
                    }
                    const isoDate = dateObj.toISOString();

                    console.log('Retrying with ISO date:', isoDate);

                    resp = await fetch(this.urls.extendRental, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': this.csrfToken,
                        },
                        body: JSON.stringify({
                            rental_id: this.rentalId,
                            new_end_date: isoDate
                        })
                    });

                    data = await resp.json();
                }

                if (data.success) {
                    alert(data.message);
                    location.reload();
                } else {
                    alert(data.error || gettext('Error extending rental'));
                }
            } catch (error) {
                console.error('Extend error:', error);
                alert(gettext('Network error'));
            }
        }

        toggleReturnForms() {
            const returnBtn = document.getElementById('returnBtn');
            if (!returnBtn) return;

            const isReturnMode = returnBtn.classList.contains('btn-outline-success') === false;

            if (isReturnMode) {
                // Exit return mode
                this.exitReturnMode();
            } else {
                // Enter return mode
                this.enterReturnMode();
            }
        }

        enterReturnMode() {
            const returnBtn = document.getElementById('returnBtn');
            if (!returnBtn) return;

            returnBtn.innerHTML = '<i class="fas fa-undo me-1"></i>' + gettext('Exit return mode');
            returnBtn.className = 'btn btn-outline-success';

            // Show checkboxes for all items that can be returned
            const checkboxes = document.querySelectorAll('.item-return-checkbox');
            checkboxes.forEach(checkbox => {
                checkbox.disabled = false;
            });

            // Update button state
            this.updateReturnButtonState();
        }

        exitReturnMode() {
            const returnBtn = document.getElementById('returnBtn');
            if (!returnBtn) return;

            returnBtn.innerHTML = '<i class="fas fa-save me-1"></i>' + gettext('Save return');
            returnBtn.className = 'btn btn-outline-success';

            // Hide all return forms
            const returnForms = document.querySelectorAll('.return-form');
            returnForms.forEach(form => {
                form.classList.add('d-none');
            });

            // Uncheck all checkboxes and remove selection styling
            const checkboxes = document.querySelectorAll('.item-return-checkbox');
            checkboxes.forEach(checkbox => {
                checkbox.checked = false;
                const itemCard = checkbox.closest('.item-card');
                itemCard.classList.remove('selected-for-return');
            });

            // Reset button state to initial
            returnBtn.disabled = false;
            returnBtn.className = 'btn btn-outline-success';
            returnBtn.innerHTML = '<i class="fas fa-save me-1"></i>' + gettext('Save return');
        }

        async processReturns() {
            const selectedCheckboxes = document.querySelectorAll('.item-return-checkbox:checked');
            const items = [];

            if (selectedCheckboxes.length === 0) {
                alert(gettext('No items selected for return'));
                return;
            }

            selectedCheckboxes.forEach(checkbox => {
                const itemId = checkbox.dataset.itemId;
                const itemCard = checkbox.closest('.item-card');
                const returnForm = itemCard.querySelector('.return-form');

                if (returnForm) {
                    const quantity = parseInt(returnForm.querySelector('.return-quantity').value) || 0;
                    const condition = returnForm.querySelector('.return-condition').value;
                    const notes = returnForm.querySelector('.return-notes').value;
                    const issues = this.collectIssues(returnForm);

                    if (quantity > 0) {
                        items.push({
                            rental_item_id: itemId,
                            quantity: quantity,
                            condition: condition,
                            notes: notes,
                            issues: issues
                        });
                    }
                }
            });

            if (items.length === 0) {
                alert(gettext('No items to return selected'));
                return;
            }

            try {
                const resp = await fetch(this.urls.returnItems, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({
                        rental_id: this.rentalId,
                        items: items
                    })
                });

                const data = await resp.json();

                if (data.success) {
                    alert(data.message);
                    if (data.rental_completed) {
                        alert(gettext('All items were returned. The rental is completed.'));
                    }
                    location.reload();
                } else {
                    alert(data.error || gettext('Error returning items'));
                }
            } catch (error) {
                console.error('Return error:', error);
                alert(gettext('Network error'));
            }
        }

        collectIssues(form) {
            const issues = [];
            const issueContainers = form.querySelectorAll('.issue-form');

            issueContainers.forEach(container => {
                const issueType = container.querySelector('.issue-type').value;
                const description = container.querySelector('.issue-description').value;
                const severity = container.querySelector('.issue-severity').value;

                if (issueType && description) {
                    issues.push({
                        issue_type: issueType,
                        description: description,
                        severity: severity
                    });
                }
            });

            return issues;
        }

        addIssueForm(button) {
            const container = button.parentElement;
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

            // Add before the add button
            container.insertBefore(issueForm, button);

            // Bind remove button
            issueForm.querySelector('.remove-issue-btn').addEventListener('click', () => {
                issueForm.remove();
            });
        }

        // Issue from Reservation functionality
        async showIssueFromReservationModal() {
            // Check if rental has equipment items
            const itemCards = document.querySelectorAll('#itemsList .item-card');
            if (itemCards.length === 0) {
                alert(gettext('This rental has no equipment items. Only equipment can be issued from reservation.'));
                return;
            }

            // Load staff users for dropdown
            await this.loadStaffUsers();

            // Render items in the modal
            this.renderIssueItems();

            // Get current rental dates from the page
            const rentalData = document.querySelector('#rental-data');
            let startDate, endDate, startTime, endTime;

            if (rentalData && rentalData.dataset.startDate && rentalData.dataset.endDate) {
                // Parse dates from dataset
                startDate = rentalData.dataset.startDate;
                endDate = rentalData.dataset.endDate;
                startTime = rentalData.dataset.startTime || '10:00';
                endTime = rentalData.dataset.endTime || '18:00';
            } else {
                // Fallback to current date
                const today = new Date();
                startDate = today.toISOString().split('T')[0];
                endDate = today.toISOString().split('T')[0];
                startTime = '10:00';
                endTime = '18:00';
            }

            // Set dates and times in the modal
            document.getElementById('issueStartDate').value = startDate;
            document.getElementById('issueEndDate').value = endDate;
            document.getElementById('issueStartTime').value = startTime;
            document.getElementById('issueEndTime').value = endTime;

            // Show modal
            const modal = new bootstrap.Modal(document.getElementById('issueFromReservationModal'));
            modal.show();
        }

        async loadStaffUsers() {
            try {
                const resp = await fetch(this.urls.getStaffUsers);
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

        renderIssueItems() {
            const container = document.getElementById('issueItemsList');
            if (!container) return;

            let html = '';

            // Add button to add new items
            html += `
                <div class="mb-3">
                    <button type="button" class="btn btn-outline-primary btn-sm" id="addItemToIssueBtn">
                        <i class="fas fa-plus me-1"></i>${gettext('Add Equipment')}
                    </button>
                </div>
            `;

            // Get items from the page
            const itemCards = document.querySelectorAll('#itemsList .item-card');
            if (itemCards.length === 0) {
                html += `<p class="text-muted">${gettext('No equipment items in this rental.')}</p>`;
                container.innerHTML = html;
                return;
            }

            itemCards.forEach(itemCard => {
                const itemId = itemCard.dataset.itemId;
                const description = itemCard.querySelector('h6').textContent;
                const inventoryNumber = itemCard.querySelector('.badge').textContent;
                const quantityRequested = parseInt(itemCard.querySelector('.col-4:first-child strong').textContent);
                const quantityIssued = parseInt(itemCard.querySelector('.col-4:nth-child(2) strong').textContent);

                html += `
                    <div class="card mb-2" data-rental-item-id="${itemId}">
                        <div class="card-body p-2">
                            <div class="row align-items-center">
                                <div class="col-md-5">
                                    <strong>${description}</strong><br>
                                    <small class="text-muted">[${inventoryNumber}]</small>
                                </div>
                                <div class="col-md-2">
                                    <label class="form-label form-label-sm">${gettext('Requested')}:</label>
                                    <input type="number" class="form-control form-control-sm issue-quantity"
                                           data-item-id="${itemId}" data-requested="${quantityRequested}"
                                           value="${quantityIssued || quantityRequested}" min="0" max="${quantityRequested}">
                                </div>
                                <div class="col-md-2">
                                    <label class="form-label form-label-sm">${gettext('Issued')}:</label>
                                    <span class="badge ${quantityIssued > 0 ? 'bg-success' : 'bg-warning'}">${quantityIssued || 0}</span>
                                </div>
                                <div class="col-md-3 text-end">
                                    <button type="button" class="btn btn-outline-danger btn-sm remove-item-btn"
                                            data-item-id="${itemId}" title="${gettext('Remove item')}">
                                        <i class="fas fa-trash"></i>
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>`;
            });

            container.innerHTML = html;

            // Add event listeners
            this.attachIssueItemEventListeners();
        }

        attachIssueItemEventListeners() {
            // Remove existing event listeners first to prevent duplicates
            const addItemBtn = document.getElementById('addItemToIssueBtn');
            if (addItemBtn) {
                // Clone the button to remove all event listeners
                const newBtn = addItemBtn.cloneNode(true);
                addItemBtn.parentNode.replaceChild(newBtn, addItemBtn);

                // Add fresh event listener
                newBtn.addEventListener('click', () => {
                    this.showAddItemModal();
                });
            }

            // Remove existing event listeners for remove buttons and add fresh ones
            document.querySelectorAll('.remove-item-btn').forEach(btn => {
                // Clone the button to remove all event listeners
                const newBtn = btn.cloneNode(true);
                btn.parentNode.replaceChild(newBtn, btn);

                // Add fresh event listener
                newBtn.addEventListener('click', (e) => {
                    const itemId = e.currentTarget.dataset.itemId;
                    this.removeItemFromIssue(itemId);
                });
            });
        }

        showAddItemModal() {
            // Show the add item modal
            const modal = new bootstrap.Modal(document.getElementById('addItemModal'));
            modal.show();

            // Load available items
            this.loadAvailableItems();

            // Add event listeners for search
            const searchInput = document.getElementById('addItemSearch');
            const searchBtn = document.getElementById('searchItemsBtn');

            if (searchInput) {
                let searchTimeout;
                searchInput.addEventListener('input', (e) => {
                    clearTimeout(searchTimeout);
                    searchTimeout = setTimeout(() => {
                        this.loadAvailableItems();
                    }, 300);
                });
            }

            if (searchBtn) {
                searchBtn.addEventListener('click', () => {
                    this.loadAvailableItems();
                });
            }
        }

        removeItemFromIssue(itemId) {
            if (confirm(gettext('Are you sure you want to remove this item from the issue?'))) {
                // Try to find the item by both selectors (existing rental items and new inventory items)
                let itemCard = document.querySelector(`[data-rental-item-id="${itemId}"]`);
                if (!itemCard) {
                    itemCard = document.querySelector(`[data-inventory-item-id="${itemId}"]`);
                }

                if (itemCard) {
                    itemCard.remove();
                } else {
                    console.error('Could not find item card for item ID:', itemId);
                }
            }
        }

        async loadAvailableItems() {
            try {
                const searchInput = document.getElementById('addItemSearch');
                const itemsContainer = document.getElementById('addItemItemsList');

                if (!searchInput || !itemsContainer) return;

                const query = searchInput.value || '';

                // Get dates from the issue modal
                const startDate = document.getElementById('issueStartDate').value;
                const endDate = document.getElementById('issueEndDate').value;

                // Build URL with parameters
                let url = `${this.urls.searchInventory}?q=${encodeURIComponent(query)}`;
                if (startDate && endDate) {
                    url += `&start_date=${startDate}&end_date=${endDate}`;
                }

                // Use the existing search API
                const response = await fetch(url);
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                const data = await response.json();

                if (data.items) {
                    this.renderAvailableItems(data.items, itemsContainer);
                }

            } catch (error) {
                console.error('Error loading available items:', error);
                alert(gettext('Error loading available items'));
            }
        }

        renderAvailableItems(items, container) {
            if (!items || items.length === 0) {
                container.innerHTML = `<p class="text-muted">${gettext('No items found.')}</p>`;
                return;
            }

            // Group items by category
            const groupedItems = {};
            items.forEach(item => {
                const category = item.category || 'Other';
                if (!groupedItems[category]) {
                    groupedItems[category] = [];
                }
                groupedItems[category].push(item);
            });

            let html = '';
            Object.keys(groupedItems).sort().forEach((category, index) => {
                const categoryId = `category-${index}`;
                html += `
                    <div class="mb-3">
                        <h6 class="text-primary border-bottom pb-1 d-flex justify-content-between align-items-center"
                            style="cursor: pointer;"
                            data-bs-toggle="collapse"
                            data-bs-target="#${categoryId}"
                            aria-expanded="true">
                            <span>${category}</span>
                            <i class="fas fa-chevron-down collapse-icon"></i>
                        </h6>
                        <div class="collapse show" id="${categoryId}">
                            <div class="row">
                `;

                groupedItems[category].forEach(item => {
                    const availableQty = item.available_quantity || 0;
                    html += `
                        <div class="col-md-6 mb-2">
                            <div class="card">
                                <div class="card-body p-2">
                                    <div class="d-flex justify-content-between align-items-center">
                                        <div>
                                            <strong>${item.description}</strong><br>
                                            <small class="text-muted">[${item.inventory_number}]</small><br>
                                            <small class="text-info">${item.location}</small><br>
                                            <small class="text-success">
                                                <i class="fas fa-check-circle me-1"></i>
                                                ${gettext('Available')}: ${availableQty}
                                            </small>
                                        </div>
                                        <button type="button" class="btn btn-outline-success btn-sm add-item-btn"
                                                data-item-id="${item.id}" data-item-name="${item.description}"
                                                ${availableQty <= 0 ? 'disabled' : ''}>
                                            <i class="fas fa-plus"></i>
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    `;
                });

                html += `
                            </div>
                        </div>
                    </div>
                `;
            });

            container.innerHTML = html;

            // Add event listeners for add buttons
            container.querySelectorAll('.add-item-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    const itemId = e.currentTarget.dataset.itemId;
                    const itemName = e.currentTarget.dataset.itemName;
                    this.addItemToIssue(itemId, itemName);
                });
            });

            // Add event listeners for collapse toggle icons
            container.querySelectorAll('[data-bs-toggle="collapse"]').forEach(trigger => {
                const target = document.querySelector(trigger.getAttribute('data-bs-target'));
                const icon = trigger.querySelector('.collapse-icon');

                if (target && icon) {
                    target.addEventListener('show.bs.collapse', () => {
                        icon.style.transform = 'rotate(180deg)';
                    });

                    target.addEventListener('hide.bs.collapse', () => {
                        icon.style.transform = 'rotate(0deg)';
                    });
                }
            });
        }

        addItemToIssue(itemId, itemName) {
            // Check if item is already in the issue
            const existingItem = document.querySelector(`[data-inventory-item-id="${itemId}"]`);
            if (existingItem) {
                alert(gettext('This item is already in the issue list.'));
                return;
            }

            // Add item to the issue items list
            const itemsList = document.getElementById('issueItemsList');
            if (!itemsList) return;

            // Find the add button and insert before it
            const addButton = itemsList.querySelector('#addItemToIssueBtn');
            if (!addButton) return;

            const newItemHtml = `
                <div class="card mb-2" data-inventory-item-id="${itemId}">
                    <div class="card-body p-2">
                        <div class="row align-items-center">
                            <div class="col-md-5">
                                <strong>${itemName}</strong><br>
                                <small class="text-muted">[${itemId}]</small>
                            </div>
                            <div class="col-md-2">
                                <label class="form-label form-label-sm">${gettext('Quantity')}:</label>
                                <input type="number" class="form-control form-control-sm issue-quantity"
                                       data-item-id="${itemId}" data-requested="1"
                                       value="1" min="1" max="1">
                            </div>
                            <div class="col-md-2">
                                <label class="form-label form-label-sm">${gettext('Issued')}:</label>
                                <span class="badge bg-warning">0</span>
                            </div>
                            <div class="col-md-3 text-end">
                                <button type="button" class="btn btn-outline-danger btn-sm remove-item-btn"
                                        data-item-id="${itemId}" title="${gettext('Remove item')}">
                                    <i class="fas fa-trash"></i>
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            `;

            // Insert the new item before the add button
            addButton.insertAdjacentHTML('beforebegin', newItemHtml);

            // Re-attach event listeners
            this.attachIssueItemEventListeners();

            // Disable the add button for this item
            const itemAddButton = document.querySelector(`[data-item-id="${itemId}"].add-item-btn`);
            if (itemAddButton) {
                itemAddButton.disabled = true;
                itemAddButton.innerHTML = '<i class="fas fa-check"></i>';
                itemAddButton.className = 'btn btn-success btn-sm';
            }

            // Show success message using the parameter
            // Create temporary success notification
            const notification = document.createElement('div');
            notification.className = 'alert alert-success alert-dismissible fade show position-fixed';
            notification.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
            notification.innerHTML = `
                <i class="fas fa-check-circle me-2"></i>
                <strong>${gettext('Item added')}:</strong> ${itemName}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            `;

            document.body.appendChild(notification);

            // Auto-remove notification after 3 seconds
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.remove();
                }
            }, 3000);
        }

        renderIssueRooms() {
            const container = document.getElementById('issueRoomsList');
            if (!container) return;

            // Get rooms from the page
            const roomCards = document.querySelectorAll('#roomsList .item-card');
            if (roomCards.length === 0) {
                container.innerHTML = `<p class="text-muted">${gettext('No rooms in this rental.')}</p>`;
                return;
            }

            let html = '';
            roomCards.forEach(roomCard => {
                const roomName = roomCard.querySelector('h6').textContent;
                const roomNumber = roomCard.querySelector('.badge').textContent;

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

                // Collect item quantities and new items
                const itemQuantities = {};
                const newItems = [];
                const quantityInputs = document.querySelectorAll('.issue-quantity');

                quantityInputs.forEach(input => {
                    const itemId = input.dataset.itemId;
                    const quantity = parseInt(input.value) || 0;

                    // Check if this is a new item (not in original rental)
                    const itemCard = input.closest('.card');
                    const isNewItem = itemCard && itemCard.hasAttribute('data-inventory-item-id');

                    if (isNewItem && quantity > 0) {
                        // This is a new item to be added
                        newItems.push({
                            inventory_id: itemId,
                            quantity: quantity
                        });
                    } else if (!isNewItem) {
                        // This is an existing rental item
                        itemQuantities[itemId] = quantity;
                    }
                });

                // Prepare data for API
                const issueData = {
                    rental_id: this.rentalId,
                    start_date: `${startDate}T${startTime}`,
                    end_date: `${endDate}T${endTime}`,
                    created_by: createdBy,
                    notes: notes,
                    item_quantities: itemQuantities,
                    new_items: newItems
                };

                // Send request to API
                const resp = await fetch(this.urls.issueFromReservation, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify(issueData)
                });

                const data = await resp.json();

                if (data.success) {
                    alert(gettext('Rental successfully issued from reservation'));

                    // Close modal
                    const modal = bootstrap.Modal.getInstance(document.getElementById('issueFromReservationModal'));
                    modal.hide();

                    // Reload page to show updated status
                    location.reload();
                } else {
                    alert(data.error || gettext('Error issuing rental from reservation'));
                }
            } catch (error) {
                console.error('Error processing issue from reservation:', error);
                alert(gettext('Network error processing issue from reservation'));
            }
        }

        async cancelRental() {
            if (!confirm(gettext('Are you sure you want to cancel this rental?'))) {
                return;
            }

            try {
                const resp = await fetch(this.urls.cancelRental, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({
                        rental_id: this.rentalId
                    })
                });

                const data = await resp.json();

                if (data.success) {
                    alert(data.message);
                    location.reload();
                } else {
                    alert(data.error || gettext('Error cancelling rental'));
                }
            } catch (error) {
                console.error('Cancel error:', error);
                alert(gettext('Network error'));
            }
        }
    }

    // Initialize if we have a rental ID
    if (document.getElementById('rental-data')) {
        new RentalDetailManager();
    }
});
