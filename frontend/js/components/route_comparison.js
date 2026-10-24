/**
 * Route Comparison Component
 * Displays alternative candidate routes with suitability badges and trade-offs.
 */

const RouteComparisonComponent = {
  renderCandidateList(candidates, selectedRouteId, onSelectCallback) {
    const container = document.getElementById('candidateRoutesContainer');
    const countTag = document.getElementById('candidateCountTag');

    if (!candidates || candidates.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <p>No alternative routes available. Click <strong>Evaluate Routes</strong>.</p>
        </div>`;
      if (countTag) countTag.textContent = "0 routes";
      return;
    }

    if (countTag) countTag.textContent = `${candidates.length} alternatives`;
    container.innerHTML = '';

    candidates.forEach((route) => {
      const isSelected = route.id === selectedRouteId;
      const durationMins = (route.traffic_duration_seconds / 60).toFixed(1);
      const distKm = (route.distance_meters / 1000).toFixed(1);
      const score = Math.round(route.suitability_score || 50);

      let badgeClass = 'medium';
      if (score >= 75) badgeClass = 'high';
      else if (score < 55) badgeClass = 'low';

      // Check for real traffic jams or severe bottleneck choke points
      let trafficAlertHtml = '';
      if (route.traffic_jams && route.traffic_jams.length > 0) {
        const jam = route.traffic_jams[0];
        const delayMin = Math.max(1, Math.round((route.delay_seconds || 60) / 60));
        trafficAlertHtml = `
          <div class="route-card-choke alert-danger">
            <span class="traffic-jam-dot"></span>
            <span>🚨 <strong>Traffic Jam:</strong> ${jam.street_name || route.name} (+${delayMin}m delay)</span>
          </div>`;
      } else if (route.delay_seconds && route.delay_seconds > 120) {
        const delayMin = Math.round(route.delay_seconds / 60);
        trafficAlertHtml = `
          <div class="route-card-choke alert-warning">
            <span>⚠️ <strong>Slowdown:</strong> Moderate traffic delays (+${delayMin}m)</span>
          </div>`;
      } else {
        trafficAlertHtml = `
          <div class="route-card-traffic-clear">
            <span class="traffic-clear-dot"></span>
            <span>✓ Smooth Flow (${route.traffic_condition || 'Normal'})</span>
          </div>`;
      }

      const card = document.createElement('div');
      card.className = `route-card ${isSelected ? 'selected' : ''}`;
      card.style.setProperty('--route-color', route.route_color || '#38bdf8');

      card.innerHTML = `
        <div class="route-card-header">
          <span class="route-card-title">${route.name}</span>
          <span class="suitability-badge ${badgeClass}" title="Road Suitability Score (0-100)">
            ${score}/100
          </span>
        </div>
        <div class="route-card-stats">
          <div class="route-stat-item">Time: <strong>${durationMins}m</strong></div>
          <div class="route-stat-item">Dist: <strong>${distKm} km</strong></div>
          <div class="route-stat-item">Conf: <strong>${Math.round((route.confidence || 0.8) * 100)}%</strong></div>
        </div>
        ${trafficAlertHtml}
      `;

      card.addEventListener('click', () => {
        if (onSelectCallback) onSelectCallback(route.id);
      });

      container.appendChild(card);
    });
  },

  updateSelectedDecisionCard(decision) {
    const card = document.getElementById('selectedRouteCard');
    if (!decision || !decision.selected_route) {
      card.style.display = 'none';
      return;
    }

    card.style.display = 'block';
    const route = decision.selected_route;
    const durationMins = (route.traffic_duration_seconds / 60).toFixed(1);
    const distKm = (route.distance_meters / 1000).toFixed(1);
    const freeFlowMins = (route.free_flow_duration_seconds / 60).toFixed(1);

    document.getElementById('selectedRouteName').textContent = route.name;
    document.getElementById('selectedRouteTime').textContent = `~${durationMins} mins`;
    document.getElementById('selectedRouteSummary').textContent = route.summary;

    const score = Math.round(route.suitability_score || 50);
    const scoreEl = document.getElementById('selectedSuitabilityScore');
    scoreEl.textContent = `${score}/100`;

    document.getElementById('selectedSuitabilityConf').textContent = `Confidence: ${Math.round((route.confidence || 0.8) * 100)}%`;
    document.getElementById('selectedDistanceVal').textContent = `${distKm} km`;
    document.getElementById('selectedFreeFlowVal').textContent = `Free-flow: ${freeFlowMins}m`;

    // Find breakdown metrics
    const breakdown = (decision.candidate_breakdowns || []).find(b => b.route_id === route.id);
    const maxVC = breakdown ? breakdown.volume_to_capacity_ratio_max : 0.4;
    document.getElementById('selectedChokeRisk').textContent = maxVC > 0.85 ? "High" : (maxVC > 0.65 ? "Moderate" : "Low");
    document.getElementById('selectedVCRatio').textContent = `Max V/C: ${maxVC.toFixed(2)}`;

    document.getElementById('selectedRationaleText').textContent = decision.recommendation_rationale;

    // Update HUD
    const hudRoute = document.getElementById('hudRouteLabel');
    if (hudRoute) hudRoute.textContent = route.name;
    const hudScore = document.getElementById('hudScoreLabel');
    if (hudScore) {
      hudScore.textContent = `${score}/100`;
      hudScore.className = `hud-val ${score >= 75 ? 'score-high' : (score >= 45 ? 'score-med' : 'score-low')}`;
    }
  },
};
