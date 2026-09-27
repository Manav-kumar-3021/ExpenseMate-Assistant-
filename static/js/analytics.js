document.addEventListener('DOMContentLoaded', function () {
    'use strict';

    const dataElement = document.getElementById('analytics-data');
    if (!dataElement) return;

    let data;
    try {
        data = JSON.parse(dataElement.textContent || '{}');
    } catch (error) {
        console.error('Unable to read analytics data.');
        return;
    }

    const selectedMonth = Number(dataElement.dataset.selectedMonth || 0) || null;
    const year = dataElement.dataset.selectedYear || '';
    const currency = dataElement.dataset.currency || 'PKR';

    const palette = {
        text: '#dbe4ee',
        muted: '#8b9aac',
        grid: '#2b3949',
        panel: '#111b27',
        income: '#1f9d78',
        expense: '#c95562',
        accent: '#6f90b2',
        accentLight: '#9fb6ce',
        border: '#3a4a5e',
        ring: '#0b131e',
        white: '#f4f7fb'
    };

    const number = new Intl.NumberFormat(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });

    const escapeHtml = function (value) {
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    };

    function valueOf(item) {
        const value = Number(item && item.total);
        return Number.isFinite(value) ? value : 0;
    }

    function scopedMonths(list) {
        const source = Array.isArray(list) ? list : [];
        if (!selectedMonth) return source.slice(0, 12);
        return source.filter(item => Number(item.month) === selectedMonth);
    }

    function hasPositiveData(list) {
        return Array.isArray(list) && list.some(item => valueOf(item) > 0);
    }

    function setTitle(id, annualTitle, monthlyTitle) {
        const node = document.getElementById(id);
        if (node) node.textContent = selectedMonth ? monthlyTitle : annualTitle;
    }

    function showEmpty(id, message) {
        const node = document.getElementById(id);
        if (!node) return;
        node.innerHTML = '<div class="chart-empty-state"><span class="chart-empty-icon">—</span><strong>' + escapeHtml(message || 'No data available for this period.') + '</strong><span>Record transactions for the selected period to populate this chart.</span></div>';
    }

    function svgShell(viewBox, label) {
        return '<svg class="analytics-svg" viewBox="' + viewBox + '" role="img" aria-label="' + escapeHtml(label) + '" preserveAspectRatio="xMidYMid meet"><title>' + escapeHtml(label) + ' — ' + escapeHtml(year) + ' — ' + escapeHtml(currency) + '</title></svg>';
    }

    function mountSvg(id, viewBox, label) {
        const node = document.getElementById(id);
        if (!node) return null;
        node.innerHTML = svgShell(viewBox, label);
        return node.querySelector('svg');
    }

    function niceMax(values) {
        const max = Math.max(0, ...values);
        if (max === 0) return 1;
        const magnitude = Math.pow(10, Math.floor(Math.log10(max)));
        const normalized = max / magnitude;
        const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
        return step * magnitude;
    }

    function niceStep(range) {
        const safeRange = Math.max(range, 1);
        const magnitude = Math.pow(10, Math.floor(Math.log10(safeRange)));
        const normalized = safeRange / magnitude;
        const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
        return step * magnitude;
    }

    function niceRange(minValue, maxValue) {
        const min = Math.min(0, minValue);
        const max = Math.max(0, maxValue);
        const step = niceStep((max - min) / 4);
        return {
            min: Math.floor(min / step) * step,
            max: Math.ceil(max / step) * step
        };
    }

    function add(node, tag, attrs, text) {
        const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
        Object.keys(attrs || {}).forEach(key => el.setAttribute(key, attrs[key]));
        if (text !== undefined) el.textContent = text;
        node.appendChild(el);
        return el;
    }

    function drawAxesRange(svg, plot, minValue, maxValue, labels) {
        const steps = 4;
        const range = maxValue - minValue || 1;
        for (let i = 0; i <= steps; i++) {
            const ratio = i / steps;
            const y = plot.top + plot.height * ratio;
            const value = maxValue - range * ratio;
            const isZero = Math.abs(value) < Math.max(Math.abs(range) * 1e-8, 0.0000001);
            add(svg, 'line', {
                x1: plot.left,
                y1: y,
                x2: plot.left + plot.width,
                y2: y,
                stroke: isZero ? palette.border : palette.grid,
                'stroke-width': isZero ? 1.5 : 1
            });
            add(svg, 'text', {
                x: plot.left - 10,
                y: y + 4,
                fill: palette.muted,
                'font-size': 11,
                'text-anchor': 'end'
            }, number.format(value));
        }
        add(svg, 'line', { x1: plot.left, y1: plot.top, x2: plot.left, y2: plot.top + plot.height, stroke: palette.border, 'stroke-width': 1 });
        add(svg, 'line', { x1: plot.left, y1: plot.top + plot.height, x2: plot.left + plot.width, y2: plot.top + plot.height, stroke: palette.border, 'stroke-width': 1 });

        if (labels.length) {
            labels.forEach((label, index) => {
                const x = labels.length === 1 ? plot.left + plot.width / 2 : plot.left + (plot.width * index / (labels.length - 1));
                add(svg, 'text', { x, y: plot.top + plot.height + 24, fill: palette.muted, 'font-size': 10.5, 'text-anchor': 'middle' }, label.slice(0, 3));
            });
        }
    }

    function drawAxes(svg, plot, maxValue, labels) {
        drawAxesRange(svg, plot, 0, maxValue, labels);
    }

    function drawLine(id, list, color, label, titleText) {
        if (!hasPositiveData(list)) {
            showEmpty(id);
            return;
        }
        const svg = mountSvg(id, '0 0 760 320', titleText);
        if (!svg) return;

        const values = list.map(valueOf);
        const labels = list.map(item => item.month_name || String(item.month || ''));
        const max = niceMax(values);
        const plot = { left: 70, top: 30, width: 650, height: 215 };
        drawAxes(svg, plot, max, labels);

        const points = values.map((value, index) => {
            const x = labels.length === 1 ? plot.left + plot.width / 2 : plot.left + plot.width * index / (labels.length - 1);
            const y = plot.top + plot.height - (value / max) * plot.height;
            return { x, y, value };
        });

        const d = points.map((point, index) => (index ? 'L' : 'M') + point.x.toFixed(2) + ' ' + point.y.toFixed(2)).join(' ');
        add(svg, 'path', { d, fill: 'none', stroke: color, 'stroke-width': 3, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' });

        points.forEach((point, index) => {
            const circle = add(svg, 'circle', { cx: point.x, cy: point.y, r: 5, fill: color, stroke: '#0b131e', 'stroke-width': 3, tabindex: 0 });
            add(circle, 'title', {}, labels[index] + ': ' + currency + ' ' + number.format(point.value));
        });

        add(svg, 'text', { x: plot.left, y: 18, fill: palette.accentLight, 'font-size': 11, 'font-weight': 700 }, label.toUpperCase());
    }

    function polarPoint(cx, cy, radius, angle) {
        const radians = (angle - 90) * Math.PI / 180;
        return { x: cx + radius * Math.cos(radians), y: cy + radius * Math.sin(radians) };
    }

    function arcPath(cx, cy, radius, startAngle, endAngle) {
        const start = polarPoint(cx, cy, radius, endAngle);
        const end = polarPoint(cx, cy, radius, startAngle);
        const large = endAngle - startAngle > 180 ? 1 : 0;
        return [
            'M', start.x, start.y,
            'A', radius, radius, 0, large, 0, end.x, end.y
        ].join(' ');
    }

    function drawDonut() {
        const list = Array.isArray(data.category_expenses) ? data.category_expenses.filter(item => valueOf(item) > 0) : [];
        if (!list.length) {
            showEmpty('expenseByCategoryChart');
            return;
        }
        const svg = mountSvg('expenseByCategoryChart', '0 0 760 320', 'Expenses by category');
        if (!svg) return;

        const total = list.reduce((sum, item) => sum + valueOf(item), 0);
        const colors = ['#5a7898', '#6d89a7', '#819ab4', '#59708a', '#8ea3b8', '#71869c', '#4c647c', '#9eafbf', '#607891', '#8799ac'];
        const cx = 235, cy = 160, radius = 92, stroke = 42;
        let angle = 0;

        add(svg, 'circle', { cx, cy, r: radius, fill: 'none', stroke: palette.ring, 'stroke-width': stroke });
        if (list.length === 1) {
            const circle = add(svg, 'circle', { cx, cy, r: radius, fill: 'none', stroke: colors[0], 'stroke-width': stroke });
            add(circle, 'title', {}, list[0].category + ': ' + currency + ' ' + number.format(valueOf(list[0])));
        } else {
            list.forEach((item, index) => {
                const slice = valueOf(item) / total * 360;
                const path = add(svg, 'path', {
                    d: arcPath(cx, cy, radius, angle, angle + slice),
                    fill: 'none',
                    stroke: colors[index % colors.length],
                    'stroke-width': stroke,
                    'stroke-linecap': 'butt'
                });
                add(path, 'title', {}, item.category + ': ' + currency + ' ' + number.format(valueOf(item)));
                angle += slice;
            });
        }

        add(svg, 'text', { x: cx, y: cy - 6, fill: palette.white, 'font-size': 22, 'font-weight': 800, 'text-anchor': 'middle' }, currency);
        add(svg, 'text', { x: cx, y: cy + 15, fill: palette.muted, 'font-size': 12, 'text-anchor': 'middle' }, 'TOTAL SPEND');

        const legendX = 390;
        const maxLegend = Math.min(list.length, 8);
        for (let i = 0; i < maxLegend; i++) {
            const y = 52 + i * 30;
            add(svg, 'rect', { x: legendX, y: y - 9, width: 10, height: 10, rx: 2, fill: colors[i % colors.length] });
            add(svg, 'text', { x: legendX + 18, y, fill: palette.text, 'font-size': 11.5 }, list[i].category.length > 28 ? list[i].category.slice(0, 25) + '…' : list[i].category);
            add(svg, 'text', { x: 690, y, fill: palette.muted, 'font-size': 11, 'text-anchor': 'end' }, currency + ' ' + number.format(valueOf(list[i])));
        }
        add(svg, 'text', { x: 70, y: 25, fill: palette.accentLight, 'font-size': 11, 'font-weight': 700 }, 'SPENDING MIX');
    }

    function drawCombined() {
        const expenses = selectedMonth ? scopedMonths(data.monthly_expenses) : (Array.isArray(data.monthly_expenses) ? data.monthly_expenses.slice(0, 12) : []);
        const incomes = selectedMonth ? scopedMonths(data.monthly_income) : (Array.isArray(data.monthly_income) ? data.monthly_income.slice(0, 12) : []);
        const length = Math.max(expenses.length, incomes.length);
        if (!length || (!hasPositiveData(expenses) && !hasPositiveData(incomes))) {
            showEmpty('incomeVsExpenseChart');
            return;
        }

        const labels = [];
        const valuesIncome = [];
        const valuesExpense = [];
        const incomeMap = new Map(incomes.map(item => [Number(item.month), valueOf(item)]));
        const expenseMap = new Map(expenses.map(item => [Number(item.month), valueOf(item)]));
        const nameMap = new Map([...incomes, ...expenses].map(item => [Number(item.month), item.month_name || String(item.month)]));
        const monthNumbers = Array.from(new Set([...incomeMap.keys(), ...expenseMap.keys()])).sort((a, b) => a - b);

        monthNumbers.forEach(monthNumber => {
            labels.push(nameMap.get(monthNumber) || String(monthNumber));
            valuesIncome.push(incomeMap.get(monthNumber) || 0);
            valuesExpense.push(expenseMap.get(monthNumber) || 0);
        });

        const svg = mountSvg('incomeVsExpenseChart', '0 0 760 340', selectedMonth ? 'Selected month cash flow' : 'Income versus expenses');
        if (!svg) return;
        const netValues = valuesIncome.map((value, index) => value - (valuesExpense[index] || 0));
        const bounds = niceRange(Math.min(0, ...netValues), Math.max(...valuesIncome, ...valuesExpense, ...netValues, 0));
        const plot = { left: 70, top: 38, width: 650, height: 220 };
        drawAxesRange(svg, plot, bounds.min, bounds.max, labels);

        const groupWidth = plot.width / labels.length;
        const barWidth = Math.min(26, groupWidth * 0.22);
        const gap = Math.min(7, groupWidth * 0.08);
        const netPoints = [];
        const range = bounds.max - bounds.min || 1;
        const yForValue = value => plot.top + plot.height - ((value - bounds.min) / range) * plot.height;
        const zeroY = yForValue(0);

        labels.forEach((_, index) => {
            const baseX = plot.left + groupWidth * index + groupWidth / 2;
            const income = valuesIncome[index] || 0;
            const expense = valuesExpense[index] || 0;
            const incomeY = yForValue(income);
            const expenseY = yForValue(expense);
            const incomeTop = Math.min(zeroY, incomeY);
            const expenseTop = Math.min(zeroY, expenseY);
            const incomeH = Math.abs(zeroY - incomeY);
            const expenseH = Math.abs(zeroY - expenseY);
            const incomeX = baseX - barWidth - gap / 2;
            const expenseX = baseX + gap / 2;

            const incomeBar = add(svg, 'rect', { x: incomeX, y: incomeTop, width: barWidth, height: Math.max(incomeH, 0), rx: 4, fill: palette.income });
            add(incomeBar, 'title', {}, labels[index] + ' — Income: ' + currency + ' ' + number.format(income));
            const expenseBar = add(svg, 'rect', { x: expenseX, y: expenseTop, width: barWidth, height: Math.max(expenseH, 0), rx: 4, fill: palette.expense });
            add(expenseBar, 'title', {}, labels[index] + ' — Expenses: ' + currency + ' ' + number.format(expense));

            const net = income - expense;
            const netY = yForValue(net);
            netPoints.push({ x: baseX, y: netY, net });
        });

        if (netPoints.length) {
            const path = netPoints.map((point, index) => (index ? 'L' : 'M') + point.x.toFixed(2) + ' ' + point.y.toFixed(2)).join(' ');
            add(svg, 'path', { d: path, fill: 'none', stroke: palette.accent, 'stroke-width': 2.5, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' });
            netPoints.forEach((point, index) => {
                const circle = add(svg, 'circle', { cx: point.x, cy: point.y, r: 4, fill: palette.accent, stroke: palette.panel, 'stroke-width': 2 });
                add(circle, 'title', {}, labels[index] + ' — Net: ' + currency + ' ' + number.format(point.net));
            });
        }

        add(svg, 'rect', { x: 70, y: 298, width: 11, height: 11, rx: 2, fill: palette.income });
        add(svg, 'text', { x: 88, y: 307, fill: palette.text, 'font-size': 11.5 }, 'Income');
        add(svg, 'rect', { x: 162, y: 298, width: 11, height: 11, rx: 2, fill: palette.expense });
        add(svg, 'text', { x: 180, y: 307, fill: palette.text, 'font-size': 11.5 }, 'Expenses');
        add(svg, 'line', { x1: 275, y1: 304, x2: 291, y2: 304, stroke: palette.accent, 'stroke-width': 3, 'stroke-linecap': 'round' });
        add(svg, 'text', { x: 298, y: 307, fill: palette.text, 'font-size': 11.5 }, 'Net cash flow');
    }

    const monthlyExpenses = scopedMonths(data.monthly_expenses);
    const monthlyIncome = scopedMonths(data.monthly_income);

    setTitle('monthlyExpensesTitle', 'Monthly Expenses', 'Selected Month Expenses');
    setTitle('monthlyIncomeTitle', 'Monthly Income', 'Selected Month Income');
    setTitle('incomeVsExpenseTitle', 'Income vs Expenses', 'Selected Month Cash Flow');

    drawDonut();
    drawLine('monthlyExpensesChart', monthlyExpenses, palette.expense, 'Expenses', selectedMonth ? 'Selected month expenses' : 'Monthly expenses');
    drawLine('monthlyIncomeChart', monthlyIncome, palette.income, 'Income', selectedMonth ? 'Selected month income' : 'Monthly income');
    drawCombined();

    const context = document.querySelector('.analytics-context');
    if (context) {
        context.setAttribute('aria-label', 'Analytics filters: ' + currency + ', ' + (selectedMonth ? 'selected month' : 'full year') + ', ' + year);
    }
});
