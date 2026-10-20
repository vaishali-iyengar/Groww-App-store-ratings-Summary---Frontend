// Pulse simulator page: pick weeks, start a job, poll it, render the pulse.
(function () {
  const $ = (id) => document.getElementById(id);
  const state = { weeks: [], selected: 4, min: 1, max: 10, minReviews: 30, running: false, markdown: "" };
  const STAGES = ["filtering", "theming", "writing"];
  const THEME_COLORS = ["var(--t1)", "var(--t2)", "var(--t3)"];
  const fmtDate = (iso, year) => new Date(iso + "T00:00:00").toLocaleDateString("en-GB",
    year ? { day: "numeric", month: "short", year: "numeric" } : { day: "numeric", month: "short" });
  const fmtNum = (n) => n.toLocaleString("en-IN");

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "style") node.style.cssText = v;
      else if (k === "text") node.textContent = v;
      else node.setAttribute(k, v);
    }
    for (const c of children) if (c != null) node.append(c);
    return node;
  }

  function stars(rating) {
    const r = Math.round(rating);
    return el("span", { class: "stars", "aria-label": "Rated " + rating + " out of 5",
      text: "★".repeat(r) + "☆".repeat(5 - r) });
  }

  // ---- Week picker ----
  function renderWeeks() {
    const box = $("weeks");
    box.replaceChildren();
    const peak = Math.max(1, ...state.weeks.map((w) => w.count));
    for (const w of state.weeks) {
      const on = w.weeks_back <= state.selected;
      const btn = el("button", {
        type: "button", class: "week", "aria-pressed": String(on),
        "aria-label": "Last " + w.weeks_back + " week" + (w.weeks_back > 1 ? "s" : "") +
          " (week of " + fmtDate(w.start) + ": " + w.count + " reviews)",
        title: fmtDate(w.start) + " – " + fmtDate(w.end) + ": " + w.count + " reviews",
      },
        el("span", { class: "count", text: String(w.count) }),
        el("span", { class: "bar", style: "height:" + Math.max(4, (w.count / peak) * 100) + "%" }),
        el("span", { class: "date", text: fmtDate(w.start) }));
      btn.addEventListener("click", () => select(w.weeks_back));
      box.append(btn);
    }
    const chosen = state.weeks.filter((w) => w.weeks_back <= state.selected);
    const total = chosen.reduce((s, w) => s + w.count, 0);
    const sel = $("selection");
    sel.replaceChildren();
    if (chosen.length) {
      sel.append("Last ", el("strong", { text: state.selected + " week" + (state.selected > 1 ? "s" : "") }),
        ", " + fmtDate(chosen[0].start) + " – " + fmtDate(chosen[chosen.length - 1].end) + ", ",
        el("strong", { text: fmtNum(total) + " reviews" }));
    }
  }

  function select(n) {
    state.selected = n;
    $("weeks-input").value = n;
    $("weeks-error").hidden = true;
    renderWeeks();
  }

  $("weeks-input").addEventListener("input", (e) => {
    const n = Number(e.target.value);
    const ok = Number.isInteger(n) && n >= state.min && n <= state.max;
    $("weeks-error").hidden = ok;
    $("weeks-error").textContent = ok ? "" : "Enter a whole number from " + state.min + " to " + state.max + ".";
    if (ok) { state.selected = n; renderWeeks(); }
  });

  // ---- Running a job ----
  function setStage(stage) {
    const idx = STAGES.indexOf(stage);
    document.querySelectorAll(".steps li").forEach((li, i) => {
      li.classList.toggle("done", idx > i);
      li.classList.toggle("active", idx === i || (idx < 0 && i === 0));
    });
  }

  function setRunning(on) {
    state.running = on;
    $("run").disabled = on;
    $("run").textContent = on ? "Running…" : "Run pulse";
  }

  async function run() {
    const n = Number($("weeks-input").value);
    if (!Number.isInteger(n) || n < state.min || n > state.max) { $("weeks-input").focus(); return; }
    setRunning(true);
    $("error").hidden = true; $("empty").hidden = true; $("progress").hidden = false;
    setStage("queued");
    try {
      const res = await fetch("/api/pulse", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ weeks: n, use_llm: !$("offline").checked }) });
      const body = await res.json();
      if (!res.ok) throw new Error(errorText(body));
      const result = body.result || await poll(body.job_id);  // sync mode (Vercel) answers inline
      $("progress").hidden = true;
      renderResult(result);
    } catch (err) {
      $("progress").hidden = true;
      $("error-text").textContent = err.message;
      $("error").hidden = false;
    } finally {
      setRunning(false);
    }
  }

  function errorText(body) {
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return "Weeks must be a whole number from " + state.min + " to " + state.max + ".";
    return "The request failed.";
  }

  async function poll(jobId) {
    for (;;) {
      const res = await fetch("/api/pulse/" + jobId);
      const job = await res.json();
      if (!res.ok) throw new Error(errorText(job));
      if (job.status === "done") return job.result;
      if (job.status === "failed") throw new Error(job.error);
      setStage(job.status);
      await new Promise((r) => setTimeout(r, 800));
    }
  }

  // ---- Results ----
  function renderResult(r) {
    const color = {};
    r.themes.forEach((t, i) => { color[t.theme_id] = THEME_COLORS[i % THEME_COLORS.length]; });
    const tag = (id, name) => el("span", { class: "tag", style: "--c:" + (color[id] || "var(--muted)"), text: name });

    $("r-count").textContent = fmtNum(r.review_count);
    $("r-weeks").textContent = String(r.weeks);
    $("r-window").textContent = fmtDate(r.window.start) + " – " + fmtDate(r.window.end, true);
    $("r-headline").textContent = r.headline;
    $("r-low").hidden = !r.low_confidence;
    $("r-low").textContent = "Low confidence: only " + r.review_count + " reviews (the pulse expects at least " +
      r.min_reviews + "). Pick more weeks for a steadier picture.";

    $("r-themes").replaceChildren(...r.themes.map((t, i) => {
      const wow = t.week_over_week_share_change_pts;
      return el("li", { class: "theme", style: "--c:" + color[t.theme_id] },
        el("span", { class: "rank", text: "Rank " + (i + 1) }),
        el("h3", { text: t.name }),
        el("div", { class: "share" }, el("b", { text: t.share_of_reviews_pct + "%" }), el("span", { text: "of reviews" })),
        el("div", { class: "share-track", "aria-hidden": "true" }, el("i", { style: "width:" + Math.min(100, t.share_of_reviews_pct) + "%" })),
        el("div", { class: "stats" },
          el("span", {}, stars(t.avg_rating), " " + t.avg_rating.toFixed(1) + " avg"),
          wow == null ? null : el("span", { text: (wow > 0 ? "▲ +" : wow < 0 ? "▼ " : "● ") + wow.toFixed(1) + " pts vs last week" })),
        el("p", { class: "summary-text", text: t.summary }));
    }));

    $("r-quotes").replaceChildren(...r.quotes.map((q) =>
      el("figure", { class: "quote", style: "--c:" + color[q.theme_id] },
        el("blockquote", { text: "“" + q.text + "”" }),
        el("figcaption", {}, stars(q.rating), tag(q.theme_id, q.theme)))));

    $("r-actions").replaceChildren(...r.actions.map((a) =>
      el("li", { class: "action" },
        el("span", { class: "owner", "data-owner": a.owner, text: a.owner }),
        el("div", {}, el("p", { text: a.action }), tag(a.theme_id, a.theme)))));

    $("r-meta").textContent = (r.mode === "llm" ? "Written by the LLM" : "Offline mode: keyword themes and template text") +
      ". " + r.words + " words, run " + r.run_id + ".";
    state.markdown = r.markdown;
    $("results").hidden = false;
  }

  $("copy").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(state.markdown);
      $("copy").textContent = "Copied";
    } catch (e) {
      $("copy").textContent = "Copy failed";
    }
    setTimeout(() => { $("copy").textContent = "Copy as Markdown"; }, 1600);
  });

  $("run").addEventListener("click", run);
  $("retry").addEventListener("click", run);

  // ---- Start ----
  fetch("/api/snapshot").then(async (res) => {
    const body = await res.json();
    if (!res.ok) throw new Error(errorText(body));
    Object.assign(state, { weeks: body.weeks, min: body.min_weeks, max: body.max_weeks, minReviews: body.min_reviews });
    if (body.sync) {  // no stage updates in sync mode, so show one step
      document.querySelector(".steps").replaceChildren(el("li", { "data-stage": "running", text: "Running the agent" }));
    }
    const snap = body.snapshot.replace(/(\d{4})(\d{2})(\d{2})/, "$1-$2-$3");
    $("snapshot-line").textContent = "Google Play reviews of Groww, downloaded on " + fmtDate(snap, true) +
      ". Choose a window, run the agent and read the weekly pulse.";
    renderWeeks();
  }).catch((err) => {
    $("snapshot-line").textContent = err.message;
    $("run").disabled = true;
  });
})();
