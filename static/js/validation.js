const MAX_AMOUNT = 99999999.99;
const MIN_YEAR = 2000;
const MAX_YEAR = 2100;
const MAX_DESCRIPTION_LENGTH = 500;
const MAX_SOURCE_LENGTH = 500;
const MAX_CSV_SIZE = 5 * 1024 * 1024;

(function () {
    'use strict';

    function isDeleteForm(form) {
        return form && form.matches('.delete-form');
    }

    function clearFieldError(field) {
        field.classList.remove('is-invalid');
        field.removeAttribute('aria-invalid');
        const errorId = field.id ? `${field.id}-error` : null;
        if (errorId) {
            const error = document.getElementById(errorId);
            if (error) error.remove();
            const describedBy = field.getAttribute('aria-describedby');
            if (describedBy === errorId) field.removeAttribute('aria-describedby');
        }
    }

    function showError(field, message) {
        clearFieldError(field);
        field.classList.add('is-invalid');
        field.setAttribute('aria-invalid', 'true');

        const errorId = field.id ? `${field.id}-error` : `error-${Date.now()}-${Math.random().toString(36).slice(2)}`;
        field.setAttribute('aria-describedby', errorId);

        const error = document.createElement('span');
        error.className = 'field-error';
        error.id = errorId;
        error.setAttribute('role', 'alert');
        error.textContent = message;

        field.insertAdjacentElement('afterend', error);
    }

    function validDateString(value) {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
        const parts = value.split('-').map(Number);
        const parsed = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
        if (
            parsed.getUTCFullYear() !== parts[0] ||
            parsed.getUTCMonth() !== parts[1] - 1 ||
            parsed.getUTCDate() !== parts[2]
        ) {
            return null;
        }
        return parsed;
    }

    function validateForm(form) {
        let valid = true;

        form.querySelectorAll('.is-invalid').forEach(clearFieldError);

        form.querySelectorAll('[required]').forEach(field => {
            if (!String(field.value || '').trim()) {
                valid = false;
                showError(field, 'This field is required.');
            }
        });

        form.querySelectorAll('input[name="amount"]').forEach(field => {
            const value = String(field.value || '').trim();
            if (!value) return;
            if (!/^\d+(?:\.\d{1,2})?$/.test(value)) {
                valid = false;
                showError(field, 'Enter a valid amount with at most 2 decimal places.');
                return;
            }
            const amount = Number(value);
            if (!Number.isFinite(amount) || amount < 0.01 || amount > MAX_AMOUNT) {
                valid = false;
                showError(field, `Amount must be between 0.01 and ${MAX_AMOUNT}.`);
            }
        });

        form.querySelectorAll('input[type="date"]').forEach(field => {
            const value = String(field.value || '').trim();
            if (!value) return;
            const parsed = validDateString(value);
            const year = parsed ? parsed.getUTCFullYear() : NaN;
            if (!parsed || year < MIN_YEAR || year > MAX_YEAR) {
                valid = false;
                showError(field, `Date must be between ${MIN_YEAR} and ${MAX_YEAR}.`);
            }
        });

        const fromDate = form.querySelector('[name="date_from"]');
        const toDate = form.querySelector('[name="date_to"]');
        if (fromDate && toDate && fromDate.value && toDate.value) {
            const from = validDateString(fromDate.value);
            const to = validDateString(toDate.value);
            if (from && to && from.getTime() > to.getTime()) {
                valid = false;
                showError(toDate, 'To date cannot be before from date.');
            }
        }

        form.querySelectorAll('input[name="description"]').forEach(field => {
            if (field.value.length > MAX_DESCRIPTION_LENGTH) {
                valid = false;
                showError(field, `Description cannot exceed ${MAX_DESCRIPTION_LENGTH} characters.`);
            }
        });

        form.querySelectorAll('input[name="source"]').forEach(field => {
            if (field.value.length > MAX_SOURCE_LENGTH) {
                valid = false;
                showError(field, `Source cannot exceed ${MAX_SOURCE_LENGTH} characters.`);
            }
        });

        form.querySelectorAll('input[name="alert_percentage"]').forEach(field => {
            if (!field.value) return;
            const value = Number(field.value);
            if (!Number.isFinite(value) || value < 1 || value > 100) {
                valid = false;
                showError(field, 'Alert percentage must be between 1 and 100.');
            }
        });

        return valid;
    }

    function setupForms() {
        document.querySelectorAll('form').forEach(form => {
            if (isDeleteForm(form)) return;

            form.addEventListener('submit', function (event) {
                if (form.dataset.submitting === 'true') {
                    event.preventDefault();
                    return;
                }

                if (!validateForm(form)) {
                    event.preventDefault();
                    return;
                }

                const csrf = form.querySelector('input[name="csrf_token"]');
                if (form.method.toUpperCase() === 'POST' && !csrf?.value) {
                    event.preventDefault();
                    window.alert('Security token is missing. Please reload the page and try again.');
                    return;
                }

                form.dataset.submitting = 'true';
                form.querySelectorAll('button[type="submit"]').forEach(button => {
                    button.disabled = true;
                    button.classList.add('btn-loading');
                    button.setAttribute('aria-disabled', 'true');
                });
            });
        });
    }

    function setupDeleteModal() {
        const modal = document.getElementById('confirmationModal');
        if (!modal) return;

        const confirmButton = modal.querySelector('#confirmActionBtn');
        const cancelButton = modal.querySelector('#cancelActionBtn');
        let currentForm = null;

        function closeModal() {
            modal.classList.remove('show');
            modal.setAttribute('aria-hidden', 'true');
            currentForm = null;
        }

        cancelButton?.addEventListener('click', closeModal);

        modal.addEventListener('click', event => {
            if (event.target === modal) closeModal();
        });

        document.addEventListener('keydown', event => {
            if (event.key === 'Escape' && modal.classList.contains('show')) closeModal();
        });

        confirmButton?.addEventListener('click', () => {
            if (!currentForm || currentForm.dataset.submitting === 'true') return;

            const csrf = currentForm.querySelector('input[name="csrf_token"]');
            if (!csrf?.value) {
                closeModal();
                window.alert('Security token is missing. Please reload the page and try again.');
                return;
            }

            currentForm.dataset.submitting = 'true';
            confirmButton.disabled = true;
            confirmButton.setAttribute('aria-disabled', 'true');
            confirmButton.classList.add('btn-loading');
            currentForm.querySelectorAll('button').forEach(button => {
                button.disabled = true;
            });
            currentForm.submit();
        });

        document.querySelectorAll('[data-action="delete"]').forEach(button => {
            button.addEventListener('click', event => {
                event.preventDefault();
                currentForm = button.closest('form');
                if (!currentForm) return;

                const message = button.getAttribute('data-delete-message') || 'Are you sure you want to delete this item? This action cannot be undone.';
                const description = modal.querySelector('#modalDescription');
                if (description) description.textContent = message;

                modal.classList.add('show');
                modal.setAttribute('aria-hidden', 'false');
                confirmButton?.focus();
            });
        });
    }

    function setupFileDropzones() {
        document.querySelectorAll('.file-dropzone').forEach(dropzone => {
            const form = dropzone.closest('form');
            const fileInput = form?.querySelector('input[type="file"]');
            const fileInfo = dropzone.querySelector('.file-info');
            if (!fileInput) return;

            const updateFileInfo = () => {
                const file = fileInput.files?.[0];
                if (!file) {
                    if (fileInfo) fileInfo.textContent = '';
                    return;
                }

                if (!file.name.toLowerCase().endsWith('.csv')) {
                    window.alert('Only CSV files are allowed.');
                    fileInput.value = '';
                    if (fileInfo) fileInfo.textContent = '';
                    return;
                }

                if (file.size > MAX_CSV_SIZE) {
                    window.alert('File size exceeds the 5MB limit.');
                    fileInput.value = '';
                    if (fileInfo) fileInfo.textContent = '';
                    return;
                }

                if (fileInfo) {
                    fileInfo.textContent = `Selected: ${file.name} (${(file.size / 1024).toFixed(2)} KB)`;
                }
            };

            dropzone.addEventListener('click', event => {
                if (event.target !== fileInput) fileInput.click();
            });

            dropzone.addEventListener('keydown', event => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    fileInput.click();
                }
            });

            dropzone.addEventListener('dragover', event => {
                event.preventDefault();
                dropzone.classList.add('dragover');
            });

            dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));

            dropzone.addEventListener('drop', event => {
                event.preventDefault();
                dropzone.classList.remove('dragover');
                const file = event.dataTransfer?.files?.[0];
                if (!file) return;

                const transfer = new DataTransfer();
                transfer.items.add(file);
                fileInput.files = transfer.files;
                updateFileInfo();
            });

            fileInput.addEventListener('change', updateFileInfo);
        });
    }

    document.addEventListener('DOMContentLoaded', () => {
        setupForms();
        setupDeleteModal();
        setupFileDropzones();
    });
})();
