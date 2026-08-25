// Data-driven dashboard shell: tabs come from datasets.json, so adding a
// dataset to the pipeline surfaces here without touching this file.
const MANIFEST = "datasets.json";

async function load() {
  const panel = document.getElementById("panel");
  const tabs = document.getElementById("tabs");
  try {
    const datasets = await (await fetch(MANIFEST, { cache: "no-store" })).json();
    if (!datasets.length) { panel.innerHTML = "<p class='muted'>No datasets published yet.</p>"; return; }
    datasets.forEach((d, i) => {
      const b = document.createElement("button");
      b.textContent = d.label;
      b.onclick = () => select(d, b);
      tabs.append(b);
      if (i === 0) select(d, b);
    });
  } catch {
    panel.innerHTML = "<p class='muted'>Manifest not available yet.</p>";
  }
}

function select(dataset, button) {
  document.querySelectorAll("#tabs button").forEach(b => b.classList.toggle("active", b === button));
  // TODO: render charts once a source is publishing; keep rendering per-dataset.
  document.getElementById("panel").innerHTML =
    `<h2>${dataset.label}</h2><p class="muted">${dataset.description ?? ""}</p>
     <p><a href="${dataset.path}">Browse raw parquet</a></p>`;
}

load();
