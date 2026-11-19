import { api, store } from "./api.js";

const slug = decodeURIComponent(location.pathname.split("/").pop());
const storeKey = `scheduler:${slug}`;
const $ = (id) => document.getElementById(id);

const state = {
  group: null,          // GET /api/groups/<slug>
  me: store.get(storeKey), // { id, name, key } once joined on this device
  mine: new Set(),      // my slots, including unsaved changes
  dirty: false,
  mode: "heat",         // "edit" (my times) or "heat" (everyone)
  highlight: null,      // { start, end } of a suggestion being shown on the grid
  focused: 0,           // slot of the cell that takes Tab focus
};
let initialized = false;

// ---------- loading ----------

async function load() {
  try {
    state.group = await api("GET", `/api/groups/${encodeURIComponent(slug)}`);
  } catch (err) {
    $("group-name").textContent = "Group not found";
    $("load-error").textContent = err.message;
    return;
  }
  const g = state.group;
  document.title = `${g.name} · Study group`;
  $("group-name").textContent = g.name;
  $("share-link").value = location.href;
  if (state.me && !g.members.some((m) => m.id === state.me.id)) {
    store.remove(storeKey); // removed from the group, or the group was recreated
    state.me = null;
  }
  if (!state.dirty) {
    const mine = state.me && g.members.find((m) => m.id === state.me.id);
    state.mine = new Set(mine ? mine.slots : []);
  }
  if (!initialized) {
    initialized = true;
    state.mode = state.me ? "edit" : "heat";
    buildDurations();
    $("quorum").value = Math.max(1, g.members.length);
  }
  $("app").hidden = false;
  renderAll();
  findTimes();
}

// ---------- rendering ----------

function renderAll() {
  renderIdentity();
  renderGrid();
  renderMembers();
  renderRequired();
}

function renderIdentity() {
  const joined = Boolean(state.me);
  $("identity").textContent = joined ? `You are ${state.me.name}` : "";
  $("join").hidden = joined;
  $("leave").hidden = !joined;
  $("mode-edit").disabled = !joined;
  $("mode-edit").setAttribute("aria-pressed", String(state.mode === "edit"));
  $("mode-heat").setAttribute("aria-pressed", String(state.mode === "heat"));
  $("save-bar").hidden = state.mode !== "edit";
  $("hint").textContent = state.mode === "edit"
    ? "Click or drag across the grid to mark when you're free. Arrow keys move, Space toggles. Then save."
    : "Darker cells mean more people are free. Hover or focus a cell to see who.";
  updateSaveStatus();
}

function renderGrid() {
  const { grid, members, heat } = state.group;
  const table = $("grid");
  table.className = `grid ${state.mode}`;
  table.replaceChildren();

  const head = table.createTHead().insertRow();
  head.appendChild(document.createElement("th"));
  for (const day of grid.days) {
    const th = document.createElement("th");
    th.scope = "col";
    th.textContent = day;
    head.appendChild(th);
  }

  const total = members.length;
  const body = table.createTBody();
  for (let i = 0; i < grid.slots_per_day; i++) {
    const row = body.insertRow();
    const th = document.createElement("th");
    th.scope = "row";
    th.textContent = i % 2 === 0 ? grid.times[i] : "";
    row.appendChild(th);
    for (let d = 0; d < grid.days.length; d++) {
      const slot = d * grid.slots_per_day + i;
      const cell = row.insertCell();
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.slot = slot;
      button.tabIndex = slot === state.focused ? 0 : -1;
      const when = `${grid.days[d]} ${grid.times[i]}–${grid.times[i + 1]}`;
      if (state.mode === "edit") {
        const free = state.mine.has(slot);
        button.setAttribute("aria-pressed", String(free));
        button.setAttribute("aria-label", `${when}, ${free ? "free" : "busy"}`);
      } else {
        const who = members.filter((m) => m.slots.includes(slot)).map((m) => m.name);
        const share = total ? heat[slot] / total : 0;
        button.style.setProperty("--share", share.toFixed(3));
        button.dataset.count = heat[slot];
        const label = `${when}: ${heat[slot]} of ${total} free${who.length ? ` (${who.join(", ")})` : ""}`;
        button.setAttribute("aria-label", label);
        button.title = label;
      }
      if (state.highlight && slot >= state.highlight.start && slot < state.highlight.end) {
        button.classList.add("picked");
      }
      cell.appendChild(button);
    }
  }
}

function renderMembers() {
  const list = $("members");
  list.replaceChildren();
  const { members, grid } = state.group;
  $("member-count").textContent = `(${members.length})`;
  if (!members.length) {
    const li = document.createElement("li");
    li.className = "muted";
    li.textContent = "Nobody has joined yet.";
    list.appendChild(li);
  }
  for (const m of members) {
    const li = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = m.name + (state.me && state.me.id === m.id ? " (you)" : "");
    const hours = document.createElement("span");
    hours.className = "muted";
    hours.textContent = `${(m.slots.length * grid.slot_minutes) / 60} h free`;
    li.append(name, hours);
    list.appendChild(li);
  }
}

function renderRequired() {
  const box = $("required");
  const checked = new Set([...box.querySelectorAll("input:checked")].map((i) => i.value));
  box.replaceChildren();
  for (const m of state.group.members) {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = String(m.id);
    input.checked = checked.has(String(m.id));
    label.append(input, ` ${m.name}`);
    box.appendChild(label);
  }
  $("required-box").hidden = state.group.members.length === 0;
}

function buildDurations() {
  const select = $("duration");
  for (let minutes = 30; minutes <= 240; minutes += 30) {
    const option = document.createElement("option");
    option.value = minutes;
    option.textContent = minutes < 60 ? `${minutes} min` : `${minutes / 60} h`.replace(".5 h", "½ h");
    if (minutes === 60) option.selected = true;
    select.appendChild(option);
  }
}

function updateSaveStatus(message) {
  if (message !== undefined) {
    $("save-status").textContent = message;
  } else if (state.dirty) {
    $("save-status").textContent = "Unsaved changes";
  }
  $("save").disabled = !state.dirty;
}

// ---------- painting (edit mode) ----------

let painting = null; // { value } while the pointer is down

function setSlot(slot, value) {
  if (state.mine.has(slot) === value) return;
  if (value) state.mine.add(slot);
  else state.mine.delete(slot);
  state.dirty = true;
  const button = $("grid").querySelector(`button[data-slot="${slot}"]`);
  if (button) {
    button.setAttribute("aria-pressed", String(value));
    button.setAttribute("aria-label", button.getAttribute("aria-label").replace(/(free|busy)$/, value ? "free" : "busy"));
  }
  updateSaveStatus();
}

function slotAt(event) {
  const el = document.elementFromPoint(event.clientX, event.clientY);
  const button = el && el.closest("button[data-slot]");
  return button ? Number(button.dataset.slot) : null;
}

$("grid").addEventListener("pointerdown", (e) => {
  if (state.mode !== "edit" || e.button !== 0) return;
  const slot = slotAt(e);
  if (slot === null) return;
  e.preventDefault();
  painting = { value: !state.mine.has(slot) };
  setSlot(slot, painting.value);
  focusSlot(slot);
});

window.addEventListener("pointermove", (e) => {
  if (!painting) return;
  const slot = slotAt(e);
  if (slot !== null) setSlot(slot, painting.value);
});

window.addEventListener("pointerup", () => { painting = null; });
window.addEventListener("pointercancel", () => { painting = null; });

// Keyboard activation (detail === 0); mouse clicks were already handled on pointerdown.
$("grid").addEventListener("click", (e) => {
  const button = e.target.closest("button[data-slot]");
  if (!button || state.mode !== "edit" || e.detail !== 0) return;
  const slot = Number(button.dataset.slot);
  setSlot(slot, !state.mine.has(slot));
});

$("grid").addEventListener("keydown", (e) => {
  const button = e.target.closest("button[data-slot]");
  if (!button) return;
  const { slots_per_day: perDay, days } = state.group.grid;
  const slot = Number(button.dataset.slot);
  const day = Math.floor(slot / perDay);
  const index = slot % perDay;
  const moves = {
    ArrowUp: [day, index - 1], ArrowDown: [day, index + 1],
    ArrowLeft: [day - 1, index], ArrowRight: [day + 1, index],
  };
  if (!(e.key in moves)) return;
  e.preventDefault();
  const [d, i] = moves[e.key];
  if (d < 0 || d >= days.length || i < 0 || i >= perDay) return;
  focusSlot(d * perDay + i, true);
});

function focusSlot(slot, move = false) {
  const grid = $("grid");
  const old = grid.querySelector(`button[data-slot="${state.focused}"]`);
  if (old) old.tabIndex = -1;
  state.focused = slot;
  const next = grid.querySelector(`button[data-slot="${slot}"]`);
  if (next) {
    next.tabIndex = 0;
    if (move) next.focus();
  }
}

// ---------- actions ----------

$("join").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("join-error").textContent = "";
  try {
    const member = await api("POST", `/api/groups/${encodeURIComponent(slug)}/members`, { name: $("member-name").value });
    state.me = member;
    store.set(storeKey, member);
    state.mode = "edit";
    state.dirty = false;
    await load();
  } catch (err) {
    $("join-error").textContent = err.message;
  }
});

$("save").addEventListener("click", async () => {
  updateSaveStatus("Saving…");
  try {
    await api("PUT", `/api/groups/${encodeURIComponent(slug)}/members/${state.me.id}/availability`,
      { slots: [...state.mine].sort((a, b) => a - b) }, state.me.key);
    state.dirty = false;
    await load();
    updateSaveStatus("Saved");
  } catch (err) {
    updateSaveStatus(`Not saved: ${err.message}`);
  }
});

$("clear").addEventListener("click", () => {
  for (const slot of [...state.mine]) setSlot(slot, false);
});

$("leave").addEventListener("click", async () => {
  if (!state.me) return;
  try {
    await api("DELETE", `/api/groups/${encodeURIComponent(slug)}/members/${state.me.id}`, undefined, state.me.key);
  } catch (err) {
    if (err.status !== 404) {
      updateSaveStatus(`Couldn't leave: ${err.message}`);
      return;
    }
  }
  store.remove(storeKey);
  state.me = null;
  state.mine = new Set();
  state.dirty = false;
  state.mode = "heat";
  await load();
});

for (const [id, mode] of [["mode-edit", "edit"], ["mode-heat", "heat"]]) {
  $(id).addEventListener("click", () => {
    state.mode = mode;
    renderIdentity();
    renderGrid();
  });
}

$("copy-link").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("share-link").value);
    $("copy-link").textContent = "Copied";
  } catch {
    $("share-link").select();
  }
});

window.addEventListener("beforeunload", (e) => {
  if (state.dirty) e.preventDefault();
});

// ---------- suggestions ----------

$("find").addEventListener("change", findTimes);
$("find").addEventListener("submit", (e) => { e.preventDefault(); findTimes(); });

let requestSeq = 0;

async function findTimes() {
  const params = new URLSearchParams({ duration: $("duration").value, quorum: $("quorum").value || "1" });
  for (const box of $("required").querySelectorAll("input:checked")) params.append("required", box.value);
  const seq = ++requestSeq;
  const list = $("results");
  try {
    const data = await api("GET", `/api/groups/${encodeURIComponent(slug)}/suggestions?${params}`);
    if (seq !== requestSeq) return; // a newer request has been sent
    list.replaceChildren();
    if (!data.windows.length) {
      const li = document.createElement("li");
      li.className = "muted";
      li.textContent = data.total_members
        ? "No time fits. Try a shorter meeting, fewer people, or fewer required members."
        : "Nobody has joined yet.";
      list.appendChild(li);
      return;
    }
    for (const w of data.windows) {
      const li = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "result";
      const when = document.createElement("strong");
      when.textContent = `${w.day} ${w.start}–${w.end}`;
      const who = document.createElement("span");
      who.textContent = `${w.attendees.length} of ${data.total_members}: ${w.attendees.join(", ")}`;
      button.append(when, who);
      if (w.missing.length) {
        const missing = document.createElement("span");
        missing.className = "muted";
        missing.textContent = `Not free: ${w.missing.join(", ")}`;
        button.appendChild(missing);
      }
      button.addEventListener("click", () => {
        state.highlight = { start: w.start_slot, end: w.end_slot };
        state.mode = "heat";
        renderIdentity();
        renderGrid();
      });
      li.appendChild(button);
      list.appendChild(li);
    }
  } catch (err) {
    if (seq !== requestSeq) return;
    list.replaceChildren();
    const li = document.createElement("li");
    li.className = "error";
    li.textContent = err.message;
    list.appendChild(li);
  }
}

load();
