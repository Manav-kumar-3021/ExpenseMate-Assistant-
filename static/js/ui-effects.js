(function () {
    'use strict';

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)').matches;

    if (reducedMotion || !finePointer) return;

    let raf = 0;
    document.addEventListener('pointermove', function (event) {
        if (raf) return;
        raf = requestAnimationFrame(function () {
            const x = (event.clientX / window.innerWidth) * 100;
            const y = (event.clientY / window.innerHeight) * 100;
            document.documentElement.style.setProperty('--pointer-x', x + '%');
            document.documentElement.style.setProperty('--pointer-y', y + '%');
            raf = 0;
        });
    }, { passive: true });

    document.querySelectorAll('.glass-card, .stat-card, .chart-container, .file-dropzone').forEach(function (surface) {
        surface.addEventListener('pointerenter', function () {
            surface.classList.add('formal-3d-hover');
        }, { passive: true });
        surface.addEventListener('pointerleave', function () {
            surface.classList.remove('formal-3d-hover');
        }, { passive: true });
    });
})();
