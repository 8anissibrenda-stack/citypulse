import sys

with open("app/static/app.js", "r", encoding="utf-8") as f:
    content = f.read()

# Map Initialization
map_init_target = """async function initMap() {
    // Demo City Center
    appState.map = L.map('map').setView([20.0060, 78.0000], 15);
    
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    }).addTo(appState.map);"""

map_init_replace = """async function initMap() {
    // Demo City Center
    appState.map = L.map('map', {zoomControl: true, attributionControl: false}).setView([20.0060, 78.0000], 15);
    // No online tiles
    document.querySelector('.leaflet-container').style.backgroundColor = '#121212';
    
    appState.routeTravelledLayer = L.polyline([], {color: '#4CAF50', weight: 4, zIndexOffset: 500}).addTo(appState.map);
"""
content = content.replace(map_init_target, map_init_replace)

route_target = """            // Extend route slightly
            latlngs.unshift([20.0000, 78.0000]);
            latlngs.push([20.0120, 78.0000]);
            appState.routeLayer = L.polyline(latlngs, {color: '#4CAF50', weight: 4, dashArray: '5, 10'}).addTo(appState.map);
        }"""
route_replace = """            // Extend route slightly
            latlngs.unshift([20.0000, 78.0000]);
            latlngs.push([20.0120, 78.0000]);
            appState.routeLayer = L.polyline(latlngs, {color: '#555', weight: 6, dashArray: '10, 15'}).addTo(appState.map);
            appState.map.fitBounds(appState.routeLayer.getBounds());
            
            // Hospital marker
            const hospIcon = L.divIcon({
                className: 'custom-div-icon',
                html: `<div style="background: white; border-radius: 4px; padding: 4px; text-align: center; border: 2px solid #555;">
                          <div style="color: red; font-weight: bold; font-size: 16px; line-height: 1;">+</div>
                          <div style="color: black; font-size: 10px; font-weight: bold;">Hospital</div>
                       </div>`,
                iconSize: [60, 40],
                iconAnchor: [30, 20]
            });
            L.marker([20.0120, 78.0000], {icon: hospIcon}).addTo(appState.map);
        }"""
content = content.replace(route_target, route_replace)

signal_target = """        signals.forEach(s => {
            const icon = L.divIcon({
                className: 'custom-div-icon',
                html: `<div style="background-color: ${getSignalColorHex(s.ns_colour)}; width: 16px; height: 16px; border-radius: 50%; border: 2px solid white;"></div>`,
                iconSize: [20, 20],
                iconAnchor: [10, 10]
            });
            
            const marker = L.marker([s.lat, s.lon], {icon: icon}).addTo(appState.map);
            marker.bindPopup(`<b>${s.name}</b><br>Code: ${s.code}`);
            appState.signalMarkers[s.id] = marker;
        });"""
signal_replace = """        signals.forEach(s => {
            const icon = L.divIcon({
                className: 'custom-div-icon',
                html: `<div style="position: relative;">
                          <div style="background-color: ${getSignalColorHex(s.ns_colour)}; width: 24px; height: 24px; border-radius: 50%; border: 2px solid white; text-align: center; line-height: 24px; color: white; font-weight: bold; font-size: 10px;">${s.code}</div>
                       </div>`,
                iconSize: [28, 28],
                iconAnchor: [14, 14]
            });
            
            const marker = L.marker([s.lat, s.lon], {icon: icon, zIndexOffset: 200}).addTo(appState.map);
            appState.signalMarkers[s.id] = marker;
        });"""
content = content.replace(signal_target, signal_replace)

update_sig_target = """function updateSignalOnMap(state) {
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
}"""
update_sig_replace = """function updateSignalOnMap(state) {
    if (!state || !state.signal_id) return;
    const marker = appState.signalMarkers[state.signal_id];
    if (marker) {
        const hex = getSignalColorHex(state.ns_colour);
        let border = '2px solid white';
        let preemptHtml = '';
        if (state.preempt_active) {
            border = '3px solid #00BCD4';
            preemptHtml = `<div style="position: absolute; top: -15px; left: -30px; width: 90px; text-align: center; color: #00BCD4; font-size: 9px; font-weight: bold; text-shadow: 1px 1px 2px black;">PRIORITY GRANTED</div>`;
        }
        
        const sigCode = "S" + state.signal_id; // Approximation
        
        const icon = L.divIcon({
            className: 'custom-div-icon',
            html: `<div style="position: relative;">
                      ${preemptHtml}
                      <div style="background-color: ${hex}; width: 24px; height: 24px; border-radius: 50%; border: ${border}; text-align: center; line-height: 24px; color: white; font-weight: bold; font-size: 10px;">${sigCode}</div>
                   </div>`,
            iconSize: [28, 28],
            iconAnchor: [14, 14]
        });
        marker.setIcon(icon);
    }
}"""
content = content.replace(update_sig_target, update_sig_replace)

update_amb_target = """function updateAmbulanceOnMap(data) {
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
}"""
update_amb_replace = """function updateAmbulanceOnMap(data) {
    if (!appState.map) return;
    
    const rot = data.heading || 0;
    let flash = '';
    if (data.emergency) {
        flash = 'animation: flash-siren 0.5s infinite alternate;';
    }
    
    const iconHtml = `<div class="amb-marker" style="transform: rotate(${rot}deg); width: 30px; height: 16px; background: white; border: 1px solid #333; border-radius: 3px; position: relative; display: flex; align-items: center; justify-content: center;">
        <div style="color: red; font-size: 14px; font-weight: bold; line-height: 14px;">+</div>
        <div style="position: absolute; left: 2px; top: -4px; width: 6px; height: 6px; background: blue; border-radius: 50%; ${flash}"></div>
        <div style="position: absolute; left: 2px; bottom: -4px; width: 6px; height: 6px; background: red; border-radius: 50%; ${flash}"></div>
    </div>`;

    if (!appState.ambMarker) {
        const icon = L.divIcon({
            className: 'custom-div-icon',
            html: iconHtml,
            iconSize: [30, 16],
            iconAnchor: [15, 8]
        });
        appState.ambMarker = L.marker([data.lat, data.lon], {icon: icon, zIndexOffset: 1000}).addTo(appState.map);
        appState.ambPath = [];
    } else {
        appState.ambMarker.setLatLng([data.lat, data.lon]);
        appState.ambMarker.setIcon(L.divIcon({
            className: 'custom-div-icon',
            html: iconHtml,
            iconSize: [30, 16],
            iconAnchor: [15, 8]
        }));
    }
    
    // Track path and color travelled green
    if (data.status === 'idle') {
        appState.ambPath = [];
        if (appState.routeTravelledLayer) appState.routeTravelledLayer.setLatLngs([]);
    } else {
        appState.ambPath.push([data.lat, data.lon]);
        if (appState.routeTravelledLayer) appState.routeTravelledLayer.setLatLngs(appState.ambPath);
    }
    
    // Status text
    els.ambStatus.innerHTML = `Ambulance - Mode: <b>${data.mode || 'N/A'}</b> | Next: ${data.next_signal || 'None'} | ETA: ${data.eta_s ? Math.round(data.eta_s) + 's' : 'N/A'}`;
}"""
content = content.replace(update_amb_target, update_amb_replace)

compare_target = """els.btnCompare.addEventListener('click', async () => {
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
        });"""
compare_replace = """els.btnCompare.addEventListener('click', async () => {
    els.ambStatus.textContent = "Running comparison (baseline then priority)...";
    els.ambSaved.style.display = 'none';
    try {
        await fetch('/api/ambulance/simulate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({route_id: 1, mode: 'baseline', sim_speed: 10})
        });
        
        await new Promise(r => setTimeout(r, 1000));
        
        await fetch('/api/ambulance/simulate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({route_id: 1, mode: 'priority', sim_speed: 10})
        });"""
content = content.replace(compare_target, compare_replace)


with open("app/static/app.js", "w", encoding="utf-8") as f:
    f.write(content)
