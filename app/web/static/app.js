// Launch pad: lane selection, file picker, task dispatch.
(function () {
  let lane = "analyze";
  const lanes = document.getElementById("lanes");
  if (!lanes) return;
  lanes.querySelectorAll(".lane").forEach(el => {
    el.addEventListener("click", () => {
      lanes.querySelectorAll(".lane").forEach(x => x.classList.remove("selected"));
      el.classList.add("selected");
      lane = el.dataset.lane;
    });
  });

  const drop = document.getElementById("file-drop");
  const input = document.getElementById("files");
  drop.addEventListener("click", () => input.click());
  input.addEventListener("change", () => {
    if (input.files.length) {
      drop.classList.add("has-files");
      drop.textContent = `${input.files.length} file(s): ${[...input.files].map(f => f.name).join(", ")}`;
    }
  });

  const form = document.getElementById("launch-form");
  const btn = document.getElementById("launch-btn");
  const err = document.getElementById("launch-error");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    err.textContent = "";
    const goal = document.getElementById("goal").value.trim();
    if (!goal) { err.textContent = "give the agent a goal first"; return; }
    btn.disabled = true;
    btn.textContent = "Dispatching…";
    try {
      const fd = new FormData();
      fd.append("goal", goal);
      fd.append("lane", lane);
      for (const f of input.files) fd.append("files", f);
      const r = await fetch("/api/tasks", { method: "POST", body: fd });
      const data = await r.json();
      if (data.task_id) {
        location.href = "/task/" + data.task_id;
      } else {
        err.textContent = data.detail || "failed to create task";
        btn.disabled = false;
        btn.textContent = "Dispatch to sandbox →";
      }
    } catch (ex) {
      err.textContent = String(ex);
      btn.disabled = false;
      btn.textContent = "Dispatch to sandbox →";
    }
  });
})();
