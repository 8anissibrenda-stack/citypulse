"""CityPulse Frontend Application Logic."""

// State
let appState = {
    pipelineRunning: false,
    mode: 'simulator',
    map: null,
    ambMarker: null,
    routeLayer: null,
    signalMarkers: {},
    chart: null
};

// Elements
const els = {
    modeSelect: document.getElementById('mode-select'),
    btnStart: document.getElementById('btn-start'),
    btnStop: document.getElementById('btn-stop'),
    statusBadge: document.getElementById('pipeline-status'),
    videoStream: document.getElementById('video-stream'),
    videoPlaceholder: document.getElementById('video-placeholder'),
    alertFeed: document.getElementById('alert-feed'),
    hotspotsBody: document.getElementById('hotspots-body'),
    scenarioList: document.getElementById('scenario-list'),
    ambChart: document.getElementById('ambChart'),
    btnSimBaseline: document.getElementById('btn-sim-baseline'),
    btnSimPriority: document.getElementById('btn-sim-priority'),
    btnCompare: document.getElementById('btn-compare'),
    ambStatus: document.getElementById('amb-status'),
    ambSaved: document.getElementById('amb-saved'),
    btnSaveSettings: document.getElementById('btn-save-settings'),
    valTtcWarn: document.getElementById('val-ttc-warn'),
    valTtcCrit: document.getElementById('val-ttc-crit'),
    setTtcWarn: document.getElementById('set-ttc-warn'),
    setTtcCrit: document.getElementById('set-ttc-crit'),
};

// WebSocket
let ws;
function connectWS() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
    
    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        handleWSMessage(msg);
    };
    
    ws.onclose = () => {
        setTimeout(connectWS, 2000); // Reconnect
    };
}

function handleWSMessage(msg) {
    if (msg.type === 'alert') {
        addAlert(msg);
    } else if (msg.type === 'alert_clear') {
        // Handled server-side usually, but could clear UI here
    } else if (msg.type === 'signal_update') {
        updateSignalOnMap(msg.state);
    } else if (msg.type === 'ambulance_update') {
        updateAmbulanceOnMap(msg);
    }
}

// UI Updaters
function addAlert(alert) {
    const feed = els.alertFeed;
    const item = document.createElement('div');
    item.className = `alert-item ${alert.event_type}`;
    
    const time = new Date().toLocaleTimeString();
    
    let title = "Warning";
    if (alert.event_type === 'critical') title = "CRITICAL ALERT";
    if (alert.event_type === 'near_miss') title = "Near Miss";
    
    item.innerHTML = `
        <div class="alert-header">
            <span>${title}</span>
            <span>${time}</span>
        </div>
        <div class="alert-details">
            TTC: ${alert.ttc_s}s | Dist: ${alert.min_distance_m}m<br>
            ${alert.vru_class} vs ${alert.vehicle_class}
            ${alert.zone_name ? `in ${alert.zone_name}` : ''}
        </div>
    `;
    
    feed.insertBefore(item, feed.firstChild);
    
    // Keep max 20 alerts
    while (feed.children.length > 20) {
        feed.removeChild(feed.lastChild);
    }
}

// API Calls
async function fetchState() {
    try {
        const res = await fetch('/api/state');
        const data = await res.json();
        
        appState.pipelineRunning = data.pipeline.running;
        appState.mode = data.pipeline.mode;
        
        els.modeSelect.value = appState.mode;
        updatePipelineUI();
        
        // Init signals on map
        data.signals.forEach(updateSignalOnMap);
        
    } catch (e) {
        console.error("Failed to fetch state", e);
    }
}

async function fetchMetrics() {
    try {
        const res = await fetch('/api/metrics');
        const data = await res.json();
        
        document.getElementById('metric-warnings').textContent = data.warnings;
        document.getElementById('metric-criticals').textContent = data.criticals;
        document.getElementById('metric-nearmiss').textContent = data.near_misses;
        document.getElementById('metric-latency').textContent = `${data.p95_latency_ms} ms`;
        
        // Update chart if comparison exists
        if (data.ambulance_comparison && data.ambulance_comparison.length > 0) {
            updateChart(data.ambulance_comparison);
        }
    } catch (e) {
        console.error("Failed to fetch metrics", e);
    }
}

async function fetchHotspots() {
    try {
        const res = await fetch('/api/hotspots');
        const data = await res.json();
        
        els.hotspotsBody.innerHTML = '';
        data.forEach(h => {
            els.hotspotsBody.innerHTML += `
                <tr>
                    <td>${h.zone_name}</td>
                    <td>${h.n_events}</td>
                    <td>${h.avg_ttc_s}s</td>
                </tr>
            `;
        });
    } catch (e) {
        console.error("Failed to fetch hotspots", e);
    }
}

async function fetchScenarios() {
    try {
        const [scenRes, resultsRes] = await Promise.all([
            fetch('/api/scenarios'),
            fetch('/api/scenarios/results')
        ]);
        
        const scenarios = await scenRes.json();
        const results = await resultsRes.json();
        
        // Get latest result per scenario
        const latestResults = {};
        results.forEach(r => {
            if (!latestResults[r.scenario_id]) {
                latestResults[r.scenario_id] = r;
            }
        });
        
        els.scenarioList.innerHTML = '';
        scenarios.forEach(s => {
            const r = latestResults[s.id];
            let statusBadge = '<span class="status-badge status-pending">Not Run</span>';
            if (r) {
                statusBadge = r.passed 
                    ? '<span class="status-badge status-pass">PASS</span>'
                    : '<span class="status-badge status-fail">FAIL</span>';
            }
            
            els.scenarioList.innerHTML += `
                <div class="scenario-item">
                    <div class="scenario-info">
                        <div class="scenario-name">${s.code}: ${s.name}</div>
                        <div class="scenario-desc">${s.expected_outcome}</div>
                    </div>
                    <div class="flex-row">
                        ${statusBadge}
                        <button class="primary" onclick="runScenario('${s.code}')" style="padding: 2px 8px; font-size: 0.8rem;">Run</button>
                    </div>
                </div>
            `;
        });
    } catch (e) {
        console.error("Failed to fetch scenarios", e);
    }
}

async function fetchConfig() {
    try {
        const res = await fetch('/api/config/risk');
        const data = await res.json();
        const cfg = {};
        data.forEach(item => cfg[item.key] = item.value);
        
        if (cfg.ttc_warning_s) {
            els.setTtcWarn.value = cfg.ttc_warning_s;
            els.valTtcWarn.textContent = cfg.ttc_warning_s;
        }
        if (cfg.ttc_critical_s) {
            els.setTtcCrit.value = cfg.ttc_critical_s;
            els.valTtcCrit.textContent = cfg.ttc_critical_s;
        }
    } catch (e) {
        console.error("Failed to fetch config", e);
    }
}

// Pipeline Controls
async function startPipeline() {
    try {
        const mode = els.modeSelect.value;
        const res = await fetch('/api/pipeline/start', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({camera_id: 1, mode: mode})
        });
        
        if (res.ok) {
            appState.pipelineRunning = true;
            appState.mode = mode;
            updatePipelineUI();
        } else {
            const err = await res.json();
            alert("Error: " + err.detail);
        }
    } catch (e) {
        alert("Failed to start pipeline.");
    }
}

async function stopPipeline() {
    try {
        await fetch('/api/pipeline/stop', {method: 'POST'});
        appState.pipelineRunning = false;
        updatePipelineUI();
    } catch (e) {
        console.error("Failed to stop pipeline", e);
    }
}

function updatePipelineUI() {
    if (appState.pipelineRunning) {
        els.btnStart.style.display = 'none';
        els.btnStop.style.display = 'block';
        els.statusBadge.textContent = 'RUNNING';
        els.statusBadge.style.backgroundColor = 'rgba(76, 175, 80, 0.2)';
        els.statusBadge.style.color = '#81C784';
        
        // Add timestamp to force reload
        els.videoStream.src = `/video_feed?t=${new Date().getTime()}`;
        els.videoStream.style.display = 'block';
        els.videoPlaceholder.style.display = 'none';
    } else {
        els.btnStart.style.display = 'block';
        els.btnStop.style.display = 'none';
        els.statusBadge.textContent = 'STOPPED';
        els.statusBadge.style.backgroundColor = 'rgba(255, 255, 255, 0.1)';
        els.statusBadge.style.color = '#ccc';
        
        els.videoStream.src = '';
        els.videoStream.style.display = 'none';
        els.videoPlaceholder.style.display = 'block';
    }
}

// Map Initialization
async function initMap() {
    // Demo City Center
    appState.map = L.map('map').setView([20.0060, 78.0000], 15);
    
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    }).addTo(appState.map);

    // Load route
    try {
        const res = await fetch('/api/junctions');
        const junctions = await res.json();
        
        // Just draw a line through junctions for visual route
        const latlngs = junctions.sort((a,b) => a.lat - b.lat).map(j => [j.lat, j.lon]);
        if (latlngs.length > 0) {
            // Extend route slightly
            latlngs.unshift([20.0000, 78.0000]);
            latlngs.push([20.0120, 78.0000]);
            appState.routeLayer = L.polyline(latlngs, {color: '#4CAF50', weight: 4, dashArray: '5, 10'}).addTo(appState.map);
        }
        
        // Setup signal markers
        const sigRes = await fetch('/api/signals');
        const signals = await sigRes.json();
        
        signals.forEach(s => {
            const icon = L.divIcon({
                className: 'custom-div-icon',
                html: `<div style="background-color: ${getSignalColorHex(s.ns_colour)}; width: 16px; height: 16px; border-radius: 50%; border: 2px solid white;"></div>`,
                iconSize: [20, 20],
                iconAnchor: [10, 10]
            });
            
            const marker = L.marker([s.lat, s.lon], {icon: icon}).addTo(appState.map);
            marker.bindPopup(`<b>${s.name}</b><br>Code: ${s.code}`);
            appState.signalMarkers[s.id] = marker;
        });
        
    } catch (e) {
        console.error("Failed to init map data", e);
    }
}

function getSignalColorHex(colorName) {
    if (colorName === 'green') return '#4CAF50';
    if (colorName === 'yellow') return '#FFEB3B';
    if (colorName === 'red') return '#F44336';
    return '#999';
}

function updateSignalOnMap(state) {
    if (!state || !state.signal_id) return;
    const marker = appState.signalMarkers[state.signal_id];
    if (marker) {
        const hex = getSignalColorHex(state.ns_colour);
        let border = '2px solid white';
        if (state.preempt_active) {
            border = '3px solid #00BCD4'; // Highlight pre-empted signals
        }
        
        const icon = L.divIcon({
            className: 'custom-div-icon',
            html: `<div style="background-color: ${hex}; width: 16px; height: 16px; border-radius: 50%; border: ${border};"></div>`,
            iconSize: [20, 20],
            iconAnchor: [10, 10]
        });
        marker.setIcon(icon);
    }
}

function updateAmbulanceOnMap(data) {
    if (!appState.map) return;
    
    if (!appState.ambMarker) {
        const icon = L.divIcon({
            className: 'custom-div-icon',
            html: `<div style="background-color: #00BCD4; width: 24px; height: 24px; text-align:center; line-height:24px; border-radius: 4px; border: 2px solid white; color: black; font-weight: bold; font-size: 14px;">+</div>`,
            iconSize: [28, 28],
            iconAnchor: [14, 14]
        });
        appState.ambMarker = L.marker([data.lat, data.lon], {icon: icon, zIndexOffset: 1000}).addTo(appState.map);
    } else {
        appState.ambMarker.setLatLng([data.lat, data.lon]);
    }
    
    // Highlight if emergency
    if (data.emergency) {
        appState.ambMarker._icon.firstChild.style.backgroundColor = '#2196F3';
        appState.ambMarker._icon.firstChild.style.boxShadow = '0 0 10px #2196F3';
    } else {
        appState.ambMarker._icon.firstChild.style.backgroundColor = '#999';
        appState.ambMarker._icon.firstChild.style.boxShadow = 'none';
    }
}

// Chart Initialization
function initChart() {
    const ctx = els.ambChart.getContext('2d');
    Chart.defaults.color = '#aaaaaa';
    Chart.defaults.font.family = "'Inter', sans-serif";
    
    appState.chart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: ['Duration (s)', 'Wait Time (s)', 'Stops'],
            datasets: [
                {
                    label: 'Baseline',
                    backgroundColor: 'rgba(255, 152, 0, 0.8)',
                    data: [0, 0, 0]
                },
                {
                    label: 'Priority',
                    backgroundColor: 'rgba(33, 150, 243, 0.8)',
                    data: [0, 0, 0]
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: { beginAtZero: true, grid: { color: 'rgba(255, 255, 255, 0.1)' } },
                x: { grid: { display: false } }
            },
            plugins: {
                legend: { position: 'bottom' }
            }
        }
    });
}

function updateChart(comparisonData) {
    if (!appState.chart) return;
    
    let base = {avg_duration_s: 0, avg_wait_s: 0, avg_stops: 0};
    let prio = {avg_duration_s: 0, avg_wait_s: 0, avg_stops: 0};
    
    comparisonData.forEach(d => {
        if (d.mode === 'baseline') base = d;
        if (d.mode === 'priority') prio = d;
    });
    
    appState.chart.data.datasets[0].data = [base.avg_duration_s, base.avg_wait_s, base.avg_stops * 10]; // scale stops for visibility
    appState.chart.data.datasets[1].data = [prio.avg_duration_s, prio.avg_wait_s, prio.avg_stops * 10];
    appState.chart.update();
}

// Actions
window.runScenario = async function(code) {
    try {
        await fetch(`/api/scenarios/${code}/run`, {method: 'POST'});
        fetchScenarios();
    } catch (e) {
        alert("Scenario failed");
    }
}

document.getElementById('btn-run-all').addEventListener('click', async () => {
    try {
        els.scenarioList.innerHTML = '<div style="text-align:center; padding:1rem;">Running all scenarios...</div>';
        await fetch('/api/scenarios/run-all', {method: 'POST'});
        fetchScenarios();
    } catch (e) {
        alert("Run all failed");
    }
});

els.btnSimBaseline.addEventListener('click', async () => {
    els.ambStatus.textContent = "Running baseline simulation...";
    try {
        await fetch('/api/ambulance/simulate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({route_id: 1, mode: 'baseline', sim_speed: 10})
        });
        els.ambStatus.textContent = "Baseline complete.";
        fetchMetrics();
    } catch (e) {
        els.ambStatus.textContent = "Simulation failed.";
    }
});

els.btnSimPriority.addEventListener('click', async () => {
    els.ambStatus.textContent = "Running priority simulation...";
    try {
        await fetch('/api/ambulance/simulate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({route_id: 1, mode: 'priority', sim_speed: 10})
        });
        els.ambStatus.textContent = "Priority complete.";
        fetchMetrics();
    } catch (e) {
        els.ambStatus.textContent = "Simulation failed.";
    }
});

els.btnCompare.addEventListener('click', async () => {
    els.ambStatus.textContent = "Running comparison (baseline then priority)...";
    els.ambSaved.style.display = 'none';
    try {
        await fetch('/api/ambulance/simulate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({route_id: 1, mode: 'baseline', sim_speed: 10})
        });
        await fetch('/api/ambulance/simulate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({route_id: 1, mode: 'priority', sim_speed: 10})
        });
        
        // Fetch comparison
        const res = await fetch('/api/ambulance/comparison');
        const data = await res.json();
        
        els.ambStatus.textContent = "Comparison complete.";
        els.ambSaved.textContent = `Priority saved ${data.time_saved_pct}% of journey time!`;
        els.ambSaved.style.display = 'block';
        
        fetchMetrics();
    } catch (e) {
        els.ambStatus.textContent = "Comparison failed.";
    }
});

// Settings
els.setTtcWarn.addEventListener('input', (e) => els.valTtcWarn.textContent = e.target.value);
els.setTtcCrit.addEventListener('input', (e) => els.valTtcCrit.textContent = e.target.value);

els.btnSaveSettings.addEventListener('click', async () => {
    try {
        await fetch('/api/config/risk', {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                values: {
                    ttc_warning_s: parseFloat(els.setTtcWarn.value),
                    ttc_critical_s: parseFloat(els.setTtcCrit.value)
                }
            })
        });
        
        const btn = els.btnSaveSettings;
        const origText = btn.textContent;
        btn.textContent = "Saved!";
        btn.classList.add("success");
        setTimeout(() => {
            btn.textContent = origText;
            btn.classList.remove("success");
        }, 2000);
    } catch (e) {
        alert("Failed to save settings");
    }
});

els.btnStart.addEventListener('click', startPipeline);
els.btnStop.addEventListener('click', stopPipeline);

// Initialization
document.addEventListener('DOMContentLoaded', () => {
    connectWS();
    initMap();
    initChart();
    
    // Initial fetches
    fetchState();
    fetchMetrics();
    fetchHotspots();
    fetchScenarios();
    fetchConfig();
    
    // Polling for metrics and hotspots
    setInterval(() => {
        fetchMetrics();
        fetchHotspots();
    }, 5000);
});
