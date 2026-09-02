/* The owner interface.
 *
 * Deliberately dependency-free. A build pipeline before there is a dashboard
 * to justify one is overhead, and the API boundary is clean enough that
 * replacing this layer later is cheap.
 */

const el = (id) => document.getElementById(id);

const app = {
  meta: { providers: {}, capability_tags: [], home: "" },
  state: null,
  connections: [],
  conversation: { id: null, messages: [] },
  streaming: false,
  editingTags: new Set(),
  workspacePath: "",
  workspaceSignature: null,
  workspaceTimer: null,
  appearance: null,
  appearanceTimer: null,
  layout: null,
  panes: [],
  lifecycle: null,
};

/* ---------- api ---------- */

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (body.detail) detail = body.detail;
    } catch (_) { /* keep the generic message */ }
    throw new Error(detail);
  }
  return response.status === 204 ? null : response.json();
}

/* ---------- boot ---------- */

async function boot() {
  const [meta, panes, layout] = await Promise.all([
    api("/api/meta"),
    api("/api/panes"),
    api("/api/layout"),
  ]);
  app.meta = meta;
  app.panes = panes;
  app.layout = layout;

  el("home-note").textContent = `This Aworg lives at ${app.meta.home}`;
  buildProviderOptions();
  buildTagChips();
  buildSettingsNav();

  // The column is assembled before anything reaches into it -- the preview,
  // the workspace listing and every resizer address elements that only exist
  // once the panes have been built.
  buildPanes();
  wireResizers();

  await refresh();
  wireEvents();
  // Home is where the owner lands, and the workspace is part of it.
  startWorkspaceWatch();
}

async function refresh() {
  const [state, connections, conversation, appearance, lifecycle] = await Promise.all([
    api("/api/state"),
    api("/api/connections"),
    api("/api/conversation"),
    api("/api/appearance"),
    api("/api/lifecycle"),
  ]);
  app.state = state;
  app.connections = connections;
  app.conversation = conversation;
  app.appearance = appearance;
  app.lifecycle = lifecycle;
  renderStatus();
  renderChat();
  renderSettings();
  renderAppearance();
  renderResetView();
  renderLifecycle();
}

/* ---------- status ---------- */

function renderStatus() {
  const resident = app.state.resident;
  el("status-dot").className = `dot ${resident.status}`;
  el("status-text").textContent =
    resident.status === "present" ? resident.model_label : resident.detail;
}

/* ---------- chat ---------- */

function renderChat() {
  const box = el("messages");
  box.innerHTML = "";

  if (!app.conversation.messages.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    if (app.state.resident.status === "present") {
      empty.innerHTML =
        "<strong>Your Resident is present.</strong>" +
        "It lives on this machine and will remember this conversation. " +
        "For now it can only talk — it has no workspace and no tools yet.";
    } else {
      empty.innerHTML =
        "<strong>No model is connected.</strong>" +
        "Open Settings and connect a model to bring your Resident to life.";
    }
    box.appendChild(empty);
    return;
  }

  for (const message of app.conversation.messages) {
    box.appendChild(messageNode(message.role, message.content, message.model_label));
  }
  box.scrollTop = box.scrollHeight;
}

function messageNode(role, content, label) {
  const wrapper = document.createElement("div");
  wrapper.className = `msg ${role}`;

  const body = document.createElement("div");
  body.className = "body";
  // What the owner typed is shown exactly as typed. What the Resident says is
  // rendered, because a developer that cannot show code legibly is hard to work
  // with -- and that matters well before it can write any.
  if (role === "resident") {
    body.classList.add("markdown");
    body.innerHTML = MD.render(content);
  } else {
    body.textContent = content;
  }
  wrapper.appendChild(body);

  // Attribution is what makes switching models mid-conversation legible:
  // the owner can see which mind produced which reply.
  if (role === "resident" && label) {
    const attrib = document.createElement("div");
    attrib.className = "attrib";
    attrib.textContent = label;
    wrapper.appendChild(attrib);
  }
  return wrapper;
}

async function send(text) {
  const box = el("messages");
  if (!app.conversation.messages.length) box.innerHTML = "";

  box.appendChild(messageNode("owner", text, null));
  app.conversation.messages.push({ role: "owner", content: text });

  const replyNode = messageNode("resident", "", null);
  const body = replyNode.querySelector(".body");
  body.classList.add("cursor");
  box.appendChild(replyNode);
  box.scrollTop = box.scrollHeight;

  setStreaming(true);
  let collected = "";
  let failed = false;

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();

      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);

        if (event.type === "delta") {
          collected += event.text;
          body.innerHTML = MD.render(collected);
          box.scrollTop = box.scrollHeight;
        } else if (event.type === "done") {
          const attrib = document.createElement("div");
          attrib.className = "attrib";
          attrib.textContent = event.model_label;
          replyNode.appendChild(attrib);
          app.conversation.messages.push({
            role: "resident",
            content: collected,
            model_label: event.model_label,
          });
        } else if (event.type === "error") {
          failed = true;
          if (!collected) replyNode.remove();
          box.appendChild(messageNode("error", event.message, null));
          box.scrollTop = box.scrollHeight;
        }
      }
    }
  } catch (error) {
    failed = true;
    if (!collected) replyNode.remove();
    box.appendChild(messageNode("error", `Lost contact with AWORG: ${error.message}`, null));
  } finally {
    body.classList.remove("cursor");
    setStreaming(false);
    if (failed) {
      // The conversation on disk is authoritative; resync rather than guess.
      app.conversation = await api("/api/conversation");
    }
  }
}

function setStreaming(on) {
  app.streaming = on;
  el("send").disabled = on;
  el("send").textContent = on ? "…" : "Send";
}

/* ---------- settings ---------- */

/* The rail is generated from the sections in the document rather than from a
 * list kept alongside them. There will be more sections than there are today,
 * and a second place to remember to update is a second place to forget. */

function buildSettingsNav() {
  const nav = el("settings-nav");
  nav.innerHTML = "";

  const sections = [...document.querySelectorAll(".settings-section")];
  for (const section of sections) {
    const item = document.createElement("button");
    item.type = "button";
    item.dataset.section = section.dataset.section;
    item.textContent = section.dataset.label;
    item.onclick = () => showSettingsSection(section.dataset.section);
    nav.appendChild(item);
  }

  if (sections.length) showSettingsSection(sections[0].dataset.section);
}

function showSettingsSection(id) {
  for (const section of document.querySelectorAll(".settings-section")) {
    section.classList.toggle("on", section.dataset.section === id);
  }
  for (const item of el("settings-nav").children) {
    item.classList.toggle("on", item.dataset.section === id);
  }
  // A new section starts at its own top, not at wherever the last one was left.
  el("settings-scroll").scrollTop = 0;
}

function buildProviderOptions() {
  const select = el("conn-provider");
  select.innerHTML = "";
  for (const [value, label] of Object.entries(app.meta.providers)) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
  }
}

function buildTagChips() {
  const container = el("conn-tags");
  container.innerHTML = "";
  for (const tag of app.meta.capability_tags) {
    const chip = document.createElement("span");
    chip.className = "tag selectable";
    chip.textContent = tag;
    chip.onclick = () => {
      if (app.editingTags.has(tag)) app.editingTags.delete(tag);
      else app.editingTags.add(tag);
      chip.classList.toggle("on");
    };
    container.appendChild(chip);
  }
}

function renderSettings() {
  const select = el("primary-select");
  select.innerHTML = "";

  if (!app.connections.length) {
    const option = document.createElement("option");
    option.textContent = "No connections yet";
    option.value = "";
    select.appendChild(option);
  }

  for (const connection of app.connections) {
    const option = document.createElement("option");
    option.value = connection.id;
    option.textContent = `${connection.name} (${connection.model})`;
    option.selected = connection.id === app.state.primary_connection_id;
    select.appendChild(option);
  }

  const worker = el("worker-select");
  worker.innerHTML = "";
  // Unassigned is a real choice, not a missing one: workers then think with
  // whatever the Resident does.
  const same = document.createElement("option");
  same.value = "";
  same.textContent = "Same as the Resident";
  worker.appendChild(same);
  for (const connection of app.connections) {
    const option = document.createElement("option");
    option.value = connection.id;
    option.textContent = `${connection.name} (${connection.model})`;
    option.selected = connection.id === app.state.worker_connection_id;
    worker.appendChild(option);
  }

  el("system-prompt").value = app.state.system_prompt;
  renderConnections();
}

function renderConnections() {
  const container = el("connections");
  container.innerHTML = "";

  if (!app.connections.length) {
    const hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent = "No models connected yet.";
    container.appendChild(hint);
    return;
  }

  for (const connection of app.connections) {
    container.appendChild(connectionNode(connection));
  }
}

function connectionNode(connection) {
  const isPrimary = connection.id === app.state.primary_connection_id;

  const card = document.createElement("div");
  card.className = "conn" + (isPrimary ? " is-primary" : "") + (connection.enabled ? "" : " disabled");

  const top = document.createElement("div");
  top.className = "conn-top";

  const left = document.createElement("div");
  const name = document.createElement("div");
  name.className = "conn-name";
  name.textContent = connection.name;
  const meta = document.createElement("div");
  meta.className = "conn-meta";
  meta.textContent =
    `${app.meta.providers[connection.provider] || connection.provider} · ${connection.model}` +
    (connection.base_url ? ` · ${connection.base_url}` : "") +
    (connection.has_credential ? "" : " · no credential");
  left.append(name, meta);
  top.appendChild(left);

  if (isPrimary) {
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = "Resident";
    top.appendChild(badge);
  }
  card.appendChild(top);

  if (connection.tags.length) {
    const tags = document.createElement("div");
    tags.className = "tags";
    for (const tag of connection.tags) {
      const chip = document.createElement("span");
      chip.className = "tag";
      chip.textContent = tag;
      tags.appendChild(chip);
    }
    card.appendChild(tags);
  }

  const actions = document.createElement("div");
  actions.className = "conn-actions";

  if (!isPrimary) {
    actions.appendChild(
      button("Make Resident", "tiny", async () => {
        await api("/api/resident", {
          method: "PATCH",
          body: JSON.stringify({ primary_connection_id: connection.id }),
        });
        await refresh();
      })
    );
  }

  const result = document.createElement("span");
  result.className = "test-result";

  actions.appendChild(
    button("Test", "tiny ghost", async (btn) => {
      btn.disabled = true;
      result.textContent = "Testing…";
      result.className = "test-result";
      try {
        const outcome = await api(`/api/connections/${connection.id}/test`, { method: "POST" });
        result.textContent = outcome.detail;
        result.className = `test-result ${outcome.ok ? "ok" : "bad"}`;
      } catch (error) {
        result.textContent = error.message;
        result.className = "test-result bad";
      } finally {
        btn.disabled = false;
      }
    })
  );

  actions.appendChild(button("Edit", "tiny ghost", () => openForm(connection)));

  actions.appendChild(
    button(connection.enabled ? "Disable" : "Enable", "tiny ghost", async () => {
      await api(`/api/connections/${connection.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !connection.enabled }),
      });
      await refresh();
    })
  );

  actions.appendChild(
    button("Delete", "tiny ghost", async () => {
      if (!confirm(`Delete "${connection.name}"? Its credential is deleted too.`)) return;
      await api(`/api/connections/${connection.id}`, { method: "DELETE" });
      await refresh();
    })
  );

  actions.appendChild(result);
  card.appendChild(actions);
  return card;
}

function button(label, className, onClick) {
  const node = document.createElement("button");
  node.type = "button";
  node.className = className;
  node.textContent = label;
  node.onclick = () => onClick(node);
  return node;
}

/* ---------- connection form ---------- */

function openForm(connection) {
  el("conn-form").hidden = false;
  el("conn-error").textContent = "";
  el("conn-id").value = connection ? connection.id : "";
  el("conn-name").value = connection ? connection.name : "";
  el("conn-provider").value = connection ? connection.provider : Object.keys(app.meta.providers)[0];
  el("conn-model").value = connection ? connection.model : "";
  el("conn-base-url").value = connection && connection.base_url ? connection.base_url : "";
  el("conn-credential").value = "";
  el("conn-credential").placeholder = connection && connection.has_credential
    ? "Stored — leave blank to keep it"
    : "Stored privately, never shown again";

  app.editingTags = new Set(connection ? connection.tags : []);
  for (const chip of el("conn-tags").children) {
    chip.classList.toggle("on", app.editingTags.has(chip.textContent));
  }
  el("conn-name").focus();
}

function closeForm() {
  el("conn-form").hidden = true;
  app.editingTags = new Set();
}

/* ---------- the status column ---------- */

/* The control room. Every pane is open at once -- a pane hidden behind a tab
 * is an instrument nobody is watching, and watching is the entire purpose of
 * this column. The column scrolls instead, and the owner decides by dragging
 * which instruments deserve the room.
 *
 * The order and the empty text come from panes.py. The two panes above them
 * are AWORG's own rather than the Resident's, so they are declared here. */

const FIXED_PANES = {
  // `derived` means the pane sizes itself -- the preview holds 16:9 against
  // the column's width -- so it carries no stored size and offers no divider
  // of its own. Dragging the column is how you make the picture bigger.
  preview: {
    label: "Application",
    hint: "The software the Resident is responsible for.",
    derived: true,
  },
  lifecycle: { label: "Lifecycle", hint: "How far along that software is." },
};

/* Which pane goes where, and in what order within its region.
 *
 * This is the only place the arrangement is written down. Moving Tasks out of
 * the activity row and into the workspace column is a line moved here; every
 * other file goes on not caring where anything is. */
const REGIONS = [
  { id: "faculties", element: "faculties", axis: "column", panes: ["capabilities", "skills", "tools"] },
  { id: "side", element: "side", axis: "column", panes: ["preview", "lifecycle", "workspace"] },
  { id: "activity", element: "activity", axis: "row", panes: ["tasks", "workers"] },
  { id: "console", element: "console", axis: "column", panes: ["log"] },
];

function buildPanes() {
  const known = new Map();
  for (const [id, pane] of Object.entries(FIXED_PANES)) known.set(id, { id, ...pane });
  for (const pane of app.panes) known.set(pane.id, pane);

  for (const region of REGIONS) {
    const container = el(region.element);
    container.innerHTML = "";
    container.classList.add("region", `region-${region.axis}`);

    const members = region.panes.map((id) => known.get(id)).filter(Boolean);
    members.forEach((pane, index) => {
      const last = index === members.length - 1;
      container.appendChild(paneNode(pane, { region, last }));
      // The last pane in a region takes the space that is left, and a derived
      // pane computes its own -- neither has a size to drag. Everything else
      // gets a divider after it.
      if (!last && !pane.derived) container.appendChild(paneResizer(pane, region));
    });
  }
}

function paneNode(pane, { region, last }) {
  const section = document.createElement("section");
  section.className = "pane";
  section.dataset.pane = pane.id;
  section.dataset.region = region.id;
  section.id = `pane-${pane.id}`;

  if (pane.derived) {
    // Sizes itself from its content; see .preview in the stylesheet.
    section.classList.add("derived");
  } else if (last) {
    // Fills whatever the panes above or beside it left over.
    section.classList.add("fills");
  } else if (region.axis === "column") {
    section.style.height = `var(--${pane.id}-height)`;
  } else {
    section.style.width = `var(--${pane.id}-width)`;
  }

  const head = document.createElement("div");
  head.className = "pane-head";

  const heading = document.createElement("h2");
  heading.textContent = pane.label;
  head.appendChild(heading);

  // The application is the one pane worth filling the screen with, so it is
  // the one that gets to. Everything else is read at a glance.
  if (pane.id === "preview") {
    head.appendChild(maximizeButton());
  } else if (pane.id === "workspace") {
    // The one pane that already updates on its own, and says so. The rest
    // have nothing to be live about yet.
    const live = document.createElement("span");
    live.className = "live";
    live.id = "workspace-live";
    live.textContent = "live";
    live.hidden = true;
    head.appendChild(live);
  } else if (pane.available === false) {
    const mark = document.createElement("span");
    mark.className = "pane-pending";
    mark.textContent = "not yet";
    mark.title = pane.hint;
    head.appendChild(mark);
  }

  const body = document.createElement("div");
  body.className = "pane-body";

  const template = document.getElementById(`body-${pane.id}`);
  if (template) {
    body.appendChild(template.content.cloneNode(true));
  } else {
    body.appendChild(emptyPane(pane));
  }

  section.append(head, body);
  return section;
}

const MAXIMIZE_ICON =
  '<path d="M6 2.6H2.6v3.4"/><path d="M10 13.4h3.4V10"/>' +
  '<path d="M13.4 6V2.6H10"/><path d="M2.6 10v3.4H6"/>';
const RESTORE_ICON =
  '<path d="M2.6 6H6V2.6"/><path d="M13.4 10H10v3.4"/>' +
  '<path d="M10 2.6V6h3.4"/><path d="M6 13.4V10H2.6"/>';

function maximizeButton() {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "pane-action";
  button.id = "maximize-preview";
  button.onclick = () => togglePreviewMaximised();
  paintMaximizeButton(button, false);
  return button;
}

function paintMaximizeButton(button, maximised) {
  const label = maximised ? "Restore the application preview" : "Expand the application preview";
  button.setAttribute("aria-label", label);
  button.setAttribute("aria-pressed", String(maximised));
  button.title = maximised ? `${label} (Esc)` : label;
  button.innerHTML =
    '<svg viewBox="0 0 16 16" width="13" height="13" fill="none" ' +
    'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" ' +
    `stroke-linejoin="round" aria-hidden="true">${maximised ? RESTORE_ICON : MAXIMIZE_ICON}</svg>`;
}

/* Expanding the preview is a way of looking at something, not a preference
 * about how the interface is arranged, so it is deliberately not stored. It
 * lasts as long as the owner is looking, and a reload puts them back in the
 * room rather than in whatever they last peered at. */
function togglePreviewMaximised(force) {
  const pane = el("pane-preview");
  if (!pane) return;

  const next = force === undefined ? !pane.classList.contains("maximised") : force;
  pane.classList.toggle("maximised", next);
  document.body.classList.toggle("has-maximised-pane", next);
  paintMaximizeButton(el("maximize-preview"), next);
  if (!next) el("maximize-preview").focus();
}

function emptyPane(pane) {
  const empty = document.createElement("div");
  empty.className = "pane-empty";

  const heading = document.createElement("strong");
  heading.textContent = pane.empty_heading;
  empty.appendChild(heading);

  if (pane.empty_detail) {
    const detail = document.createElement("span");
    detail.textContent = pane.empty_detail;
    empty.appendChild(detail);
  }
  return empty;
}

function paneResizer(pane, region) {
  const vertical = region.axis === "row";
  const handle = document.createElement("div");
  handle.className = `resizer ${vertical ? "vertical" : "horizontal"}`;
  handle.id = `resize-${pane.id}`;
  handle.setAttribute("role", "separator");
  handle.setAttribute("aria-orientation", vertical ? "vertical" : "horizontal");
  handle.setAttribute("tabindex", "0");
  handle.setAttribute("aria-label", `${vertical ? "Width" : "Height"} of ${pane.label}`);
  handle.setAttribute("aria-controls", `pane-${pane.id}`);
  return handle;
}

/* ---------- lifecycle ---------- */

function renderLifecycle() {
  const list = el("stages");
  if (!list || !app.lifecycle) return;
  list.innerHTML = "";

  for (const stage of app.lifecycle.stages) {
    const item = document.createElement("li");
    item.className = `stage ${stage.state}`;
    item.title = `Reached when: ${stage.evidence}`;

    const mark = document.createElement("span");
    mark.className = "stage-mark";

    const label = document.createElement("span");
    label.className = "stage-label";
    label.textContent = stage.label;

    item.append(mark, label);
    if (stage.state === "current") item.setAttribute("aria-current", "step");
    list.appendChild(item);
  }

  const current = app.lifecycle.stages.find((s) => s.state === "current");
  const caption = el("stage-detail");
  caption.textContent = current ? current.detail : app.lifecycle.reason;
  // The evidence, for an owner who wants to know why it says that. It is not
  // in the caption because for the early stages it only restates it.
  caption.title = app.lifecycle.reason;
}

/* ---------- resizing ---------- */

/* The sizes are already applied before this file runs -- /api/interface.css
 * carries them alongside the colours. What happens here is changing them.
 *
 * A drag writes straight to the custom property, so the pane follows the
 * pointer with no re-render in between. Only the release is written down.
 * Persisting every intermediate pixel would be a request per frame to record
 * sizes the owner was moving through rather than choosing. */

function wireResizers() {
  // One rule for every divider on the screen, whatever it separates.
  //
  // A divider names the element it sizes, and the size is read off that
  // element's own edge rather than its container's -- so a column in the
  // middle of the row measures as correctly as the one at the edge.
  for (const handle of document.querySelectorAll(".resizer")) {
    const controlled = document.getElementById(handle.getAttribute("aria-controls"));
    if (!controlled) continue;

    const vertical = handle.classList.contains("vertical");
    // Most dividers sit after the thing they size, so dragging away from it
    // makes it bigger. The console's sits before it, and dragging down has
    // to make it smaller.
    const fromEnd = handle.dataset.anchor === "end";

    const token = `${controlled.dataset.pane || controlled.id}-${vertical ? "width" : "height"}`;
    const unit = (app.layout.panes[token] || {}).unit || "px";

    bindResizer(handle, {
      pane: token,
      axis: vertical ? "col" : "row",
      fromEnd,
      unit,
      measure: (event) => {
        const box = controlled.getBoundingClientRect();
        const pixels = vertical
          ? (fromEnd ? box.right - event.clientX : event.clientX - box.left)
          : (fromEnd ? box.bottom - event.clientY : event.clientY - box.top);
        if (unit !== "%") return pixels;

        // A share is measured against whatever the pane is a share of -- the
        // row of columns for a column, the activity row for Tasks -- so the
        // same drag means the same proportion on any size of screen.
        const whole = controlled.parentElement.getBoundingClientRect();
        const against = vertical ? whole.width : whole.height;
        return against ? (pixels / against) * 100 : 0;
      },
    });
  }
}

function bindResizer(handle, { pane, axis, measure, fromEnd = false, unit = "px" }) {
  const bounds = app.layout.panes[pane];

  handle.dataset.pane = pane;
  handle.setAttribute("aria-valuemin", bounds.min);
  handle.setAttribute("aria-valuemax", bounds.max);
  handle.setAttribute("aria-valuenow", app.layout.sizes[pane]);
  if (unit === "%") handle.setAttribute("aria-valuetext", `${app.layout.sizes[pane]}%`);

  // Whole pixels, but tenths of a percent: one percent of a wide window is
  // fifteen pixels, and a drag that can only land on whole percents does not
  // feel like a drag. The server rounds to the same places.
  const round = (value) => (unit === "%" ? Math.round(value * 10) / 10 : Math.round(value));
  const clamp = (value) => round(Math.max(bounds.min, Math.min(bounds.max, value)));

  // A splitter that reports its position only when the drag ends is a
  // splitter nobody driving it by keyboard can follow.
  const apply = (value) => {
    document.documentElement.style.setProperty(`--${pane}`, `${value}${unit}`);
    handle.setAttribute("aria-valuenow", value);
    if (unit === "%") handle.setAttribute("aria-valuetext", `${value}%`);
  };

  handle.addEventListener("pointerdown", (event) => {
    // Ignore anything but a plain primary-button drag.
    if (event.button !== 0) return;
    event.preventDefault();

    let size = clamp(measure(event));
    handle.setPointerCapture(event.pointerId);
    handle.classList.add("dragging");
    document.body.classList.add("resizing", axis);

    const onMove = (moveEvent) => {
      size = clamp(measure(moveEvent));
      apply(size);
    };

    const onUp = () => {
      handle.removeEventListener("pointermove", onMove);
      handle.removeEventListener("pointerup", onUp);
      handle.removeEventListener("pointercancel", onUp);
      handle.classList.remove("dragging");
      document.body.classList.remove("resizing", axis);
      saveLayout({ ...app.layout.sizes, [pane]: size });
    };

    handle.addEventListener("pointermove", onMove);
    handle.addEventListener("pointerup", onUp);
    handle.addEventListener("pointercancel", onUp);
  });

  // Double-clicking a divider resets that one pane. Every editor does this,
  // and it saves reaching for the general reset to undo one mistake.
  handle.addEventListener("dblclick", () => {
    const sizes = { ...app.layout.sizes };
    delete sizes[pane];
    saveLayout(sizes);
  });

  // Reachable without a pointer. The arrow keys nudge, as they do on any
  // separator that claims the role.
  handle.addEventListener("keydown", (event) => {
    const step = unit === "%" ? (event.shiftKey ? 5 : 1) : (event.shiftKey ? 40 : 10);
    const forward = axis === "col" ? "ArrowRight" : "ArrowDown";
    const back = axis === "col" ? "ArrowLeft" : "ArrowUp";
    if (event.key !== forward && event.key !== back) return;
    event.preventDefault();
    // The key moves the divider, not the number. On a pane anchored to the
    // far edge, moving the divider forward makes it smaller -- pressing Down
    // on the console must lower the console, not raise it.
    const towards = event.key === forward ? 1 : -1;
    const current = app.layout.sizes[pane];
    saveLayout({
      ...app.layout.sizes,
      [pane]: clamp(current + step * towards * (fromEnd ? -1 : 1)),
    });
  });
}

async function saveLayout(sizes) {
  app.layout = await api("/api/layout", {
    method: "PATCH",
    body: JSON.stringify({ sizes }),
  });
  applyLayout();
  renderResetView();
}

function applyLayout() {
  for (const [pane, size] of Object.entries(app.layout.sizes)) {
    const unit = (app.layout.panes[pane] || {}).unit || "px";
    document.documentElement.style.setProperty(`--${pane}`, `${size}${unit}`);
    const handle = document.querySelector(`.resizer[aria-controls][data-pane="${pane}"]`);
    if (handle) {
      handle.setAttribute("aria-valuenow", size);
      if (unit === "%") handle.setAttribute("aria-valuetext", `${size}%`);
    }
  }
}

function renderResetView() {
  el("reset-view").hidden = app.layout.is_default;
}

async function resetView() {
  // Storing nothing rather than storing the defaults back: the view then
  // means "whatever the defaults are", not "whatever they were the day this
  // was reset".
  await saveLayout({});
}

/* ---------- appearance ---------- */

/* The scheme is already on screen before this file runs -- /api/interface.css
 * saw to that. What happens here is editing it: every change is shown immediately
 * on the real interface rather than in a preview swatch, because the only
 * useful question about a colour scheme is what it looks like to work in. */

function applyColors(colors) {
  for (const [token, value] of Object.entries(colors)) {
    document.documentElement.style.setProperty(`--${token}`, value);
  }
}

function renderAppearance() {
  const { preset, presets, groups, colors, overrides } = app.appearance;

  const presetBox = el("presets");
  presetBox.innerHTML = "";
  for (const option of presets) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "preset" + (option.id === preset ? " on" : "");

    const swatches = document.createElement("div");
    swatches.className = "preset-swatches";
    for (const colour of option.swatches) {
      const band = document.createElement("span");
      band.style.background = colour;
      swatches.appendChild(band);
    }

    const label = document.createElement("div");
    label.className = "preset-label";
    const name = document.createElement("span");
    name.className = "preset-name";
    name.textContent = option.label;
    const kind = document.createElement("span");
    kind.className = "preset-kind";
    kind.textContent = option.dark ? "dark" : "light";
    label.append(name, kind);

    const note = document.createElement("p");
    note.className = "preset-note";
    note.textContent = option.note;

    card.append(swatches, label, note);
    card.onclick = () => choosePreset(option.id);
    presetBox.appendChild(card);
  }

  const groupBox = el("token-groups");
  groupBox.innerHTML = "";
  for (const group of groups) {
    const section = document.createElement("div");
    section.className = "token-group";

    const heading = document.createElement("h3");
    heading.textContent = group.label;
    const hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent = group.hint;

    const tokens = document.createElement("div");
    tokens.className = "tokens";
    for (const token of group.tokens) {
      tokens.appendChild(tokenRow(token, colors[token.name], token.name in overrides));
    }

    section.append(heading, hint, tokens);
    groupBox.appendChild(section);
  }

  const changed = Object.keys(overrides).length;
  const label = (presets.find((p) => p.id === preset) || {}).label || preset;
  el("appearance-note").textContent = changed
    ? `${changed} colour${changed === 1 ? "" : "s"} changed from ${label}.`
    : `Unchanged from ${label}.`;
  el("reset-appearance").disabled = changed === 0;
}

function tokenRow(token, value, edited) {
  const row = document.createElement("div");
  row.className = "token" + (edited ? " edited" : "");

  const picker = document.createElement("input");
  picker.type = "color";
  picker.value = expandHex(value);
  picker.title = token.label;

  const text = document.createElement("div");
  text.className = "token-text";
  const label = document.createElement("div");
  label.className = "token-label";
  label.textContent = token.label;
  const hex = document.createElement("div");
  hex.className = "token-hex";
  hex.textContent = value;
  text.append(label, hex);

  const revert = document.createElement("button");
  revert.type = "button";
  revert.className = "token-revert";
  revert.textContent = "×";
  revert.title = "Back to the preset's colour";
  revert.onclick = () => setOverride(token.name, null);

  picker.addEventListener("input", () => {
    // Paint first, persist after. Dragging a colour picker fires constantly,
    // and the owner should see the interface follow their thumb rather than
    // wait on a round trip for every intermediate shade.
    document.documentElement.style.setProperty(`--${token.name}`, picker.value);
    hex.textContent = picker.value;
    row.classList.add("edited");
    setOverride(token.name, picker.value, { debounce: true });
  });

  row.append(picker, text, revert);
  return row;
}

function expandHex(value) {
  // <input type="color"> only understands the six-digit form.
  if (/^#[0-9a-fA-F]{3}$/.test(value)) {
    return "#" + value.slice(1).split("").map((c) => c + c).join("");
  }
  return value;
}

async function choosePreset(presetId) {
  // Overrides are deliberately kept. Someone who set their accent to a
  // particular green meant it, and should not lose it for trying a preset on.
  app.appearance = await api("/api/appearance", {
    method: "PATCH",
    body: JSON.stringify({ preset: presetId }),
  });
  applyColors(app.appearance.colors);
  renderAppearance();
}

function setOverride(token, value, { debounce = false } = {}) {
  const overrides = { ...app.appearance.overrides };
  if (value === null) delete overrides[token];
  else overrides[token] = value;

  const commit = async () => {
    app.appearance = await api("/api/appearance", {
      method: "PATCH",
      body: JSON.stringify({ overrides }),
    });
    applyColors(app.appearance.colors);
    renderAppearance();
  };

  clearTimeout(app.appearanceTimer);
  if (debounce) app.appearanceTimer = setTimeout(commit, 300);
  else commit();
}

async function resetAppearance() {
  app.appearance = await api("/api/appearance", {
    method: "PATCH",
    body: JSON.stringify({ overrides: {} }),
  });
  applyColors(app.appearance.colors);
  renderAppearance();
}

/* ---------- workspace ---------- */

/* The Living Workspace is the Resident's territory. The owner should be able to
 * watch it change rather than take the Resident's word for what it did -- which
 * is the same instinct the autonomous repair loop will later depend on.
 *
 * It is empty until Milestone 2 gives the Resident the ability to act.
 */

function startWorkspaceWatch() {
  if (app.workspaceTimer) return;
  loadPreview();
  loadWorkspace();
  app.workspaceTimer = setInterval(loadWorkspace, 2000);
  el("workspace-live").hidden = false;
}

function stopWorkspaceWatch() {
  clearInterval(app.workspaceTimer);
  app.workspaceTimer = null;
  el("workspace-live").hidden = true;
}

async function loadPreview() {
  const inner = el("preview-inner");
  let preview;
  try {
    preview = await api("/api/preview");
  } catch (_) {
    return;
  }

  inner.innerHTML = "";
  if (preview.available && preview.url) {
    const frame = document.createElement("iframe");
    frame.src = preview.url;
    frame.title = "Application preview";
    inner.appendChild(frame);
    return;
  }

  const empty = document.createElement("div");
  empty.className = "preview-empty";
  const detail = document.createElement("strong");
  detail.textContent = preview.detail;
  const hint = document.createElement("span");
  hint.textContent = preview.hint || "";
  empty.append(detail, hint);
  inner.appendChild(empty);
}

async function loadWorkspace(path) {
  if (path !== undefined) {
    app.workspacePath = path;
    app.workspaceSignature = null;
  }

  let data;
  try {
    data = await api(`/api/workspace?path=${encodeURIComponent(app.workspacePath)}`);
  } catch (_) {
    // The directory was probably removed underneath us. Fall back to the root.
    if (app.workspacePath) loadWorkspace("");
    return;
  }

  // Polling redraws would fight with the owner's scroll position, so redraw
  // only when something actually changed.
  const signature = JSON.stringify(data);
  if (signature === app.workspaceSignature) return;
  app.workspaceSignature = signature;
  app.workspace = data;
  renderWorkspace();

  // The workspace changing is the only evidence that can currently move the
  // application's stage, so this is the moment to ask again -- and the only
  // moment worth asking. A lifecycle that updates on reload would show the
  // owner a stale stage for exactly as long as they were watching.
  refreshLifecycle();
}

async function refreshLifecycle() {
  try {
    app.lifecycle = await api("/api/lifecycle");
  } catch (_) {
    return;  // the server will be back; the stage on screen is still the last true one
  }
  renderLifecycle();
}

function renderWorkspace() {
  const data = app.workspace;
  const crumbs = el("crumbs");
  crumbs.innerHTML = "";
  const segments = data.path ? data.path.split("/") : [];

  crumbs.appendChild(crumb("workspace", "", segments.length === 0));
  let walked = "";
  segments.forEach((segment, index) => {
    walked = walked ? `${walked}/${segment}` : segment;
    const separator = document.createElement("span");
    separator.className = "crumb-sep";
    separator.textContent = "/";
    crumbs.appendChild(separator);
    crumbs.appendChild(crumb(segment, walked, index === segments.length - 1));
  });

  const files = el("files");
  files.innerHTML = "";

  if (!data.entries.length) {
    const empty = document.createElement("div");
    empty.className = "files-empty";
    empty.innerHTML =
      "<strong>Nothing here yet.</strong>" +
      "Your Resident cannot create files until it is given tools and the " +
      "ability to act.";
    files.appendChild(empty);
    return;
  }

  if (data.parent !== null) {
    files.appendChild(fileRow({ name: "..", type: "directory" }, data.parent));
  }
  for (const entry of data.entries) {
    const next = data.path ? `${data.path}/${entry.name}` : entry.name;
    files.appendChild(fileRow(entry, entry.type === "directory" ? next : null));
  }
}

function crumb(label, path, isCurrent) {
  const node = document.createElement("button");
  node.type = "button";
  node.className = "crumb" + (isCurrent ? " current" : "");
  node.textContent = label;
  node.onclick = () => loadWorkspace(path);
  return node;
}

/* File-type icons.
 *
 * Colour carries the type, shape carries the category. Recognising a Python
 * file at a glance is the difference between reading a listing and scanning
 * one, and the Resident's output deserves to be scannable.
 */

const ICON_SHAPES = {
  folder:
    '<path d="M1.8 12.6V4.4a1 1 0 0 1 1-1h3.3l1.4 1.8h5.7a1 1 0 0 1 1 1v6.4a1 1 0 0 1-1 1H2.8a1 1 0 0 1-1-1z"/>',
  up: '<path d="M8 12.6V4.3"/><path d="M4.4 7.9 8 4.3l3.6 3.6"/>',
  page:
    '<path d="M4 1.9h4.7l3.4 3.4v8.8a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V2.9a1 1 0 0 1 1-1z"/>' +
    '<path d="M8.5 2v3.4h3.4"/>',
  braces:
    '<path d="M6.4 2.6c-1.5 0-1.7 1-1.7 2.4s-.2 2.7-1.4 3.1c1.2.4 1.4 1.6 1.4 3s.2 2.4 1.7 2.4"/>' +
    '<path d="M9.6 2.6c1.5 0 1.7 1 1.7 2.4s.2 2.7 1.4 3.1c-1.2.4-1.4 1.6-1.4 3s-.2 2.4-1.7 2.4"/>',
  angle: '<path d="M6.1 4.4 2.6 8l3.5 3.6"/><path d="M9.9 4.4 13.4 8l-3.5 3.6"/>',
  database:
    '<ellipse cx="8" cy="4.1" rx="4.9" ry="2.1"/>' +
    '<path d="M3.1 4.1v7.8c0 1.2 2.2 2.1 4.9 2.1s4.9-.9 4.9-2.1V4.1"/>' +
    '<path d="M3.1 8c0 1.2 2.2 2.1 4.9 2.1s4.9-.9 4.9-2.1"/>',
  image:
    '<rect x="2.4" y="3.4" width="11.2" height="9.2" rx="1.2"/>' +
    '<circle cx="6" cy="6.7" r="1"/><path d="M2.9 11.9 6.4 8.6l2.4 2 2.1-1.7 2.2 2"/>',
  terminal:
    '<rect x="2" y="3" width="12" height="10" rx="1.4"/>' +
    '<path d="M4.9 6.6 7 8.6l-2.1 2"/><path d="M8.6 11.1h3"/>',
};

/* File icons borrow the syntax palette rather than carrying colours of their
 * own -- a Python file in the listing is the colour Python is in a code block.
 * The token is named in a style attribute rather than resolved here, so the
 * icons follow a theme change without anything having to redraw them. */
const FILE_TYPES = [
  { match: /\.(py|pyw|pyi)$/i, shape: "page", token: "--t-fn" },
  { match: /\.(js|mjs|cjs|ts|jsx|tsx)$/i, shape: "page", token: "--t-decorator" },
  { match: /\.(json|ya?ml|toml|ini|cfg|env|lock)$/i, shape: "braces", token: "--t-number" },
  { match: /\.(png|jpe?g|gif|webp|ico|bmp|svg)$/i, shape: "image", token: "--t-builtin" },
  { match: /\.(html?|xml|vue)$/i, shape: "angle", token: "--t-tag" },
  { match: /\.(css|scss|sass|less)$/i, shape: "page", token: "--t-builtin" },
  { match: /\.(md|markdown|txt|rst)$/i, shape: "page", token: "--t-string" },
  { match: /\.(db|sqlite3?|sql)$/i, shape: "database", token: "--t-keyword" },
  { match: /\.(sh|bash|zsh|ps1|bat|cmd)$/i, shape: "terminal", token: "--t-string" },
];

const ICON_NEUTRAL = "--muted";

function iconSvg(shape, token) {
  return (
    '<svg viewBox="0 0 16 16" width="15" height="15" fill="none" ' +
    `style="stroke: var(${token})" ` +
    'stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round">' +
    `${shape}</svg>`
  );
}

function fileIcon(entry) {
  if (entry.name === "..") return iconSvg(ICON_SHAPES.up, ICON_NEUTRAL);
  if (entry.type === "directory") return iconSvg(ICON_SHAPES.folder, "--t-decorator");
  const type = FILE_TYPES.find((candidate) => candidate.match.test(entry.name));
  return iconSvg(
    ICON_SHAPES[type ? type.shape : "page"],
    type ? type.token : ICON_NEUTRAL
  );
}

function fileRow(entry, navigateTo) {
  const row = document.createElement("div");
  row.className = `file ${entry.type}` + (navigateTo !== null ? " navigable" : "");

  const icon = document.createElement("span");
  icon.className = "file-icon";
  icon.innerHTML = fileIcon(entry);

  const name = document.createElement("span");
  name.className = "file-name";
  name.textContent = entry.name;

  const size = document.createElement("span");
  size.className = "file-size";
  size.textContent = entry.size === null || entry.size === undefined ? "" : formatSize(entry.size);

  const modified = document.createElement("span");
  modified.className = "file-modified";
  modified.textContent = entry.modified ? entry.modified.replace("T", " ") : "";

  row.append(icon, name, size, modified);
  if (navigateTo !== null) row.onclick = () => loadWorkspace(navigateTo);
  return row;
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/* ---------- events ---------- */

function wireEvents() {
  for (const tab of document.querySelectorAll(".viewtab")) {
    tab.onclick = () => {
      for (const other of document.querySelectorAll(".viewtab")) {
        other.classList.toggle("active", other === tab);
      }
      for (const view of document.querySelectorAll(".view")) {
        view.classList.toggle("active", view.id === `view-${tab.dataset.view}`);
      }
      // Only watch the workspace while the owner is looking at it.
      if (tab.dataset.view === "home") startWorkspaceWatch();
      else stopWorkspaceWatch();
    };
  }

  // Copy buttons are created by the markdown renderer, so they are handled by
  // delegation rather than wired up per code block.
  el("messages").addEventListener("click", async (event) => {
    const button = event.target.closest(".code-copy");
    if (!button) return;
    const code = button.closest(".code").querySelector("code");
    try {
      await navigator.clipboard.writeText(code.textContent);
      button.textContent = "Copied";
    } catch (_) {
      button.textContent = "Copy failed";
    }
    setTimeout(() => { button.textContent = "Copy"; }, 1500);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (!document.body.classList.contains("has-maximised-pane")) return;
    event.preventDefault();
    togglePreviewMaximised(false);
  });

  const input = el("input");
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 200)}px`;
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      el("composer").requestSubmit();
    }
  });

  el("composer").onsubmit = (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text || app.streaming) return;
    input.value = "";
    input.style.height = "auto";
    send(text);
  };

  el("save-resident").onclick = async () => {
    const body = {
      system_prompt: el("system-prompt").value,
    };
    const chosen = el("primary-select").value;
    if (chosen) body.primary_connection_id = chosen;
    // Sent even when empty -- that is how the assignment is cleared.
    body.worker_connection_id = el("worker-select").value;
    await api("/api/resident", { method: "PATCH", body: JSON.stringify(body) });
    await refresh();
    const saved = el("resident-saved");
    saved.textContent = "Saved";
    setTimeout(() => { saved.textContent = ""; }, 2000);
  };

  el("reset-appearance").onclick = resetAppearance;
  el("reset-view").onclick = resetView;

  el("add-connection").onclick = () => openForm(null);
  el("conn-cancel").onclick = closeForm;

  el("conn-form").onsubmit = async (event) => {
    event.preventDefault();
    const error = el("conn-error");
    error.textContent = "";

    const payload = {
      name: el("conn-name").value.trim(),
      provider: el("conn-provider").value,
      model: el("conn-model").value.trim(),
      base_url: el("conn-base-url").value.trim() || null,
      tags: [...app.editingTags],
      credential: el("conn-credential").value || null,
    };

    if (!payload.name || !payload.model) {
      error.textContent = "A name and a model identifier are required.";
      return;
    }

    const id = el("conn-id").value;
    try {
      if (id) {
        await api(`/api/connections/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
      } else {
        await api("/api/connections", { method: "POST", body: JSON.stringify(payload) });
      }
      closeForm();
      await refresh();
    } catch (err) {
      error.textContent = err.message;
    }
  };
}

boot();
