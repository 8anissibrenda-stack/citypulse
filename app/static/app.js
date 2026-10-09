// CityPulse Frontend Logic
let ws = null;
let currentMode = 'simulator';
let isRunning = false;

// DOM Elements
const canvas = document.getElementById('scene-canvas');
const ctx = canvas.getContext('2d');
const videoFeed = document.getElementById('video-feed');
const badge = document.getElementById('status-badge');
const driverDisplay = document.getElementById('driver-display');
const driverMain = document.getElementById('display-main');
const driverSub = document.getElementById('display-sub');
const liveAlerts = document.getElementById('live-alerts');

// Tokens
// Add sigColor helper
function sigColor(state) {
    if (!state) return '#EB3C3C'; // default red
    const s = String(state).toLowerCase();
    if (['green', 'g', 'green_ns', 'ns_green'].includes(s)) return '#5AC850';
    if (['yellow', 'amber', 'y'].includes(s)) return '#FAAA28';
    if (['red', 'all_red', 'r'].includes(s)) return '#EB3C3C';
    return '#EB3C3C'; // default
}

// Tokens
const TOKENS = {
    grass: '#243426', sidewalk: '#3C423E', road: '#3E3E40',
    zone: '#28C8DC', zoneBg: 'rgba(40, 200, 220, 0.12)',
    car: '#2196F3', ped: '#FF9800', amber: '#FAAA28', red: '#EB3C3C',
    chipOn: '#2878C8', chipOff: '#3A3E46'
};

const CAPTIONS = {
    1: "1. Camera frames are captured, road users detected and tracked",
    2: "2. Engine predicts the car and pedestrian paths - collision course found",
    3: "3. TTC under 3 s for 3 frames -> warning sent to driver display",
    4: "4. Driver brakes in time - car slows before the crossing",
    5: "5. Pedestrian crosses safely while the car waits - event saved to the database",
    6: "6. Crossing clear - traffic resumes, alert clears automatically"
};

// State
let lastFrameData = null;

function switchTab(tabId) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    
    event.target.classList.add('active');
    document.getElementById('tab-' + tabId).classList.add('active');
    
    if (tabId === 'analytics') {
        fetchAnalytics();
    }
}

function startPipeline() {
    currentMode = document.getElementById('mode-select').value;
    fetch(`/api/pipeline/start?mode=${currentMode}`, { method: 'POST' })
        .then(res => res.json())
        .then(data => {
            isRunning = true;
            badge.textContent = 'RUNNING';
            badge.className = 'badge running';
            if (currentMode === 'video') {
                canvas.style.display = 'none';
                videoFeed.style.display = 'block';
                videoFeed.src = '/video_feed?' + new Date().getTime();
            } else {
                canvas.style.display = 'block';
                videoFeed.style.display = 'none';
                videoFeed.src = '';
            }
            connectWebSocket();
        });
}

function stopPipeline() {
    fetch('/api/pipeline/stop', { method: 'POST' })
        .then(() => {
            isRunning = false;
            badge.textContent = 'STOPPED';
            badge.className = 'badge stopped';
            if (ws) ws.close();
            videoFeed.src = '';
        });
}

function replayScenario() {
    stopPipeline();
    setTimeout(startPipeline, 500);
}

function connectWebSocket() {
    if (ws) ws.close();
    ws = new WebSocket(`ws://${window.location.host}/ws`);
    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === 'frame') {
            lastFrameData = msg;
            if (currentMode === 'simulator') {
                drawScene(msg);
            }
            updateUI(msg);
        } else if (msg.type === 'signal_update') {
            console.log('WS signal_update:', msg);
        }
    };
}

function drawScene(data) {
    ctx.save();
    ctx.clearRect(0, 0, 930, 674);
    ctx.translate(0, -46);

    // Grass is canvas bg.
    // Sidewalks
    ctx.fillStyle = TOKENS.sidewalk;
    ctx.fillRect(0, 0, 930, 330);
    ctx.fillRect(0, 490, 930, 720); // 720 is beyond 674+46

    // Road
    ctx.fillStyle = TOKENS.road;
    ctx.fillRect(0, 330, 930, 160);

    // Dashed center line
    ctx.strokeStyle = '#FFF';
    ctx.lineWidth = 2;
    ctx.setLineDash([20, 20]);
    ctx.beginPath();
    ctx.moveTo(0, 410);
    ctx.lineTo(930, 410);
    ctx.stroke();
    ctx.setLineDash([]);

    // Zebra crossing
    ctx.fillStyle = '#FFF';
    for (let y = 336; y <= 490 - 12; y += 24) {
        ctx.fillRect(560, y, 140, 12);
    }

    // Conflict zone
    ctx.fillStyle = TOKENS.zoneBg;
    ctx.strokeStyle = TOKENS.zone;
    ctx.lineWidth = 1;
    ctx.fillRect(560, 230, 140, 360);
    ctx.strokeRect(560, 230, 140, 360);
    ctx.fillStyle = TOKENS.zone;
    ctx.font = '11px sans-serif';
    ctx.fillText('Zebra crossing (conflict zone)', 560, 225);

    // Objects
    let carObj = null;
    let pedObj = null;

    data.objects.forEach(o => {
        if (o.cls === 'car') {
            carObj = o;
            ctx.fillStyle = TOKENS.car;
            // Draw rounded rect 70x34
            ctx.beginPath();
            ctx.roundRect(o.x - 35, o.y - 17, 70, 34, 4);
            ctx.fill();
            // Windscreen (front is right)
            ctx.fillStyle = '#64B5F6';
            ctx.fillRect(o.x + 10, o.y - 13, 15, 26);
            
            // Label
            ctx.strokeStyle = TOKENS.car;
            ctx.strokeRect(o.x - 35, o.y - 17, 70, 34);
            ctx.fillStyle = TOKENS.car;
            ctx.fillText(`car #${o.id}  ${o.conf.toFixed(2)}`, o.x - 35, o.y - 20);
        } else if (o.cls === 'person') {
            pedObj = o;
            // Orange box
            ctx.strokeStyle = TOKENS.ped;
            ctx.lineWidth = 2;
            ctx.strokeRect(o.x - 14, o.y - 21, 28, 42);
            // Head circle + body line
            ctx.beginPath();
            ctx.arc(o.x, o.y - 8, 6, 0, Math.PI * 2);
            ctx.moveTo(o.x, o.y - 2);
            ctx.lineTo(o.x, o.y + 12);
            ctx.stroke();
            // Label
            ctx.fillStyle = TOKENS.ped;
            ctx.fillText(`person #${o.id}  ${o.conf.toFixed(2)}`, o.x - 14, o.y - 25);
        }
    });

    // Conflict Line
    if (data.conflict && carObj && pedObj) {
        ctx.strokeStyle = data.conflict.level === 'critical' ? TOKENS.red : TOKENS.amber;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(carObj.x, carObj.y);
        ctx.lineTo(pedObj.x, pedObj.y);
        ctx.stroke();

        // Midpoint label
        const mx = (carObj.x + pedObj.x) / 2;
        const my = (carObj.y + pedObj.y) / 2;
        ctx.fillStyle = '#000';
        ctx.fillRect(mx - 25, my - 10, 50, 20);
        ctx.fillStyle = ctx.strokeStyle;
        ctx.fillText(`TTC ${data.conflict.ttc}s`, mx - 20, my + 4);
    }

    ctx.restore();

    // Chips & Captions (handled outside canvas)
    document.getElementById('caption-text').textContent = CAPTIONS[data.stage] || "";
    for (let i = 1; i <= 6; i++) {
        const chip = document.getElementById('chip-' + i);
        let isOn = false;
        if (i <= 3) isOn = true;
        else if (i === 4) isOn = (data.display !== 'clear' || data.conflict);
        else if (i === 5) isOn = (data.display !== 'clear');
        else if (i === 6) isOn = data.record;

        chip.style.background = isOn ? (i === 5 ? TOKENS.amber : TOKENS.chipOn) : TOKENS.chipOff;
        if (isOn && i === 5) {
            chip.style.color = '#000';
        } else {
            chip.style.color = '#FFF';
        }
    }
}

let flashState = false;
setInterval(() => { 
    if (driverDisplay.classList.contains('warning') || driverDisplay.classList.contains('critical')) {
        driverDisplay.classList.toggle('flash');
    }
}, 166);

function updateUI(data) {
    // Driver display
    if (data.display === 'clear') {
        driverDisplay.className = 'driver-display clear';
        driverMain.textContent = 'ROAD CLEAR';
        driverSub.textContent = '';
    } else {
        const isCrit = data.display === 'critical';
        const baseClass = `driver-display ${isCrit ? 'critical' : 'warning'}`;
        const hasFlash = driverDisplay.classList.contains('flash');
        driverDisplay.className = baseClass + (hasFlash ? ' flash' : '');
        driverMain.textContent = 'SLOW DOWN';
        driverSub.textContent = 'PEDESTRIAN CROSSING';
    }

    // Alerts
    if (data.alerts && data.alerts.length > 0) {
        liveAlerts.innerHTML = data.alerts.map(a => `
            <div class="alert-card ${a.level}">
                <div class="alert-title">${a.level === 'critical' ? 'CRITICAL' : 'WARNING'} TTC ${a.ttc}s</div>
                <div class="alert-desc">${a.desc}</div>
            </div>
        `).join('');
    }

    // Metrics
    if (data.metrics) {
        document.getElementById('metric-warnings').textContent = `Warnings logged: ${data.metrics.warnings}`;
        document.getElementById('metric-latency').textContent = `Response time: ${data.metrics.response_ms > 0 ? data.metrics.response_ms + ' ms' : '-'}`;
        document.getElementById('metric-false').textContent = `False alerts: ${data.metrics.false_alerts}`;
    }
}

// Ambulance Flow
let ambAnimId = null;

function runAmbulance(mode) {
    if (ambAnimId) cancelAnimationFrame(ambAnimId);
    
    // Reset visuals
    ['base', 'prio'].forEach(prefix => {
        document.getElementById(`amb-${prefix}`).setAttribute('transform', 'translate(294, 620)');
        document.getElementById(`arr-${prefix}`).setAttribute('opacity', '0');
        document.getElementById(`stat-${prefix}-time`).textContent = 'Journey time: - s';
        document.getElementById(`stat-${prefix}-stops`).textContent = 'Red-light stops: -';
        document.getElementById(`stat-${prefix}-wait`).textContent = 'Waiting: - s';
        [1,2,3].forEach(i => {
            const r = document.getElementById(`${prefix}-ring-s${i}`);
            if (r) r.setAttribute('opacity', '0');
            const t = document.getElementById(`${prefix}-text-s${i}`);
            if (t) t.setAttribute('opacity', '0');
        });
    });
    document.getElementById('amb-overlay').style.display = 'none';

    fetch('/api/ambulance/compare', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            updateAmbulanceChart(data.summary);
            let startT = performance.now();
            function animate(time) {
                // ~10x compression: 1 real second = 10 sim seconds
                let elapsedSim = (time - startT) / 100;
                
                let baseTicks = data.baseline.ticks || [];
                let prioTicks = data.priority.ticks || [];
                let maxTicks = Math.max(baseTicks.length, prioTicks.length);
                
                let tick = Math.floor(elapsedSim / 0.1);
                
                let bTick = Math.min(baseTicks.length > 0 ? baseTicks.length - 1 : 0, tick);
                let pTick = Math.min(prioTicks.length > 0 ? prioTicks.length - 1 : 0, tick);
                
                let baseDone = updateAmbulancePanel('base', baseTicks[bTick], elapsedSim);
                let prioDone = updateAmbulancePanel('prio', prioTicks[pTick], elapsedSim);
                
                if (mode === 'compare' && baseDone && prioDone) {
                    showAmbulanceOverlay(data.summary);
                    setTimeout(resetAmbulances, 5000);
                } else if (mode === 'baseline' && baseDone) {
                    setTimeout(resetAmbulances, 5000);
                } else if (mode === 'priority' && prioDone) {
                    setTimeout(resetAmbulances, 5000);
                } else {
                    ambAnimId = requestAnimationFrame(animate);
                }
            }
            ambAnimId = requestAnimationFrame(animate);
        });
}

function updateAmbulancePanel(prefix, frame, elapsedSim) {
    if (!frame) return true;
    
    let y = frame.y_px;
    document.getElementById(`amb-${prefix}`).setAttribute('transform', `translate(294, ${y})`);
    
    [1,2,3].forEach(i => {
        const state = frame.signals[i-1];
        document.getElementById(`${prefix}-s${i}`).setAttribute('fill', sigColor(state));
        
        if (prefix === 'prio') {
            const isPrio = frame.priority_active[i-1];
            document.getElementById(`prio-ring-s${i}`).setAttribute('opacity', isPrio ? '1' : '0');
            document.getElementById(`prio-text-s${i}`).setAttribute('opacity', isPrio ? '1' : '0');
        }
    });
    
    document.getElementById(`stat-${prefix}-stops`).textContent = `Red-light stops: ${frame.stops}`;
    document.getElementById(`stat-${prefix}-wait`).textContent = `Waiting: ${frame.wait_s.toFixed(1)} s`;
    
    if (frame.done) {
        document.getElementById(`arr-${prefix}`).setAttribute('opacity', '1');
        document.getElementById(`stat-${prefix}-time`).textContent = `Journey time: ${frame.clock_s.toFixed(1)} s`;
    } else {
        document.getElementById(`stat-${prefix}-time`).textContent = `Journey time: ${elapsedSim.toFixed(1)} s`;
    }
    return frame.done;
}

function showAmbulanceOverlay(summary) {
    document.getElementById('amb-overlay').style.display = 'flex';
    document.getElementById('amb-saved').textContent = `Journey time saved: ${summary.time_saved_pct}%`;
    document.getElementById('amb-saved-sub').textContent = `${summary.baseline.duration_s.toFixed(1)} s -> ${summary.priority.duration_s.toFixed(1)} s, ${summary.baseline.stops} stops -> ${summary.priority.stops} stops`;
}

function resetAmbulances() {
    ['base', 'prio'].forEach(prefix => {
        document.getElementById(`amb-${prefix}`).setAttribute('transform', 'translate(294, 620)');
        document.getElementById(`arr-${prefix}`).setAttribute('opacity', '0');
    });
    document.getElementById('amb-overlay').style.display = 'none';
}

let ambChart = null;
function updateAmbulanceChart(summary) {
    if (!summary || !document.getElementById('ambChart')) return;
    const ctx = document.getElementById('ambChart').getContext('2d');
    if (ambChart) ambChart.destroy();
    
    Chart.defaults.color = '#F0F0F0';
    ambChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: ['Journey Time (s)', 'Wait Time (s)', 'Stops'],
            datasets: [
                {
                    label: 'Baseline',
                    backgroundColor: '#AAAAAA',
                    data: [summary.baseline.duration_s, summary.baseline.wait_s, summary.baseline.stops]
                },
                {
                    label: 'Priority',
                    backgroundColor: '#5AC850',
                    data: [summary.priority.duration_s, summary.priority.wait_s, summary.priority.stops]
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: { beginAtZero: true, grid: { color: '#333' } },
                x: { grid: { color: '#333' } }
            },
            plugins: {
                legend: { labels: { color: '#F0F0F0' } }
            }
        }
    });
}

// Analytics Tab
function fetchAnalytics() {
    fetch('/api/signals').then(r => r.json()).then(data => console.log('/api/signals:', data));
    
    fetch('/api/hotspots')
        .then(r => r.json())
        .then(data => {
            document.getElementById('hotspots-body').innerHTML = data.map(h => `
                <tr>
                    <td>Cam ${h.camera_id}</td>
                    <td>${h.zone_name}</td>
                    <td>${h.alert_count} <span class="demo-label">demo data</span></td>
                </tr>
            `).join('');
        });
        
    fetch('/api/scenarios/results')
        .then(r => r.json())
        .then(data => {
            renderScenarios(data);
        });
}

function renderScenarios(results) {
    document.getElementById('scenarios-body').innerHTML = results.map(r => `
        <div style="display:flex; justify-content:space-between; padding:8px; background:var(--card); border-radius:4px;">
            <div>
                <div style="font-weight:bold;">${r.scenario_id}</div>
                <div style="font-size:12px; color:var(--muted);">${r.description}</div>
            </div>
            <div class="status-badge ${r.passed ? 'status-pass' : 'status-fail'}">${r.passed ? 'PASS' : 'FAIL'}</div>
        </div>
    `).join('');
}

function runScenarios() {
    fetch('/api/scenarios/run-all', { method: 'POST' })
        .then(r => r.json())
        .then(data => renderScenarios(data.results));
}

// Risk Settings
document.getElementById('set-ttc-warn')?.addEventListener('input', e => {
    document.getElementById('val-ttc-warn').textContent = parseFloat(e.target.value).toFixed(1);
});
document.getElementById('set-ttc-crit')?.addEventListener('input', e => {
    document.getElementById('val-ttc-crit').textContent = parseFloat(e.target.value).toFixed(1);
});
