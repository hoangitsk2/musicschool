const STORAGE_KEY = "raspberry-break-dj.apiBase";
const DAY_OPTIONS = [
  { value: "0", label: "Mon" },
  { value: "1", label: "Tue" },
  { value: "2", label: "Wed" },
  { value: "3", label: "Thu" },
  { value: "4", label: "Fri" },
  { value: "5", label: "Sat" },
  { value: "6", label: "Sun" },
];
const DEFAULT_DAYS = new Set(["0", "1", "2", "3", "4"]);

const state = {
  apiBase: "",
  playlists: [],
  tracks: new Map(),
  status: null,
  statusTimer: null,
};

const elements = {
  apiBaseInput: document.getElementById("api-base"),
  currentApiBase: document.getElementById("current-api-base"),
  connectionForm: document.getElementById("connection-form"),
  playlistSelect: document.getElementById("playlist-select"),
  breakPlaylistSelect: document.getElementById("break-playlist"),
  breakDays: document.getElementById("break-days"),
  breakForm: document.getElementById("break-form"),
  breakTimes: document.getElementById("break-times"),
  breakName: document.getElementById("break-name"),
  breakDuration: document.getElementById("break-duration"),
  breakReplace: document.getElementById("break-replace"),
  playMinutes: document.getElementById("play-minutes"),
  volumeSlider: document.getElementById("volume-slider"),
  volumeOutput: document.getElementById("volume-output"),
  scheduleList: document.getElementById("schedule-list"),
  messageLog: document.getElementById("message-log"),
  statusPower: document.getElementById("status-power"),
  statusPlayback: document.getElementById("status-playback"),
  statusTrack: document.getElementById("status-track"),
  statusVolume: document.getElementById("status-volume"),
  statusUpdated: document.getElementById("status-updated"),
};

function initDayCheckboxes() {
  elements.breakDays.innerHTML = "";
  DAY_OPTIONS.forEach((day) => {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = day.value;
    input.checked = DEFAULT_DAYS.has(day.value);
    label.append(input, document.createTextNode(day.label));
    elements.breakDays.append(label);
  });
}

function logMessage(type, text) {
  const message = document.createElement("li");
  message.classList.add(type);
  const content = document.createElement("span");
  content.textContent = text;
  const time = document.createElement("time");
  const now = new Date();
  time.dateTime = now.toISOString();
  time.textContent = now.toLocaleTimeString();
  message.append(content, time);
  elements.messageLog.prepend(message);
  const limit = 12;
  while (elements.messageLog.children.length > limit) {
    elements.messageLog.removeChild(elements.messageLog.lastElementChild);
  }
}

function setApiBase(value, { silent = false } = {}) {
  const sanitized = value ? value.replace(/\/+$/, "") : "";
  state.apiBase = sanitized;
  localStorage.setItem(STORAGE_KEY, sanitized);
  elements.currentApiBase.textContent = sanitized || "not configured";
  elements.apiBaseInput.value = sanitized;
  if (!silent) {
    logMessage("success", `API base saved: ${sanitized || "not configured"}`);
  }
  restartStatusTimer();
}

function ensureApiBase() {
  if (!state.apiBase) {
    throw new Error("Configure the API base URL first.");
  }
}

function buildUrl(path) {
  ensureApiBase();
  const base = state.apiBase.endsWith("/") ? state.apiBase : `${state.apiBase}/`;
  return new URL(path.replace(/^\//, ""), base).toString();
}

async function fetchJson(path, options = {}) {
  try {
    const url = buildUrl(path);
    const fetchOptions = { method: options.method || "GET", headers: options.headers || {}, mode: "cors" };
    if (options.body !== undefined) {
      if (options.body instanceof FormData) {
        fetchOptions.body = options.body;
      } else {
        fetchOptions.headers = { ...fetchOptions.headers, "Content-Type": "application/json" };
        fetchOptions.body = JSON.stringify(options.body);
      }
    }
    const response = await fetch(url, fetchOptions);
    const text = await response.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (err) {
        throw new Error(`Không đọc được phản hồi JSON: ${err.message}`);
      }
    }
    if (!response.ok) {
      const message = data && data.error ? data.error : response.statusText;
      throw new Error(message || "Yêu cầu thất bại");
    }
    return data;
  } catch (error) {
    logMessage("error", error.message);
    throw error;
  }
}

function restartStatusTimer() {
  if (state.statusTimer) {
    clearInterval(state.statusTimer);
  }
  if (!state.apiBase) {
    return;
  }
  state.statusTimer = setInterval(() => {
    refreshStatus().catch(() => {});
  }, 20000);
}

function updateStatusUi(status) {
  elements.statusPower.textContent = status.power_on ? "On" : "Off";
  let playbackText = status.status || "Idle";
  if (status.session_end_at) {
    const end = new Date(status.session_end_at);
    playbackText = `${playbackText} until ${end.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
  }
  elements.statusPlayback.textContent = playbackText;
  const trackName = status.current_track_id
    ? state.tracks.get(status.current_track_id) || `Track #${status.current_track_id}`
    : "—";
  const playlistName = status.playlist_id
    ? state.playlists.find((p) => p.id === status.playlist_id)?.name || `Playlist #${status.playlist_id}`
    : null;
  elements.statusTrack.textContent = playlistName ? `${playlistName} · ${trackName}` : trackName;
  elements.statusVolume.textContent = `${status.volume}%`;
  if (typeof status.volume === "number") {
    elements.volumeSlider.value = String(status.volume);
    elements.volumeOutput.textContent = String(status.volume);
  }
  const heartbeat = status.heartbeat_at ? new Date(status.heartbeat_at) : new Date();
  elements.statusUpdated.textContent = heartbeat.toLocaleTimeString();
  state.status = status;
}

function renderPlaylists(playlists) {
  const makeOptions = (select) => {
    const previous = select.value;
    select.innerHTML = "";
    if (!playlists.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "No playlists found";
      option.disabled = true;
      option.selected = true;
      select.append(option);
      return;
    }
    playlists.forEach((playlist, index) => {
      const option = document.createElement("option");
      option.value = String(playlist.id);
      option.textContent = playlist.name;
      if (previous && previous === option.value) {
        option.selected = true;
      } else if (!previous && index === 0) {
        option.selected = true;
      }
      select.append(option);
    });
  };
  makeOptions(elements.playlistSelect);
  makeOptions(elements.breakPlaylistSelect);
}

function renderSchedules(schedules) {
  if (!schedules.length) {
    elements.scheduleList.innerHTML = '<p class="muted">No schedules yet.</p>';
    return;
  }
  elements.scheduleList.innerHTML = "";
  schedules.forEach((schedule) => {
    const container = document.createElement("div");
    container.className = "schedule-item";

    const header = document.createElement("header");
    const title = document.createElement("h3");
    title.textContent = schedule.name;
    const toggle = document.createElement("button");
    toggle.textContent = schedule.enabled ? "Disable" : "Enable";
    toggle.className = schedule.enabled ? "danger" : "accent";
    toggle.dataset.scheduleId = String(schedule.id);
    toggle.dataset.enabled = schedule.enabled ? "1" : "0";
    header.append(title, toggle);

    const details = document.createElement("div");
    const days = formatDays(schedule.days);
    const playlistName = state.playlists.find((p) => p.id === schedule.playlist_id)?.name ||
      (schedule.playlist_id ? `Playlist #${schedule.playlist_id}` : "Any");
    details.innerHTML = `
      <p><strong>Playlist:</strong> ${playlistName}</p>
      <p><strong>Days:</strong> ${days}</p>
      <p><strong>Start:</strong> ${schedule.start_time} &middot; <strong>Duration:</strong> ${schedule.session_minutes} min</p>
      <p><strong>Status:</strong> ${schedule.enabled ? "Enabled" : "Disabled"}</p>
    `;

    container.append(header, details);
    elements.scheduleList.append(container);
  });
}

function formatDays(daysCsv) {
  if (!daysCsv) {
    return "Every day";
  }
  const values = daysCsv.split(",").map((value) => value.trim()).filter(Boolean);
  if (!values.length) {
    return "Every day";
  }
  const labels = values.map((value) => DAY_OPTIONS.find((day) => day.value === value)?.label || value);
  return labels.join(", ");
}

async function refreshPlaylists() {
  const playlists = await fetchJson("/api/playlists");
  state.playlists = playlists || [];
  renderPlaylists(state.playlists);
}

async function refreshTracks() {
  const tracks = await fetchJson("/api/tracks");
  state.tracks = new Map();
  tracks.forEach((track) => {
    state.tracks.set(track.id, track.name);
  });
  if (state.status) {
    updateStatusUi(state.status);
  }
}

async function refreshSchedules() {
  const schedules = await fetchJson("/api/schedules");
  renderSchedules(schedules || []);
}

async function refreshStatus() {
  const status = await fetchJson("/api/status");
  updateStatusUi(status);
}

async function refreshAll() {
  if (!state.apiBase) {
    return;
  }
  await refreshPlaylists();
  await refreshTracks();
  await Promise.all([refreshStatus(), refreshSchedules()]);
}

function collectSelectedDays() {
  const days = [];
  elements.breakDays.querySelectorAll("input[type='checkbox']").forEach((input) => {
    if (input.checked) {
      days.push(input.value);
    }
  });
  return days;
}

async function handleControlAction(event) {
  const button = event.target.closest("button[data-action]");
  if (!button) {
    return;
  }
  const action = button.dataset.action;
  try {
    switch (action) {
      case "refresh":
        await refreshAll();
        logMessage("success", "Status refreshed");
        break;
      case "power": {
        ensureApiBase();
        const desired = !(state.status && state.status.power_on);
        await fetchJson("/api/power", { method: "POST", body: { on: desired } });
        logMessage("success", `Power ${desired ? "on" : "off"} command sent`);
        await refreshStatus();
        break;
      }
      case "play": {
        const playlistId = elements.playlistSelect.value;
        if (!playlistId) {
          throw new Error("Chọn playlist trước khi phát");
        }
        const minutes = parseInt(elements.playMinutes.value, 10) || 15;
        await fetchJson("/api/play", {
          method: "POST",
          body: { playlist_id: Number(playlistId), minutes },
        });
        logMessage("success", "Playback queued");
        await refreshStatus();
        break;
      }
      case "stop":
        await fetchJson("/api/stop", { method: "POST" });
        logMessage("success", "Stop command sent");
        await refreshStatus();
        break;
      case "skip":
        await fetchJson("/api/skip", { method: "POST" });
        logMessage("success", "Skip command sent");
        await refreshStatus();
        break;
      default:
        break;
    }
  } catch (error) {
    // errors already logged in fetchJson
  }
}

async function handleVolumeChange(event) {
  const value = Number(event.target.value);
  elements.volumeOutput.textContent = String(value);
  try {
    await fetchJson("/api/volume", { method: "POST", body: { volume: value } });
    logMessage("success", `Volume set to ${value}`);
    await refreshStatus();
  } catch (error) {
    // error logged
  }
}

async function handleBreakForm(event) {
  event.preventDefault();
  try {
    const playlistId = elements.breakPlaylistSelect.value;
    if (!playlistId) {
      throw new Error("Chọn playlist cho kế hoạch giờ ra chơi");
    }
    const minutes = parseInt(elements.breakDuration.value, 10) || 15;
    const days = collectSelectedDays();
    const times = elements.breakTimes.value
      .split(/\s+/)
      .map((entry) => entry.trim())
      .filter(Boolean);
    if (!times.length) {
      throw new Error("Nhập ít nhất một thời gian bắt đầu (HH:MM)");
    }
    const replace = elements.breakReplace.value === "yes";
    const body = {
      playlist_id: Number(playlistId),
      session_minutes: minutes,
      days,
      start_times: times,
      name_prefix: elements.breakName.value || undefined,
      replace,
    };
    const result = await fetchJson("/api/schedules/break-plan", { method: "POST", body });
    logMessage(
      "success",
      `Break plan saved (${result.created.length} created, ${result.updated.length} updated)`
    );
    elements.breakForm.reset();
    initDayCheckboxes();
    await refreshSchedules();
  } catch (error) {
    // fetchJson already logs errors
  }
}

function handleScheduleToggle(event) {
  const button = event.target.closest("button[data-schedule-id]");
  if (!button) {
    return;
  }
  const scheduleId = Number(button.dataset.scheduleId);
  const enabled = button.dataset.enabled === "1";
  fetchJson(`/api/schedules/${scheduleId}/toggle`, {
    method: "POST",
    body: { enabled: !enabled },
  })
    .then((result) => {
      logMessage("success", `Schedule ${result.enabled ? "enabled" : "disabled"}`);
      return refreshSchedules();
    })
    .catch(() => {});
}

function loadStoredApiBase() {
  const stored = localStorage.getItem(STORAGE_KEY) || "";
  if (stored) {
    setApiBase(stored, { silent: true });
  }
}

function setupEventListeners() {
  document.body.addEventListener("click", handleControlAction);
  elements.volumeSlider.addEventListener("input", (event) => {
    elements.volumeOutput.textContent = event.target.value;
  });
  elements.volumeSlider.addEventListener("change", handleVolumeChange);
  elements.breakForm.addEventListener("submit", handleBreakForm);
  elements.scheduleList.addEventListener("click", handleScheduleToggle);
  elements.connectionForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const value = elements.apiBaseInput.value.trim();
    if (!value) {
      logMessage("error", "Nhập URL API hợp lệ");
      return;
    }
    setApiBase(value);
    refreshAll();
  });
}

function init() {
  initDayCheckboxes();
  loadStoredApiBase();
  setupEventListeners();
  if (state.apiBase) {
    refreshAll();
  }
}

init();
