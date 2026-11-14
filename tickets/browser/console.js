"use strict";

const byId = (id) => document.getElementById(id);
const api = "/api/v1";
const labels = {in_progress: "In progress", due_soon: "Due soon", on_track: "On track"};
const demoActors = JSON.parse(byId("demo-actors").textContent);
const state = {token: "", actor: null, selected: null, offset: 0, nextOffset: null, busy: false};
const notice = byId("notice");
const dialog = byId("create-dialog");
const dateFormat = new Intl.DateTimeFormat(undefined, {dateStyle: "medium", timeStyle: "short"});

function label(value) {
  return labels[value] || value.charAt(0).toUpperCase() + value.slice(1);
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function button(text, action) {
  const node = element("button", text);
  node.type = "button";
  node.addEventListener("click", action);
  return node;
}

function message(text, error = false) {
  notice.textContent = text;
  notice.classList.toggle("error", error);
}

async function request(path, {body, token = state.token, key} = {}) {
  const headers = {Authorization: "Bearer " + token};
  if (body) headers["Content-Type"] = "application/json";
  if (key) headers["Idempotency-Key"] = key;
  const response = await fetch(api + path, {
    method: body ? "POST" : "GET",
    headers,
    body: body ? JSON.stringify(body) : undefined,
    redirect: "error",
  });
  const payload = await response.json();
  if (!response.ok) {
    const error = new Error(payload.error?.message || "The request failed.");
    error.code = payload.error?.code;
    throw error;
  }
  return payload;
}

async function run(action, {trigger, errorTarget = notice} = {}) {
  if (state.busy) return;
  state.busy = true;
  if (trigger) trigger.disabled = true;
  message("");
  if (errorTarget !== notice) errorTarget.textContent = "";
  try {
    await action();
  } catch (error) {
    const text = error instanceof TypeError ? "Could not reach the server. Check that it is running." : error.message;
    if (errorTarget === notice || !dialog.open) message(text, true);
    else errorTarget.textContent = text;
  } finally {
    if (trigger?.isConnected) trigger.disabled = false;
    state.busy = false;
  }
}

async function connect(token) {
  const actor = await request("/me", {token});
  Object.assign(state, {token, actor, selected: null, offset: 0});
  byId("session-label").textContent = actor.handle + " · " + label(actor.role);
  byId("new-ticket").disabled = false;
  byId("detail").replaceChildren(element("p", "Select a ticket to view its details.", "empty"));
  byId("queue").replaceChildren(element("p", "Loading tickets…", "empty"));
  byId("metrics").hidden = true;
  byId("filters").reset();
  await refresh();
}

async function refresh() {
  await loadQueue(state.offset);
  if (state.actor.role === "manager") {
    const metrics = await request("/metrics/queue");
    const values = [
      ["Backlog", metrics.backlog], ["Unassigned", metrics.unassigned],
      ["Due soon", metrics.due_soon], ["Breached", metrics.breached],
    ];
    byId("metrics").replaceChildren(...values.map(([name, value]) => {
      const item = element("div");
      item.append(element("dt", name), element("dd", value));
      return item;
    }));
    byId("metrics").hidden = false;
  }
}

async function loadQueue(offset) {
  const params = new URLSearchParams({limit: "25", offset: String(offset)});
  for (const [key, value] of new FormData(byId("filters"))) {
    if (value.trim()) params.set(key, value.trim());
  }
  const page = await request("/tickets?" + params);
  state.offset = offset;
  state.nextOffset = page.next_offset;
  const rows = page.items.map((ticket) => {
    const row = button(ticket.title, () => run(() => openTicket(ticket.id)));
    row.dataset.ticketId = ticket.id;
    row.setAttribute("aria-pressed", String(ticket.id === state.selected));
    row.append(element("span", [
      label(ticket.status), label(ticket.priority), ticket.assignee || "Unassigned",
      "Resolution " + label(ticket.sla.resolution.status).toLowerCase(),
    ].join(" · "), "ticket-meta"));
    return row;
  });
  byId("queue").replaceChildren(...(rows.length ? rows : [element("p", "No tickets match.", "empty")]));
  byId("previous").disabled = offset === 0;
  byId("next").disabled = page.next_offset === null;
  document.querySelector(".pagination").hidden = offset === 0 && page.next_offset === null;
}

async function openTicket(id) {
  const path = "/tickets/" + id;
  const ticket = await request(path);
  state.selected = id;
  for (const row of byId("queue").querySelectorAll("button")) {
    row.setAttribute("aria-pressed", String(row.dataset.ticketId === id));
  }
  const detail = byId("detail");
  detail.replaceChildren(
    element("h2", ticket.title),
    element("p", [label(ticket.status), label(ticket.priority), ticket.assignee || "Unassigned",
      "Version " + ticket.version].join(" · "), "ticket-meta"),
    element("p", ticket.description, "description"),
    renderClocks(ticket),
    renderActions(ticket, path),
  );
  if (state.actor.role === "manager") {
    const audit = element("ol", undefined, "audit");
    detail.append(element("h3", "Audit history"), audit);
    await loadAudit(path, audit, 0);
  }
}

function renderClocks(ticket) {
  const clocks = element("dl", undefined, "sla");
  for (const [name, clock] of [["First response", ticket.sla.first_response], ["Resolution", ticket.sla.resolution]]) {
    const group = element("div");
    group.append(element("dt", name), element("dd", label(clock.status) + " · Due " + dateFormat.format(new Date(clock.due_at))));
    clocks.append(group);
  }
  return clocks;
}

function renderActions(ticket, path) {
  const actions = element("div", undefined, "detail-actions");
  const manager = state.actor.role === "manager";
  if (manager && ticket.status !== "resolved") {
    const assignee = element("input");
    assignee.required = true;
    assignee.pattern = "[a-z0-9_\\-]{1,50}";
    assignee.value = ticket.assignee || "";
    assignee.placeholder = "e.g. casey";
    actions.append(actionForm("Agent handle", assignee, "Assign", path + "/assignment", "assignee", ticket));
    const priority = element("select");
    for (const value of ["low", "normal", "high", "urgent"]) {
      priority.add(new Option(label(value), value));
    }
    priority.value = ticket.priority;
    actions.append(actionForm("Priority", priority, "Update priority", path + "/priority", "priority", ticket));
  }
  const assignedAgent = state.actor.role === "agent" && state.actor.handle === ticket.assignee;
  const transition = {open: ["Start work", "in_progress"], in_progress: ["Resolve ticket", "resolved"], resolved: ["Reopen ticket", "open"]};
  if ((manager || assignedAgent) && ticket.assignee && (ticket.status !== "resolved" || manager)) {
    const [title, status] = transition[ticket.status];
    actions.append(button(title, (event) => run(
      () => change(ticket, path + "/transition", {status}), {trigger: event.currentTarget}
    )));
  }
  return actions;
}

function actionForm(title, input, action, path, field, ticket) {
  const form = element("form", undefined, "action-form");
  const caption = element("label", title);
  caption.append(input);
  const submit = element("button", action);
  form.append(caption, submit);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    run(() => change(ticket, path, {[field]: input.value}), {trigger: submit});
  });
  return form;
}

async function change(ticket, path, body) {
  try {
    await request(path, {body: {...body, expected_version: ticket.version}});
  } catch (error) {
    if (error.code === "version_conflict") await openTicket(ticket.id);
    throw error;
  }
  await openTicket(ticket.id);
  await refresh();
  message("Ticket updated.");
}

async function loadAudit(path, list, offset) {
  const page = await request(path + "/audit?offset=" + offset);
  for (const event of page.items) {
    const item = element("li", label(event.action.replaceAll("_", " ")) + " · " + event.actor);
    item.append(element("span", dateFormat.format(new Date(event.occurred_at)) + " · Version " + event.version, "ticket-meta"));
    const changes = element("details");
    changes.append(element("summary", "View changes"), element("pre", JSON.stringify(event.changes, null, 2)));
    item.append(changes);
    list.append(item);
  }
  if (page.next_offset !== null) {
    const next = button("More audit events", () => run(async () => {
      await loadAudit(path, list, page.next_offset);
      next.remove();
    }, {trigger: next}));
    list.after(next);
  }
}

byId("connect").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = event.currentTarget.elements.token;
  run(async () => {
    await connect(input.value.trim());
    input.value = "";
  }, {trigger: event.submitter});
});
byId("filters").addEventListener("submit", (event) => {
  event.preventDefault();
  if (state.actor) run(() => loadQueue(0));
});
byId("previous").addEventListener("click", () => run(() => loadQueue(Math.max(0, state.offset - 25))));
byId("next").addEventListener("click", () => {
  if (state.nextOffset !== null) run(() => loadQueue(state.nextOffset));
});

let draftKey;
let draftBody;
byId("new-ticket").addEventListener("click", () => {
  if (state.busy) return;
  byId("create-ticket").reset();
  byId("create-error").textContent = "";
  draftKey = null;
  draftBody = null;
  dialog.showModal();
});
byId("cancel-create").addEventListener("click", () => { if (!state.busy) dialog.close(); });
dialog.addEventListener("cancel", (event) => { if (state.busy) event.preventDefault(); });
byId("create-ticket").addEventListener("submit", (event) => {
  event.preventDefault();
  const body = Object.fromEntries(new FormData(event.currentTarget));
  run(async () => {
    const snapshot = JSON.stringify(body);
    if (draftBody !== snapshot) {
      draftBody = snapshot;
      draftKey = crypto.randomUUID();
    }
    const ticket = await request("/tickets", {body, key: draftKey});
    dialog.close();
    byId("filters").reset();
    state.offset = 0;
    await openTicket(ticket.id);
    await refresh();
    message("Ticket created.");
  }, {trigger: event.submitter, errorTarget: byId("create-error")});
});

if (demoActors.manager) {
  byId("connect").hidden = true;
  byId("demo-switch").hidden = false;
  const roles = byId("demo-role");
  roles.addEventListener("change", () => run(() => connect(demoActors[roles.value].token), {trigger: roles}));
  run(() => connect(demoActors.manager.token), {trigger: roles});
}
