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
  //: What each polled pane last held, so a repaint only happens when
  //: something actually changed -- these panes carry scroll positions and
  //: switches the owner may be reaching for.
  paneSignatures: {},
  lifecycle: null,
  // The last answer from /api/context, plus what has been added since: the
  // draft in the composer and the reply as it streams in. The ring is exact
  // right after a fetch and drifts to an estimate in between, and says so.
  context: null,
  contextDraft: 0,
  contextStreamed: 0,
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
  const [meta, panes, layout, personas] = await Promise.all([
    api("/api/meta"),
    api("/api/panes"),
    api("/api/layout"),
    api("/api/personas"),
  ]);
  app.meta = meta;
  app.panes = panes;
  app.layout = layout;
  setPersonas(personas);

  el("home-note").textContent = `This Aworg lives at ${app.meta.home}`;
  buildProviderOptions();
  buildTagChips();
  buildSettingsNav();

  // The column is assembled before anything reaches into it -- the preview,
  // the workspace listing and every resizer address elements that only exist
  // once the panes have been built.
  buildPanes();
  wireResizers();
  // The Workers pane ages its own rows out, so it needs a heartbeat rather
  // than only repainting when something happens -- otherwise the last
  // finished worker would sit there until the next unrelated event.
  setInterval(paintWorkers, 2000);
  wireReset();

  await refresh();
  wireEvents();
  // If a reply was in flight when the page went away, pick it back up.
  resumeReply();
  // Home is where the owner lands, and the workspace is part of it.
  startWorkspaceWatch();
  // Not awaited: it holds a connection open for the life of the page, and
  // waiting on it would mean boot never finishing.
  startActivities();
  startLivingLog();
  startPanes();
  watchPreviewSize();
}

/* Keep the status panes current.
 *
 * /api/panes was fetched once at boot and then only when the owner toggled a
 * skill, a worker or a capability. So the Tasks pane showed whatever the plan
 * was at the moment the page loaded -- which is to say "No plan yet", for the
 * whole of the first job, while the Resident wrote eight tasks and worked
 * through them. Skills had the same silence: getting-started never visibly
 * retired when a plan appeared.
 *
 * Activities streams, the Living Log polls, the workspace polls. These had
 * neither, and they are the panes that answer what the Resident is *for*.
 *
 * Repainted only where something actually changed, because these panes hold
 * scroll positions and switches the owner may be reaching for. */
const PANES_EVERY = 2500;

//: Panes painted from the /api/panes payload. The others -- Activities,
//: Workers, the preview, the workspace -- draw themselves from their own
//: live sources and must not be repainted from a snapshot.
const POLLED_PANES = ["tasks", "skills", "capabilities", "environment"];

async function startPanes() {
  setInterval(refreshPanes, PANES_EVERY);
}

async function refreshPanes() {
  let panes;
  try {
    panes = await api("/api/panes");
  } catch (_) {
    // A failed poll leaves the last good picture up, which is truer than
    // blanking a pane because one request did not land.
    return;
  }
  const byId = new Map(panes.map((pane) => [pane.id, pane]));
  for (const id of POLLED_PANES) {
    const fresh = byId.get(id);
    if (!fresh) continue;
    const signature = JSON.stringify(fresh.items || []);
    if (signature === app.paneSignatures[id]) continue;
    app.paneSignatures[id] = signature;
    const at = app.panes.findIndex((pane) => pane.id === id);
    if (at >= 0) app.panes[at] = fresh;
    repaintPane(id);
  }
}

/* Re-fit the miniature whenever the pane's size changes.
 *
 * A ResizeObserver rather than a resize listener, because the three things
 * that change this size are the window, a dragged divider, and expanding the
 * preview -- and only the first of those fires a window event. */
function watchPreviewSize() {
  const inner = el("preview-inner");
  if (!inner || typeof ResizeObserver === "undefined") return;
  new ResizeObserver(() => fitPreview()).observe(inner);
}

/* Who the Resident is, as far as the interface is concerned.
 *
 * Held apart from the list because every message asks for it and almost
 * nothing asks for the list. The colours and the background are already in
 * the stylesheet by the time this runs -- they load before first paint, so
 * the chat is the Resident's room from the very first frame rather than
 * becoming it a moment later. What is left for here is the avatar, which
 * belongs to messages rather than to the surface. */
function setPersonas(payload) {
  app.personas = payload.personas || [];
  app.persona =
    app.personas.find((p) => p.name === payload.active) || null;
  paintPersonas();
}

/* The picker: who your Resident could be.
 *
 * Shown as cards rather than a dropdown, because a persona is chosen by
 * reading what it is like. A name in a select list tells an owner nothing
 * about whether they want to talk to it. */
function paintPersonas() {
  const host = el("persona-list");
  if (!host) return;
  host.innerHTML = "";

  for (const persona of app.personas) {
    const active = app.persona && app.persona.name === persona.name;
    const card = document.createElement("button");
    card.type = "button";
    card.className = `persona-card${active ? " active" : ""}`;
    card.setAttribute("aria-pressed", String(!!active));
    card.onclick = () => wearPersona(persona.name);

    if (persona.has_avatar) {
      const face = document.createElement("img");
      face.className = "persona-face";
      face.src = `/api/personas/${encodeURIComponent(persona.name)}/avatar`;
      face.alt = "";
      card.appendChild(face);
    }

    const text = document.createElement("span");
    text.className = "persona-text";

    const name = document.createElement("strong");
    name.textContent = persona.name;
    const detail = document.createElement("span");
    detail.textContent = persona.description || "";
    text.append(name, detail);
    card.appendChild(text);

    // The accent is the one thing about a persona you cannot read, so it is
    // shown rather than described.
    if (persona.accent) {
      const swatch = document.createElement("span");
      swatch.className = "persona-accent";
      swatch.style.background = persona.accent;
      swatch.title = `Chat accent ${persona.accent}`;
      card.appendChild(swatch);
    }
    host.appendChild(card);
  }
}

async function wearPersona(name) {
  try {
    await api("/api/personas", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
  } catch (error) {
    return;
  }
  setPersonas(await api("/api/personas"));
  // The colours and any background live in the stylesheet, which was fetched
  // once at load. Re-fetching it is what makes the change visible now rather
  // than at the next reload -- and it is a whole stylesheet swap rather than
  // patched properties so that the old persona's room leaves nothing behind.
  reloadInterfaceCss();
  // Already-drawn replies were painted with the previous face.
  renderChat();
}

/* Swap the stylesheet that carries the owner's colours and the persona's
 * room. Cache-busted, because it is served no-store but a browser that has
 * it in memory for this page will not ask again on its own. */
function reloadInterfaceCss() {
  const link = document.querySelector('link[href^="/api/interface.css"]');
  if (!link) return;
  link.href = `/api/interface.css?v=${Date.now()}`;
}

/* Keep the Living Log current.
 *
 * Polled rather than streamed, and the reason is the entry that matters
 * most. A program dying on its own produces no Activity event at all --
 * nothing started, nothing failed, a pipe simply closed -- so a Living Log
 * that only woke when the Activity stream did would be deaf to exactly the
 * thing it exists to report. Something has to ask.
 *
 * Slowly, because this is the pane about what happened rather than what is
 * happening. Twenty seconds is far too slow for Activities and about right
 * here, and it is one small query against a table capped at a few hundred
 * rows. */
const LIVING_LOG_EVERY = 20000;

async function startLivingLog() {
  await refreshLivingLog();
  setInterval(refreshLivingLog, LIVING_LOG_EVERY);
}

/* Ask again shortly, however many times you are told to.
 *
 * A busy turn ends twenty tool calls in a second or two. Refreshing on each
 * would be twenty requests for one answer, so they collapse into one that
 * lands just after the last of them -- and after the follower on the server
 * has had a moment to write anything down, which is the reason for the delay
 * rather than firing immediately. */
let livingLogSoon = null;

function nudgeLivingLog() {
  if (livingLogSoon) clearTimeout(livingLogSoon);
  livingLogSoon = setTimeout(() => {
    livingLogSoon = null;
    refreshLivingLog();
  }, 600);
}

async function refreshLivingLog() {
  let entries;
  try {
    ({ entries } = await api("/api/journal"));
  } catch (_) {
    // A failed poll leaves the last good picture up. An empty pane would
    // claim nothing has happened, which is a different and untrue thing.
    return;
  }
  const pane = app.panes.find((candidate) => candidate.id === "log");
  if (!pane) return;
  pane.items = entries.map((entry) => ({
    kind: "entry",
    id: String(entry.id),
    level: entry.level || "note",
    category: entry.kind || "aworg",
    source: entry.source || "aworg",
    name: entry.summary || "",
    detail: entry.detail || "",
    at: entry.at || "",
    activity_id: entry.activity_id,
    open: !entry.resolved && ["concern", "alarm"].includes(entry.level),
    resolution: entry.resolution || "",
    resolved_by: entry.resolved_by || "",
  }));

  // Not while somebody is writing in it.
  //
  // The repaint rebuilds every row, so it takes any open resolver -- and the
  // account half-typed in it -- with it. This pane refreshes on a twenty
  // second timer and again after every busy turn, and saying properly what
  // happened to a concern takes longer than twenty seconds, which made the
  // box a trap: type a real account, lose it, learn to type "fixed".
  //
  // The held-back picture is a few seconds of history, and history is the
  // one thing that does not go stale. It lands the moment the box closes,
  // which refreshLivingLog is called again for.
  if (document.querySelector(".log-resolver")) return;

  repaintPane("log");
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
  refreshContext();
  renderLifecycle();
  renderProject();
}

/* A failed turn leaves the owner's message with no answer under it. Putting
 * the text back in the composer is the whole of the fix -- retyping it is
 * the sort of small insult that makes an interface tiring. */
function offerRetry(text) {
  const box = el("messages");
  const old = document.getElementById("retry-offer");
  if (old) old.remove();

  const wrap = document.createElement("div");
  wrap.className = "retry";
  wrap.id = "retry-offer";
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "Put that back in the box";
  button.onclick = () => {
    const input = el("input");
    input.value = text;
    wrap.remove();
    fitComposer();
    app.contextDraft = estimateTokens(text);
    renderContext();
    input.focus();
  };
  wrap.appendChild(button);
  box.appendChild(wrap);
}

/* ---------- context window ---------- */

/* The ring is refreshed from the server whenever the conversation actually
 * changes, because only the model's server can count exactly. Between
 * refreshes it moves on an estimate -- the draft as it is typed, the reply
 * as it streams -- so it is never frozen at a number that is already wrong,
 * and it is drawn lighter while it is guessing. */

async function refreshContext() {
  try {
    app.context = await api("/api/context");
  } catch (_) {
    app.context = null;
  }
  app.contextDraft = 0;
  app.contextStreamed = 0;
  renderContext();
}

function estimateTokens(text) {
  const per = (app.context && app.context.chars_per_token) || 3.6;
  return Math.round(text.length / per);
}

function renderContext() {
  const ring = el("context");
  const info = app.context;
  if (!info) { ring.hidden = true; return; }
  ring.hidden = false;

  const added = app.contextDraft + app.contextStreamed;
  const tokens = info.tokens + added;
  const exact = info.exact && added === 0;
  const limit = info.window;
  const pct = limit ? Math.min(100, (100 * tokens) / limit) : null;

  ring.classList.toggle("estimate", !exact);
  ring.classList.toggle("warn", pct !== null && pct >= 75 && pct < 92);
  ring.classList.toggle("full", (pct !== null && pct >= 92) || info.dropped > 0);

  // The conversation has outgrown the window: the chat says so as a whole,
  // and a marker in the list says where the Resident's memory now starts.
  document.querySelector(".chat").classList.toggle("truncating", info.dropped > 0);
  markTruncation(info);
  el("context-fill").setAttribute("stroke-dasharray", pct === null ? "0 100" : pct.toFixed(1) + " 100");

  const compact = tokens >= 10000 ? Math.round(tokens / 1000) + "k"
    : tokens >= 1000 ? (tokens / 1000).toFixed(1) + "k" : String(tokens);
  el("context-pct").textContent = pct === null ? compact : Math.round(pct) + "%";
  ring.setAttribute("aria-valuenow", pct === null ? 0 : Math.round(pct));

  renderComposerLimit();

  const how = exact ? "exact" : "estimated";
  const cut = info.dropped
    ? `\n${info.dropped} older ${info.dropped === 1 ? "message is" : "messages are"} `
      + `no longer sent (${info.stored} kept on disk)`
    : "";
  const fmt = (n) => n.toLocaleString();
  ring.title = limit
    ? fmt(tokens) + " of " + fmt(limit) + " tokens (" + pct.toFixed(1) + "%) - " + how
      + "\n" + info.messages + " messages in context" + cut
    : fmt(tokens) + " tokens - " + how + "\nContext window unknown - set it on the connection";
}

/* Where the Resident's memory begins.
 *
 * A border on the chat says the conversation is being truncated; it does not
 * say which part. This marks the seam in the list itself, so the owner can
 * see exactly what is no longer being sent -- and that it is still there to
 * scroll back to, because nothing was deleted. */
function markTruncation(info) {
  const existing = document.getElementById("truncation-mark");
  if (existing) existing.remove();
  const dropped = (info && info.dropped) || 0;
  if (!dropped) return;

  const box = el("messages");
  // The boundary is a message, not a position. Counting dropped rows into a
  // list of rendered nodes puts the seam in the wrong place, because a tool
  // exchange is two stored rows and one thing on screen.
  const first = info.visible_from != null
    ? box.querySelector(`[data-mid="${info.visible_from}"]`)
    : null;
  if (!first) return;

  const mark = document.createElement("div");
  mark.className = "truncation";
  mark.id = "truncation-mark";
  mark.innerHTML =
    "<span></span><strong>The Resident's memory starts here</strong>"
    + `<span title="Everything above is still saved, and still yours to read.">`
    + `${dropped} earlier ${dropped === 1 ? "message" : "messages"} no longer sent</span>`;
  box.insertBefore(mark, first);
}

/* Grow the box to the text, but never past the room there is for it.
 *
 * The ceiling is not a number someone chose: it is what is actually
 * available once the conversation still has somewhere to be. A
 * viewport-relative cap cannot know that -- the chat is one pane among
 * several and is routinely far shorter than the window -- which is how a
 * 60vh rule produced a 516px composer inside a 308px chat, squeezing the
 * messages to 26 pixels and pushing the composer's own warning off the
 * bottom of the screen. */
function fitComposer() {
  const input = el("input");
  const chat = document.querySelector(".chat");
  input.style.height = "auto";
  const ceiling = chat && chat.clientHeight
    ? Math.max(120, chat.clientHeight * 0.6)
    : Infinity;
  input.style.height = `${Math.min(input.scrollHeight, ceiling)}px`;
}

/* The guard on the composer.
 *
 * Truncation means a long message is not dangerous -- it pushes older ones
 * out of view and the conversation carries on. The one thing that cannot be
 * rescued is a single message larger than the budget itself: no amount of
 * dropping history makes room for it, and the provider refuses the turn
 * outright. That is the only thing worth stopping, and it is worth stopping
 * before it is typed rather than after it is sent.
 *
 * It will not fire for most people. It is here for a small window on a
 * budget model, where a pasted file is over the line in one keystroke. */

function maxDraftChars() {
  const info = app.context;
  if (!info || !info.max_message_chars) return null;   // no window, no edge
  return info.max_message_chars;
}

function renderComposerLimit() {
  const input = el("input");
  const box = document.querySelector(".composer-box");
  const limit = maxDraftChars();
  const note = el("composer-note");
  if (!limit) {
    box.classList.remove("at-limit");
    note.hidden = true;
    return;
  }
  const over = input.value.length >= limit;
  box.classList.toggle("at-limit", over);
  note.hidden = !over;
  if (over) {
    const model = (app.state && app.state.resident && app.state.resident.model_label) || "this model";
    note.textContent =
      `That is as much as ${model} can take in one message. `
      + `Anything longer cannot be sent, however much of the conversation is dropped.`;
  }
}

/* ---------- status ---------- */

function renderStatus() {
  const resident = app.state.resident;
  el("status-dot").className = `dot ${resident.status}`;
  el("status-text").textContent =
    resident.status === "present" ? resident.model_label : resident.detail;
}

/* ---------- chat ---------- */

/* Follow the newest text, unless the owner has scrolled away to read
 * something. Being dragged back to the bottom every time a chunk arrives
 * makes it impossible to re-read anything while a reply is coming in, which
 * is exactly when someone most wants to. */

const NEAR_BOTTOM = 80;   // px of slack, so a stray pixel does not count

function atBottom(box) {
  return box.scrollHeight - box.scrollTop - box.clientHeight <= NEAR_BOTTOM;
}

function keepAtBottom(box, wasAtBottom) {
  if (wasAtBottom) box.scrollTop = box.scrollHeight;
}

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
        "It can read and write files, run commands, and fetch things — " +
        "watch the Activities pane to see what it does.";
    } else {
      empty.innerHTML =
        "<strong>No model is connected.</strong>" +
        "Open Settings and connect a model to bring your Resident to life.";
    }
    box.appendChild(empty);
    return;
  }

  for (const message of app.conversation.messages) {
    // Every node remembers which stored row it came from, so the truncation
    // seam can be placed at the actual boundary rather than counted to.
    const node = messageNode(
      message.role, message.content, message.model_label, message.blocks
    );
    if (message.id !== undefined) node.dataset.mid = message.id;
    box.appendChild(node);
  }
  box.scrollTop = box.scrollHeight;
}

/* What the Resident did, rather than what it said.
 *
 * Tool work is part of the conversation -- it is what happened -- but it is
 * not speech, and rendering it as another chat bubble would bury the reply
 * under a wall of command output. So it gets its own shape: one line saying
 * what ran and how it went, and the output folded underneath for whoever
 * wants it. The exit code is on the outside, because that is the part the
 * owner cannot afford to miss. */
/* Whether this reply was tool calls and nothing else.
 *
 * The blocks are the truth when they are there -- a reply with tool_use and
 * no text block said nothing. Older messages were stored before blocks
 * existed, so their rendered text is read instead: a bare list of tool names
 * with no sentence in it. */
function isOnlyCalls(content, blocks) {
  if (Array.isArray(blocks) && blocks.length) {
    return (
      blocks.some((b) => b && b.type === "tool_use") &&
      !blocks.some((b) => b && b.type === "text" && (b.text || "").trim())
    );
  }
  const text = (content || "").trim();
  if (!text || /[.!?:]/.test(text) || text.length > 90) return false;
  return text.split(/,\s*/).every((part) => /^[a-z][a-z0-9_]*$/.test(part.trim()));
}

const MACHINERY_ICON =
  '<path d="M2.5 5h11"/><path d="M2.5 11h11"/><circle cx="6" cy="5" r="1.6"/>' +
  '<circle cx="10" cy="11" r="1.6"/>';

/* One quiet line for what ran, with the detail folded behind it.
 *
 * Deliberately not a chat bubble. What the Resident *did* is not what it
 * *said*, and rendering the two the same way is what buried the reply under
 * its own plumbing. */
function machineryNode(role, content, blocks) {
  const wrapper = document.createElement("details");
  wrapper.className = `msg machinery ${role}`;

  const summary = document.createElement("summary");
  summary.innerHTML =
    '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" ' +
    'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" ' +
    `aria-hidden="true">${MACHINERY_ICON}</svg>`;

  const label = document.createElement("span");
  label.textContent = machineryLabel(role, content, blocks);
  summary.appendChild(label);
  wrapper.appendChild(summary);

  const body = document.createElement("pre");
  body.className = "machinery-body";
  body.textContent = content || "";
  wrapper.appendChild(body);
  return wrapper;
}

/* What the folded line says. Names rather than counts where the names are
 * the useful part: "delegate, read_file" tells the owner what happened,
 * where "2 tool calls" tells them only that something did. */
function machineryLabel(role, content, blocks) {
  const list = Array.isArray(blocks) ? blocks : [];
  if (role === "resident") {
    const names = list
      .filter((b) => b && b.type === "tool_use")
      .map((b) => b.name)
      .filter(Boolean);
    const shown = names.length ? names : (content || "").split(/,\s*/);
    return shown.slice(0, 4).join(", ") + (shown.length > 4 ? ", …" : "");
  }
  const failed = list.filter((b) => b && b.is_error).length;
  const count = list.length || 1;
  return (
    `${count} result${count === 1 ? "" : "s"}` +
    (failed ? ` — ${failed} failed` : "")
  );
}

/* A line above the reply saying why nothing is arriving.
 *
 * Replaced rather than appended: "waiting 40s" followed by "waiting 20s" is
 * a countdown the owner has to read backwards. There is one note and it says
 * the current reason, and it goes as soon as the reply starts.
 */
function setReplyNote(node, text) {
  if (!node) return;
  let note = node.querySelector(".reply-note");
  if (!note) {
    note = document.createElement("div");
    note.className = "reply-note";
    node.insertBefore(note, node.firstChild);
  }
  note.textContent = text;
}

function clearReplyNote(node) {
  const note = node && node.querySelector(".reply-note");
  if (note) note.remove();
}

function messageNode(role, content, label, blocks) {
  // Machinery, not speech.
  //
  // A reply that asked for tools and said nothing was stored with the tool
  // names as its text, so the conversation showed "delegate" and
  // "update_task" as things the Resident had told the owner. The results
  // came out in full underneath -- a skill body, a worker's whole report,
  // 25,000 tokens of a fetched page.
  //
  // The empty state of this very pane says to watch Activities to see what
  // the Resident does. This is what makes that true. The record is still
  // here and still openable, because Activities is runtime state and a
  // conversation scrolled back through a week later is all there is; it is
  // simply folded, so the reading order is what was said.
  if (role === "tool" || (role === "resident" && isOnlyCalls(content, blocks))) {
    return machineryNode(role, content, blocks);
  }

  const wrapper = document.createElement("div");
  wrapper.className = `msg ${role}`;

  // The Resident's face, on the Resident's messages.
  //
  // This is most of what makes Forever Chat feel like somebody's room rather
  // than a model interface, and it is why it goes on every reply instead of
  // only the first of a run: a conversation scrolled back through should
  // show who was speaking at any point in it, not only at the top.
  //
  // The owner gets none. They know who they are, and a second avatar would
  // make the pane a transcript of two strangers rather than the Resident's
  // own space.
  if (role === "resident" && app.persona && app.persona.has_avatar) {
    const face = document.createElement("img");
    face.className = "avatar";
    face.src = `/api/personas/${encodeURIComponent(app.persona.name)}/avatar`;
    face.alt = "";
    wrapper.appendChild(face);
    // The column only exists when something is standing in it. Without this
    // a persona with no avatar would indent every reply by the width of a
    // face that is not there.
    wrapper.classList.add("faced");
  }

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
  return watchTurn(
    () => fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    }),
    text
  );
}

/* Rejoin a reply that was already running.
 *
 * The turn lives on the server, so a refresh in the middle of one is not the
 * end of it: everything said so far is replayed and then followed live. What
 * used to happen was that the model kept working, the browser stopped
 * listening, and the answer was lost -- leaving the owner's message sitting
 * there with nothing under it. */
async function resumeReply() {
  let active = false;
  try {
    active = (await api("/api/chat/active")).active;
  } catch (_) {
    return;
  }
  if (!active) return;
  await watchTurn(() => fetch("/api/chat/stream"), null);
}

async function watchTurn(open, text) {
  const box = el("messages");

  const replyNode = messageNode("resident", "", null);
  const body = replyNode.querySelector(".body");
  body.classList.add("cursor");
  box.appendChild(replyNode);
  box.scrollTop = box.scrollHeight;

  setStreaming(true);
  let collected = "";
  let thinking = "";
  let failed = false;

  // While the model thinks, the thinking is the thing to show -- open, live,
  // with the seconds ticking -- because a blinking cursor over an empty
  // bubble reads as a hang. The moment a real word arrives it folds down to
  // a one-line record of how long that took.
  const thoughts = document.createElement("details");
  thoughts.className = "thinking";
  const summary = document.createElement("summary");
  const stream = document.createElement("div");
  stream.className = "thinking-stream";
  thoughts.append(summary, stream);
  const startedAt = Date.now();
  let ticker = null;
  const elapsed = () => Math.max(1, Math.round((Date.now() - startedAt) / 1000));

  try {
    const response = await open();
    if (!response.ok) {
      throw new Error(`AWORG replied ${response.status}`);
    }

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

        const following = atBottom(box);

        if (event.type === "context") {
          // Said before the reply begins, so the owner learns the Resident
          // has stopped seeing the start of the conversation at the moment
          // it becomes true, not afterwards.
          document.querySelector(".chat").classList.add("truncating");
        } else if (event.type === "continuing") {
          // A visible seam, not a hidden step. The Resident carried on by
          // itself because its own plan still had work in it, and an owner
          // who cannot see that happen cannot tell whose idea it was --
          // which is exactly the thing an autonomous system owes them.
          const seam = document.createElement("div");
          seam.className = "turn-seam";
          const count = event.remaining;
          seam.textContent =
            `Carrying on with the plan — ${count} task${count === 1 ? "" : "s"} left`;
          box.appendChild(seam);
        } else if (event.type === "waiting") {
        // AWORG holding off on purpose -- a rate limit, almost always. Shown
        // in the reply itself rather than in a corner, because the owner is
        // watching this space and the alternative is a Resident that appears
        // to have hung.
        setReplyNote(replyNode, event.text);
      } else if (event.type === "thinking") {
          thinking += event.text;
          if (!thoughts.isConnected) {
            replyNode.insertBefore(thoughts, body);
            thoughts.open = true;
            thoughts.classList.add("live");
            // The cursor promises words are coming; while thinking they are
            // not, so it steps aside for the indicator that tells the truth.
            body.classList.remove("cursor");
            summary.textContent = "Thinking";
            ticker = setInterval(() => {
              summary.textContent = `Thinking · ${elapsed()}s`;
            }, 1000);
          }
          stream.textContent = thinking;
          stream.scrollTop = stream.scrollHeight;
          keepAtBottom(box, following);
        } else if (event.type === "delta") {
        clearReplyNote(replyNode);
          if (!replyNode.isConnected) box.appendChild(replyNode);
          collected += event.text;
          app.contextStreamed = estimateTokens(collected);
          renderContext();
          if (thoughts.classList.contains("live")) {
            // It has started answering. Fold the reasoning down to a record
            // of how long it took, and give the cursor back to the reply.
            clearInterval(ticker);
            thoughts.classList.remove("live");
            thoughts.open = false;
            summary.textContent = `Thought for ${elapsed()}s`;
            body.classList.add("cursor");
          }
          body.innerHTML = MD.render(collected);
          keepAtBottom(box, following);
        } else if (event.type === "stopped") {
          const note = document.createElement("div");
          note.className = "stopped-note";
          note.textContent = event.partial
            ? "Stopped. What it had said is kept."
            : "Stopped before it said anything.";
          replyNode.appendChild(note);
          if (!event.partial) collected = " ";   // keep the node, it explains itself
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
          clearInterval(ticker);
          if (!collected) replyNode.remove();
          thoughts.remove();
          box.appendChild(messageNode("error", event.message, null));
          if (text) offerRetry(text);
          keepAtBottom(box, following);
        }
      }
    }
  } catch (error) {
    failed = true;
    if (!collected) replyNode.remove();
    box.appendChild(messageNode("error", `Lost contact with AWORG: ${error.message}`, null));
  } finally {
    clearInterval(ticker);
    body.classList.remove("cursor");
    setStreaming(false);
    // The conversation changed; ask for the exact count.
    refreshContext();
    if (failed) {
      // The conversation on disk is authoritative; resync rather than guess.
      app.conversation = await api("/api/conversation");
    }
  }
}

/* Stopping is server-side, not a closed connection.
 *
 * Aborting the browser's request would only stop the watching: the model
 * would carry on generating a reply nobody would ever read, holding the GPU
 * for it. This asks the Resident to stop, and what it had said by then is
 * kept -- it did say it. */
async function stopReply() {
  el("stop").disabled = true;
  try {
    await api("/api/chat/stop", { method: "POST" });
  } catch (_) {
    // It very likely finished on its own between the click and the call.
  }
}

function setStreaming(on) {
  app.streaming = on;
  // Stop stands where send does, so the control is always in one place.
  el("send").hidden = on;
  el("stop").hidden = !on;
  el("stop").disabled = false;
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

  // Reset is drawn on arrival rather than on the button, because the list is
  // what the owner came to read. Counts are live at the moment they look,
  // which is also why it is fetched here and not once at boot.
  if (id === "reset") drawResetParts();
}

/* The providers, by name rather than by wire format.
 *
 * An owner knows they are connecting to Groq. That Groq happens to implement
 * OpenAI's API is true and not their problem, so it is not what the list
 * offers. Grouped because the three kinds are reached for in different
 * moods: a hosted service, something already running on this machine, or an
 * endpoint the owner has and this list does not know about. */
function providerProfile(id) {
  return (app.meta.provider_profiles || []).find((p) => p.id === id) || null;
}

function buildProviderOptions() {
  const select = el("conn-provider");
  select.innerHTML = "";
  const profiles = app.meta.provider_profiles || [];

  const groups = [
    ["Hosted", profiles.filter((p) => !p.generic && !isLocal(p))],
    ["On this machine", profiles.filter((p) => !p.generic && isLocal(p))],
    ["Anything else", profiles.filter((p) => p.generic)],
  ];
  for (const [label, members] of groups) {
    if (!members.length) continue;
    const group = document.createElement("optgroup");
    group.label = label;
    for (const profile of members) {
      const option = document.createElement("option");
      option.value = profile.id;
      option.textContent = profile.label;
      group.appendChild(option);
    }
    select.appendChild(group);
  }
}

function isLocal(profile) {
  return /\/\/(127\.|localhost)/.test(profile.base_url || "");
}

/* What changes when the provider changes.
 *
 * The endpoint is filled in rather than fixed. Locking it would stop the
 * mistake of pointing Anthropic at an OpenAI URL, but it would also stop
 * every owner behind a proxy or a company gateway, and they are the ones
 * who cannot work around it. The mistake is caught instead: the wire format
 * comes from the provider, so a wrong URL fails at the first request and
 * says so, and the field warns before it gets that far. */
function applyProviderProfile({ keepValues } = {}) {
  const profile = providerProfile(el("conn-provider").value);
  if (!profile) return;

  const url = el("conn-base-url");
  if (!keepValues || !url.value.trim()) url.value = profile.base_url || "";
  url.placeholder = profile.base_url || "https://...";

  // A local server that checks nothing should not be demanding a key.
  const needsKey = profile.auth !== "none";
  el("conn-credential-field").classList.toggle("optional", !needsKey);
  const credNote = el("conn-credential-note");
  credNote.hidden = needsKey;
  credNote.textContent = needsKey ? "" : "This provider does not check one. Anything will do.";

  // The provider's own note is more specific than the generic line about
  // tool support, so where there is one it stands in for it rather than
  // being followed by a vaguer version of the same sentence.
  const note = el("conn-model-note");
  const parts = [];
  if (profile.note) parts.push(profile.note);
  else if (profile.tools === "yes") parts.push("Every model here can use tools.");
  else if (profile.tools === "per-model") parts.push("Tool support varies by model.");
  else if (profile.tools === "unknown") parts.push("Tool support unknown until tried.");
  note.textContent = parts.join(" ");
  note.hidden = !parts.length;
  note.classList.remove("warn");

  warnAboutUrl();
}

function warnAboutUrl() {
  const profile = providerProfile(el("conn-provider").value);
  const warn = el("conn-url-warn");
  const url = el("conn-base-url").value.trim().toLowerCase();
  warn.hidden = true;
  if (!profile || !url) return;

  for (const other of app.meta.provider_profiles || []) {
    if (other.id === profile.id || !other.base_url) continue;
    const host = other.base_url.split("//")[1].split("/")[0];
    if (/^(127\.|localhost)/.test(host)) continue;
    if (url.includes(host)) {
      warn.textContent = `That looks like ${other.label}, but this connection is `
        + `set to ${profile.label} and will be spoken to as ${profile.label}.`;
      warn.hidden = false;
      return;
    }
  }
}

/* Ask the provider what it serves.
 *
 * A list beats typing an identifier from memory -- "claude-opus-4-5" is
 * exactly the kind of string that is wrong by one character and fails as an
 * unhelpful 404. But it is a fetch that can fail, against a provider that
 * may not publish one, so the text field never goes away: it is what the
 * list writes into, and what the owner uses when there is no list. */
async function fetchModels() {
  const button = el("conn-model-fetch");
  const note = el("conn-model-note");
  const list = el("conn-model-list");
  const typed = el("conn-model");

  button.disabled = true;
  button.textContent = "Asking…";
  note.hidden = false;
  note.classList.remove("warn");
  note.textContent = "Asking the provider what it serves…";

  let data;
  try {
    data = await api("/api/models", {
      method: "POST",
      body: JSON.stringify({
        provider: el("conn-provider").value,
        base_url: el("conn-base-url").value.trim() || null,
        credential: el("conn-credential").value || null,
        connection_id: el("conn-id").value || null,
      }),
    });
  } catch (err) {
    data = { ok: false, detail: err.message, models: [] };
  }

  button.disabled = false;
  button.textContent = "Refresh";

  if (!data.ok || !data.models.length) {
    // Not an error worth stopping for: the field beside it still works.
    list.hidden = true;
    typed.hidden = false;
    note.classList.add("warn");
    note.textContent = data.detail || "No models came back. Type the name instead.";
    return;
  }

  const current = typed.value.trim();
  list.innerHTML = "";
  for (const name of data.models) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    list.appendChild(option);
  }
  // A model already chosen stays chosen, even if this provider no longer
  // lists it -- it may still work, and silently swapping it would change a
  // connection the owner did not ask to change.
  if (current && !data.models.includes(current)) {
    const kept = document.createElement("option");
    kept.value = current;
    kept.textContent = `${current} (not in the list)`;
    list.insertBefore(kept, list.firstChild);
  }
  list.value = current || data.models[0];
  typed.value = list.value;
  list.hidden = false;
  typed.hidden = true;
  const many = data.models.length === 1 ? "1 model" : `${data.models.length} models`;
  note.textContent = `${many}. Refresh to ask again.`;
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
    (connection.context ? ` · ${connection.context.toLocaleString()} tokens` : " · context unknown") +
    (connection.reasoning === "off" ? " · no thinking" : "") +
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
  el("conn-provider").value = connection ? connection.provider : "openai";
  el("conn-model").value = connection ? connection.model : "";
  el("conn-base-url").value = connection && connection.base_url ? connection.base_url : "";

  // The list belongs to a provider, so it starts closed on every open. It
  // is one click to fill, and a stale list of someone else's models would
  // be worse than none.
  el("conn-model-list").hidden = true;
  el("conn-model-list").innerHTML = "";
  el("conn-model").hidden = false;
  el("conn-model-fetch").textContent = "Fetch";
  el("conn-model-fetch").disabled = false;
  applyProviderProfile({ keepValues: true });
  el("conn-reasoning").value = (connection && connection.reasoning) || "auto";
  el("conn-context").value = connection && connection.context ? connection.context : "";
  el("conn-tpm").value =
    connection && connection.tokens_per_minute ? connection.tokens_per_minute : "";
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
    // A placeholder until the first /api/state lands and renderProject puts
    // the real name in. The pane is named for the project because that is
    // what it holds -- the picture, and the stage that picture is at.
    label: "Project",
    hint: "The software the Resident is responsible for, and how far along it is.",
    derived: true,
  },
};

/* Which pane goes where, and in what order within its region.
 *
 * This is the only place the arrangement is written down. Moving Tasks out of
 * the activity row and into the workspace column is a line moved here; every
 * other file goes on not caring where anything is. */
const REGIONS = [
  // System first: what this machine *is* frames what any capability could
  // do on it, and it is read once rather than worked in. Capabilities and
  // Skills sit below it, where the owner reaches for them deliberately.
  { id: "faculties", element: "faculties", axis: "column", panes: ["environment", "capabilities", "skills"] },
  // Lifecycle is not a pane any more. It lives inside the preview, under the
  // picture, because all six of its stages describe the thing in the picture.
  { id: "side", element: "side", axis: "column", panes: ["preview", "workspace"] },
  { id: "activity", element: "activity", axis: "row", panes: ["tasks", "workers"] },
  // What happened, then what is happening. Reading order follows the way
  // work actually moves: an Activity that turns out to matter becomes a
  // Living Log entry, and both halves are visible while it does.
  { id: "console", element: "console", axis: "row", panes: ["log", "activities"] },
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
  // The pane is rebuilt whenever the arrangement changes, which throws away
  // whatever was drawn in it. Repainting from state kept outside the DOM is
  // what stops a capability toggle wiping the running Activities list.
  paintActivities();
  paintWorkers();
  // The listing is cloned fresh from its template here, so the drop handlers
  // have to be put back on the copy that is actually in the page.
  wireWorkspaceDrop();
}

/* ---------- Activities ---------- */

/* What is happening right now, as its own pane beside the Living Log.
 *
 * Kept out of the conversation on purpose. A Resident that narrates every
 * tool call into Forever Chat buries the parts an owner actually wants to
 * read -- the reasoning, the decisions, what it concluded -- under
 * mechanics. So the mechanics come here, where they are watchable while
 * they happen and gone when they stop mattering. */

const activityState = {
  // id -> snapshot, in insertion order, which is the order work started.
  known: new Map(),
  stream: null,
  // Which rows the owner has opened, and what came back. Both live out here
  // rather than in the DOM because the list is rebuilt on every lifecycle
  // event -- an open payload would otherwise slam shut whenever anything
  // else in the pane changed.
  expanded: new Set(),
  payloads: new Map(),
};

/* Finished work lingers briefly rather than vanishing the instant it ends.
 *
 * A tool that takes 200ms would otherwise appear and disappear before the
 * owner's eye reached it, and the pane would look broken -- it would seem
 * that nothing had run at all. Holding the last few means the owner sees
 * that something happened even when it happened quickly. */
const ACTIVITY_KEEP_FINISHED = 6;

async function startActivities() {
  try {
    const current = await api("/api/activities");
    for (const item of current.live) activityState.known.set(item.id, item);
    for (const item of current.recent.slice(-ACTIVITY_KEEP_FINISHED)) {
      if (!activityState.known.has(item.id)) activityState.known.set(item.id, item);
    }
    paintActivities();
  } catch (_) { /* the stream below is the one that matters */ }

  followActivities();
}

/* One long-lived connection, reopened if it drops.
 *
 * Reconnecting matters more than it looks: the Activity Manager holds its
 * state server-side, so a browser that comes back re-reads the snapshot and
 * is immediately correct again rather than showing a frozen picture of
 * whatever was running when the connection died. */
async function followActivities() {
  while (true) {
    try {
      const response = await fetch("/api/activities/stream");
      if (!response.ok) throw new Error(String(response.status));
      for await (const event of ndjson(response)) {
        if (event.event === "snapshot") {
          for (const item of event.live) activityState.known.set(item.id, item);
        } else if (event.activity) {
          activityState.known.set(event.activity.id, event.activity);
          trimFinishedActivities();
          // Anything that ended may have been judged worth keeping. Asking
          // then, rather than waiting out the poll, is what stops a failure
          // sitting invisible for twenty seconds while the owner is looking
          // straight at the pane it should be in.
          if (isActivityFinished(event.activity)) nudgeLivingLog();
        }
        paintActivities();
        paintWorkers();
      }
    } catch (_) { /* fall through to the wait below */ }
    // The server may simply be restarting. Waiting a moment and trying
    // again is right; a page that needs reloading to show live work is not.
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
}

/* Forget the oldest finished work, per kind rather than in total.
 *
 * In total was wrong, and wrong in a way that hid exactly what the owner
 * wanted to see: a single busy worker made eleven tool calls, those eleven
 * finished activities blew straight past the keep-six limit, and the worker
 * row that spawned them was evicted by its own children. Two workers ran for
 * thirty seconds and the Workers pane stayed empty the whole time.
 *
 * A worker and a tool call are not the same size of thing. One tool call is
 * a moment; one worker is a piece of delegated work with a name, and it is
 * worth keeping several of those around even while the calls beneath them
 * are being forgotten. */
const KEEP_FINISHED_BY_KIND = { worker: 12, tool: ACTIVITY_KEEP_FINISHED };

function trimFinishedActivities() {
  const byKind = new Map();
  for (const item of activityState.known.values()) {
    if (!isActivityFinished(item)) continue;
    if (!byKind.has(item.kind)) byKind.set(item.kind, []);
    byKind.get(item.kind).push(item);
  }
  for (const [kind, items] of byKind) {
    const keep = KEEP_FINISHED_BY_KIND[kind] ?? ACTIVITY_KEEP_FINISHED;
    for (let i = 0; i < items.length - keep; i += 1) {
      activityState.known.delete(items[i].id);
    }
  }
}

const ACTIVITY_TERMINAL = ["completed", "failed", "cancelled", "timed_out"];
const isActivityFinished = (item) => ACTIVITY_TERMINAL.includes(item.state);

function paintActivities() {
  const host = el("activities");
  if (!host) return;

  const items = [...activityState.known.values()];
  if (!items.length) {
    host.replaceChildren(
      emptyPane({
        empty_heading: "Nothing running.",
        empty_detail: "Tool calls and other work appear here while they happen.",
      })
    );
    return;
  }

  const list = document.createElement("div");
  list.className = "activity-list";
  // Newest at the top: the thing that just started is the thing being
  // watched, and it should not be below a scroll.
  for (const item of items.reverse()) {
    list.appendChild(activityRow(item));
    if (activityState.expanded.has(item.id)) list.appendChild(activityPayload(item));
  }
  host.replaceChildren(list);
}

/* The whole of what a tool returned, for an owner who wants to check.
 *
 * This is the other half of the split the conversation makes. What the model
 * saw is an extract sized to fit a window, and that extract is what the
 * conversation stores, because it is what was said. The Activity kept the
 * rest -- and evidence nobody can open is not evidence, which is why this
 * exists rather than the endpoint merely being available. */
function activityPayload(item) {
  const block = document.createElement("pre");
  block.className = "activity-payload";
  const held = activityState.payloads.get(item.id);
  block.textContent = held === undefined ? "Loading…" : held;
  return block;
}

async function toggleActivityPayload(item) {
  if (activityState.expanded.has(item.id)) {
    activityState.expanded.delete(item.id);
    paintActivities();
    return;
  }
  activityState.expanded.add(item.id);
  paintActivities();

  if (activityState.payloads.has(item.id)) return;
  try {
    const full = await api(`/api/activities/${encodeURIComponent(item.id)}/payload`);
    activityState.payloads.set(
      item.id,
      full.payload || full.error || "(this tool returned nothing)"
    );
  } catch (error) {
    // Activities are runtime state and are forgotten in time. Saying so is
    // better than an empty box that looks like the tool returned nothing.
    activityState.payloads.set(item.id, `Could not load: ${error.message}`);
  }
  paintActivities();
}

/* Who is working right now.
 *
 * Painted from the same live stream as Activities rather than from the pane
 * payload, because a worker's whole nature is to appear and then go: a pane
 * drawn from a snapshot would show a roster that is already out of date.
 *
 * Only unfinished workers. A worker that has finished is not working for you
 * any more, and leaving it here would rebuild the permanent list this pane
 * was changed to stop being. What it did remains in Activities, which is the
 * pane that answers what happened. */
//: How long a finished worker stays visible. Twelve seconds is long enough
//: that an owner glancing over sees it happened, and short enough that the
//: pane still answers "who is working now" rather than "who has ever worked".
const WORKER_LINGER = 12;

function paintWorkers() {
  const host = document.querySelector("#pane-workers .pane-body");
  if (!host) return;

  // Running ones, plus any that finished a moment ago.
  //
  // Dropping a worker the instant it finishes is technically right and
  // practically useless: a worker that did eight tool calls and left was
  // never on screen long enough to be seen, so the pane read as permanently
  // empty while workers were in fact doing the job. "I did not see any
  // workers working" was the report, and the workers had worked.
  //
  // So a finished one lingers briefly, dimmed, then goes. Long enough to
  // notice, short enough that this stays a pane about now rather than
  // becoming the roster it was changed to stop being.
  const now = Date.now() / 1000;
  const workers = [...activityState.known.values()].filter(
    (a) =>
      a.kind === "worker" &&
      (!isActivityFinished(a) ||
        now - (a.created_at + (a.duration || 0)) < WORKER_LINGER)
  );

  if (!workers.length) {
    host.replaceChildren(
      emptyPane({
        empty_heading: "No workers running.",
        empty_detail:
          "Workers appear here while they are working and leave when they " +
          "finish. What kinds of worker exist is set in Settings.",
      })
    );
    return;
  }

  const list = document.createElement("div");
  list.className = "activity-list";
  for (const worker of workers.reverse()) {
    const row = document.createElement("div");
    row.className = `activity-row worker ${worker.state}`;
    if (isActivityFinished(worker)) row.classList.add("leaving");

    const dot = document.createElement("span");
    dot.className = "activity-dot";

    const name = document.createElement("span");
    name.className = "activity-name";
    name.textContent = worker.label;

    // What it was actually asked to do. Without it the pane says three
    // workers are running and nothing about what any of them is doing.
    const detail = document.createElement("span");
    detail.className = "activity-detail";
    detail.textContent = worker.detail || "";

    row.append(dot, name, detail);
    list.appendChild(row);
  }
  host.replaceChildren(list);
}

function activityRow(item) {
  const row = document.createElement("div");
  row.className = `activity-row ${item.state}`;
  if (item.parent_id) row.classList.add("child");
  // A worker is a different kind of thing from a tool call -- it is someone
  // the Resident handed a job to, and the calls underneath it are its work.
  if (item.kind === "worker") row.classList.add("worker");

  // Only rows that actually kept something are openable. A row that offers
  // to show evidence and then has none would be worse than a plain one.
  if (item.has_payload) {
    row.classList.add("openable");
    if (activityState.expanded.has(item.id)) row.classList.add("open");
    row.tabIndex = 0;
    row.title = "Show everything this returned";
    row.onclick = () => toggleActivityPayload(item);
    row.onkeydown = (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggleActivityPayload(item);
      }
    };
  }

  const dot = document.createElement("span");
  dot.className = "activity-dot";

  const name = document.createElement("code");
  name.className = "activity-name";
  name.textContent = item.label;

  const detail = document.createElement("span");
  detail.className = "activity-detail";
  // Once it is over, what it did matters more than what it was called with.
  detail.textContent = isActivityFinished(item)
    ? item.error || item.summary || ""
    : item.detail || "";

  const meta = document.createElement("span");
  meta.className = "activity-meta";
  meta.textContent = activityMeta(item);

  row.append(dot, name, detail, meta);
  return row;
}

function activityMeta(item) {
  if (item.state === "running") {
    return item.duration > 1 ? `${item.duration.toFixed(1)}s` : "running";
  }
  if (item.state === "failed") return "failed";
  if (item.state === "cancelled") return "stopped";
  if (item.state === "timed_out") return "timed out";
  if (item.state === "completed") {
    return item.duration != null ? `${item.duration.toFixed(1)}s` : "done";
  }
  return item.state;
}

/* Newline-delimited JSON off a fetch body, a record at a time.
 *
 * A chunk is not a line: one read can carry half a record or three of them,
 * so the tail is held until its newline arrives. Parsing per chunk would
 * work in testing and fail on the first long tool result. */
async function* ndjson(response) {
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
      try {
        yield JSON.parse(line);
      } catch (_) { /* a partial record; the next chunk completes it */ }
    }
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
    // Refresh, open fully, expand -- the three the application preview is
    // specified to have. Expand was the only one that existed.
    head.appendChild(previewAction("refresh", "Reload the application", REFRESH_ICON,
                                   () => loadPreview({ reload: true })));
    head.appendChild(previewAction("open", "Open the application in a new tab",
                                   OPEN_ICON, openPreviewFully));
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

  // What the pane's contents cost the Resident per message, for the panes
  // whose contents are sent. Capabilities prices each capability separately
  // because each has its own switch; the environment goes as one block and is
  // priced as one. Same argument either way: a thing that rides along with
  // every request should not be the only thing in the interface with no
  // number on it.
  if (typeof pane.tokens === "number") {
    const cost = document.createElement("span");
    cost.className = "pane-cost";
    cost.textContent = `~${pane.tokens} tok`;
    // Two panes carry a price and they are priced for different reasons, so
    // they say different things. Capabilities totals what is switched on
    // right now -- the number that moves when the owner presses something --
    // and the environment is one block that either goes or does not.
    cost.title = pane.id === "capabilities"
      ? `The tools you have switched on are offered to your Resident with ` +
        `every message, and their descriptions cost roughly ${pane.tokens} ` +
        `tokens of its context each time. Switching one off lowers this.`
      : `These facts are sent to your Resident with every message, and cost ` +
        `roughly ${pane.tokens} tokens of its context each time.`;
    head.appendChild(cost);
  }

  const body = document.createElement("div");
  body.className = "pane-body";

  const template = document.getElementById(`body-${pane.id}`);
  if (template) {
    body.appendChild(template.content.cloneNode(true));
  } else if (pane.items && pane.items.length) {
    body.appendChild(paneItems(pane.items));
  } else {
    body.appendChild(emptyPane(pane));
  }

  section.append(head, body);
  return section;
}

const REFRESH_ICON =
  '<path d="M13.6 6.8A5.6 5.6 0 1 0 13.9 9.6"/><path d="M13.9 2.8v4h-4"/>';
const OPEN_ICON =
  '<path d="M9.4 2.6h4v4"/><path d="M13.4 2.6 7.6 8.4"/>' +
  '<path d="M11.6 9.6v3.8H2.6V4.4h3.8"/>';

/* One of the small controls in the Application pane's own header.
 *
 * Built here rather than in markup because the pane is assembled from a
 * template, and a control that only makes sense for one pane belongs with
 * the code that knows which pane it is. */
function previewAction(name, label, icon, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "pane-action";
  button.id = `preview-${name}`;
  button.setAttribute("aria-label", label);
  button.title = label;
  button.onclick = onClick;
  button.innerHTML =
    '<svg viewBox="0 0 16 16" width="13" height="13" fill="none" ' +
    'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" ' +
    `stroke-linejoin="round" aria-hidden="true">${icon}</svg>`;
  return button;
}

/* The application in a tab of its own, at its real size.
 *
 * The preview is a miniature and always will be; this is the escape hatch to
 * the actual thing, which is what an owner wants the moment they see
 * something they care about. */
function openPreviewFully() {
  const url = app.previewUrl;
  if (url) window.open(url, "_blank", "noopener");
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
  // The observer catches this too, but calling directly means the miniature
  // is already the right size in the frame the expansion paints.
  fitPreview();
  document.body.classList.toggle("has-maximised-pane", next);
  paintMaximizeButton(el("maximize-preview"), next);
  if (!next) el("maximize-preview").focus();
}

/* A pane with something to say says it as a list of facts, each with the
 * plain reading of what it means. "Not elevated" is only useful next to
 * "anything needing root will fail" -- the fact and its consequence belong
 * together, because the owner is the one who has to act on it. */
function paneItems(items) {
  const list = document.createElement("div");
  list.className = "pane-items";
  for (const item of items) {
    list.appendChild(
      item.kind === "capability" ? capabilityRow(item)
      : item.kind === "worker" ? workerRow(item)
      : item.kind === "task" ? taskRow(item)
      : item.kind === "skill" ? skillRow(item)
      : item.kind === "entry" ? logRow(item)
      : factRow(item)
    );
  }
  return list;
}

/* One line of the Living Log.
 *
 * The level is the whole design of this row. `alarm` means something is
 * wrong now and nobody asked for it, and it is the only thing here that
 * should catch an eye crossing the screen -- so it is the only one that
 * gets colour. `concern` is something that failed and is over; `note` is
 * something that merely happened. A pane that shouted about all three would
 * be a pane whose owner learns to stop looking at it.
 *
 * The detail is always shown rather than hidden behind a click. An alarm
 * whose last words are one expand away is an alarm that gets read as "the
 * server died" and no further, and the last twelve lines a dying server
 * printed are usually the entire reason it died. */
function logRow(item) {
  const row = document.createElement("div");
  row.className = `pane-item log-entry ${item.level || "note"}`;

  const head = document.createElement("div");
  head.className = "log-head";

  const name = document.createElement("span");
  name.className = "pane-item-name";
  name.textContent = item.name;

  // Still open, or dealt with. The distinction is the pane's most useful
  // fact once anything is reading this list to decide what to work on, and
  // an owner glancing at it wants to know what is outstanding rather than
  // what has ever been wrong.
  if (item.open) row.classList.add("open");

  const when = document.createElement("span");
  when.className = "log-when";
  when.textContent = logTime(item.at);
  // The full stamp on hover: the short form drops the date, which is the
  // right default and the wrong thing to be stuck with when reading back
  // across a night.
  when.title = item.at || "";

  head.append(name, when);

  // A way to close it, on the ones that are open.
  //
  // The pane has shown `resolved_by: resolution` since it was written, and
  // until now nothing on this machine could ever set them: the store could
  // close an entry and the endpoint could close an entry, and no owner and
  // no Resident was ever given the means to ask. Forty-two entries in, not
  // one had been resolved -- so "what is outstanding" meant "everything
  // that has ever gone wrong", and a working list that only grows is one
  // its owner stops reading.
  if (item.open) {
    const close = document.createElement("button");
    close.type = "button";
    close.className = "log-close";
    close.textContent = "Resolve";
    close.title = "Close this out, saying what happened to it.";
    close.onclick = () => openResolver(row, item);
    head.appendChild(close);
  }

  row.appendChild(head);

  if (item.detail) {
    const detail = document.createElement("pre");
    detail.className = "log-detail";
    detail.textContent = item.detail;
    row.appendChild(detail);
  }

  // What was done about it, when something was. Shown rather than only
  // stored: "resolved" with no account of how is a claim, and this pane is
  // the one place an owner goes to check rather than take someone's word.
  if (item.resolution) {
    const done = document.createElement("span");
    done.className = "log-resolution";
    done.textContent = item.resolved_by
      ? `${item.resolved_by}: ${item.resolution}`
      : item.resolution;
    row.appendChild(done);
  }
  return row;
}

/* Time of day, in the reader's own zone.
 *
 * Stored as UTC by SQLite's datetime('now') and shown local, because an
 * owner asking when the site went down means their own clock. Falls back to
 * the raw string rather than showing "Invalid Date" if anything is off. */
function logTime(stamp) {
  if (!stamp) return "";
  const parsed = new Date(stamp.replace(" ", "T") + "Z");
  if (Number.isNaN(parsed.getTime())) return stamp;
  return parsed.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/* Ask the owner what happened, then close the entry out.
 *
 * Inline rather than a prompt() box, because the account is the point. What
 * is stored is read back by an owner in the morning and, before long, by
 * the repair loop deciding whether it has seen this before -- and a dialog
 * that can be dismissed with the return key is a dialog that fills a column
 * with empty strings.
 *
 * The row is left in place while this is open so the entry being closed
 * stays visible above the box. Closing without typing anything is allowed
 * and does nothing, which is the right outcome for a button pressed by
 * accident. */
function openResolver(row, item) {
  if (row.querySelector(".log-resolver")) return;

  const box = document.createElement("form");
  box.className = "log-resolver";

  const field = document.createElement("input");
  field.type = "text";
  field.className = "log-resolution-input";
  field.placeholder = "What happened to it?";
  field.maxLength = 500;

  const confirm = document.createElement("button");
  confirm.type = "submit";
  confirm.className = "log-close confirm";
  confirm.textContent = "Close";

  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "log-close";
  cancel.textContent = "Cancel";
  // Refreshed on the way out, not merely closed: repaints were held back
  // while this was open, so the pane is behind by however long the owner
  // spent thinking about it.
  cancel.onclick = () => {
    box.remove();
    refreshLivingLog();
  };

  box.append(field, confirm, cancel);
  box.onsubmit = async (event) => {
    event.preventDefault();
    const resolution = field.value.trim();
    if (!resolution) {
      field.focus();
      return;
    }
    confirm.disabled = true;
    try {
      await api(`/api/journal/${encodeURIComponent(item.id)}/resolve`, {
        method: "POST",
        body: JSON.stringify({ by: "owner", resolution }),
      });
    } catch (error) {
      confirm.disabled = false;
      field.value = "";
      field.placeholder = error.message || "That did not work.";
      return;
    }
    // Re-read rather than striking the row out here. The server is what
    // knows whether it closed, and a row that greys itself out on a request
    // it did not watch land is the same claim-over-evidence this pane
    // exists to refuse.
    box.remove();
    await refreshLivingLog();
  };

  row.appendChild(box);
  field.focus();
}

/* One observed fact: a label and its reading.
 *
 * Laid out as a pair on one line rather than stacked, because that is what
 * these are. The stacked form is right for a Capability, where the detail is
 * a sentence explaining a switch; here the detail is `AMD64` or `12 CPUs`,
 * and giving it its own line cost the pane four hundred pixels to say ten
 * short things. A label beside its value also reads as a spec sheet, which
 * is the correct impression: these are readings, not entries.
 */
function factRow(item) {
  const row = document.createElement("div");
  row.className = `pane-item fact ${item.state || ""}`;
  const name = document.createElement("span");
  name.className = "pane-item-name";
  name.textContent = item.name;
  const detail = document.createElement("span");
  detail.className = "pane-item-detail";
  detail.textContent = item.detail || "";
  // The whole reading, for the ones that are too long for the column -- a
  // truncated path is worse than no path, and this pane exists so the owner
  // can check what their Resident was told.
  detail.title = item.detail || "";
  row.append(name, detail);
  return row;
}

/* An installed Capability, with the Tools it actually contains named.
 *
 * The Tools are listed rather than counted because "3 tools" tells an owner
 * nothing they can act on. Seeing `read_file, write_file, search_files` is
 * what makes the switch beside it a decision they can make -- turning off
 * Shell is only an informed choice if you can see it is the thing holding
 * execute_command. */
function capabilityRow(item) {
  const row = document.createElement("div");
  row.className = `pane-item capability ${item.state || ""}`;

  const head = document.createElement("div");
  head.className = "capability-head";

  const name = document.createElement("span");
  name.className = "pane-item-name";
  name.textContent = item.name;

  // A required capability gets a label where the switch would be, not a
  // disabled-looking switch. A greyed control invites the owner to work out
  // why they cannot press it; a word tells them there was never a decision
  // here. What it costs still shows, because that is information rather than
  // a choice, and it is the half of this pane that still applies.
  const control = document.createElement(item.required ? "span" : "button");
  if (item.required) {
    control.className = "capability-fixed";
    control.textContent = "Always on";
    control.title =
      `${item.name} cannot be switched off. Without it your Resident could ` +
      `not read or write a single file, which is most of what it is for.`;
  } else {
    control.type = "button";
    control.className = "capability-toggle";
    control.setAttribute("aria-pressed", String(item.enabled));
    control.textContent = item.enabled ? "On" : "Off";
    control.title = item.enabled
      ? `Turn ${item.name} off. Its tools disappear from the Resident immediately.`
      : `Turn ${item.name} back on.`;
    control.onclick = () => setCapability(item.id, !item.enabled);
  }
  const toggle = control;

  // What it costs to leave switched on. Tool schemas ride along with every
  // single request, so an owner who enables everything and forgets is paying
  // on each message -- and until this was shown, in a currency nobody named.
  const cost = document.createElement("span");
  cost.className = "capability-cost";
  cost.textContent = `~${item.tokens ?? 0} tok`;
  cost.title =
    `Offering ${item.name} costs roughly ${item.tokens ?? 0} tokens of ` +
    `context on every message, whether or not the Resident uses it.`;

  head.append(name, cost, toggle);

  const detail = document.createElement("span");
  detail.className = "pane-item-detail";
  detail.textContent = item.detail || "";

  const tools = document.createElement("div");
  tools.className = "capability-tools";
  for (const tool of item.tools || []) {
    const chip = document.createElement("code");
    chip.className = "tool-chip";
    chip.textContent = tool.name;
    chip.title = tool.description || "";
    tools.appendChild(chip);
  }
  // A tool file that would not load is named here rather than being silently
  // missing. "This capability has two tools" and "it has three and one is
  // broken" are different facts.
  for (const broken of item.broken || []) {
    const chip = document.createElement("code");
    chip.className = "tool-chip broken";
    chip.textContent = broken.name;
    chip.title = `This tool could not be loaded: it ${broken.detail}`;
    tools.appendChild(chip);
  }

  row.append(head, detail, tools);
  return row;
}

/* A configured worker, with the tools it is allowed to use.
 *
 * The scope is the interesting fact about a worker, so it is shown rather
 * than summarised. Seeing that the checker holds no write tool is what makes
 * it worth trusting to check -- it is not being asked to avoid changing
 * things, it has not been handed the means. */
function workerRow(item) {
  const row = document.createElement("div");
  row.className = `pane-item capability ${item.state || ""}`;

  const head = document.createElement("div");
  head.className = "capability-head";

  const name = document.createElement("span");
  name.className = "pane-item-name";
  name.textContent = item.name;

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "capability-toggle";
  toggle.setAttribute("aria-pressed", String(item.enabled));
  toggle.textContent = item.enabled ? "On" : "Off";
  toggle.title = item.enabled
    ? `Stop offering ${item.name} to the Resident.`
    : `Offer ${item.name} to the Resident again.`;
  toggle.onclick = () => setWorker(item.id, !item.enabled);
  head.append(name, toggle);

  const detail = document.createElement("span");
  detail.className = "pane-item-detail";
  detail.textContent = item.detail || "";

  const tools = document.createElement("div");
  tools.className = "capability-tools";
  if (!item.tools.length) {
    const none = document.createElement("span");
    none.className = "pane-item-detail";
    none.textContent = "No tools — it can only talk.";
    tools.appendChild(none);
  }
  for (const tool of item.tools) {
    const chip = document.createElement("code");
    chip.className = "tool-chip";
    chip.textContent = tool.name;
    tools.appendChild(chip);
  }

  row.append(head, detail, tools);
  return row;
}

/* One task in the plan.
 *
 * State is shown as a word rather than only a colour, because "blocked" and
 * "active" are different in a way an owner needs to read rather than infer,
 * and a colour alone is no use to anyone who cannot distinguish it. */
function taskRow(item) {
  const row = document.createElement("div");
  row.className = `pane-item task ${item.state}`;
  if (item.child) row.classList.add("child");

  const head = document.createElement("div");
  head.className = "capability-head";

  const name = document.createElement("span");
  name.className = "pane-item-name";
  name.textContent = item.name;

  const state = document.createElement("span");
  state.className = `task-state ${item.state}`;
  state.textContent = item.state;
  head.append(name, state);

  row.appendChild(head);
  if (item.detail) {
    const detail = document.createElement("span");
    detail.className = "pane-item-detail";
    detail.textContent = item.detail;
    row.appendChild(detail);
  }
  return row;
}

/* One procedure the Resident knows.
 *
 * The description is shown in full rather than clipped to a label, because it
 * is the whole of what makes a skill usable -- it is what tells the Resident
 * when to reach for this one, and the owner reading this pane is reading the
 * same sentence the Resident reads every message. */
function skillRow(item) {
  const row = document.createElement("div");
  row.className = `pane-item capability skill ${item.state || ""}`;

  const head = document.createElement("div");
  head.className = "capability-head";

  const name = document.createElement("span");
  name.className = "pane-item-name";
  name.textContent = item.name;

  // Where it came from. A shipped skill and one the owner (or the Resident)
  // wrote are different things to trust and different things to edit.
  // How it reaches the Resident, which is the fact that decides whether
  // switching it off changes anything today.
  const mode = document.createElement("span");
  // Retired skills read differently from switched-off ones. A skill that
  // has done its job and stepped back is working correctly; one the owner
  // turned off is a decision. Showing both as simply absent would make the
  // first look broken.
  const retired = item.enabled && !item.offered && item.model_invocable;
  mode.className = `skill-source ${retired ? "retired" : item.source}`;
  mode.textContent = retired
    ? "done"
    : item.model_invocable ? item.source : "owner only";
  mode.title = retired
    ? "Not being offered: this skill applies only while there is no plan, "
      + "and there is one now. It comes back on a fresh start."
    : item.model_invocable
      ? "Described in every message; the Resident loads it with read_skill."
      : "This skill asks not to be loaded by the Resident.";

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "capability-toggle";
  toggle.setAttribute("aria-pressed", String(item.enabled));
  toggle.textContent = item.enabled ? "On" : "Off";
  toggle.title = item.enabled
    ? `Stop offering ${item.name} to the Resident.`
    : `Offer ${item.name} to the Resident again.`;
  toggle.onclick = () => setSkill(item.id, !item.enabled);

  // What offering it costs per message, the same as a capability carries.
  // A skill's body is free until read_skill fetches it; what rides along
  // every message is its name and description, and that is what this is.
  // Zero is shown rather than hidden: a switched-off or retired skill
  // costing nothing is the other half of the decision the switch offers.
  const cost = document.createElement("span");
  cost.className = "capability-cost";
  cost.textContent = `~${item.tokens ?? 0} tok`;
  cost.title = item.tokens
    ? `Offering ${item.name} costs roughly ${item.tokens} tokens of context ` +
      `on every message. Its steps cost nothing until the Resident reads it.`
    : `${item.name} is not being offered, so it costs nothing right now.`;

  head.append(name, mode, cost, toggle);

  const detail = document.createElement("span");
  detail.className = "pane-item-detail";
  detail.textContent = item.detail || "";

  row.append(head, detail);

  if (item.references) {
    const refs = document.createElement("span");
    refs.className = "pane-item-detail skill-refs";
    refs.textContent =
      `${item.references} reference file${item.references === 1 ? "" : "s"} alongside it`;
    row.appendChild(refs);
  }
  return row;
}

async function setSkill(name, enabled) {
  try {
    await api(`/api/skills/${encodeURIComponent(name)}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    });
  } catch (error) {
    return;
  }
  app.panes = await api("/api/panes");
  repaintPane("skills");
}

async function setWorker(id, enabled) {
  try {
    await api(`/api/workers/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    });
  } catch (error) {
    return;
  }
  app.panes = await api("/api/panes");
  repaintPane("workers");
}

async function setCapability(id, enabled) {
  try {
    await api(`/api/capabilities/${encodeURIComponent(id)}`, {
      method: "POST",
      body: JSON.stringify({ enabled }),
    });
  } catch (error) {
    return;
  }
  // Re-read rather than patching the row in place: the server is the one
  // that knows what is enabled, and a button that lies about it is worse
  // than one that takes a moment.
  app.panes = await api("/api/panes");
  repaintPane("capabilities");
}

/* Redraw one pane's body from the current payload.
 *
 * Deliberately not buildPanes(). That rebuilds every pane from its template,
 * which blanks the ones whose contents are painted elsewhere -- the
 * lifecycle stepper, the workspace listing, the Activities list. It was only
 * ever called once at boot, before any of those had been filled in, so
 * calling it again mid-session emptied three panes as a side effect of
 * toggling a capability. */
function repaintPane(id) {
  const pane = app.panes.find((candidate) => candidate.id === id);
  const body = document.querySelector(`#pane-${id} .pane-body`);
  if (!pane || !body) return;
  body.replaceChildren(
    pane.items && pane.items.length ? paneItems(pane.items) : emptyPane(pane)
  );
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

  // The sentence that used to sit under the stepper has nowhere to go in a
  // single row, so it moves onto the row itself. Nothing is lost that was
  // being read -- the detail and the evidence are both still one hover away,
  // and the stage an owner is actually at is named in full beneath its mark.
  const current = app.lifecycle.stages.find((s) => s.state === "current");
  const strip = el("lifecycle");
  if (strip) {
    strip.title = current
      ? `${current.detail}\n\nReached when: ${app.lifecycle.reason}`
      : app.lifecycle.reason;
  }
}

/* What the Resident is building, by name, in the pane that holds it.
 *
 * Written straight into the header rather than through buildPanes, which
 * tears down and rebuilds every pane in the region -- a rename is one string
 * changing, and rebuilding nine panes to show it would throw away the
 * Activities list and every scroll position in the column. */
function renderProject() {
  const project = app.state && app.state.project;
  const heading = document.querySelector("#pane-preview .pane-head h2");
  if (!project || !heading) return;
  heading.textContent = `Project: ${project.name} v${project.version}`;
}

/* ---------- resizing ---------- */

/* The sizes are already applied before this file runs -- /api/interface.css
 * carries them alongside the colours. What happens here is changing them.
 *
 * A drag writes straight to the custom property, so the pane follows the
 * pointer with no re-render in between. Only the release is written down.
 * Persisting every intermediate pixel would be a request per frame to record
 * sizes the owner was moving through rather than choosing. */

/* ---------- Reset ---------- */

/* Putting an Aworg back the way it arrived.
 *
 * Guarded by a code the server issues per dialog rather than a fixed word.
 * "DELETE" typed three times becomes something the hands do without the eyes
 * reading, which defeats the entire purpose of asking -- a confirmation that
 * can be given absent-mindedly is not a confirmation.
 *
 * The counts are shown before the code, because "your conversation" is easy
 * to agree to and "47 messages" is the thing actually being weighed. */
/* The list, and the counts as they are right now. Drawn whenever the section
 * is opened; the confirmation code it also fetches is only revealed when the
 * owner presses the button. */
async function drawResetParts() {
  let preview;
  try {
    preview = await api("/api/reset/preview");
  } catch (error) {
    el("reset-list").textContent = "Could not read what this Aworg is holding.";
    return;
  }
  // Kept rather than shown: pressing the button reveals it, and pressing it
  // again refreshes both this and the counts.
  el("reset-code").textContent = preview.code;

  const list = el("reset-list");
  // What they have already ticked, so a redraw does not undo their choices.
  const previous = new Map(
    [...list.querySelectorAll("input")].map((box) => [box.dataset.part, box.checked])
  );
  list.innerHTML = "";
  for (const part of preview.parts) {
    // A row for everything, including the zeroes. "0 tasks" tells the owner
    // the plan is already empty, where an absent row leaves them wondering
    // whether tasks are even covered by this.
    const row = document.createElement("label");
    row.className = "check reset-part";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = previous.has(part.id) ? previous.get(part.id) : part.default;
    box.dataset.part = part.id;
    box.onchange = syncResetList;
    const what = document.createElement("span");
    what.textContent = part.what;
    const count = document.createElement("em");
    // The four that are not lists of things answer a different question --
    // whether they differ from a fresh Aworg at all -- so they say that
    // rather than pretending to a count.
    count.textContent = COUNTLESS.has(part.id)
      ? (part.count ? "changed" : "as it ships")
      : String(part.count);
    row.append(box, what, count);
    list.appendChild(row);
  }

  syncResetList();
}

async function startReset() {
  // Redrawn rather than reused: the owner may have been sitting on this
  // screen while the Resident worked, and a stale count is the one thing
  // this list must not show.
  await drawResetParts();
  el("reset-code-input").value = "";
  el("reset-error").textContent = "";
  el("reset-error").classList.remove("ok");
  el("reset-start-row").hidden = true;
  el("reset-confirm").hidden = false;
  el("reset-code-input").focus();
  syncResetList();
}

/* The parts whose "count" is really a yes or no. */
const COUNTLESS = new Set(["project", "layout", "appearance", "persona", "prompt"]);

function chosenParts() {
  return [...document.querySelectorAll("#reset-list input:checked")]
    .map((box) => box.dataset.part);
}

/* Nothing chosen is not a reset, and the button says so rather than failing
 * at the server after the owner has typed a confirmation code. */
function syncResetList() {
  const chosen = chosenParts();
  const typed = el("reset-code-input").value.trim().toUpperCase();
  el("reset-chosen").textContent = chosen.length
    ? `${chosen.length} of ${document.querySelectorAll("#reset-list input").length} chosen`
    : "Nothing chosen";
  el("reset-go").disabled = !chosen.length || typed !== el("reset-code").textContent;
  el("reset-go").textContent = chosen.length > 1
    ? `Reset ${chosen.length} parts` : "Reset";
}

function setAllParts(on) {
  for (const box of document.querySelectorAll("#reset-list input")) box.checked = on;
  syncResetList();
}

function cancelReset() {
  el("reset-confirm").hidden = true;
  el("reset-start-row").hidden = false;
  el("reset-error").textContent = "";
}

async function doReset() {
  const button = el("reset-go");
  button.disabled = true;
  button.textContent = "Resetting…";
  try {
    const result = await api("/api/reset", {
      method: "POST",
      body: JSON.stringify({
        confirm: el("reset-code-input").value.trim(),
        parts: chosenParts(),
      }),
    });
    // Reloaded rather than repainted. A reset changes the panes, the layout,
    // the theme and the conversation at once, and every one of those is read
    // at boot -- patching them all up in place would be a second, less
    // tested, path to the same state.
    sessionStorage.setItem("aworg-reset", JSON.stringify(result.left_behind || []));
    location.reload();
  } catch (error) {
    el("reset-error").textContent = error.message;
    button.textContent = "Reset this Aworg";
    button.disabled = false;
  }
}

function wireReset() {
  el("reset-start").onclick = startReset;
  el("reset-cancel").onclick = cancelReset;
  el("reset-go").onclick = doReset;
  el("reset-all").onclick = () => setAllParts(true);
  el("reset-none").onclick = () => setAllParts(false);
  el("reset-code-input").oninput = syncResetList;

  // Say what happened, once, on the far side of the reload -- in the panel
  // the owner was standing in when they did it, rather than in a toast
  // invented for one message.
  const outcome = sessionStorage.getItem("aworg-reset");
  if (outcome !== null) {
    sessionStorage.removeItem("aworg-reset");
    // Anything that could not be removed is named here rather than left for
    // the owner to discover. A reset that was not complete should not read
    // the same as one that was.
    const stuck = JSON.parse(outcome);
    const done = el("reset-error");
    done.classList.toggle("ok", !stuck.length);
    done.textContent = stuck.length
      ? `Reset, but these could not be removed: ${stuck.join("; ")}`
      : "Reset. Nothing was kept.";
  }
}

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

  // A divider for a pane the server has no size for. This used to throw,
  // and because resizers are wired during boot it took the whole interface
  // down with it: panes never built, the conversation never loaded, and the
  // status sat on "Waking…" forever. The cause was one new pane added
  // without a matching entry in layout.py.
  //
  // The cost of the wrong behaviour was enormously out of proportion to the
  // fault, so the fault is now survivable: that one divider does not drag,
  // and everything else works. The console still says which, because a
  // divider that silently does nothing is its own small mystery.
  if (!bounds) {
    console.warn(
      `No registered size for "${pane}" — its divider will not drag. ` +
      `Add it to PANES in aworg/layout.py.`
    );
    handle.remove();
    return;
  }

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
      // A pane resize changes how much room the composer has.
      fitComposer();
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
  app.workspaceTimer = setInterval(() => {
    loadWorkspace();
    // Asked on the same heartbeat, because a server starting changes nothing
    // in the workspace and the preview would otherwise stay empty until the
    // owner reloaded the page. It was: the application only ever appeared on
    // a fresh load, never at the moment the Resident served it.
    //
    // Safe to poll because loadPreview rebuilds the frame only when the URL
    // actually changes -- otherwise this would reload the running
    // application every two seconds and throw away whatever the owner had
    // scrolled to.
    loadPreview();
  }, 1000);
  el("workspace-live").hidden = false;
}

/* Files the owner drops onto the listing.
 *
 * The workspace is the Resident's territory, but the owner has things it
 * needs -- a logo, a spreadsheet, the spec they were describing in words. The
 * alternative is telling someone to open a file manager and find a path,
 * which is precisely the kind of thing they installed an Aworg to stop doing.
 *
 * Wired from buildPanes rather than once at boot: #files lives in a template
 * that is cloned each time the panes are assembled, so handlers attached to
 * an earlier copy are attached to an element no longer in the page.
 */
function wireWorkspaceDrop() {
  const zone = el("files");
  if (!zone || zone.dataset.dropWired) return;
  zone.dataset.dropWired = "1";

  // Both are needed and neither is optional: without preventDefault on
  // dragover the browser refuses the drop, and without it on drop the browser
  // navigates away to the file instead, throwing the page away.
  zone.addEventListener("dragover", (event) => {
    if (!event.dataTransfer.types.includes("Files")) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    zone.classList.add("dropping");
  });
  // dragleave fires when crossing onto a child, so the pointer position is
  // checked rather than trusted -- otherwise the highlight flickers off every
  // time the cursor passes over a row.
  zone.addEventListener("dragleave", (event) => {
    if (zone.contains(event.relatedTarget)) return;
    zone.classList.remove("dropping");
  });
  zone.addEventListener("drop", async (event) => {
    if (!event.dataTransfer.types.includes("Files")) return;
    event.preventDefault();
    zone.classList.remove("dropping");
    await acceptDrop([...event.dataTransfer.items], event.dataTransfer.files);
  });
}

async function acceptDrop(items, files) {
  // A dropped folder arrives as one entry with an empty type and no usable
  // bytes. Uploading it would silently write a zero-byte file named after the
  // directory, so it is refused by name instead -- an owner told "folders are
  // not supported yet" can zip it; one given an empty file finds out later.
  const folders = items
    .map((item) => (item.webkitGetAsEntry ? item.webkitGetAsEntry() : null))
    .filter((entry) => entry && entry.isDirectory)
    .map((entry) => entry.name);

  // Every file is attempted, and one failing does not stop the rest. An
  // owner who drags in a folder's worth of material and has the third item
  // rejected should not silently lose the other seven -- they would have no
  // way of telling which landed except by counting the listing.
  //
  // Sequential rather than in parallel on purpose: the server picks a free
  // name by looking for one, so two uploads of the same name racing each
  // other could both decide on "notes (2).md".
  const sent = [];
  const failed = [];
  for (const file of files) {
    if (folders.includes(file.name)) continue;
    try {
      const result = await uploadFile(file);
      sent.push(result.name);
    } catch (error) {
      failed.push(`${file.name} (${error.message})`);
    }
  }

  // One note covering everything that happened, because they can happen
  // together. Composed rather than branched: an earlier version wrote the
  // failure and then overwrote it with the success, so a drop where one file
  // failed and another worked reported only the good news.
  const parts = [];
  if (sent.length) {
    // Named, because the server may have renamed one around something the
    // Resident already had there, and an owner who is not told will go
    // looking for the name they dropped.
    parts.push(`Added ${sent.join(", ")}.`);
  }
  if (failed.length) parts.push(`Not added: ${failed.join("; ")}.`);
  if (folders.length) {
    parts.push(
      `Folders cannot be dropped yet, so ${folders.join(", ")} ${
        folders.length === 1 ? "was" : "were"
      } skipped — add it as a zip and ask your Resident to unpack it.`,
    );
  }
  if (parts.length) {
    workspaceNote(parts.join(" "), failed.length > 0 || folders.length > 0);
  }

  // Straight away rather than on the next tick: the owner just did something
  // and should see it land.
  app.workspaceSignature = null;
  loadWorkspace();
}

async function uploadFile(file) {
  const query = new URLSearchParams({
    path: app.workspacePath || "",
    name: file.name,
  });
  const response = await fetch(`/api/workspace/upload?${query}`, {
    method: "POST",
    // The file itself, with no form around it. The server reads the stream.
    body: file,
  });
  if (!response.ok) {
    let detail = `the server said ${response.status}`;
    try {
      detail = (await response.json()).detail || detail;
    } catch (_) {
      /* a non-JSON error body is still an error; the status will do */
    }
    throw new Error(detail);
  }
  return response.json();
}

/* One line under the crumbs, for something that just happened to the
 * workspace. Cleared on a timer because it reports an event, not a state --
 * a message that outlives what it describes becomes furniture. */
function workspaceNote(text, isProblem = false) {
  const note = el("workspace-note");
  if (!note) return;
  note.textContent = text;
  note.classList.toggle("problem", isProblem);
  note.hidden = false;
  clearTimeout(app.workspaceNoteTimer);
  app.workspaceNoteTimer = setTimeout(() => {
    note.hidden = true;
  }, isProblem ? 9000 : 4000);
}

function stopWorkspaceWatch() {
  clearInterval(app.workspaceTimer);
  app.workspaceTimer = null;
  el("workspace-live").hidden = true;
}

/* The width the application is rendered at, whatever size the pane is.
 *
 * **This is the whole point of the preview zooming.** An iframe sized to the
 * pane is an iframe about 420 pixels wide, so a desktop site renders its
 * phone layout and the owner is shown something they did not build. Worse,
 * they are shown it at full scale: the last preview held a header and three
 * words of a headline.
 *
 * So the frame is given a real desktop viewport and the whole thing is
 * scaled down to fit. What the owner sees is a true miniature -- the layout
 * they asked for, small -- rather than a crop of a different layout. */
const PREVIEW_WIDTH = 1280;

/* Never scaled up past life size. A pane wider than 1280 would otherwise
 * enlarge the page, which is not a preview of anything. */
const PREVIEW_MAX_SCALE = 1;

async function loadPreview(options) {
  const inner = el("preview-inner");
  let preview;
  try {
    preview = await api("/api/preview");
  } catch (_) {
    return;
  }

  // Nothing changed and nobody asked -- leave the frame alone. Rebuilding it
  // on every poll would reload the application every two seconds, losing
  // whatever the owner had scrolled to or typed into it.
  // The revision is part of this, and it is the part that matters. The URL
  // does not change when the files behind it do, so a signature of the
  // address alone left the owner watching the page from before the edit.
  const signature =
    `${preview.available}|${preview.url || ""}|${preview.revision || ""}`;
  const reload = options && options.reload;
  if (!reload && signature === app.previewSignature) return;
  app.previewSignature = signature;
  app.previewUrl = preview.available ? preview.url : null;

  inner.innerHTML = "";
  if (preview.available && preview.url) {
    const stage = document.createElement("div");
    stage.className = "preview-stage";

    const frame = document.createElement("iframe");
    // Cache-busted on a deliberate refresh so the owner gets the application
    // as it is now rather than as the browser remembers it.
    frame.src = reload
      ? preview.url + (preview.url.includes("?") ? "&" : "?") + "r=" + Date.now()
      : preview.url;
    frame.title = "Application preview";
    frame.style.width = `${PREVIEW_WIDTH}px`;
    stage.appendChild(frame);
    inner.appendChild(stage);
    fitPreview();
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

/* Scale the rendered application down until it fits the pane.
 *
 * Recomputed rather than set once, because the pane is resizable, the window
 * is resizable, and expanding the preview changes its size by a factor of
 * three. A scale that was right when the frame was built is wrong the moment
 * the owner drags a divider.
 *
 * The frame's height is derived from the scale rather than fixed, so the
 * miniature shows as much of the page as the pane's shape allows: a tall
 * pane shows more of the application, which is what a taller pane is for.
 */
function fitPreview() {
  const inner = el("preview-inner");
  const stage = inner && inner.querySelector(".preview-stage");
  const frame = stage && stage.querySelector("iframe");
  if (!frame) return;

  const width = inner.clientWidth;
  const height = inner.clientHeight;
  if (!width || !height) return;

  const scale = Math.min(width / PREVIEW_WIDTH, PREVIEW_MAX_SCALE);
  frame.style.height = `${Math.round(height / scale)}px`;
  stage.style.transform = `scale(${scale})`;
  // Announced, because a miniature that does not say it is one invites the
  // owner to judge type sizes and spacing from it.
  inner.dataset.scale = `${Math.round(scale * 100)}%`;
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
      "Ask your Resident to build something and it will appear here as " +
      "it works.";
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
  // A file had nothing to click. Folders navigate; a file just sat there, so
  // an owner could see a thing the Resident had made and do nothing about
  // it except describe it out loud in the composer.
  else row.onclick = (event) => openFileMenu(entry, event);
  // Right-click works on both, because a folder is a thing you may want to
  // rename as much as a file is, and losing that to navigation would be odd.
  row.oncontextmenu = (event) => {
    event.preventDefault();
    openFileMenu(entry, event);
  };
  return row;
}

/* What the owner can ask about one file.
 *
 * **These compose a message. They do not do anything.** Every entry writes a
 * sentence into the composer, focuses it, and stops -- the owner reads it,
 * edits it if they want, and sends it or does not.
 *
 * That is the whole design, and it is not timidity about wiring up a delete
 * button. The workspace is the Resident's territory: it holds the plan it is
 * working from and the files a running job has open. An owner deleting
 * something underneath that, through a path the Resident never sees, gives it
 * a workspace that changed for reasons it has no record of. Routing the
 * request through the conversation means the Resident knows, the Activities
 * feed shows the tool call, and the Living Log keeps whatever mattered --
 * the same account as everything else it does.
 *
 * It also means the one irreversible action in the list is never one click
 * away from happening.
 */
const FILE_ACTIONS = [
  { label: "Show me this", say: (p) => `Show me what is in ${p}` },
  { label: "Rename…", say: (p) => `Rename ${p} to `, open: true },
  { label: "Duplicate", say: (p) => `Make a copy of ${p}` },
  { label: "Move…", say: (p) => `Move ${p} to `, open: true },
  { label: "Delete", say: (p) => `Delete ${p}`, danger: true },
];

function openFileMenu(entry, event) {
  closeFileMenu();
  const here = app.workspacePath ? `${app.workspacePath}/${entry.name}` : entry.name;

  const menu = document.createElement("div");
  menu.className = "file-menu";
  menu.id = "file-menu";

  const title = document.createElement("div");
  title.className = "file-menu-title";
  title.textContent = entry.name;
  menu.appendChild(title);

  for (const action of FILE_ACTIONS) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "file-menu-item" + (action.danger ? " danger" : "");
    button.textContent = action.label;
    button.onclick = () => {
      closeFileMenu();
      suggestToResident(action.say(here));
    };
    menu.appendChild(button);
  }

  const note = document.createElement("div");
  note.className = "file-menu-note";
  // Said rather than assumed. An owner who expects a menu item to *do* the
  // thing and finds a sentence in the composer instead should be told why
  // once, here, rather than work it out.
  note.textContent = "Puts it to your Resident. Nothing happens until you send.";
  menu.appendChild(note);

  document.body.appendChild(menu);

  // Positioned after mounting, because the size is not known until then and
  // a menu opened near the bottom edge should come up rather than off.
  const box = menu.getBoundingClientRect();
  const x = Math.min(event.clientX, window.innerWidth - box.width - 8);
  const y = event.clientY + box.height > window.innerHeight - 8
    ? event.clientY - box.height
    : event.clientY;
  menu.style.left = `${Math.max(8, x)}px`;
  menu.style.top = `${Math.max(8, y)}px`;

  // Deferred, or the click that opened it closes it again.
  setTimeout(() => {
    document.addEventListener("click", closeFileMenu, { once: true });
    document.addEventListener("keydown", escapeFileMenu);
  }, 0);
}

function closeFileMenu() {
  const menu = el("file-menu");
  if (menu) menu.remove();
  document.removeEventListener("keydown", escapeFileMenu);
}

function escapeFileMenu(event) {
  if (event.key === "Escape") closeFileMenu();
}

/* Put words in the owner's mouth, and leave them there.
 *
 * Appended rather than replacing, so a half-written message is not thrown
 * away by a stray right-click -- and the cursor lands at the end either way,
 * which is where "Rename x to " needs it.
 */
function suggestToResident(text) {
  const input = el("input");
  if (!input) return;
  const existing = input.value.trim();
  input.value = existing ? `${existing} ${text}` : text;
  fitComposer();
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
  app.contextDraft = estimateTokens(input.value);
  renderContext();
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

  // Refuse an insertion that would carry the draft past what could ever be
  // sent. beforeinput rather than input, so the characters never appear and
  // then vanish -- and it covers typing, pasting and dropping alike.
  input.addEventListener("beforeinput", (event) => {
    const limit = maxDraftChars();
    if (!limit) return;
    // Deletions and anything that shortens the text are always allowed --
    // including when already over, which is how someone gets back under.
    if (!event.data && event.inputType !== "insertFromPaste"
        && event.inputType !== "insertFromDrop") return;

    const incoming = event.data
      || (event.dataTransfer && event.dataTransfer.getData("text")) || "";
    const selected = input.selectionEnd - input.selectionStart;
    if (input.value.length - selected + incoming.length <= limit) return;

    event.preventDefault();
    renderComposerLimit();
    // Say why, rather than letting the keystroke silently do nothing.
    const note = el("composer-note");
    note.hidden = false;
    const model = (app.state && app.state.resident && app.state.resident.model_label) || "this model";
    note.textContent = incoming.length > 40
      ? `That paste is too large for ${model}: ${incoming.length.toLocaleString()} characters `
        + `against a limit of ${limit.toLocaleString()}. Nothing was inserted, so it is still on your clipboard.`
      : `That is as much as ${model} can take in one message.`;
    note.classList.add("flash");
    setTimeout(() => note.classList.remove("flash"), 600);
  });

  input.addEventListener("input", () => {
    // The draft counts before it is sent -- that is the point of the ring.
    app.contextDraft = estimateTokens(input.value);
    renderContext();
    fitComposer();
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
    fitComposer();
    app.contextDraft = estimateTokens(text);
    renderContext();
    renderComposerLimit();
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

  el("stop").onclick = stopReply;

  el("reset-appearance").onclick = resetAppearance;
  el("reset-view").onclick = resetView;

  el("add-connection").onclick = () => openForm(null);
  el("conn-cancel").onclick = closeForm;
  el("conn-provider").onchange = () => applyProviderProfile();
  el("conn-base-url").oninput = warnAboutUrl;
  el("conn-model-fetch").onclick = fetchModels;
  // Choosing from the list is what fills the field the form actually reads,
  // so there is one answer to "which model is this" rather than two.
  el("conn-model-list").onchange = () => {
    el("conn-model").value = el("conn-model-list").value;
  };

  el("conn-form").onsubmit = async (event) => {
    event.preventDefault();
    const error = el("conn-error");
    error.textContent = "";

    const payload = {
      name: el("conn-name").value.trim(),
      provider: el("conn-provider").value,
      model: el("conn-model").value.trim(),
      base_url: el("conn-base-url").value.trim() || null,
      reasoning: el("conn-reasoning").value,
      // Blank means unknown. It is sent as 0 so that clearing a value that
      // was set before actually clears it, rather than being read as "not
      // supplied" and left alone.
      context: parseInt(el("conn-context").value, 10) || 0,
      // Blank means "use the provider's entry tier", which is not the
      // same as 0 -- that is the owner saying there is no limit at all.
      tokens_per_minute: el("conn-tpm").value.trim() === ""
        ? null
        : parseInt(el("conn-tpm").value, 10) || 0,
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
