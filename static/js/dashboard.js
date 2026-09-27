document.addEventListener('DOMContentLoaded', function() {
    // Mobile sidebar toggle
    const sidebarToggle = document.getElementById('sidebarToggle');
    const sidebar = document.getElementById('sidebar');
    const sidebarOverlay = document.getElementById('sidebarOverlay');

    function toggleSidebar(force) {
        if (!sidebar) return;
        const isOpen = typeof force === 'boolean' ? force : !sidebar.classList.contains('open');
        
        sidebar.classList.toggle('open', isOpen);
        if (sidebarOverlay) sidebarOverlay.classList.toggle('show', isOpen);
        
        if (sidebarToggle) {
            sidebarToggle.setAttribute('aria-expanded', isOpen.toString());
        }
    }

    if (sidebarToggle) {
        sidebarToggle.addEventListener('click', () => toggleSidebar());
    }

    if (sidebarOverlay) {
        sidebarOverlay.addEventListener('click', () => toggleSidebar(false));
    }

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && sidebar && sidebar.classList.contains('open')) {
            toggleSidebar(false);
        }
    });

    // Auto-submit filter form
    const filterForm = document.querySelector('.filter-form');
    if (filterForm) {
        const selects = filterForm.querySelectorAll('select');
        selects.forEach(select => {
            select.addEventListener('change', () => filterForm.submit());
        });
    }

    // Number formatting
    const numberElements = document.querySelectorAll('.card-value:not(.count-value), .budget-amount');
    numberElements.forEach(el => {
        let val = el.innerText.trim();
        let prefix = val.match(/^[^\d.-]+/);
        prefix = prefix ? prefix[0] : '';
        let numStr = val.replace(/[^0-9.-]+/g, "");
        let num = parseFloat(numStr);
        if (!isNaN(num)) {
            el.innerText = prefix + num.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
        }
    });

    // Toast system
    const toasts = document.querySelectorAll('.toast');
    toasts.forEach(toast => {
        const isError = toast.classList.contains('toast-danger') || toast.classList.contains('toast-error');
        const duration = isError ? 10000 : 5000;
        
        if (!isError) {
            setTimeout(() => {
                dismissToast(toast);
            }, duration);
        }
        
        const closeBtn = toast.querySelector('.toast-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => dismissToast(toast));
        }
    });

    function dismissToast(toast) {
        if(window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
            toast.remove();
        } else {
            toast.classList.add('fade-out');
            setTimeout(() => toast.remove(), 500);
        }
    }
});
