const state = {
  today: startOfDay(new Date()),
  selectedDate: startOfDay(new Date()),
  calendarMonth: new Date(new Date().getFullYear(), new Date().getMonth(), 1),
  todayItems: [],
  calendarItems: [],
  todayMember: "all",
  calendarMember: "all",
  todayMealType: "all",
  ticket: null,
  idToken: null,
  mockMode: false,
};

const memberColors = ["#2f6b4f", "#d7654c", "#4f729c", "#d19a35", "#735a9c", "#40848a"];
const mealLabels = { breakfast: "早餐", lunch: "午餐", dinner: "晚餐", late_night: "宵夜", unknown: "其他" };
const weekdayLabels = ["星期日", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六"];

window.addEventListener("DOMContentLoaded", initialize);

async function initialize() {
  bindEvents();
  renderHeaderDates();
  state.ticket = readTicketFromUrl();
  setLoading(true);

  try {
    const configResponse = await fetch("/api/liff/config");
    const config = configResponse.ok ? await configResponse.json() : {};
    if (config.liff_id && state.ticket && window.liff) {
      await initializeLiff(config.liff_id);
      await loadInitialApiData();
    } else {
      enableMockMode();
    }
  } catch (error) {
    console.error(error);
    enableMockMode();
    showToast("目前顯示預覽資料");
  } finally {
    setLoading(false);
    renderAll();
  }
}

async function initializeLiff(liffId) {
  await window.liff.init({ liffId, withLoginOnExternalBrowser: true });
  if (!window.liff.isLoggedIn()) {
    window.liff.login({ redirectUri: window.location.href });
    return new Promise(() => {});
  }
  state.idToken = window.liff.getIDToken();
  if (!state.idToken) throw new Error("LIFF ID token is unavailable");
}

async function loadInitialApiData() {
  state.mockMode = false;
  document.getElementById("preview-banner").hidden = true;
  const monthRange = getMonthRange(state.calendarMonth);
  const todayKey = formatDateKey(state.today);
  const [todayItems, calendarItems] = await Promise.all([
    fetchAllMeals(todayKey, todayKey),
    fetchAllMeals(monthRange.from, monthRange.to),
  ]);
  state.todayItems = todayItems;
  state.calendarItems = calendarItems;
}

function enableMockMode() {
  state.mockMode = true;
  document.getElementById("preview-banner").hidden = false;
  document.getElementById("group-label").textContent = "週末吃飯團";
  const mockItems = buildMockMeals();
  const todayKey = formatDateKey(state.today);
  const monthRange = getMonthRange(state.calendarMonth);
  state.todayItems = mockItems.filter((item) => item.local_date === todayKey);
  state.calendarItems = mockItems.filter((item) => item.local_date >= monthRange.from && item.local_date <= monthRange.to);
}

async function fetchAllMeals(from, to) {
  const items = [];
  let cursor = null;
  do {
    const params = new URLSearchParams({ ticket: state.ticket, from, to, limit: "100" });
    if (cursor) params.set("cursor", cursor);
    const response = await fetch(`/api/liff/group-meals?${params}`, {
      headers: { Authorization: `Bearer ${state.idToken}` },
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || "無法讀取群組紀錄");
    }
    const payload = await response.json();
    items.push(...(payload.items || []));
    cursor = payload.next_cursor || null;
  } while (cursor);
  return items;
}

function bindEvents() {
  document.querySelectorAll(".tab-button").forEach((button) => {
    button.addEventListener("click", () => switchView(button.dataset.view));
  });
  document.getElementById("today-meal-filter").addEventListener("change", (event) => {
    state.todayMealType = event.target.value;
    renderToday();
  });
  document.getElementById("refresh-button").addEventListener("click", refreshCurrentData);
  document.getElementById("previous-month").addEventListener("click", () => changeMonth(-1));
  document.getElementById("next-month").addEventListener("click", () => changeMonth(1));
}

function switchView(view) {
  document.querySelectorAll(".tab-button").forEach((button) => {
    const active = button.dataset.view === view;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll(".view-panel").forEach((panel) => panel.classList.remove("is-active"));
  document.getElementById(`${view}-view`).classList.add("is-active");
}

async function refreshCurrentData() {
  if (state.mockMode) {
    showToast("預覽資料已更新");
    return;
  }
  setLoading(true);
  try {
    await loadInitialApiData();
    renderAll();
    showToast("紀錄已更新");
  } catch (error) {
    showToast(error.message);
  } finally {
    setLoading(false);
  }
}

async function changeMonth(offset) {
  state.calendarMonth = new Date(state.calendarMonth.getFullYear(), state.calendarMonth.getMonth() + offset, 1);
  state.selectedDate = new Date(state.calendarMonth.getFullYear(), state.calendarMonth.getMonth(), 1);
  state.calendarMember = "all";
  if (state.mockMode) {
    const range = getMonthRange(state.calendarMonth);
    state.calendarItems = buildMockMeals().filter((item) => item.local_date >= range.from && item.local_date <= range.to);
    renderCalendar();
    return;
  }
  setLoading(true);
  try {
    const range = getMonthRange(state.calendarMonth);
    state.calendarItems = await fetchAllMeals(range.from, range.to);
    renderCalendar();
  } catch (error) {
    showToast(error.message);
  } finally {
    setLoading(false);
  }
}

function renderAll() {
  renderHeaderDates();
  renderToday();
  renderCalendar();
}

function renderHeaderDates() {
  document.getElementById("header-month").textContent = `${state.today.getMonth() + 1}月`;
  document.getElementById("header-day").textContent = state.today.getDate();
  document.getElementById("today-date-label").textContent = formatLongDate(state.today);
}

function renderToday() {
  const members = getMembers(state.todayItems);
  if (state.todayMember !== "all" && !members.some((member) => member.key === state.todayMember)) state.todayMember = "all";
  renderMemberFilters("today-member-filters", members, state.todayMember, (key) => {
    state.todayMember = key;
    renderToday();
  });

  const filteredItems = state.todayItems.filter((item) => {
    const memberMatch = state.todayMember === "all" || item.member_key === state.todayMember;
    const mealMatch = state.todayMealType === "all" || item.meal_type === state.todayMealType;
    return memberMatch && mealMatch;
  });
  const uniqueMembers = new Set(state.todayItems.map((item) => item.member_key));
  const calories = state.todayItems.reduce((sum, item) => sum + numericNutrition(item, "calories_kcal"), 0);
  document.getElementById("meal-count").textContent = state.todayItems.length;
  document.getElementById("member-count").textContent = uniqueMembers.size;
  document.getElementById("calorie-total").textContent = Math.round(calories).toLocaleString("zh-TW");
  renderMealList("today-meal-list", filteredItems);
  document.getElementById("today-empty").hidden = filteredItems.length > 0;
}

function renderCalendar() {
  document.getElementById("calendar-title").textContent = `${state.calendarMonth.getFullYear()}年 ${state.calendarMonth.getMonth() + 1}月`;
  const grid = document.getElementById("calendar-grid");
  grid.replaceChildren();
  const first = new Date(state.calendarMonth.getFullYear(), state.calendarMonth.getMonth(), 1);
  const gridStart = new Date(first);
  gridStart.setDate(first.getDate() - first.getDay());

  for (let index = 0; index < 42; index += 1) {
    const date = new Date(gridStart);
    date.setDate(gridStart.getDate() + index);
    const key = formatDateKey(date);
    const dayItems = state.calendarItems.filter((item) => item.local_date === key);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "calendar-day";
    button.classList.toggle("is-outside", date.getMonth() !== state.calendarMonth.getMonth());
    button.classList.toggle("is-today", key === formatDateKey(state.today));
    button.classList.toggle("is-selected", key === formatDateKey(state.selectedDate));
    button.setAttribute("aria-label", `${formatLongDate(date)}，${dayItems.length} 筆紀錄`);
    button.innerHTML = `<span>${date.getDate()}</span><span class="day-dots">${renderDayDots(dayItems)}</span>`;
    button.addEventListener("click", () => {
      state.selectedDate = date;
      state.calendarMember = "all";
      renderCalendar();
    });
    grid.appendChild(button);
  }
  renderSelectedDate();
}

function renderSelectedDate() {
  const selectedKey = formatDateKey(state.selectedDate);
  const selectedItems = state.calendarItems.filter((item) => item.local_date === selectedKey);
  const members = getMembers(state.calendarItems);
  if (state.calendarMember !== "all" && !members.some((member) => member.key === state.calendarMember)) state.calendarMember = "all";
  renderMemberFilters("calendar-member-filters", members, state.calendarMember, (key) => {
    state.calendarMember = key;
    renderSelectedDate();
  });
  const filteredItems = selectedItems.filter((item) => state.calendarMember === "all" || item.member_key === state.calendarMember);
  document.getElementById("selected-weekday").textContent = weekdayLabels[state.selectedDate.getDay()];
  document.getElementById("selected-date-title").textContent = `${state.selectedDate.getMonth() + 1}月${state.selectedDate.getDate()}日`;
  document.getElementById("selected-record-count").textContent = `${filteredItems.length} 筆`;
  renderMealList("calendar-meal-list", filteredItems);
  document.getElementById("calendar-empty").hidden = filteredItems.length > 0;
}

function renderMemberFilters(containerId, members, activeKey, onSelect) {
  const container = document.getElementById(containerId);
  container.replaceChildren();
  [{ key: "all", name: "全部" }, ...members].forEach((member) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "filter-chip";
    button.classList.toggle("is-active", member.key === activeKey);
    button.textContent = member.name;
    button.addEventListener("click", () => onSelect(member.key));
    container.appendChild(button);
  });
}

function renderMealList(containerId, items) {
  const container = document.getElementById(containerId);
  container.replaceChildren();
  [...items]
    .sort((a, b) => `${b.local_date}${b.local_time}`.localeCompare(`${a.local_date}${a.local_time}`))
    .forEach((item) => container.appendChild(createMealCard(item)));
}

function createMealCard(item) {
  const card = document.createElement("article");
  card.className = "meal-card";
  const color = getMemberColor(item.member_key);
  card.style.setProperty("--member-color", color);
  const calories = numericNutrition(item, "calories_kcal");
  const protein = numericNutrition(item, "protein_g");
  const carbs = numericNutrition(item, "carbohydrates_g");
  const fat = numericNutrition(item, "fat_g");
  const nutritionParts = [];
  if (protein) nutritionParts.push(`蛋白質 ${formatNumber(protein)}g`);
  if (carbs) nutritionParts.push(`碳水 ${formatNumber(carbs)}g`);
  if (fat) nutritionParts.push(`脂肪 ${formatNumber(fat)}g`);
  card.innerHTML = `
    <div class="member-avatar" aria-hidden="true">${escapeHTML(getInitials(item.display_name))}</div>
    <div class="meal-body">
      <div class="meal-meta"><strong>${escapeHTML(item.display_name)}</strong><span>${escapeHTML(mealLabels[item.meal_type] || "其他")}</span><span>${escapeHTML(formatTime(item.local_time))}</span></div>
      <p class="meal-name">${escapeHTML(item.description)}</p>
      ${nutritionParts.length ? `<p class="nutrition-line">${escapeHTML(nutritionParts.join(" · "))}</p>` : ""}
    </div>
    <div class="calorie-value">${calories ? `<strong>${Math.round(calories)}</strong><span>kcal</span>` : `<span>未估算</span>`}</div>`;
  return card;
}

function renderDayDots(items) {
  const members = [...new Set(items.map((item) => item.member_key))].slice(0, 3);
  return members.map((key) => `<i class="day-dot" style="--dot-color:${getMemberColor(key)}"></i>`).join("");
}

function getMembers(items) {
  const members = new Map();
  items.forEach((item) => {
    if (!members.has(item.member_key)) members.set(item.member_key, item.display_name);
  });
  return [...members.entries()].map(([key, name]) => ({ key, name }));
}

function getMemberColor(key) {
  let hash = 0;
  for (const character of String(key)) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  return memberColors[hash % memberColors.length];
}

function numericNutrition(item, key) {
  const value = item.nutrition?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function getInitials(name) {
  const cleanName = String(name || "有人").trim();
  return [...cleanName].slice(-2).join("");
}

function formatNumber(value) {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function formatTime(value) {
  return /^\d{2}:\d{2}/.test(value || "") ? value.slice(0, 5) : "";
}

function formatLongDate(date) {
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`;
}

function formatDateKey(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function startOfDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function getMonthRange(date) {
  const from = new Date(date.getFullYear(), date.getMonth(), 1);
  const to = new Date(date.getFullYear(), date.getMonth() + 1, 0);
  return { from: formatDateKey(from), to: formatDateKey(to) };
}

function readTicketFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const directTicket = params.get("ticket");
  if (directTicket) return directTicket;
  const liffState = params.get("liff.state");
  if (!liffState) return null;
  try {
    const decodedState = decodeURIComponent(liffState);
    const query = decodedState.includes("?") ? decodedState.slice(decodedState.indexOf("?") + 1) : decodedState.replace(/^\?/, "");
    return new URLSearchParams(query).get("ticket");
  } catch {
    return null;
  }
}

function setLoading(visible) {
  document.getElementById("loading-overlay").hidden = !visible;
}

let toastTimer;
function showToast(message) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.hidden = true; }, 2600);
}

function escapeHTML(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function buildMockMeals() {
  const date = (offset) => {
    const value = new Date(state.today);
    value.setDate(value.getDate() + offset);
    return formatDateKey(value);
  };
  return [
    mockMeal("r1", "m1", "小安", "lunch", "烤雞腿藜麥沙拉", 612, 42, 58, 22, date(0), "12:18:00"),
    mockMeal("r2", "m2", "Wayne", "breakfast", "鮪魚蛋吐司與無糖豆漿", 438, 29, 47, 15, date(0), "08:26:00"),
    mockMeal("r3", "m3", "怡君", "lunch", "番茄牛肉麵", 720, 36, 86, 25, date(0), "13:02:00"),
    mockMeal("r4", "m1", "小安", "dinner", "鮭魚時蔬便當", 680, 40, 70, 24, date(0), "19:10:00"),
    mockMeal("r5", "m4", "阿哲", "late_night", "香蕉優格與堅果", 310, 12, 38, 14, date(-1), "22:34:00"),
    mockMeal("r6", "m2", "Wayne", "lunch", "日式咖哩雞飯", 790, 31, 104, 27, date(-1), "12:42:00"),
    mockMeal("r7", "m3", "怡君", "dinner", "蒸鱈魚、地瓜與青花菜", 540, 43, 52, 17, date(-3), "18:48:00"),
    mockMeal("r8", "m1", "小安", "breakfast", "酪梨雞蛋貝果", 510, 23, 55, 23, date(-3), "08:05:00"),
    mockMeal("r9", "m4", "阿哲", "lunch", "麻醬雞絲涼麵", 650, 28, 82, 23, date(-6), "12:21:00"),
    mockMeal("r10", "m2", "Wayne", "dinner", "韓式豆腐鍋與白飯", 705, 35, 78, 27, date(-8), "19:32:00"),
    mockMeal("r11", "m3", "怡君", "breakfast", "燕麥水果優格碗", 390, 15, 62, 10, date(-12), "07:54:00"),
  ];
}

function mockMeal(recordKey, memberKey, displayName, mealType, description, calories, protein, carbs, fat, localDate, localTime) {
  return {
    record_key: recordKey,
    member_key: memberKey,
    display_name: displayName,
    meal_type: mealType,
    description,
    nutrition: { calories_kcal: calories, protein_g: protein, carbohydrates_g: carbs, fat_g: fat },
    local_date: localDate,
    local_time: localTime,
    timezone: "Asia/Taipei",
  };
}
