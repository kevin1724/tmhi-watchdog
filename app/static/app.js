const state = {
  config: null,
  status: null,
  gatewayLoginBusy: false,
  settingsBusy: false,
  seriesRunning: false,
  seriesAbort: false,
};

const TUTORIAL_STORAGE_KEY = "tmhi-watchdog-tutorial-seen";

const phaseGroups = {
  good: new Set(["online"]),
  warn: new Set([
    "startup_grace",
    "confirming_outage",
    "outage_confirmed",
    "post_reboot_grace",
    "reboot_cooldown",
    "dry_run_reboot",
    "disabled",
  ]),
  bad: new Set([
    "gateway_unreachable",
    "reboot_limit_reached",
    "reboot_failed",
    "error",
  ]),
};

const configLabels = {
  gateway_host: "Gateway host",
  gateway_port: "Gateway port",
  gateway_username: "Gateway user",
  gateway_password_configured: "Gateway password",
  gateway_password_source: "Gateway login source",
  gateway_login_saved: "Gateway login saved",
  watchdog_enabled: "Watchdog",
  dry_run: "Dry run",
  check_interval_seconds: "Check interval",
  tests_per_hour: "Tests per hour",
  failure_threshold_seconds: "Failure threshold",
  startup_grace_seconds: "Startup grace",
  post_reboot_grace_seconds: "Post-reboot grace",
  reboot_cooldown_seconds: "Reboot cooldown",
  max_reboots_per_24h: "24h reboot limit",
  probe_urls: "Probe URLs",
  minimum_successful_probes: "Required probes",
  database_path: "Database",
  managed_env_path: "Settings file",
};

const els = {};

document.addEventListener("DOMContentLoaded", () => {
  bindElements();
  bindEvents();
  updateControlState();
  loadInitialData().finally(maybeShowTutorial);
  window.setInterval(refreshStatusAndEvents, 10000);
});

function bindElements() {
  [
    "tutorialButton",
    "tutorialModal",
    "tutorialCloseButton",
    "tutorialDoneButton",
    "phasePill",
    "updatedAt",
    "refreshButton",
    "internetValue",
    "probeValue",
    "gatewayValue",
    "dryRunValue",
    "lastCheckValue",
    "rebootValue",
    "lastError",
    "settingsState",
    "dryRunToggle",
    "dryRunHint",
    "testsPerHour",
    "saveSettingsButton",
    "gatewayLoginState",
    "gatewayPasswordRow",
    "gatewayPassword",
    "saveGatewayLogin",
    "saveGatewayLoginButton",
    "clearGatewayLoginButton",
    "checkButton",
    "gatewayButton",
    "forceReboot",
    "rebootButton",
    "actionMessage",
    "seriesForm",
    "seriesCount",
    "seriesInterval",
    "seriesStartButton",
    "seriesStopButton",
    "seriesState",
    "seriesProgress",
    "seriesProgressText",
    "seriesResults",
    "probeResults",
    "configList",
    "eventsButton",
    "eventRows",
  ].forEach((id) => {
    els[id] = document.getElementById(id);
  });
}

function bindEvents() {
  els.tutorialButton.addEventListener("click", openTutorial);
  els.tutorialCloseButton.addEventListener("click", closeTutorial);
  els.tutorialDoneButton.addEventListener("click", closeTutorial);
  els.tutorialModal.addEventListener("click", (event) => {
    if (event.target === els.tutorialModal) {
      closeTutorial();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !els.tutorialModal.classList.contains("modal--hidden")) {
      closeTutorial();
    }
  });
  els.refreshButton.addEventListener("click", refreshStatusAndEvents);
  els.eventsButton.addEventListener("click", refreshEvents);
  els.saveSettingsButton.addEventListener("click", saveSettings);
  els.dryRunToggle.addEventListener("change", updateDryRunHint);
  els.gatewayPassword.addEventListener("input", updateControlState);
  els.saveGatewayLoginButton.addEventListener("click", saveGatewayLogin);
  els.clearGatewayLoginButton.addEventListener("click", clearGatewayLogin);
  els.checkButton.addEventListener("click", runSingleCheck);
  els.gatewayButton.addEventListener("click", runGatewayTest);
  els.rebootButton.addEventListener("click", requestReboot);
  els.seriesForm.addEventListener("submit", runSeries);
  els.seriesStopButton.addEventListener("click", stopSeries);
}

async function loadInitialData() {
  await Promise.allSettled([loadConfig(), refreshStatusAndEvents()]);
}

async function api(path, options = {}) {
  const headers = { Accept: "application/json" };
  let body;

  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }

  const response = await fetch(path, {
    method: options.method || (body ? "POST" : "GET"),
    headers,
    body,
  });

  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    throw new Error(readError(payload, response.status));
  }

  return payload;
}

function readError(payload, status) {
  if (payload && typeof payload === "object") {
    if (Array.isArray(payload.detail)) {
      return payload.detail.map((item) => item.msg || String(item)).join(", ");
    }
    if (payload.detail) {
      return String(payload.detail);
    }
    if (payload.message) {
      return String(payload.message);
    }
  }
  if (typeof payload === "string" && payload.trim()) {
    return payload.trim();
  }
  return `Request failed with HTTP ${status}`;
}

async function loadConfig() {
  try {
    state.config = await api("/api/config");
    renderConfig(state.config);
    renderSettingsControls(state.config);
    updateControlState();
  } catch (error) {
    setActionMessage(error.message, "error");
  }
}

async function refreshStatusAndEvents() {
  await Promise.allSettled([refreshStatus(), refreshEvents()]);
}

async function refreshStatus() {
  try {
    const status = await api("/api/status");
    state.status = status;
    renderStatus(status);
  } catch (error) {
    setActionMessage(error.message, "error");
  }
}

async function refreshEvents() {
  try {
    const events = await api("/api/events?limit=10");
    renderEvents(events);
  } catch (error) {
    setActionMessage(error.message, "error");
  }
}

async function saveSettings() {
  let testsPerHour;
  try {
    testsPerHour = readTestsPerHour();
  } catch (error) {
    setActionMessage(error.message, "error");
    els.testsPerHour.focus();
    return;
  }

  const dryRun = els.dryRunToggle.checked;
  const turningLive = state.config && state.config.dry_run && !dryRun;
  if (turningLive && !state.config.gateway_password_configured) {
    setActionMessage("Save the gateway admin password before turning Dry Run off.", "error");
    els.gatewayPassword.focus();
    return;
  }
  if (turningLive) {
    const confirmed = window.confirm("Turn Dry Run off and allow real gateway reboots?");
    if (!confirmed) {
      els.dryRunToggle.checked = true;
      updateDryRunHint();
      return;
    }
  }

  state.settingsBusy = true;
  updateControlState();
  try {
    const config = await api("/api/settings", {
      method: "POST",
      body: {
        dry_run: dryRun,
        tests_per_hour: testsPerHour,
      },
    });
    state.config = config;
    renderConfig(config);
    renderSettingsControls(config);
    await refreshStatusAndEvents();
    setActionMessage("Settings saved.", "success");
  } catch (error) {
    setActionMessage(error.message, "error");
    await loadConfig();
  } finally {
    state.settingsBusy = false;
    updateControlState();
  }
}

function readTestsPerHour() {
  const testsPerHour = Number.parseInt(els.testsPerHour.value, 10);
  if (!Number.isInteger(testsPerHour) || testsPerHour < 1 || testsPerHour > 720) {
    throw new Error("Tests per hour must be between 1 and 720.");
  }
  return testsPerHour;
}

function intervalToTestsPerHour(intervalSeconds) {
  const safeInterval = Number(intervalSeconds) || 20;
  return Math.max(1, Math.min(720, Math.round(3600 / safeInterval)));
}

function updateControlState() {
  const controlsDisabled =
    state.seriesRunning || state.gatewayLoginBusy || state.settingsBusy;
  const loginControlsDisabled = controlsDisabled;
  const gatewayPasswordConfigured = state.config
    ? Boolean(state.config.gateway_password_configured)
    : true;
  const gatewayPasswordSource = state.config
    ? state.config.gateway_password_source || "none"
    : "unknown";
  const canClearGatewayLogin =
    gatewayPasswordSource === "saved" || gatewayPasswordSource === "runtime";

  [els.checkButton, els.gatewayButton, els.rebootButton, els.seriesStartButton].forEach(
    (button) => {
      button.disabled = controlsDisabled;
    },
  );
  els.forceReboot.disabled = controlsDisabled;
  els.seriesStopButton.disabled = !state.seriesRunning;
  els.dryRunToggle.disabled = controlsDisabled || !state.config;
  els.testsPerHour.disabled = controlsDisabled || !state.config;
  els.saveSettingsButton.disabled = controlsDisabled || !state.config;
  els.gatewayPassword.disabled = loginControlsDisabled;
  els.saveGatewayLogin.disabled = loginControlsDisabled;
  els.saveGatewayLoginButton.disabled =
    loginControlsDisabled || !els.gatewayPassword.value;
  els.clearGatewayLoginButton.disabled = loginControlsDisabled || !canClearGatewayLogin;

  if (state.settingsBusy) {
    setTag(els.settingsState, "Saving", "warn");
  } else if (state.config && state.config.dry_run) {
    setTag(els.settingsState, "Safe mode", "warn");
  } else if (state.config) {
    setTag(els.settingsState, "Live reboots", "good");
  } else {
    setTag(els.settingsState, "Checking", "");
  }

  if (state.gatewayLoginBusy) {
    setTag(els.gatewayLoginState, "Logging in", "warn");
  } else if (!gatewayPasswordConfigured) {
    setTag(els.gatewayLoginState, "Login needed", "warn");
  } else if (gatewayPasswordSource === "environment") {
    setTag(els.gatewayLoginState, "Env configured", "good");
  } else if (gatewayPasswordSource === "saved") {
    setTag(els.gatewayLoginState, "Saved", "good");
  } else if (gatewayPasswordSource === "runtime") {
    setTag(els.gatewayLoginState, "Session", "warn");
  } else {
    setTag(els.gatewayLoginState, "Configured", "good");
  }
}

function renderSettingsControls(config) {
  els.dryRunToggle.checked = Boolean(config.dry_run);
  els.testsPerHour.value = String(config.tests_per_hour || intervalToTestsPerHour(config.check_interval_seconds));
  updateDryRunHint();
}

function updateDryRunHint() {
  els.dryRunHint.textContent = els.dryRunToggle.checked ? "Test only" : "Can reboot";
}

function maybeShowTutorial() {
  const tutorialRequested = new URLSearchParams(window.location.search).get("tutorial") === "1";
  if (tutorialRequested || !localStorage.getItem(TUTORIAL_STORAGE_KEY)) {
    openTutorial();
  }
}

function openTutorial() {
  els.tutorialModal.classList.remove("modal--hidden");
  els.tutorialDoneButton.focus();
}

function closeTutorial() {
  localStorage.setItem(TUTORIAL_STORAGE_KEY, "true");
  els.tutorialModal.classList.add("modal--hidden");
}

function renderStatus(status) {
  renderPhase(status.phase);
  setStatusText(
    els.internetValue,
    status.internet_online,
    "Online",
    "Offline",
    "Unknown",
  );
  els.probeValue.textContent = `${status.successful_probes || 0} / ${
    status.total_probes || 0
  }`;
  renderGatewayStatus(status);
  setStatusText(els.dryRunValue, status.dry_run, "On", "Off", "Unknown");
  els.lastCheckValue.textContent = formatDate(status.last_check_at);
  els.rebootValue.textContent = String(status.reboot_count_24h || 0);
  els.updatedAt.textContent = `Refreshed ${new Date().toLocaleTimeString()}`;

  if (status.last_error) {
    els.lastError.textContent = status.last_error;
    els.lastError.className = "alert alert--error";
  } else {
    els.lastError.textContent = "";
    els.lastError.className = "alert alert--hidden";
  }

  renderProbes(status.last_probe_results || []);
}

function renderPhase(phase) {
  const value = phase || "unknown";
  let className = "phase-pill phase-pill--unknown";
  if (phaseGroups.good.has(value)) {
    className = "phase-pill phase-pill--good";
  } else if (phaseGroups.warn.has(value)) {
    className = "phase-pill phase-pill--warn";
  } else if (phaseGroups.bad.has(value)) {
    className = "phase-pill phase-pill--bad";
  }
  els.phasePill.className = className;
  els.phasePill.textContent = humanize(value);
}

function renderGatewayStatus(status) {
  els.gatewayValue.className = "";
  if (status.gateway_reachable === true) {
    const label = status.gateway_model || status.gateway_name || "Reachable";
    els.gatewayValue.textContent =
      status.gateway_supported === false ? `${label} (unsupported)` : label;
    els.gatewayValue.classList.add(
      status.gateway_supported === false ? "status-warn" : "status-good",
    );
  } else if (status.gateway_reachable === false) {
    els.gatewayValue.textContent = "Not found";
    els.gatewayValue.classList.add("status-bad");
  } else {
    els.gatewayValue.textContent = "Detecting";
    els.gatewayValue.classList.add("status-muted");
  }
}

function renderProbes(probes) {
  clearRows(els.probeResults);
  if (!probes.length) {
    addEmptyRow(els.probeResults, 3, "No probes yet");
    return;
  }

  probes.forEach((probe) => {
    const row = document.createElement("tr");
    row.append(
      cell(probe.url || "Unknown"),
      statusCell(probe.success, probe.status_code),
      cell(formatLatency(probe.latency_ms, probe.error)),
    );
    els.probeResults.append(row);
  });
}

function renderConfig(config) {
  els.configList.textContent = "";
  Object.entries(configLabels).forEach(([key, label]) => {
    if (!(key in config)) {
      return;
    }
    const term = document.createElement("dt");
    term.textContent = label;
    const detail = document.createElement("dd");
    detail.textContent = formatConfigValue(config[key], key);
    els.configList.append(term, detail);
  });
}

function renderEvents(events) {
  clearRows(els.eventRows);
  if (!events.length) {
    addEmptyRow(els.eventRows, 3, "No events recorded");
    return;
  }

  events.forEach((event) => {
    const row = document.createElement("tr");
    row.append(
      cell(formatDate(event.timestamp)),
      cell(humanize(event.kind || "event")),
      cell(event.message || ""),
    );
    els.eventRows.append(row);
  });
}

async function runSingleCheck() {
  try {
    setActionMessage("Running connectivity check.", "");
    const status = await api("/api/check", { method: "POST" });
    state.status = status;
    renderStatus(status);
    await refreshEvents();
    setActionMessage("Connectivity check complete.", "success");
  } catch (error) {
    setActionMessage(error.message, "error");
  }
}

async function runGatewayTest() {
  const gatewayPasswordConfigured = state.config
    ? Boolean(state.config.gateway_password_configured)
    : true;
  const gatewayPassword = els.gatewayPassword.value;
  if (!gatewayPasswordConfigured && !gatewayPassword) {
    setActionMessage("Enter the gateway admin password or save the gateway login first.", "error");
    els.gatewayPassword.focus();
    return;
  }

  try {
    setActionMessage("Testing gateway.", "");
    const result = await api("/api/gateway/test", {
      method: "POST",
      body: gatewayPassword ? { gateway_password: gatewayPassword } : {},
    });
    const reachable = result.reachable ? "reachable" : "not reachable";
    const authenticated = result.authenticated ? "authenticated" : "not authenticated";
    const suffix = result.used_supplied_password ? " Password was tested but not saved." : "";
    setActionMessage(`Gateway ${reachable}, ${authenticated}.${suffix}`, "success");
    await refreshStatusAndEvents();
  } catch (error) {
    setActionMessage(error.message, "error");
  }
}

async function saveGatewayLogin() {
  const gatewayPassword = els.gatewayPassword.value;
  if (!gatewayPassword) {
    setActionMessage("Enter the gateway admin password first.", "error");
    els.gatewayPassword.focus();
    return;
  }

  state.gatewayLoginBusy = true;
  updateControlState();
  try {
    setActionMessage("Logging in to gateway.", "");
    const result = await api("/api/gateway/login", {
      method: "POST",
      body: {
        gateway_password: gatewayPassword,
        remember: els.saveGatewayLogin.checked,
      },
    });
    if (!result.reachable) {
      setActionMessage("Gateway is not reachable. Login was not saved.", "error");
      return;
    }

    els.gatewayPassword.value = "";
    await loadConfig();
    await refreshStatusAndEvents();
    setActionMessage(
      result.saved ? "Gateway login saved." : "Gateway login active for this session.",
      "success",
    );
  } catch (error) {
    setActionMessage(error.message, "error");
  } finally {
    state.gatewayLoginBusy = false;
    updateControlState();
  }
}

async function clearGatewayLogin() {
  const confirmed = window.confirm("Forget the saved gateway login?");
  if (!confirmed) {
    return;
  }

  state.gatewayLoginBusy = true;
  updateControlState();
  try {
    setActionMessage("Clearing gateway login.", "");
    const result = await api("/api/gateway/login", {
      method: "DELETE",
    });
    els.gatewayPassword.value = "";
    await loadConfig();
    await refreshStatusAndEvents();
    if (result.gateway_password_source === "environment") {
      setActionMessage("Saved gateway login cleared. Environment password remains active.", "success");
    } else {
      setActionMessage("Gateway login cleared.", "success");
    }
  } catch (error) {
    setActionMessage(error.message, "error");
  } finally {
    state.gatewayLoginBusy = false;
    updateControlState();
  }
}

async function requestReboot() {
  const force = els.forceReboot.checked;
  const confirmed = window.confirm(
    force
      ? "Request a forced gateway reboot?"
      : "Request a gateway reboot if limits allow it?",
  );
  if (!confirmed) {
    return;
  }

  try {
    setActionMessage("Requesting reboot.", "");
    const status = await api("/api/reboot", {
      method: "POST",
      body: { force },
    });
    state.status = status;
    renderStatus(status);
    await refreshEvents();
    setActionMessage("Reboot request complete.", "success");
  } catch (error) {
    setActionMessage(error.message, "error");
  }
}

async function runSeries(event) {
  event.preventDefault();
  if (state.seriesRunning) {
    return;
  }

  let settings;
  try {
    settings = readSeriesSettings();
  } catch (error) {
    setActionMessage(error.message, "error");
    return;
  }

  state.seriesRunning = true;
  state.seriesAbort = false;
  updateControlState();
  clearRows(els.seriesResults);
  updateSeriesProgress(0, settings.count);
  setTag(els.seriesState, "Running", "warn");
  setActionMessage("Connection tests started.", "");

  let completed = 0;
  try {
    for (let index = 1; index <= settings.count; index += 1) {
      if (state.seriesAbort) {
        break;
      }
      setTag(els.seriesState, `${index} / ${settings.count}`, "warn");
      const status = await api("/api/check", { method: "POST" });
      completed = index;
      state.status = status;
      renderStatus(status);
      addSeriesRow(index, status);
      updateSeriesProgress(completed, settings.count);
      await refreshEvents();

      if (index < settings.count && !state.seriesAbort) {
        await waitForAbortable(settings.intervalSeconds * 1000);
      }
    }

    if (state.seriesAbort) {
      setTag(els.seriesState, "Stopped", "warn");
      setActionMessage(`Stopped after ${completed} of ${settings.count} tests.`, "");
    } else {
      setTag(els.seriesState, "Complete", "good");
      setActionMessage(`Completed ${completed} connection tests.`, "success");
    }
  } catch (error) {
    setTag(els.seriesState, "Error", "bad");
    setActionMessage(error.message, "error");
  } finally {
    state.seriesRunning = false;
    updateControlState();
  }
}

function stopSeries() {
  state.seriesAbort = true;
  setTag(els.seriesState, "Stopping", "warn");
}

function readSeriesSettings() {
  const count = Number.parseInt(els.seriesCount.value, 10);
  const intervalSeconds = Number.parseFloat(els.seriesInterval.value);
  if (!Number.isInteger(count) || count < 1 || count > 30) {
    throw new Error("Tests must be between 1 and 30.");
  }
  if (!Number.isFinite(intervalSeconds) || intervalSeconds < 0 || intervalSeconds > 300) {
    throw new Error("Seconds apart must be between 0 and 300.");
  }
  return { count, intervalSeconds };
}

function waitForAbortable(ms) {
  if (ms <= 0) {
    return Promise.resolve();
  }

  return new Promise((resolve) => {
    const started = Date.now();
    const tick = () => {
      const elapsed = Date.now() - started;
      if (state.seriesAbort || elapsed >= ms) {
        resolve();
        return;
      }
      window.setTimeout(tick, Math.min(250, ms - elapsed));
    };
    tick();
  });
}

function addSeriesRow(index, status) {
  if (els.seriesResults.querySelector(".empty-cell")) {
    clearRows(els.seriesResults);
  }
  const row = document.createElement("tr");
  row.append(
    cell(String(index)),
    cell(formatDate(status.last_check_at)),
    statusCell(status.internet_online),
    cell(`${status.successful_probes || 0} / ${status.total_probes || 0}`),
    cell(humanize(status.phase || "unknown")),
  );
  els.seriesResults.prepend(row);
}

function updateSeriesProgress(completed, total) {
  const safeTotal = total || 0;
  const percent = safeTotal ? Math.round((completed / safeTotal) * 100) : 0;
  els.seriesProgress.value = percent;
  els.seriesProgressText.textContent = `${completed} / ${safeTotal} complete`;
}

function setActionMessage(message, type) {
  els.actionMessage.textContent = message;
  els.actionMessage.className = "message";
  if (type === "error") {
    els.actionMessage.classList.add("message--error");
  } else if (type === "success") {
    els.actionMessage.classList.add("message--success");
  }
}

function setTag(element, text, tone) {
  element.textContent = text;
  element.className = "tag";
  if (tone === "good") {
    element.classList.add("tag--good");
  } else if (tone === "warn") {
    element.classList.add("tag--warn");
  } else if (tone === "bad") {
    element.classList.add("tag--bad");
  }
}

function setStatusText(element, value, trueText, falseText, unknownText) {
  element.className = "";
  if (value === true) {
    element.textContent = trueText;
    element.classList.add("status-good");
  } else if (value === false) {
    element.textContent = falseText;
    element.classList.add("status-bad");
  } else {
    element.textContent = unknownText;
    element.classList.add("status-muted");
  }
}

function clearRows(tableBody) {
  tableBody.textContent = "";
}

function addEmptyRow(tableBody, colspan, text) {
  const row = document.createElement("tr");
  const item = document.createElement("td");
  item.colSpan = colspan;
  item.className = "empty-cell";
  item.textContent = text;
  row.append(item);
  tableBody.append(row);
}

function cell(text) {
  const item = document.createElement("td");
  item.textContent = text;
  return item;
}

function statusCell(success, statusCode) {
  const item = cell("");
  if (success === true) {
    item.textContent = statusCode ? `OK ${statusCode}` : "OK";
    item.className = "status-good";
  } else if (success === false) {
    item.textContent = statusCode ? `Failed ${statusCode}` : "Failed";
    item.className = "status-bad";
  } else {
    item.textContent = "Unknown";
    item.className = "status-muted";
  }
  return item;
}

function formatLatency(latencyMs, error) {
  if (typeof latencyMs === "number") {
    return `${latencyMs} ms`;
  }
  return error || "Unknown";
}

function formatDate(value) {
  if (!value) {
    return "Never";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Invalid date";
  }
  return date.toLocaleString();
}

function formatConfigValue(value, key) {
  if (Array.isArray(value)) {
    return value.join(", ");
  }
  if (key === "gateway_password_configured") {
    return value ? "Configured" : "Not configured";
  }
  if (key === "gateway_password_source") {
    return humanize(value || "none");
  }
  if (typeof value === "boolean") {
    return value ? "On" : "Off";
  }
  if (typeof value === "number" && key.endsWith("_seconds")) {
    return `${value} seconds`;
  }
  return String(value);
}

function humanize(value) {
  return String(value)
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}
