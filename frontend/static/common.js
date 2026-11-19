// Small helpers shared by the customer app and the admin panel.
const $ = id => document.getElementById(id);

// Turn a <label class="drop"> into a click / drag-and-drop image box with preview.
// Returns an object whose .file holds the chosen File and .clear() resets it.
function setupDrop(box, onChange) {
  const input = box.querySelector("input");
  const state = { file: null, clear() { state.file = null; box.querySelector("img")?.remove(); input.value = ""; } };
  const setFile = f => {
    if (!f) return;
    if (!["image/jpeg", "image/png"].includes(f.type)) return alert("Please choose a JPG or PNG image.");
    if (f.size > 10 * 1024 * 1024) return alert("That image is larger than 10 MB.");
    state.file = f;
    box.querySelector("img")?.remove();
    const img = document.createElement("img");
    img.src = URL.createObjectURL(f);
    box.appendChild(img);
    onChange && onChange(f);
  };
  input.addEventListener("change", () => setFile(input.files[0]));
  ["dragenter", "dragover"].forEach(e => box.addEventListener(e, ev => { ev.preventDefault(); box.classList.add("over"); }));
  ["dragleave", "drop"].forEach(e => box.addEventListener(e, ev => { ev.preventDefault(); box.classList.remove("over"); }));
  box.addEventListener("drop", ev => setFile(ev.dataTransfer.files[0]));
  return state;
}

// fetch() that returns parsed JSON and throws Error(message) for any failure.
async function api(url, options = {}) {
  let res;
  try { res = await fetch(url, options); }
  catch { throw new Error("Network error. Is the server running?"); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.success === false) {
    const detail = Array.isArray(data.detail) ? data.detail[0]?.msg : data.detail;
    const err = new Error(data.error || detail || "Request failed.");
    err.status = res.status;
    throw err;
  }
  return data;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
