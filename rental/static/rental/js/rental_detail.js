// Rental Detail Page JavaScript

// Django i18n support
const gettext = window.gettext || function(str) { return str; };
const ngettext = window.ngettext || function(singular, plural, count) { return count === 1 ? singular : plural; };

document.addEventListener('DOMContentLoaded', function() {
    class RentalDetailManager {
        constructor() {
            this.initializeData();
            this.bindEvents();
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
                    cancelRental: dataElement.dataset.cancelUrl || ''
                };
            } else {
                this.rentalId = 0;
                this.csrfToken = '';
                this.urls = {};
            }
        }

        bindEvents() {
            // Extend button
            const extendBtn = document.getElementById('extendBtn');
            if (extendBtn) extendBtn.addEventListener('click', this.showExtendModal.bind(this));

            // Return button
            const returnBtn = document.getElementById('returnBtn');
            if (returnBtn) returnBtn.addEventListener('click', this.toggleReturnForms.bind(this));

            // Cancel button
            const cancelBtn = document.getElementById('cancelBtn');
            if (cancelBtn) cancelBtn.addEventListener('click', this.cancelRental.bind(this));

            // Extend modal confirm
            const confirmExtend = document.getElementById('confirmExtend');
            if (confirmExtend) confirmExtend.addEventListener('click', this.extendRental.bind(this));

            // Add issue buttons
            document.addEventListener('click', (e) => {
                if (e.target.classList.contains('add-issue-btn')) {
                    this.addIssueForm(e.target);
                }
            });
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
            const returnForms = document.querySelectorAll('.return-form');
            const returnBtn = document.getElementById('returnBtn');

            const isVisible = !returnForms[0].classList.contains('d-none');

            returnForms.forEach(form => {
                if (isVisible) {
                    form.classList.add('d-none');
                } else {
                    form.classList.remove('d-none');
                }
            });

            if (isVisible) {
                returnBtn.innerHTML = '<i class="fas fa-undo me-1"></i>' + gettext('Edit return');
                returnBtn.className = 'btn btn-outline-success';
            } else {
                returnBtn.innerHTML = '<i class="fas fa-save me-1"></i>' + gettext('Save return');
                returnBtn.className = 'btn btn-success';
                returnBtn.onclick = () => this.processReturns();
            }
        }

        async processReturns() {
            const returnForms = document.querySelectorAll('.return-form:not(.d-none)');
            const items = [];

            returnForms.forEach(form => {
                const itemId = form.dataset.itemId;
                const quantity = parseInt(form.querySelector('.return-quantity').value) || 0;
                const condition = form.querySelector('.return-condition').value;
                const notes = form.querySelector('.return-notes').value;
                const issues = this.collectIssues(form);

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
