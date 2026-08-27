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
  app.meta = await api("/api/meta");
  el("home-note").textContent = `This Aworg lives at ${app.meta.home}`;
  buildProviderOptions();
  buildTagChips();
  await refresh();
  wireEvents();
}

async function refresh() {
  const [state, connections, conversation] = await Promise.all([
    api("/api/state"),
    api("/api/connections"),
    api("/api/conversation"),
  ]);
  app.state = state;
  app.connections = connections;
  app.conversation = conversation;
  renderStatus();
  renderChat();
  renderSettings();
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
}

function renderWorkspace() {
  const data = app.workspace;
  el("workspace-path").textContent = data.root;

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

function fileRow(entry, navigateTo) {
  const row = document.createElement("div");
  row.className = `file ${entry.type}` + (navigateTo !== null ? " navigable" : "");

  const icon = document.createElement("span");
  icon.className = "file-icon";
  icon.textContent = entry.type === "directory" ? "▸" : "·";

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
      if (tab.dataset.view === "workspace") startWorkspaceWatch();
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

  el("new-conversation").onclick = async () => {
    if (app.streaming) return;
    if (app.conversation.messages.length &&
        !confirm("Start a new conversation? The Resident will not carry this one forward.")) return;
    app.conversation = await api("/api/conversation/new", { method: "POST" });
    renderChat();
  };

  el("save-resident").onclick = async () => {
    const body = {
      system_prompt: el("system-prompt").value,
    };
    const chosen = el("primary-select").value;
    if (chosen) body.primary_connection_id = chosen;
    await api("/api/resident", { method: "PATCH", body: JSON.stringify(body) });
    await refresh();
    const saved = el("resident-saved");
    saved.textContent = "Saved";
    setTimeout(() => { saved.textContent = ""; }, 2000);
  };

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
