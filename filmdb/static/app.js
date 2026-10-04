"use strict";

const $ = (sel) => document.querySelector(sel);
const LETTERS = ["#", ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ"];
const state = { q: "", letter: "", sort: "title", genre: "", year: "", format: "" };
let facets = { letters: [], genres: [], years: [], formats: [], total: 0 };

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  const body = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, body };
}

function coverHtml(m) {
  const src = m.poster ? `/covers/${m.poster}` : m.photo ? `/photos/${m.photo}` : "";
  const fmt = m.media_format;
  const badge = fmt
    ? `<span class="badge ${fmt === "Blu-ray" ? "bluray" : fmt === "4K UHD" ? "uhd" : ""}">${esc(fmt)}</span>`
    : "";
  const img = src
    ? `<img src="${src}" alt="Cover: ${esc(m.title)}" loading="lazy">`
    : `<div class="placeholder">${esc(m.title)}</div>`;
  return `<div class="poster">${img}${badge}</div>`;
}

// ---------- Liste & Filtercockpit ----------

let loadToken = 0;
async function load() {
  const token = ++loadToken;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(state)) if (v) params.set(k, v);
  const { body } = await api(`/api/movies?${params}`);
  if (token !== loadToken) return; // veraltete Antwort
  facets = body.facets;
  renderCockpit();
  renderGrid(body.movies);
  try { localStorage.setItem("filmdb-filter", JSON.stringify(state)); } catch {}
}

function fillSelect(sel, values, allLabel, current) {
  if (current && !values.map(String).includes(String(current))) values = [current, ...values];
  sel.innerHTML = `<option value="">${allLabel}</option>` +
    values.map((v) => `<option ${String(v) === String(current) ? "selected" : ""}>${esc(v)}</option>`).join("");
}

function renderCockpit() {
  $("#letters").innerHTML =
    `<button data-letter="" class="${state.letter ? "" : "active"}">Alle</button>` +
    LETTERS.map((l) => {
      const has = facets.letters.includes(l);
      return `<button data-letter="${l}" class="${state.letter === l ? "active" : ""}" ${has || state.letter === l ? "" : "disabled"}>${l}</button>`;
    }).join("");
  fillSelect($("#genre"), facets.genres, "Alle Genres", state.genre);
  fillSelect($("#year"), facets.years, "Alle Jahre", state.year);
  fillSelect($("#format"), facets.formats, "DVD &amp; Blu-ray", state.format);
  $("#sort").value = state.sort;
}

function renderGrid(movies) {
  const filtered = Object.entries(state).some(([k, v]) => k !== "sort" && v);
  $("#count").textContent = filtered
    ? `${movies.length} von ${facets.total} Filmen`
    : `${facets.total} Filme in der Sammlung`;
  $("#grid").innerHTML = movies.map((m) => `
    <button class="card" data-id="${m.id}">
      ${coverHtml(m)}
      <span class="t">${esc(m.title)}</span>
      <span class="y">${esc(m.year || "")}${m.genres.length ? " · " + esc(m.genres.slice(0, 2).join(", ")) : ""}</span>
    </button>`).join("");
  const empty = $("#empty");
  empty.hidden = movies.length > 0;
  empty.textContent = facets.total
    ? "Keine Filme passen zu diesen Filtern."
    : "Noch keine Filme. Tippe auf „＋ Film per Foto“ und fotografiere die Rückseite einer DVD oder Blu-ray.";
}

let searchTimer;
$("#q").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { state.q = e.target.value.trim(); load(); }, 200);
});
$("#letters").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-letter]");
  if (!b || b.disabled) return;
  state.letter = b.dataset.letter;
  load();
});
for (const key of ["sort", "genre", "year", "format"]) {
  $("#" + key).addEventListener("change", (e) => { state[key] = e.target.value; load(); });
}
$("#reset").addEventListener("click", () => {
  Object.assign(state, { q: "", letter: "", sort: "title", genre: "", year: "", format: "" });
  $("#q").value = "";
  load();
});
$("#grid").addEventListener("click", (e) => {
  const card = e.target.closest(".card");
  if (card) openDetail(Number(card.dataset.id));
});

// ---------- Details, Bearbeiten, Löschen ----------

const detail = $("#detail");

async function openDetail(id) {
  const { ok, body: m } = await api(`/api/movies/${id}`);
  if (!ok) return;
  const chips = (list, filterKey) => list.length
    ? `<div class="chips">${list.map((v) => filterKey
        ? `<button class="chip" data-filter="${filterKey}" data-value="${esc(v)}">${esc(v)}</button>`
        : `<span class="chip">${esc(v)}</span>`).join("")}</div>`
    : "–";
  const row = (label, value) => value ? `<dt>${label}</dt><dd>${value}</dd>` : "";
  const links = [
    m.imdb_id && `<a href="https://www.imdb.com/title/${esc(m.imdb_id)}/" target="_blank" rel="noopener">IMDb</a>`,
    m.tmdb_id && `<a href="https://www.themoviedb.org/movie/${m.tmdb_id}" target="_blank" rel="noopener">TMDB</a>`,
  ].filter(Boolean).join(" · ");

  detail.innerHTML = `
    <form method="dialog" class="dialog-head"><span></span><button class="icon" aria-label="Schließen">✕</button></form>
    <div class="detail-body">
      <div>${coverHtml(m)}</div>
      <div>
        <h2>${esc(m.title)}</h2>
        <p class="sub">${[m.original_title !== m.title && esc(m.original_title), m.year, m.runtime && m.runtime + " Min.", esc(m.fsk)].filter(Boolean).join(" · ")}</p>
        ${m.overview ? `<p>${esc(m.overview)}</p>` : ""}
        <dl>
          ${row("Genre", chips(m.genres, "genre"))}
          ${row("Regie", chips(m.directors, "q"))}
          ${row("Darsteller", chips(m.actors, "q"))}
          ${row("Format", esc(m.media_format))}
          ${row("Studio", esc(m.studio))}
          ${row("Bewertung", m.rating ? `★ ${m.rating}/10` : "")}
          ${row("Erschienen", esc(m.release_date))}
          ${row("Notizen", esc(m.notes))}
          ${row("Links", links)}
        </dl>
      </div>
    </div>
    <div class="actions">
      <button class="ghost" data-act="edit">✏️ Bearbeiten</button>
      <button class="ghost" data-act="cover">🖼️ Cover ändern</button>
      ${m.photo ? `<button class="ghost" data-act="photo">📷 Foto der Rückseite</button>` : ""}
      <button class="ghost danger" data-act="delete">🗑️ Löschen</button>
    </div>
    <div id="extra"></div>`;
  detail.onclick = (e) => onDetailClick(e, m);
  if (!detail.open) detail.showModal();
}

function onDetailClick(e, m) {
  const chip = e.target.closest("[data-filter]");
  if (chip) {
    if (chip.dataset.filter === "genre") state.genre = chip.dataset.value;
    else { state.q = chip.dataset.value; $("#q").value = state.q; }
    detail.close();
    load();
    return;
  }
  const act = e.target.closest("[data-act]")?.dataset.act;
  if (act === "delete") return deleteMovie(m);
  if (act === "edit") return showEditForm(m);
  if (act === "cover") return showCoverForm(m);
  if (act === "photo") {
    $("#extra").innerHTML = `<img class="photo-full" src="/photos/${m.photo}" alt="Foto der Rückseite">`;
  }
}

async function deleteMovie(m) {
  if (!confirm(`„${m.title}“ wirklich aus der Sammlung löschen?`)) return;
  await api(`/api/movies/${m.id}`, { method: "DELETE" });
  detail.close();
  load();
}

function showEditForm(m) {
  const f = (key, label, value = m[key]) =>
    `<label>${label}<input name="${key}" value="${esc(value ?? "")}"></label>`;
  $("#extra").innerHTML = `
    <form class="form" id="editForm">
      <div class="two">${f("title", "Titel")}${f("original_title", "Originaltitel")}</div>
      <div class="two">${f("year", "Jahr")}${f("release_date", "Erscheinungsdatum (JJJJ-MM-TT)")}</div>
      <div class="two">
        <label>Format<select name="media_format">
          ${["", "DVD", "Blu-ray", "4K UHD"].map((v) => `<option value="${v}" ${v === m.media_format ? "selected" : ""}>${v || "–"}</option>`).join("")}
        </select></label>
        ${f("runtime", "Laufzeit (Min.)")}
      </div>
      ${f("genres", "Genres (mit Komma getrennt)", m.genres.join(", "))}
      ${f("actors", "Darsteller (mit Komma getrennt)", m.actors.join(", "))}
      ${f("directors", "Regie (mit Komma getrennt)", m.directors.join(", "))}
      <div class="two">${f("studio", "Studio")}${f("fsk", "FSK")}</div>
      <label>Inhalt<textarea name="overview">${esc(m.overview)}</textarea></label>
      ${f("notes", "Notizen (z. B. verliehen an …)")}
      <div class="actions"><button class="primary">Speichern</button></div>
    </form>`;
  $("#editForm").onsubmit = async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target));
    for (const k of ["genres", "actors", "directors"]) {
      data[k] = data[k].split(",").map((s) => s.trim()).filter(Boolean);
    }
    const { ok, body } = await api(`/api/movies/${m.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
    });
    if (!ok) return alert(body.error || "Speichern fehlgeschlagen");
    await openDetail(m.id);
    load();
  };
}

function showCoverForm(m) {
  $("#extra").innerHTML = `
    <form class="form" id="coverForm">
      <label>Bild-URL<input name="url" placeholder="https://…/cover.jpg"></label>
      <label>… oder Bild hochladen<input name="cover" type="file" accept="image/jpeg,image/png,image/webp"></label>
      <div class="actions"><button class="primary">Cover übernehmen</button></div>
    </form>`;
  $("#coverForm").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    if (!fd.get("cover")?.size) fd.delete("cover");
    const { ok, body } = await api(`/api/movies/${m.id}/cover`, { method: "POST", body: fd });
    if (!ok) return alert(body.error || "Cover konnte nicht gesetzt werden");
    await openDetail(m.id);
    load();
  };
}

// ---------- Foto hochladen & erkennen ----------

const addDialog = $("#addDialog");
$("#addBtn").addEventListener("click", () => addDialog.showModal());
$("#photos").addEventListener("change", (e) => {
  enqueue([...e.target.files]);
  e.target.value = "";
});
const drop = $("#drop");
drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", (e) => {
  e.preventDefault();
  drop.classList.remove("over");
  enqueue([...e.dataTransfer.files].filter((f) => f.type.startsWith("image/")));
});
$("#byTitle").addEventListener("click", () => {
  if (!$("#hint").value.trim()) return alert("Bitte zuerst einen Titel als Hinweis eintragen.");
  enqueue([null]);
});

// Handyfotos vor dem Hochladen verkleinern (schneller, und Safari wandelt HEIC dabei in JPEG um)
async function shrink(file) {
  try {
    const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
    const scale = Math.min(1, 2000 / Math.max(bmp.width, bmp.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bmp.width * scale);
    canvas.height = Math.round(bmp.height * scale);
    canvas.getContext("2d").drawImage(bmp, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((r) => canvas.toBlob(r, "image/jpeg", 0.88));
    return blob ? new File([blob], "foto.jpg", { type: "image/jpeg" }) : file;
  } catch {
    return file;
  }
}

let chain = Promise.resolve();
function enqueue(files) {
  const hint = $("#hint").value.trim();
  const format = $("#addFormat").value;
  for (const file of files) {
    const li = document.createElement("li");
    const thumb = file ? `<img src="${URL.createObjectURL(file)}" alt="">` : "🔎";
    li.innerHTML = `${thumb}<span class="msg">Wartet …</span><span class="spinner"></span>`;
    $("#queue").prepend(li);
    // nacheinander verarbeiten, damit die API nicht überlastet wird
    chain = chain.then(() => recognize(li, file, hint, format, false));
  }
  $("#hint").value = "";
}

async function recognize(li, file, hint, format, allowDuplicate) {
  const msg = li.querySelector(".msg");
  const spinner = li.querySelector(".spinner") || li.appendChild(Object.assign(document.createElement("span"), { className: "spinner" }));
  msg.className = "msg";
  msg.textContent = "Erkenne Film und suche Metadaten im Internet …";
  const fd = new FormData();
  if (file) fd.append("photo", await shrink(file));
  if (hint) fd.append("hint", hint);
  if (format) fd.append("format", format);
  if (allowDuplicate) fd.append("allow_duplicate", "1");

  const { ok, status, body } = await api("/api/recognize", { method: "POST", body: fd })
    .catch(() => ({ ok: false, body: { error: "Server nicht erreichbar" } }));
  spinner.remove();
  if (ok) {
    const m = body.movie;
    const unsure = body.confidence === "niedrig";
    msg.className = "msg " + (unsure ? "warn" : "ok");
    msg.innerHTML = `${unsure ? "⚠️ Unsicher erkannt" : "✓ Gespeichert"}: <strong>${esc(m.title)}</strong> (${esc(m.year || "?")})` +
      (unsure && body.hint ? `<br><small>${esc(body.hint)}</small>` : "") +
      ` <button class="ghost" data-open="${m.id}">Ansehen</button>`;
    load();
  } else if (status === 409) {
    msg.className = "msg warn";
    msg.innerHTML = `„${esc(body.movie.title)}“ ist bereits in der Sammlung. <button class="ghost" data-dup>Trotzdem hinzufügen</button>`;
    msg.querySelector("[data-dup]").onclick = () => recognize(li, file, hint, format, true);
  } else {
    msg.className = "msg err";
    msg.textContent = "✕ " + (body.error || "Fehler bei der Erkennung");
  }
  const open = msg.querySelector("[data-open]");
  if (open) open.onclick = () => { addDialog.close(); openDetail(Number(open.dataset.open)); };
}

// ---------- Start ----------

try { Object.assign(state, JSON.parse(localStorage.getItem("filmdb-filter") || "{}")); } catch {}
$("#q").value = state.q;
load();
