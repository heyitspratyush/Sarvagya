/**
 * SettlementLens Merchant Dashboard Client Logic
 */

let currentData = null;
let allFindings = [];
let activeStageFilter = null;
let activeRawTab = 'orders';

document.addEventListener('DOMContentLoaded', () => {
    initLucide();
    setupEventListeners();
    fetchScenarios();
    runReconciliation(); // Load default
});

function initLucide() {
    if (window.lucide) {
        window.lucide.createIcons();
    }
}

function setupEventListeners() {
    // Scenario selector
    const selector = document.getElementById('scenarioSelector');
    selector.addEventListener('change', () => {
        runReconciliation(selector.value);
    });

    // Run reconciliation button
    document.getElementById('runReconcileBtn').addEventListener('click', () => {
        runReconciliation(selector.value);
    });

    // Reset stage filter button
    document.getElementById('resetStageFilterBtn').addEventListener('click', () => {
        activeStageFilter = null;
        document.getElementById('layerFilter').value = 'ALL';
        document.getElementById('resetStageFilterBtn').classList.add('hidden');
        document.querySelectorAll('.stepper-card').forEach(c => c.classList.remove('active-stage'));
        renderFindings();
    });

    // Filters & Search
    document.getElementById('layerFilter').addEventListener('change', renderFindings);
    document.getElementById('statusFilter').addEventListener('change', renderFindings);
    document.getElementById('searchInput').addEventListener('input', renderFindings);

    // Slide-over drawer controls
    const drawer = document.getElementById('investigationDrawer');
    const overlay = document.getElementById('drawerOverlay');
    const closeDrawer = () => {
        drawer.classList.add('translate-x-full');
        overlay.classList.add('hidden');
    };

    document.getElementById('closeDrawerBtn').addEventListener('click', closeDrawer);
    document.getElementById('closeDrawerFooterBtn').addEventListener('click', closeDrawer);
    overlay.addEventListener('click', closeDrawer);

    // Technical collapsible in drawer
    document.getElementById('toggleTechnicalBtn').addEventListener('click', () => {
        const content = document.getElementById('technicalContent');
        const chevron = document.getElementById('techChevron');
        content.classList.toggle('hidden');
        chevron.classList.toggle('rotate-180');
    });

    // Raw data accordion
    document.getElementById('toggleRawDataBtn').addEventListener('click', () => {
        const container = document.getElementById('rawDataContainer');
        const chevron = document.getElementById('rawChevron');
        container.classList.toggle('hidden');
        chevron.classList.toggle('rotate-180');
    });

    // Raw data tabs
    document.querySelectorAll('.raw-tab-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            document.querySelectorAll('.raw-tab-btn').forEach(b => {
                b.classList.remove('active', 'bg-indigo-50', 'text-indigo-700', 'font-semibold');
                b.classList.add('text-slate-500');
            });
            btn.classList.add('active', 'bg-indigo-50', 'text-indigo-700', 'font-semibold');
            btn.classList.remove('text-slate-500');
            activeRawTab = btn.getAttribute('data-target');
            renderRawContent();
        });
    });

    // Upload Modal controls
    const uploadModal = document.getElementById('uploadModal');
    document.getElementById('openUploadModalBtn').addEventListener('click', () => {
        uploadModal.classList.remove('hidden');
    });
    document.getElementById('closeUploadModalBtn').addEventListener('click', () => {
        uploadModal.classList.add('hidden');
    });
    document.getElementById('cancelUploadBtn').addEventListener('click', () => {
        uploadModal.classList.add('hidden');
    });

    // CSV Upload Form Submit
    document.getElementById('csvUploadForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const formData = new FormData(e.target);
        
        showLoadingState();
        try {
            const res = await fetch('/api/upload/csv', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();
            uploadModal.classList.add('hidden');
            processReconciliationResponse(data);
        } catch (err) {
            alert('Failed to process uploaded files: ' + err.message);
        }
    });

    // Export CSV
    document.getElementById('exportCsvBtn').addEventListener('click', exportFindingsToCsv);
}

// ----------------- API Calls ----------------- //

async function fetchScenarios() {
    try {
        const res = await fetch('/api/scenarios');
        const data = await res.json();
        const selector = document.getElementById('scenarioSelector');
        selector.innerHTML = '';

        // Add special "All Combined" option
        const combinedOpt = document.createElement('option');
        combinedOpt.value = 'ALL_COMBINED';
        combinedOpt.textContent = '⭐ Run All Scenarios (Full Test Suite)';
        selector.appendChild(combinedOpt);

        data.scenarios.forEach(sc => {
            const opt = document.createElement('option');
            opt.value = sc.id;
            opt.textContent = `${sc.name} (${sc.category})`;
            selector.appendChild(opt);
        });

        selector.value = 'gt01_normal_payment';
    } catch (err) {
        console.error('Failed to fetch scenarios:', err);
    }
}

async function runReconciliation(scenarioId = 'gt01_normal_payment') {
    showLoadingState();
    try {
        let body = {};
        if (scenarioId === 'ALL_COMBINED') {
            const resSc = await fetch('/api/scenarios');
            const dataSc = await resSc.json();
            body = { scenario_ids: dataSc.scenarios.map(s => s.id) };
        } else {
            body = { scenario_id: scenarioId };
        }

        const res = await fetch('/api/reconcile/scenario', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });

        const data = await res.json();
        processReconciliationResponse(data);
    } catch (err) {
        console.error('Reconciliation error:', err);
        alert('Reconciliation failed: ' + err.message);
    }
}

function showLoadingState() {
    const tbody = document.getElementById('findingsTableBody');
    tbody.innerHTML = `
        <tr>
            <td colspan="6" class="py-12 text-center text-slate-500">
                <div class="inline-block animate-spin rounded-full h-6 w-6 border-2 border-indigo-600 border-t-transparent mb-2"></div>
                <div>Executing deterministic reconciliation engine...</div>
            </td>
        </tr>
    `;
}

function processReconciliationResponse(data) {
    currentData = data;
    allFindings = data.findings || [];

    // Update Context Banner
    updateContextBanner(data);

    // Update KPIs
    updateKpis(data.summary);

    // Update 5-Stage Stepper
    renderLifecycleStepper(data.summary.lifecycle_stages);

    // Update Raw Feeds
    updateRawDataCounts(data.source_data);
    renderRawContent();

    // Render Findings Table
    renderFindings();

    initLucide();
}

function updateContextBanner(data) {
    const titleElem = document.getElementById('activeScenarioTitle');
    const descElem = document.getElementById('activeScenarioDesc');
    const catElem = document.getElementById('activeScenarioCategory');
    const timeElem = document.getElementById('reconcileTimestamp');

    const scId = data.active_scenario || 'gt01_normal_payment';
    titleElem.textContent = scId.replace(/_/g, ' ').toUpperCase();
    descElem.textContent = `Processed ${data.summary.orders_count} orders across 5 reconciliation layers.`;
    catElem.textContent = data.summary.discrepancy_count > 0 ? 'Discrepancy Detected' : 'Clean Processing';
    timeElem.textContent = 'Reconciled at ' + new Date().toLocaleTimeString();
}

function updateKpis(summary) {
    document.getElementById('kpiGrossVolume').textContent = summary.gross_order_volume;
    document.getElementById('kpiOrderCount').textContent = `(${summary.orders_count} orders)`;

    const deltaElem = document.getElementById('kpiDiscrepancyDelta');
    const deltaBadge = document.getElementById('kpiDiscrepancyBadge');
    const deltaCard = document.getElementById('discrepancyKpiCard');
    const deltaIconBox = document.getElementById('discrepancyIconBox');
    const deltaSubtitle = document.getElementById('kpiDiscrepancySubtitle');

    deltaElem.textContent = summary.net_financial_discrepancy;

    if (summary.net_discrepancy_raw !== 0) {
        deltaBadge.className = 'text-xs font-semibold px-2 py-0.5 rounded-full bg-rose-100 text-rose-800';
        deltaBadge.textContent = 'Mismatch Detected';
        deltaIconBox.className = 'w-8 h-8 rounded-lg bg-rose-50 text-rose-600 flex items-center justify-center';
        deltaSubtitle.textContent = 'Signed variance (Expected - Observed)';
    } else {
        deltaBadge.className = 'text-xs font-semibold px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800';
        deltaBadge.textContent = 'Balanced';
        deltaIconBox.className = 'w-8 h-8 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center';
        deltaSubtitle.textContent = 'Reported net equals calculated net';
    }

    document.getElementById('kpiActionCount').textContent = summary.discrepancy_count + summary.unresolved_count + summary.late_count;
    document.getElementById('kpiUnresolvedCount').textContent = `${summary.discrepancy_count} discrepancies`;
    document.getElementById('kpiLateCount').textContent = `${summary.late_count} late`;

    document.getElementById('kpiBankVolume').textContent = summary.total_bank_volume;
    document.getElementById('kpiBankCount').textContent = `(${summary.bank_count} deposits)`;
}

function renderLifecycleStepper(stages) {
    const container = document.getElementById('lifecycleStepper');
    container.innerHTML = '';

    const layerMap = {
        orders: 'Order and payment attempt',
        attempts: 'Payment and processor',
        processor: 'Processor and settlement',
        settlements: 'Settlement amounts',
        bank: 'Settlement and bank payout',
    };

    stages.forEach((st, idx) => {
        const card = document.createElement('div');
        const isSelected = activeStageFilter === st.id;
        card.className = `stepper-card p-3.5 rounded-xl border ${isSelected ? 'active-stage border-indigo-600' : 'border-slate-200 bg-slate-50/50'} relative`;
        
        let statusColor = 'bg-slate-300';
        let badgeColor = 'text-slate-600 bg-slate-100';
        if (st.status === 'success') {
            statusColor = 'bg-emerald-500';
            badgeColor = 'text-emerald-700 bg-emerald-50';
        } else if (st.status === 'danger') {
            statusColor = 'bg-rose-500';
            badgeColor = 'text-rose-700 bg-rose-50';
        } else if (st.status === 'warning') {
            statusColor = 'bg-amber-500';
            badgeColor = 'text-amber-700 bg-amber-50';
        }

        card.innerHTML = `
            <div class="flex items-center justify-between mb-2">
                <span class="text-[11px] font-bold text-slate-500">${st.name}</span>
                <span class="w-2 h-2 rounded-full ${statusColor}"></span>
            </div>
            <div class="text-sm font-extrabold text-slate-900">${st.amount}</div>
            <div class="flex items-center justify-between mt-1 text-[11px]">
                <span class="text-slate-400">${st.count} records</span>
                <span class="text-[10px] font-semibold px-1.5 py-0.5 rounded ${badgeColor}">${st.status.toUpperCase()}</span>
            </div>
        `;

        card.addEventListener('click', () => {
            if (activeStageFilter === st.id) {
                activeStageFilter = null;
                document.getElementById('layerFilter').value = 'ALL';
                document.getElementById('resetStageFilterBtn').classList.add('hidden');
                card.classList.remove('active-stage');
            } else {
                activeStageFilter = st.id;
                const layerName = layerMap[st.id] || 'ALL';
                document.getElementById('layerFilter').value = layerName;
                document.getElementById('resetStageFilterBtn').classList.remove('hidden');
                document.querySelectorAll('.stepper-card').forEach(c => c.classList.remove('active-stage'));
                card.classList.add('active-stage');
            }
            renderFindings();
        });

        container.appendChild(card);
    });
}

function renderFindings() {
    const layerFilter = document.getElementById('layerFilter').value;
    const statusFilter = document.getElementById('statusFilter').value;
    const searchQuery = document.getElementById('searchInput').value.trim().toLowerCase();

    const filtered = allFindings.filter(f => {
        // Layer filter
        if (layerFilter !== 'ALL' && f.layer !== layerFilter) {
            return false;
        }

        // Status filter
        const status = (f.status || '').toLowerCase();
        if (statusFilter === 'ACTION') {
            if (!status.includes('discrepancy') && !status.includes('mismatch') && !status.includes('late') && !status.includes('unresolved') && !status.includes('unverified')) {
                return false;
            }
        } else if (statusFilter === 'RESOLVED') {
            if (status.includes('discrepancy') || status.includes('mismatch') || status.includes('late') || status.includes('unresolved')) {
                return false;
            }
        }

        // Search query
        if (searchQuery) {
            const textToSearch = [
                f.finding_id,
                f.title,
                f.description,
                f.suggested_check,
                ...(f.references || []).map(r => r.value)
            ].join(' ').toLowerCase();

            if (!textToSearch.includes(searchQuery)) {
                return false;
            }
        }

        return true;
    });

    document.getElementById('findingsCountBadge').textContent = `${filtered.length} Items`;

    const tbody = document.getElementById('findingsTableBody');
    const emptyState = document.getElementById('noFindingsState');

    if (filtered.length === 0) {
        tbody.innerHTML = '';
        emptyState.classList.remove('hidden');
        return;
    }

    emptyState.classList.add('hidden');
    tbody.innerHTML = '';

    filtered.forEach(finding => {
        const tr = document.createElement('tr');
        tr.className = 'finding-row border-b border-slate-100 cursor-pointer';

        const statusBadge = getStatusBadge(finding.status);
        const refsHtml = (finding.references || []).slice(0, 2).map(r => 
            `<span class="inline-block text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-700 font-mono font-medium">${r.label}: ${r.value}</span>`
        ).join(' ');

        // Variance / Amount
        let varianceHtml = '<span class="text-slate-400">N/A</span>';
        const fin = finding.financials || {};
        if (fin.difference_amount_formatted && fin.difference_amount_formatted !== 'Not available') {
            const isNegative = fin.difference_amount_formatted.startsWith('-');
            const colorClass = isNegative ? 'text-rose-600 font-bold' : (fin.difference_amount_formatted === '₹0.00' ? 'text-emerald-600 font-semibold' : 'text-slate-900 font-bold');
            varianceHtml = `<span class="${colorClass}">${fin.difference_amount_formatted}</span>`;
        } else if (fin.observed_amount_formatted && fin.observed_amount_formatted !== 'Not available') {
            varianceHtml = `<span class="text-slate-700 font-semibold">${fin.observed_amount_formatted}</span>`;
        }

        tr.innerHTML = `
            <td class="py-3 px-4 whitespace-nowrap">${statusBadge}</td>
            <td class="py-3 px-4 font-semibold text-slate-700">${finding.layer}</td>
            <td class="py-3 px-4">
                <div class="font-bold text-slate-900">${finding.title}</div>
                <div class="text-[11px] text-slate-500 truncate max-w-xs mt-0.5">${finding.description}</div>
            </td>
            <td class="py-3 px-4 space-x-1">${refsHtml || '<span class="text-slate-400 text-[10px]">None</span>'}</td>
            <td class="py-3 px-4 text-right font-mono">${varianceHtml}</td>
            <td class="py-3 px-4 text-center">
                <button class="investigate-btn px-2.5 py-1 rounded bg-indigo-50 hover:bg-indigo-100 text-indigo-700 font-semibold text-[11px] transition">
                    Investigate
                </button>
            </td>
        `;

        tr.addEventListener('click', () => openInvestigationDrawer(finding));
        tbody.appendChild(tr);
    });

    initLucide();
}

function getStatusBadge(status) {
    const s = (status || '').toLowerCase();
    if (s.includes('discrepancy') || s.includes('mismatch')) {
        return `<span class="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full badge-discrepancy font-semibold"><i data-lucide="alert-circle" class="w-3 h-3"></i> ${status}</span>`;
    }
    if (s.includes('late')) {
        return `<span class="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full badge-late font-semibold"><i data-lucide="clock" class="w-3 h-3"></i> ${status}</span>`;
    }
    if (s.includes('resolved') || s.includes('on time')) {
        return `<span class="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full badge-resolved font-semibold"><i data-lucide="check" class="w-3 h-3"></i> ${status}</span>`;
    }
    return `<span class="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full badge-unresolved font-semibold"><i data-lucide="help-circle" class="w-3 h-3"></i> ${status || 'Unresolved'}</span>`;
}

function openInvestigationDrawer(finding) {
    document.getElementById('drawerLayer').textContent = finding.layer;
    document.getElementById('drawerTitle').textContent = finding.title;
    document.getElementById('drawerFindingId').textContent = finding.finding_id;
    document.getElementById('drawerStatusBadge').innerHTML = getStatusBadge(finding.status);
    document.getElementById('drawerDescription').textContent = finding.description;
    document.getElementById('drawerSuggestedCheck').textContent = finding.suggested_check || 'Review transaction references and ensure source feeds are up to date.';

    // Financials
    const fin = finding.financials || {};
    document.getElementById('drawerExpectedAmount').textContent = fin.expected_amount_formatted || 'N/A';
    document.getElementById('drawerObservedAmount').textContent = fin.observed_amount_formatted || 'N/A';
    document.getElementById('drawerDifferenceAmount').textContent = fin.difference_amount_formatted || '₹0.00';

    // Timeline / Dates
    const dates = finding.dates || {};
    const timingSec = document.getElementById('drawerTimingSection');
    if (dates.expected_date || dates.actual_date) {
        timingSec.classList.remove('hidden');
        document.getElementById('drawerExpectedDate').textContent = dates.expected_date || 'Not specified';
        document.getElementById('drawerActualDate').textContent = dates.actual_date || 'Not recorded';
    } else {
        timingSec.classList.add('hidden');
    }

    // Entity References
    const refContainer = document.getElementById('drawerReferencesList');
    refContainer.innerHTML = '';
    (finding.references || []).forEach(ref => {
        const badge = document.createElement('div');
        badge.className = 'px-2.5 py-1 rounded-lg bg-slate-100 border border-slate-200 text-xs font-mono text-slate-800 flex items-center gap-1.5 cursor-pointer hover:bg-slate-200 transition';
        badge.title = 'Click to copy';
        badge.innerHTML = `
            <span class="text-slate-500 font-sans text-[10px] uppercase font-bold">${ref.label}:</span>
            <span class="font-bold">${ref.value}</span>
            <i data-lucide="copy" class="w-3 h-3 text-slate-400"></i>
        `;
        badge.addEventListener('click', () => {
            navigator.clipboard.writeText(ref.value);
            badge.classList.add('bg-emerald-100', 'text-emerald-800');
            setTimeout(() => badge.classList.remove('bg-emerald-100', 'text-emerald-800'), 1000);
        });
        refContainer.appendChild(badge);
    });

    // Technical details
    document.getElementById('drawerClassification').textContent = finding.classification || 'N/A';
    document.getElementById('drawerLimitation').textContent = finding.limitation || 'No specific technical limitation recorded.';
    document.getElementById('drawerRawPayload').textContent = JSON.stringify(finding.technical || finding, null, 2);

    // Open drawer
    document.getElementById('investigationDrawer').classList.remove('translate-x-full');
    document.getElementById('drawerOverlay').classList.remove('hidden');

    initLucide();
}

function updateRawDataCounts(sourceData) {
    if (!sourceData) return;
    document.getElementById('rawCountOrders').textContent = (sourceData.orders || []).length;
    document.getElementById('rawCountAttempts').textContent = (sourceData.attempts || []).length;
    document.getElementById('rawCountProcessor').textContent = (sourceData.processor || []).length;
    document.getElementById('rawCountSettlements').textContent = (sourceData.settlements || []).length;
    document.getElementById('rawCountBank').textContent = (sourceData.bank || []).length;
}

function renderRawContent() {
    if (!currentData || !currentData.source_data) return;
    const contentArea = document.getElementById('rawContentArea');
    const records = currentData.source_data[activeRawTab] || [];
    if (records.length === 0) {
        contentArea.innerHTML = `<div class="text-slate-400 p-3 italic">No raw records for this table.</div>`;
        return;
    }
    contentArea.innerHTML = `<pre class="text-slate-700 font-mono text-[11px] overflow-x-auto">${JSON.stringify(records, null, 2)}</pre>`;
}

function exportFindingsToCsv() {
    if (!allFindings || allFindings.length === 0) {
        alert('No findings to export.');
        return;
    }

    const headers = ['Finding ID', 'Layer', 'Status', 'Title', 'Expected Amount', 'Observed Amount', 'Difference', 'Suggested Check'];
    const rows = allFindings.map(f => {
        const fin = f.financials || {};
        return [
            `"${f.finding_id || ''}"`,
            `"${f.layer || ''}"`,
            `"${f.status || ''}"`,
            `"${(f.title || '').replace(/"/g, '""')}"`,
            `"${fin.expected_amount || ''}"`,
            `"${fin.observed_amount || ''}"`,
            `"${fin.difference_amount || ''}"`,
            `"${(f.suggested_check || '').replace(/"/g, '""')}"`
        ];
    });

    const csvContent = [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.setAttribute('href', url);
    link.setAttribute('download', `SettlementLens_Findings_Report_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}
