"use strict";
const $ = id => document.getElementById(id);
const node = (tag, text) => Object.assign(document.createElement(tag), { textContent: text });
let catalog, active, token;
async function api(path, data) {
  const response = await fetch(path, {
    method: data === undefined ? "GET" : "POST",
    headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
    body: data === undefined ? undefined : JSON.stringify(data)
  });
  const value = await response.json();
  if (!response.ok) throw Error(value.message);
  return value;
}
function handle(action) {
  return async event => {
    event.preventDefault();
    try { await action(event); }
    catch (error) { $("status").textContent = error.message; }
  };
}
function measures() {
  const subject = catalog.subjects.find(s => s.id === $("subject").value);
  $("period").value = subject.kind === "macro" ? "2025-03-12" : "FY2024";
  $("measures").replaceChildren();
  for (const [key, metric] of Object.entries(catalog.metrics)) {
    if (metric.kind !== subject.kind) continue;
    const label = node("label", "");
    const input = Object.assign(document.createElement("input"), {type:"checkbox", checked:true, value:key});
    label.append(input, metric.name);
    $("measures").append(label);
  }
}
async function historyList() {
  const rows = await api("/api/briefs");
  $("recent").replaceChildren();
  for (const row of rows) {
    const spec = row.request;
    const b = node("button", spec.subject + " · " + spec.period + " · " + spec.as_of.slice(0,10) + (row.decision ? " · " + row.decision : ""));
    b.onclick = handle(async () => display(await api("/api/briefs/" + row.id)));
    $("recent").append(b);
  }
}
function display(brief) {
  active = brief;
  const r = brief.result;
  $("title").textContent = catalog.subjects.find(s => s.id === r.subject).name + " · " + r.period;
  const result = $("result");
  result.replaceChildren(node("p", "As of " + r.as_of + " · " + r.status));
  if (r.reason) result.append(node("p", r.reason.replaceAll("_", " ")));
  for (const item of r.items) {
    const article = node("article", "");
    article.append(node("h3", catalog.metrics[item.metric].name), node("p", item.text || item.status.replaceAll("_", " ")));
    for (const c of (item.citations || (item.observations || []).map(o => o.citation))) {
      const b = node("button", c.document + " · line " + c.line);
      b.className = "passage";
      const quote = node("blockquote", c.passage);
      quote.hidden = true;
      b.onclick = handle(async () => {
        if (quote.hidden) {
          const passage = await api(c.href);
          quote.textContent = passage.text + " · Retrieved " + passage.metadata.retrieved;
        }
        quote.hidden = !quote.hidden;
      });
      article.append(b, quote);
    }
    result.append(article);
  }
  $("note").value = "";
  $("review").hidden = !!brief.review;
  $("review").querySelector("[value=approve]").disabled = r.status !== "supported";
  if (brief.review) result.append(node("p", [brief.review.decision, brief.review.actor, brief.review.reviewed, brief.review.note].join(" · ")));
}
$("subject").onchange = measures;
$("login").onsubmit = handle(async () => {
  $("workspace").hidden = true;
  token = $("token").value;
  $("token").value = "";
  catalog = await api("/api/catalog");
  $("subject").replaceChildren(...catalog.subjects.map(s => new Option(s.name, s.id)));
  measures();
  await historyList();
  $("workspace").hidden = false;
  $("status").textContent = "Connected";
});
$("query").onsubmit = handle(async () => {
  const metrics = Array.from($("measures").querySelectorAll("input:checked"), el => el.value);
  const brief = await api("/api/briefs", {subject:$("subject").value, period:$("period").value, as_of:$("asof").value, metrics});
  display(brief);
  await historyList();
  $("status").textContent = "Brief ready";
});
$("review").onsubmit = handle(async event => {
  const brief = await api("/api/briefs/" + active.id + "/review", {decision:event.submitter.value, note:$("note").value});
  display(brief);
  await historyList();
  $("status").textContent = "Decision recorded";
});
