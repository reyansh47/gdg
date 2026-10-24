/**
 * FlowSplit Map Controller
 * Seamlessly toggles between Google Maps JavaScript API and a built-in interactive
 * Canvas/Vector map engine for complete offline and zero-config operation.
 */

class MapController {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
    this.mode = 'canvas'; // 'google' or 'canvas'
    this.googleMap = null;
    this.googlePolylines = [];
    this.googleMarkers = [];
    
    // Canvas Engine State
    this.canvas = null;
    this.ctx = null;
    this.routes = [];
    this.selectedRouteId = null;
    this.userLocation = null;
    this.origin = { lat: 37.7749, lng: -122.4494 };
    this.destination = { lat: 37.7915, lng: -122.3999 };
    
    // Viewport transform
    this.zoom = 13.5;
    this.center = { lat: 37.7832, lng: -122.4246 };
    this.isDragging = false;
    this.dragStart = { x: 0, y: 0 };
    
    // Callbacks
    this.onRouteSelected = null;
  }

  async init(browserApiKey = null, mapsJsUrl = "https://maps.googleapis.com/maps/api/js") {
    // Graceful fallback if Google Maps JS fails authentication on localhost / domain
    window.gm_authFailure = () => {
      console.warn("Google Maps JS API authentication failed. Switching to interactive Canvas Vector engine.");
      const hud = document.getElementById('hudEngineLabel');
      if (hud) hud.textContent = "Interactive Vector / Canvas (Active)";
      this.mode = 'canvas';
      this.initCanvasMap();
      if (this.routes && this.routes.length) {
        this.fitBoundsToRoutes();
        this.renderCanvas();
      }
    };

    if (browserApiKey) {
      try {
        await this.loadGoogleMapsScript(browserApiKey, mapsJsUrl);
        await this.initGoogleMap();
        this.mode = 'google';
        const hud = document.getElementById('hudEngineLabel');
        if (hud) hud.textContent = "Google Maps JS API (Live)";
        return;
      } catch (err) {
        console.warn("Failed to load Google Maps JS API, falling back to Canvas engine:", err);
      }
    }

    this.initCanvasMap();
    this.mode = 'canvas';
    const hud = document.getElementById('hudEngineLabel');
    if (hud) hud.textContent = "Interactive Vector / Canvas";
  }

  loadGoogleMapsScript(apiKey, mapsJsUrl = "https://maps.googleapis.com/maps/api/js") {
    return new Promise((resolve, reject) => {
      // If Map is already a constructor, resolve immediately
      if (window.google && window.google.maps && typeof window.google.maps.Map === 'function') {
        resolve();
        return;
      }

      const callbackName = '__flowsplitMapsLoaded';
      let timeoutId = null;

      window[callbackName] = async () => {
        if (timeoutId) clearTimeout(timeoutId);
        try {
          if (window.google && window.google.maps && typeof window.google.maps.importLibrary === 'function') {
            await Promise.allSettled([
              google.maps.importLibrary("maps"),
              google.maps.importLibrary("marker"),
              google.maps.importLibrary("places")
            ]);
          }
        } catch (e) {
          console.warn("importLibrary notice during callback:", e);
        } finally {
          try { delete window[callbackName]; } catch (_) {}
          resolve();
        }
      };

      // Fallback timeout in case of network or key failure
      timeoutId = setTimeout(() => {
        if (window.google && window.google.maps && typeof window.google.maps.Map === 'function') {
          resolve();
        } else {
          reject(new Error("Google Maps script load timed out"));
        }
      }, 10000);

      const script = document.createElement('script');
      let cleanUrl = mapsJsUrl;
      if (!cleanUrl.includes('key=')) {
        cleanUrl += `${cleanUrl.includes('?') ? '&' : '?'}key=${apiKey}`;
      }
      if (!cleanUrl.includes('libraries=')) {
        cleanUrl += `&libraries=places,marker`;
      }
      if (!cleanUrl.includes('loading=')) {
        cleanUrl += `&loading=async`;
      }
      if (!cleanUrl.includes('callback=')) {
        cleanUrl += `&callback=${callbackName}`;
      }
      script.src = cleanUrl;
      script.async = true;
      script.defer = true;
      script.onerror = () => {
        if (timeoutId) clearTimeout(timeoutId);
        reject(new Error("Google Maps script load error"));
      };
      document.head.appendChild(script);
    });
  }

  async initGoogleMap() {
    this.container.innerHTML = '';

    let MapConstructor = window.google?.maps?.Map;
    if (window.google?.maps && typeof window.google.maps.importLibrary === 'function') {
      try {
        const mapsLib = await google.maps.importLibrary("maps");
        if (mapsLib && mapsLib.Map) {
          MapConstructor = mapsLib.Map;
        }
        await google.maps.importLibrary("marker");
      } catch (err) {
        console.warn("Notice importing Google Maps libraries in initGoogleMap:", err);
      }
    }

    if (!MapConstructor && window.google?.maps?.Map) {
      MapConstructor = window.google.maps.Map;
    }

    if (typeof MapConstructor !== 'function') {
      throw new TypeError("google.maps.Map is not a constructor");
    }

    const lightTransitStyle = [
      { elementType: "geometry", stylers: [{ color: "#f8fafc" }] },
      { elementType: "labels.text.stroke", stylers: [{ color: "#ffffff" }] },
      { elementType: "labels.text.fill", stylers: [{ color: "#475569" }] },
      { featureType: "road", elementType: "geometry", stylers: [{ color: "#ffffff" }] },
      { featureType: "road", elementType: "geometry.stroke", stylers: [{ color: "#e2e8f0" }] },
      { featureType: "road.highway", elementType: "geometry", stylers: [{ color: "#ffedd5" }] },
      { featureType: "road.highway", elementType: "geometry.stroke", stylers: [{ color: "#fed7aa" }] },
      { featureType: "water", elementType: "geometry", stylers: [{ color: "#e0f2fe" }] },
      { featureType: "water", elementType: "labels.text.fill", stylers: [{ color: "#0284c7" }] },
      { featureType: "transit", elementType: "geometry", stylers: [{ color: "#f1f5f9" }] },
      { featureType: "poi", elementType: "labels", stylers: [{ visibility: "off" }] },
    ];

    this.googleMap = new MapConstructor(this.container, {
      center: this.center,
      zoom: 13,
      mapId: 'flowsplit_transit_map',
      styles: lightTransitStyle,
      disableDefaultUI: false,
      zoomControl: true,
      mapTypeControl: false,
    });

    // Initialize real-time Google Live Traffic Layer
    try {
      this.trafficLayer = new google.maps.TrafficLayer();
      this.trafficLayer.setMap(this.googleMap);
      console.info("Google Maps live traffic layer initialized successfully.");
    } catch (err) {
      console.warn("Notice: TrafficLayer initialization deferred:", err);
    }
  }

  createTrafficJamMarker(options) {
    const { position, title, streetName, delaySeconds, severity = 'heavy' } = options;
    const isHeavy = severity === 'heavy';
    const delayMin = Math.max(1, Math.round((delaySeconds || 60) / 60));

    if (window.google?.maps?.marker?.AdvancedMarkerElement) {
      const pinDiv = document.createElement('div');
      pinDiv.className = 'custom-traffic-jam-pin';
      pinDiv.style.position = 'relative';
      pinDiv.style.cursor = 'pointer';
      pinDiv.innerHTML = `
        <div style="
          width: 28px;
          height: 28px;
          border-radius: 50%;
          background: ${isHeavy ? '#dc2626' : '#d97706'};
          border: 2px solid #ffffff;
          box-shadow: 0 0 10px ${isHeavy ? 'rgba(220, 38, 38, 0.7)' : 'rgba(217, 119, 6, 0.7)'};
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 13px;
        ">🚨</div>
      `;

      const marker = new google.maps.marker.AdvancedMarkerElement({
        map: this.googleMap,
        position: position,
        title: title || 'Live Traffic Jam Warning',
        content: pinDiv,
      });

      const infoWindow = new google.maps.InfoWindow({
        content: `
          <div style="font-family: Outfit, sans-serif; padding: 6px 10px; color: #0f172a; max-width: 220px;">
            <div style="font-weight: 700; color: #dc2626; font-size: 13px; display: flex; align-items: center; gap: 5px;">
              <span>🚨</span> Real-Time Traffic Jam
            </div>
            <div style="font-size: 12px; margin-top: 4px; font-weight: 600;">
              ${streetName || 'Corridor Bottleneck'}
            </div>
            <div style="font-size: 11px; color: #64748b; margin-top: 2px;">
              Detected Delay: +${delayMin} mins
            </div>
          </div>
        `
      });

      pinDiv.addEventListener('click', () => {
        infoWindow.open(this.googleMap, marker);
      });

      return marker;
    }

    if (window.google?.maps?.Marker) {
      return new google.maps.Marker({
        position: position,
        map: this.googleMap,
        title: title || 'Traffic Jam Hazard',
        icon: {
          path: google.maps.SymbolPath.CIRCLE,
          scale: 9,
          fillColor: '#dc2626',
          fillOpacity: 1,
          strokeColor: '#ffffff',
          strokeWeight: 2.5,
        },
      });
    }
    return null;
  }

  createMarker(options) {
    const { position, title, label, color = '#ea580c', scale = 11 } = options;
    const labelText = typeof label === 'object' ? label.text : (label || '');

    if (google.maps.marker && google.maps.marker.AdvancedMarkerElement) {
      const pinDiv = document.createElement('div');
      pinDiv.className = 'custom-map-pin';
      pinDiv.style.width = `${scale * 2}px`;
      pinDiv.style.height = `${scale * 2}px`;
      pinDiv.style.borderRadius = '50%';
      pinDiv.style.backgroundColor = color;
      pinDiv.style.border = '2.5px solid #ffffff';
      pinDiv.style.boxShadow = '0 2px 6px rgba(0,0,0,0.3)';
      pinDiv.style.display = 'flex';
      pinDiv.style.alignItems = 'center';
      pinDiv.style.justifyContent = 'center';
      pinDiv.style.color = '#ffffff';
      pinDiv.style.fontWeight = 'bold';
      pinDiv.style.fontSize = `${Math.max(9, Math.round(scale * 0.9))}px`;
      pinDiv.style.fontFamily = 'Outfit, sans-serif';
      if (labelText) {
        pinDiv.textContent = labelText;
      }

      return new google.maps.marker.AdvancedMarkerElement({
        map: this.googleMap,
        position: position,
        title: title || '',
        content: pinDiv,
      });
    }

    return new google.maps.Marker({
      position: position,
      map: this.googleMap,
      title: title || '',
      label: labelText ? { text: labelText, color: '#ffffff', fontWeight: 'bold' } : undefined,
      icon: {
        path: google.maps.SymbolPath.CIRCLE,
        scale: scale,
        fillColor: color,
        fillOpacity: 1,
        strokeColor: '#ffffff',
        strokeWeight: 2.5,
      },
    });
  }

  initCanvasMap() {
    this.container.innerHTML = '';
    this.canvas = document.createElement('canvas');
    this.canvas.style.width = '100%';
    this.canvas.style.height = '100%';
    this.canvas.style.display = 'block';
    this.canvas.style.cursor = 'grab';
    this.container.appendChild(this.canvas);
    this.ctx = this.canvas.getContext('2d');

    this.resizeCanvas();
    window.addEventListener('resize', () => {
      this.resizeCanvas();
      this.renderCanvas();
    });

    // Mouse Interaction
    this.canvas.addEventListener('mousedown', (e) => {
      this.isDragging = true;
      this.dragStart = { x: e.clientX, y: e.clientY };
      this.canvas.style.cursor = 'grabbing';
    });

    window.addEventListener('mousemove', (e) => {
      if (!this.isDragging) return;
      const dx = e.clientX - this.dragStart.x;
      const dy = e.clientY - this.dragStart.y;
      this.dragStart = { x: e.clientX, y: e.clientY };

      const scale = Math.pow(2, this.zoom) * 256 / 360;
      this.center.lng -= dx / scale;
      this.center.lat += (dy / scale) * Math.cos(this.center.lat * Math.PI / 180);
      this.renderCanvas();
    });

    window.addEventListener('mouseup', () => {
      if (this.isDragging) {
        this.isDragging = false;
        if (this.canvas) this.canvas.style.cursor = 'grab';
      }
    });

    this.canvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      const zoomFactor = e.deltaY < 0 ? 0.2 : -0.2;
      this.zoom = Math.max(10, Math.min(18, this.zoom + zoomFactor));
      this.renderCanvas();
    });

    // Route click detection
    this.canvas.addEventListener('click', (e) => {
      const rect = this.canvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      this.handleCanvasClick(mouseX, mouseY);
    });

    this.renderCanvas();
  }

  resizeCanvas() {
    if (!this.canvas || !this.ctx) return;
    const rect = this.container.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = rect.width * dpr;
    this.canvas.height = rect.height * dpr;
    this.ctx.setTransform(1, 0, 0, 1, 0, 0);
    this.ctx.scale(dpr, dpr);
  }

  latLngToPixel(lat, lng) {
    const width = this.container.clientWidth;
    const height = this.container.clientHeight;
    const scale = Math.pow(2, this.zoom) * 256 / 360;
    const cosLat = Math.cos(this.center.lat * Math.PI / 180);

    const x = width / 2 + (lng - this.center.lng) * scale;
    const y = height / 2 - (lat - this.center.lat) * scale / cosLat;
    return { x, y };
  }

  pixelToLatLng(x, y) {
    const width = this.container.clientWidth;
    const height = this.container.clientHeight;
    const scale = Math.pow(2, this.zoom) * 256 / 360;
    const cosLat = Math.cos(this.center.lat * Math.PI / 180);

    const lng = this.center.lng + (x - width / 2) / scale;
    const lat = this.center.lat - (y - height / 2) * cosLat / scale;
    return { lat, lng };
  }

  setRoutes(routes, selectedRouteId = null) {
    this.routes = routes || [];
    this.selectedRouteId = selectedRouteId || (routes.length ? routes[0].id : null);

    this.updateMapLegendUI();

    if (this.mode === 'google' && this.googleMap && window.google && window.google.maps) {
      try {
        this.renderGoogleRoutes();
        return;
      } catch (err) {
        console.warn("renderGoogleRoutes error, rendering canvas fallback:", err);
      }
    }

    if (!this.canvas) {
      this.initCanvasMap();
    }
    this.fitBoundsToRoutes();
    this.renderCanvas();
  }

  updateMapLegendUI() {
    const legendEl = document.getElementById('mapLegend');
    if (!legendEl) return;

    if (!this.routes || this.routes.length === 0) {
      legendEl.innerHTML = `
        <div class="legend-header">Candidate Paths</div>
        <div class="legend-item"><span class="legend-text" style="color: #94a3b8;">Awaiting live route evaluation...</span></div>
      `;
      return;
    }

    let itemsHtml = '<div class="legend-header">Candidate Paths (Online)</div>';
    this.routes.forEach(r => {
      const isSelected = r.id === this.selectedRouteId;
      itemsHtml += `
        <div class="legend-item ${isSelected ? 'active-legend' : ''}" style="cursor: pointer;" data-route-id="${r.id}">
          <span class="legend-color-bar" style="background: ${r.route_color || '#3b82f6'};"></span>
          <span class="legend-text" style="${isSelected ? 'font-weight: 700; color: #fff;' : ''}">${r.name}</span>
        </div>
      `;
    });
    legendEl.innerHTML = itemsHtml;

    // Allow clicking legend to switch selected route
    legendEl.querySelectorAll('.legend-item').forEach(item => {
      item.addEventListener('click', () => {
        const routeId = item.getAttribute('data-route-id');
        if (routeId && this.onRouteSelected) {
          this.onRouteSelected(routeId);
        }
      });
    });
  }

  setSelectedRoute(routeId) {
    this.selectedRouteId = routeId;
    if (this.mode === 'google') {
      this.highlightGoogleRoute(routeId);
    } else {
      this.renderCanvas();
    }
  }

  clearGoogleOverlays() {
    if (this.googlePolylines) {
      this.googlePolylines.forEach(item => {
        if (item.polyline) item.polyline.setMap(null);
      });
      this.googlePolylines = [];
    }
    if (this.googleMarkers) {
      this.googleMarkers.forEach(marker => {
        if (marker) {
          if (typeof marker.setMap === 'function') {
            marker.setMap(null);
          } else {
            marker.map = null;
          }
        }
      });
      this.googleMarkers = [];
    }
  }

  renderGoogleRoutes() {
    if (!this.googleMap || !window.google || !google.maps) return;
    this.clearGoogleOverlays();

    if (!this.routes || this.routes.length === 0) return;

    const bounds = new google.maps.LatLngBounds();

    this.routes.forEach(route => {
      const isSelected = route.id === this.selectedRouteId;
      const coords = (route.coordinates || []).map(c => ({ lat: c.lat, lng: c.lng }));
      if (coords.length === 0) return;

      coords.forEach(pt => bounds.extend(pt));

      const polyline = new google.maps.Polyline({
        path: coords,
        geodesic: true,
        strokeColor: isSelected ? '#ea580c' : (route.route_color || '#94a3b8'),
        strokeOpacity: isSelected ? 1.0 : 0.5,
        strokeWeight: isSelected ? 6 : 4,
        zIndex: isSelected ? 100 : 10,
        map: this.googleMap,
      });

      polyline.addListener('click', () => {
        this.setSelectedRoute(route.id);
        if (this.onRouteSelected) {
          this.onRouteSelected(route.id);
        }
      });

      this.googlePolylines.push({
        routeId: route.id,
        polyline: polyline,
        color: route.route_color || '#94a3b8',
      });
    });

    // Origin marker (Pin A)
    if (this.origin) {
      const origMarker = this.createMarker({
        position: this.origin,
        title: "Origin",
        label: "A",
        color: "#ea580c",
        scale: 11,
      });
      this.googleMarkers.push(origMarker);
      bounds.extend(this.origin);
    }

    // Destination marker (Pin B)
    if (this.destination) {
      const destMarker = this.createMarker({
        position: this.destination,
        title: "Destination",
        label: "B",
        color: "#0f172a",
        scale: 11,
      });
      this.googleMarkers.push(destMarker);
      bounds.extend(this.destination);
    }

    // Render Real-Time Traffic Jam Hazard Markers
    this.routes.forEach(route => {
      (route.traffic_jams || []).forEach(jam => {
        if (!jam.lat || !jam.lng) return;
        const jamMarker = this.createTrafficJamMarker({
          position: { lat: jam.lat, lng: jam.lng },
          title: `Traffic Jam on ${jam.street_name || route.name}`,
          streetName: jam.street_name || route.name,
          delaySeconds: jam.delay_seconds || route.delay_seconds,
          severity: jam.severity || 'heavy',
        });
        if (jamMarker) {
          this.googleMarkers.push(jamMarker);
        }
      });
    });

    // User location marker if present
    if (this.userLocation) {
      const userMarker = this.createMarker({
        position: this.userLocation,
        title: "Your Location",
        color: "#ea580c",
        scale: 8,
      });
      this.googleMarkers.push(userMarker);
    }

    if (!bounds.isEmpty()) {
      this.googleMap.fitBounds(bounds, { top: 50, right: 50, bottom: 50, left: 50 });
    }
  }

  highlightGoogleRoute(routeId) {
    if (!this.googlePolylines) return;
    this.googlePolylines.forEach(item => {
      const isSelected = item.routeId === routeId;
      item.polyline.setOptions({
        strokeColor: isSelected ? '#ea580c' : (item.color || '#94a3b8'),
        strokeOpacity: isSelected ? 1.0 : 0.5,
        strokeWeight: isSelected ? 6 : 4,
        zIndex: isSelected ? 100 : 10,
      });
    });
  }

  setUserLocation(lat, lng) {
    this.userLocation = { lat, lng };
    this.origin = { lat, lng };
    this.center = { lat, lng };
    if (this.mode === 'google' && this.googleMap) {
      const userMarker = this.createMarker({
        position: { lat, lng },
        title: "Your Location",
        color: "#ea580c",
        scale: 8,
      });
      this.googleMarkers.push(userMarker);
      this.googleMap.setCenter({ lat, lng });
    } else {
      this.renderCanvas();
    }
  }

  fitBoundsToRoutes() {
    if (!this.routes.length) return;
    let minLat = 90, maxLat = -90, minLng = 180, maxLng = -180;
    this.routes.forEach(r => {
      (r.coordinates || []).forEach(pt => {
        if (pt.lat < minLat) minLat = pt.lat;
        if (pt.lat > maxLat) maxLat = pt.lat;
        if (pt.lng < minLng) minLng = pt.lng;
        if (pt.lng > maxLng) maxLng = pt.lng;
      });
    });

    if (minLat <= maxLat) {
      this.center = {
        lat: (minLat + maxLat) / 2,
        lng: (minLng + maxLng) / 2,
      };
    }
  }

  renderCanvas() {
    if (!this.ctx || !this.canvas) return;
    const width = this.container.clientWidth;
    const height = this.container.clientHeight;

    const isDark = document.body.classList.contains('dark-transit-theme');
    // 1. Clean modern geospatial canvas background
    this.ctx.fillStyle = isDark ? '#0b1120' : '#f8fafc';
    this.ctx.fillRect(0, 0, width, height);

    // 2. Subtle geometric grid lines
    this.ctx.strokeStyle = isDark ? 'rgba(255, 255, 255, 0.06)' : '#e2e8f0';
    this.ctx.lineWidth = 1;
    const gridSize = 60;
    for (let x = 0; x < width; x += gridSize) {
      this.ctx.beginPath();
      this.ctx.moveTo(x, 0);
      this.ctx.lineTo(x, height);
      this.ctx.stroke();
    }
    for (let y = 0; y < height; y += gridSize) {
      this.ctx.beginPath();
      this.ctx.moveTo(0, y);
      this.ctx.lineTo(width, y);
      this.ctx.stroke();
    }

    // 3. Draw Candidate Routes
    this.routes.forEach(route => {
      const isSelected = route.id === this.selectedRouteId;
      const coords = route.coordinates || [];
      if (coords.length < 2) return;

      this.ctx.beginPath();
      coords.forEach((pt, i) => {
        const pix = this.latLngToPixel(pt.lat, pt.lng);
        if (i === 0) this.ctx.moveTo(pix.x, pix.y);
        else this.ctx.lineTo(pix.x, pix.y);
      });

      if (isSelected) {
        // Soft orange halo layer
        this.ctx.strokeStyle = '#fed7aa';
        this.ctx.lineWidth = 10;
        this.ctx.lineCap = 'round';
        this.ctx.lineJoin = 'round';
        this.ctx.stroke();

        // Primary transit orange line
        this.ctx.strokeStyle = '#ea580c';
        this.ctx.lineWidth = 5;
        this.ctx.stroke();
      } else {
        // Unselected alternative route line
        this.ctx.strokeStyle = '#94a3b8';
        this.ctx.lineWidth = 4;
        this.ctx.lineCap = 'round';
        this.ctx.lineJoin = 'round';
        this.ctx.globalAlpha = 0.65;
        this.ctx.stroke();
        this.ctx.globalAlpha = 1.0;
      }
    });

    // 4. Draw real traffic jam indicators on map
    this.routes.forEach(route => {
      (route.traffic_jams || []).forEach(jam => {
        if (jam.lat && jam.lng) {
          const pt = this.latLngToPixel(jam.lat, jam.lng);
          const isHeavy = jam.severity === 'heavy';

          // Outer glowing halo
          this.ctx.fillStyle = isHeavy ? 'rgba(220, 38, 38, 0.35)' : 'rgba(217, 119, 6, 0.35)';
          this.ctx.beginPath();
          this.ctx.arc(pt.x, pt.y, 14, 0, Math.PI * 2);
          this.ctx.fill();

          // Core pin
          this.ctx.fillStyle = isHeavy ? '#dc2626' : '#d97706';
          this.ctx.beginPath();
          this.ctx.arc(pt.x, pt.y, 7, 0, Math.PI * 2);
          this.ctx.fill();
          this.ctx.strokeStyle = '#ffffff';
          this.ctx.lineWidth = 2;
          this.ctx.stroke();

          // Label
          this.ctx.fillStyle = isHeavy ? '#dc2626' : '#d97706';
          this.ctx.font = 'bold 10px Outfit, sans-serif';
          this.ctx.textAlign = 'left';
          this.ctx.fillText(`🚨 ${jam.label || 'Traffic Jam'}`, pt.x + 11, pt.y + 4);
        }
      });
    });

    // 5. Draw Origin and Destination Pins
    if (this.origin) {
      const origPix = this.latLngToPixel(this.origin.lat, this.origin.lng);
      this.drawPin(origPix.x, origPix.y, '#ea580c', 'START');
    }
    if (this.destination) {
      const destPix = this.latLngToPixel(this.destination.lat, this.destination.lng);
      this.drawPin(destPix.x, destPix.y, '#0f172a', 'END');
    }

    // 6. Draw User Location if available
    if (this.userLocation) {
      const userPix = this.latLngToPixel(this.userLocation.lat, this.userLocation.lng);
      this.ctx.fillStyle = 'rgba(234, 88, 12, 0.2)';
      this.ctx.beginPath();
      this.ctx.arc(userPix.x, userPix.y, 14, 0, Math.PI * 2);
      this.ctx.fill();

      this.ctx.fillStyle = '#ea580c';
      this.ctx.beginPath();
      this.ctx.arc(userPix.x, userPix.y, 6, 0, Math.PI * 2);
      this.ctx.fill();
    }
  }

  drawPin(x, y, color, label) {
    this.ctx.fillStyle = color;
    this.ctx.beginPath();
    this.ctx.arc(x, y, 9, 0, Math.PI * 2);
    this.ctx.fill();
    this.ctx.strokeStyle = '#ffffff';
    this.ctx.lineWidth = 2.5;
    this.ctx.stroke();

    this.ctx.fillStyle = '#ffffff';
    this.ctx.font = 'bold 9px Outfit, sans-serif';
    this.ctx.textAlign = 'center';
    this.ctx.fillText(label, x, y - 13);
  }

  handleCanvasClick(x, y) {
    // Check if clicked close to any route line
    for (const route of this.routes) {
      const coords = route.coordinates || [];
      for (let i = 0; i < coords.length - 1; i++) {
        const p1 = this.latLngToPixel(coords[i].lat, coords[i].lng);
        const p2 = this.latLngToPixel(coords[i + 1].lat, coords[i + 1].lng);

        const dist = this.distToSegment({ x, y }, p1, p2);
        if (dist < 15) {
          this.setSelectedRoute(route.id);
          if (this.onRouteSelected) {
            this.onRouteSelected(route.id);
          }
          return;
        }
      }
    }
  }

  distToSegment(p, v, w) {
    const l2 = (v.x - w.x) * (v.x - w.x) + (v.y - w.y) * (v.y - w.y);
    if (l2 === 0) return Math.hypot(p.x - v.x, p.y - v.y);
    let t = ((p.x - v.x) * (w.x - v.x) + (p.y - v.y) * (w.y - v.y)) / l2;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(p.x - (v.x + t * (w.x - v.x)), p.y - (v.y + t * (w.y - v.y)));
  }

  zoomIn() {
    this.zoom = Math.min(18, this.zoom + 0.5);
    if (this.mode === 'google' && this.googleMap) {
      this.googleMap.setZoom(this.googleMap.getZoom() + 1);
    } else {
      this.renderCanvas();
    }
  }

  zoomOut() {
    this.zoom = Math.max(10, this.zoom - 0.5);
    if (this.mode === 'google' && this.googleMap) {
      this.googleMap.setZoom(this.googleMap.getZoom() - 1);
    } else {
      this.renderCanvas();
    }
  }

  resetView() {
    this.zoom = 13.5;
    this.fitBoundsToRoutes();
    if (this.mode === 'google' && this.googleMap) {
      this.googleMap.setCenter(this.center);
      this.googleMap.setZoom(13);
    } else {
      this.renderCanvas();
    }
  }
}
