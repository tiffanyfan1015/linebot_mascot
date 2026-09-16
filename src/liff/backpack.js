(() => {
  let period = "month", map, markers, latestLocations = [], latestSightings = [];
  window.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-backpack-period]").forEach((button) => button.addEventListener("click", () => loadDashboard(button.dataset.backpackPeriod)));
    document.querySelector('[data-view="backpack"]').addEventListener("click", () => setTimeout(() => renderMap(latestLocations), 50));
    document.getElementById("location-search-form").addEventListener("submit", searchLocations);
    document.getElementById("member-sightings-close").addEventListener("click", hideMemberSightings);
    waitForLiff();
  });
  function waitForLiff() { if (state.ticket && state.idToken) { new URLSearchParams(location.search).get("mode") === "backpack-location" ? openLocationPicker() : loadDashboard(period); return; } if (!state.mockMode) setTimeout(waitForLiff, 200); }
  async function api(path, options = {}) { const response = await fetch(`${path}${path.includes("?") ? "&" : "?"}ticket=${encodeURIComponent(state.ticket)}`, { ...options, headers: { Authorization: `Bearer ${state.idToken}`, "Content-Type": "application/json", ...(options.headers || {}) } }); const payload = await response.json().catch(() => ({})); if (!response.ok) throw new Error(payload.detail || "讀取藝寶包資料失敗"); return payload; }
  async function loadDashboard(nextPeriod) { if (state.mockMode) return; period = nextPeriod; try { const data = await api(`/api/liff/group-backpacks?period=${period}`); latestLocations = data.locations || []; document.querySelectorAll("[data-backpack-period]").forEach((button) => button.classList.toggle("is-active", button.dataset.backpackPeriod === period)); document.getElementById("backpack-total").textContent = data.total_sightings || 0; renderLeaderboard(data.leaderboard || []); renderMap(latestLocations); } catch (error) { showToast(error.message); } }
  function renderLeaderboard(items) { const list = document.getElementById("backpack-leaderboard"); list.replaceChildren(); if (!items.length) { list.innerHTML = "<li class='empty-row'>還沒有藝寶包發現紀錄。</li>"; return; } items.forEach((item, index) => { const row = document.createElement("li"); row.innerHTML = `<span class="rank">${index + 1}</span><strong></strong><span>${item.count} 次</span>`; row.querySelector("strong").textContent = item.display_name; list.appendChild(row); }); }
  function renderMap(locations) { if (!window.L || !document.getElementById("backpack-view").classList.contains("is-active")) return; const container = document.getElementById("backpack-map"); if (!map) { map = L.map(container, { zoomControl: false }).setView([23.7, 121], 7); L.control.zoom({ position: "bottomright" }).addTo(map); L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap contributors" }).addTo(map); markers = L.featureGroup().addTo(map); } markers.clearLayers(); locations.forEach((item) => { const marker = L.marker([item.latitude, item.longitude]); marker.bindPopup(`<strong>${escapeHtml(item.finder_display_name)}</strong><br>${escapeHtml(item.local_date || "")} ${escapeHtml(item.local_time || "")}<br>${escapeHtml(item.location_title || item.location_address || "")}`); markers.addLayer(marker); }); map.invalidateSize(true); if (locations.length) map.fitBounds(markers.getBounds().pad(0.2), { maxZoom: 15 }); else map.setView([23.7, 121], 7); }
  function openLocationPicker() { document.querySelectorAll(".view-tabs, #today-view, #calendar-view, .period-tabs, .backpack-stats, .backpack-leaderboard, .map-section").forEach((element) => { element.hidden = true; }); document.getElementById("backpack-view").classList.add("is-active"); document.getElementById("location-picker").hidden = false; document.querySelector(".backpack-hero").classList.add("is-picker"); document.querySelector(".backpack-hero img").hidden = true; document.getElementById("app-title").textContent = "補上發現地點"; document.getElementById("backpack-title").textContent = "選擇藝寶包發現地點"; }
  async function searchLocations(event) { event.preventDefault(); const query = document.getElementById("location-search-input").value.trim(); if (!query) return; try { const data = await api(`/api/liff/backpack-location/search?q=${encodeURIComponent(query)}`); const container = document.getElementById("location-search-results"); container.replaceChildren(); if (!data.items.length) { container.textContent = "找不到符合的地點，請換一個更完整的名稱。"; return; } data.items.forEach((item) => { const button = document.createElement("button"); button.type = "button"; button.className = "location-result"; button.textContent = item.label; button.addEventListener("click", () => saveLocation(item)); container.appendChild(button); }); } catch (error) { showToast(error.message); } }
  async function saveLocation(item) { try { await api("/api/liff/backpack-location", { method: "PUT", body: JSON.stringify(item) }); showToast("已記錄發現地點"); setTimeout(() => window.liff?.closeWindow(), 600); } catch (error) { showToast(error.message); } }
  function escapeHtml(value) { const node = document.createElement("span"); node.textContent = String(value || ""); return node.innerHTML; }
  async function loadDashboard(nextPeriod) {
    if (state.mockMode) return;
    period = nextPeriod;
    hideMemberSightings();
    try {
      const data = await api(`/api/liff/group-backpacks?period=${period}`);
      latestLocations = data.locations || [];
      latestSightings = data.sightings || [];
      document.querySelectorAll("[data-backpack-period]").forEach((button) => button.classList.toggle("is-active", button.dataset.backpackPeriod === period));
      document.getElementById("backpack-total").textContent = data.total_sightings || 0;
      renderLeaderboard(data.leaderboard || []);
      renderMap(latestLocations);
    } catch (error) { showToast(error.message); }
  }
  function renderLeaderboard(items) {
    const list = document.getElementById("backpack-leaderboard");
    list.replaceChildren();
    if (!items.length) { list.innerHTML = "<li class='empty-row'>還沒有藝寶包發現紀錄。</li>"; return; }
    items.forEach((item, index) => {
      const row = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "leaderboard-member";
      const rank = document.createElement("span"); rank.className = "rank"; rank.textContent = String(index + 1);
      const name = document.createElement("strong"); name.textContent = item.display_name;
      const count = document.createElement("span"); count.textContent = `${item.count} 次`;
      button.append(rank, name, count);
      button.addEventListener("click", () => showMemberSightings(item.user_id, item.display_name));
      row.appendChild(button);
      list.appendChild(row);
    });
  }
  function showMemberSightings(userId, displayName) {
    const section = document.getElementById("member-sightings");
    const items = latestSightings.filter((item) => item.finder_user_id === userId);
    document.getElementById("member-sightings-kicker").textContent = `總共有 ${items.length} 次`;
    document.getElementById("member-sightings-title").textContent = `${displayName} 的發現紀錄`;
    const list = document.getElementById("member-sighting-list");
    list.replaceChildren();
    items.forEach((item) => {
      const record = document.createElement("article"); record.className = "member-sighting-item";
      const time = document.createElement("time"); time.textContent = [item.local_date, item.local_time].filter(Boolean).join(" ") || "時間未記錄";
      const location = document.createElement("p"); location.textContent = `📍 ${item.location_label || "未填寫地點"}`;
      record.append(time, location); list.appendChild(record);
    });
    section.hidden = false;
    section.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  function hideMemberSightings() {
    const section = document.getElementById("member-sightings");
    if (section) section.hidden = true;
  }
})();
