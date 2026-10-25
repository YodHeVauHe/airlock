// Task live view: SSE timeline, blast-radius panel, artifacts, explanation.
(function () {
  const taskId = window.TASK_ID;
  const timeline = document.getElementById("timeline");
  const empty = document.getElementById("tl-empty");
  const statusPill = document.getElementById("status-pill");
  const evCount = document.getElementById("ev-count");
  let seq = 0;
  let count = 0;
  let maxRisk = 0;
  let sandboxDestroyed = false;
  let hostBefore = null;
  let hostAfter = null;
  const renderedCode = new Set();

  function el(html) {
    const t = document.createElement("template");
    t.innerHTML = html.trim();
    return t.content.firstChild;
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
  }

  function addEvent(ev) {
    if (ev.seq <= seq) return;
    seq = ev.seq;
    count++;
    evCount.textContent = `— ${count} events, hash-chained`;
    if (empty) empty.remove();

    const time = new Date(ev.ts * 1000).toTimeString().slice(0, 8);
    const tags = (ev.tags || []).map(t =>
      `<span class="tl-tag risk-${ev.risk}">${esc(t)}</span>`).join("");
    const riskTag = ev.risk > 0
      ? `<span class="tl-tag risk-${ev.risk}">risk:${ev.risk}</span>` : "";

    let detail = "";
    if (ev.type === "code.content" && ev.detail && ev.detail.code) {
      const key = ev.task_id + ":" + ev.seq;
      if (!renderedCode.has(key)) {
        renderedCode.add(key);
        detail = `<details class="fold" open><summary>generated code</summary>
          <pre class="codeblock">${esc(ev.detail.code)}</pre></details>`;
      }
    } else if (ev.type === "exec.finished" && ev.detail && (ev.detail.stdout_tail || ev.detail.stderr_tail)) {
      const out = [ev.detail.stdout_tail && `stdout:\n${ev.detail.stdout_tail}`,
                   ev.detail.stderr_tail && `stderr:\n${ev.detail.stderr_tail}`].filter(Boolean).join("\n\n");
      detail = `<details class="fold"><summary>sandbox output</summary>
        <pre class="codeblock">${esc(out)}</pre></details>`;
    } else if (ev.type === "explain.ready" && ev.detail && ev.detail.markdown) {
      renderExplain(ev.detail.markdown);
    } else if (ev.type === "artifact.saved" && ev.detail) {
      addArtifact(ev.detail);
    } else if (ev.type === "sandbox.destroyed") {
      sandboxDestroyed = true;
    } else if (ev.type === "host.proof" && ev.detail && ev.detail.fingerprint) {
      if (hostBefore === null) { hostBefore = ev.detail.fingerprint; }
      else { hostAfter = ev.detail.fingerprint; }
    } else if (ev.type === "policy.verdict" && ev.detail) {
      const vd = document.getElementById("br-verdict");
      if (vd) vd.textContent = ev.title;
    } else if (ev.type === "containment.verdict") {
      const banner = document.getElementById("br-verdict");
      if (banner) {
        banner.innerHTML = ev.detail.host_intact
          ? `<span class="v-ok">CONTAINED — host fingerprint unchanged.</span>`
          : `<span class="v-hot">HOST CHANGED — investigate immediately.</span>`;
      }
    }

    const row = el(`<div class="tl-event tl-flash">
      <div class="tl-time">${time}</div>
      <div class="tl-body">
        <div class="tl-title">${esc(ev.title)}</div>
        ${(tags || riskTag) ? `<div class="tl-tags">${tags}${riskTag}</div>` : ""}
        ${detail ? `<div class="tl-detail">${detail}</div>` : ""}
      </div>
    </div>`);
    timeline.appendChild(row);
    row.scrollIntoView({ block: "nearest" });
    if (ev.risk > maxRisk && ev.type !== "torture.started" && ev.type !== "policy.verdict") {
      maxRisk = ev.risk;
    }
    if (ev.risk > 0 && ev.type !== "torture.started") updateScore();
    updatePanel(ev);
  }

  function updateScore() {
    const s = document.getElementById("br-score");
    s.textContent = maxRisk;
    s.className = "big" + (maxRisk >= 3 ? " hot" : maxRisk >= 2 ? " elevated" : "");
  }

  function updatePanel(ev) {
    const chain = document.getElementById("br-chain");
    if (chain && ev.hash) chain.innerHTML = `<span class="v-ok">intact · head ${esc(ev.hash.slice(0, 10))}…</span>`;
    const lc = document.getElementById("br-lifecycle");
    if (lc) {
      if (sandboxDestroyed) lc.innerHTML = `<span class="v-ok">destroyed after task ✔</span>`;
      else if (ev.type === "sandbox.created" || ev.type === "sandbox.creating")
        lc.textContent = "live (will be destroyed)";
    }
    const host = document.getElementById("br-host");
    if (host && hostAfter) {
      host.innerHTML = hostBefore === hostAfter
        ? `<span class="v-ok">unchanged ✔ ${esc(hostAfter.slice(0, 8))}</span>`
        : `<span class="v-hot">CHANGED ✖</span>`;
    }
    if (ev.type === "task.status" || ev.type === "task.completed" || ev.type === "task.failed"
        || ev.type === "policy.blocked") {
      statusPill.textContent = ev.detail && ev.detail.status ? ev.detail.status : statusPill.textContent;
      if (ev.type === "task.completed") statusPill.textContent = "completed";
      if (ev.type === "task.failed") statusPill.textContent = "failed";
      if (ev.type === "policy.blocked") statusPill.textContent = "blocked";
      statusPill.className = "pill pill-" + statusPill.textContent;
    }
  }

  function addArtifact(a) {
    const wrap = document.getElementById("artifacts");
    const emptyEl = wrap.querySelector(".empty");
    if (emptyEl) emptyEl.remove();
    const isImg = a.kind === "image";
    const row = el(`<div class="artifact">
      <div style="min-width:0;">
        <div>${esc(a.name)} <span class="mono" style="color:var(--dimmer);font-size:11px;">${a.size} B</span></div>
        ${isImg ? `<img src="/api/tasks/${taskId}/artifacts/${encodeURIComponent(a.name)}" alt="${esc(a.name)}">` : ""}
      </div>
      <a class="dl" href="/api/tasks/${taskId}/artifacts/${encodeURIComponent(a.name)}">download ↓</a>
    </div>`);
    wrap.appendChild(row);
  }

  function renderExplain(md) {
    const box = document.getElementById("explain");
    // minimal markdown: headings, bold, code blocks, list items
    let html = esc(md)
      .replace(/```([\s\S]*?)```/g, (_, c) => `<pre class="codeblock">${c.trim()}</pre>`)
      .replace(/^### (.*)$/gm, "<h3>$1</h3>")
      .replace(/^## (.*)$/gm, "<h2>$1</h2>")
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/^- (.*)$/gm, "<li>$1</li>")
      .replace(/(<li>[\s\S]*?<\/li>)/g, "<ul>$1</ul>")
      .replace(/<\/ul>\s*<ul>/g, "")
      .replace(/\n{2,}/g, "<br><br>");
    box.innerHTML = html;
  }

  // receipt verification badge
  fetch(`/api/tasks/${taskId}/receipt/verify`).then(r => r.ok ? r.json() : null).then(d => {
    if (!d) return;
    const lc = document.getElementById("br-chain");
    if (lc) lc.innerHTML = d.ok
      ? `<span class="v-ok">verified ✔ sealed</span>`
      : `<span class="v-hot">TAMPERED: ${esc(d.reason)}</span>`;
  }).catch(() => {});

  const es = new EventSource(`/api/tasks/${taskId}/stream`);
  es.onmessage = (m) => { try { addEvent(JSON.parse(m.data)); } catch (e) {} };
  es.addEventListener("done", () => es.close());
  es.onerror = () => { /* stream ends when run completes; poll fallback */ };
})();
