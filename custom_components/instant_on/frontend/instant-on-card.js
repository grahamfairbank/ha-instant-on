/*
 * instant-on-card: a "mission control" style dashboard card for the HPE Instant On integration.
 * Served by the integration itself at /instant_on/instant-on-card.js (no resource setup needed).
 *
 *   type: custom:instant-on-card
 *   site: Home            # optional: site name or id (default: first site)
 *   sections: [header, kpis, map, aps, switches, talkers]   # optional subset / order
 */
const VERSION = "0.2.0";
const REFRESH_MS = 30000;
const HISTORY_MS = 300000;
const ALL_SECTIONS = ["header", "kpis", "map", "aps", "switches", "talkers"];

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtRate = (bps) => {
  bps = Number(bps) || 0;
  if (bps >= 1e9) return [(bps / 1e9).toFixed(2), "Gb/s"];
  if (bps >= 1e6) return [(bps / 1e6).toFixed(bps >= 1e8 ? 0 : 1), "Mb/s"];
  if (bps >= 1e3) return [(bps / 1e3).toFixed(0), "kb/s"];
  return [bps.toFixed(0), "b/s"];
};
const rate = (bps) => fmtRate(bps).join(" ");
const fmtUptime = (s) => {
  if (s == null) return "–";
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600);
  return d ? `${d}d ${h}h` : `${h}h ${Math.floor((s % 3600) / 60)}m`;
};
const ago = (iso) => {
  if (!iso) return "never";
  const s = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000));
  return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.round(s / 60)}m ago` : `${Math.round(s / 3600)}h ago`;
};
const band = (b) => ({ "2.4ghz": "2.4 GHz", "5ghz": "5 GHz", "6ghz": "6 GHz" }[b] || b || "");
const speed = (s) => ({ mbps10: "10M", mbps100: "100M", mbps1000: "1G", mbps2500: "2.5G", mbps5000: "5G", mbps10000: "10G" }[s] || "");
const utilColor = (u) => (u >= 70 ? "var(--red)" : u >= 40 ? "var(--amber)" : "var(--green)");

const ICON = {
  switch: '<path d="M3 8h18v8H3z" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M6 12h.01M9 12h.01M12 12h.01M15 12h.01" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/>',
  accessPoint: '<circle cx="12" cy="16" r="1.6" fill="currentColor"/><path d="M8.5 12.5a5 5 0 0 1 7 0M5.5 9.5a9.2 9.2 0 0 1 13 0" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
  gateway: '<circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M4 12h16M12 4c3 3.2 3 12.8 0 16M12 4c-3 3.2-3 12.8 0 16" fill="none" stroke="currentColor" stroke-width="1.3"/>',
  client: '<rect x="7" y="4" width="10" height="16" rx="2" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M11 17h2" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
};
const icon = (k, size = 18) => `<svg viewBox="0 0 24 24" width="${size}" height="${size}" aria-hidden="true">${ICON[k] || ICON.switch}</svg>`;

const STYLE = `
:host{--bg:#070b14;--panel:#0e1524;--panel2:#111a2c;--line:#1d2940;--text:#e6edf7;--dim:#7f8da8;
  --cyan:#3ee0ff;--violet:#9b7bff;--green:#3dffa2;--amber:#ffc24a;--red:#ff5c7a;display:block}
ha-card{background:radial-gradient(1200px 500px at 10% -10%,#13204066,transparent 60%),radial-gradient(900px 400px at 110% 10%,#2a1a5544,transparent 60%),var(--bg);
  color:var(--text);border:1px solid var(--line);border-radius:18px;overflow:hidden;font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{padding:18px;display:grid;gap:14px;container-type:inline-size}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums}
.dim{color:var(--dim)} .small{font-size:12px}
.panel{background:linear-gradient(180deg,#0f1729e6,#0b1220e6);border:1px solid var(--line);border-radius:14px;padding:14px;position:relative;min-width:0}
.panel h3{margin:0 0 10px;font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--dim);font-weight:600;display:flex;justify-content:space-between;align-items:center;gap:8px}
.head{display:flex;align-items:center;gap:14px}
.logo{width:42px;height:42px;border-radius:12px;display:grid;place-items:center;color:var(--cyan);background:linear-gradient(135deg,#3ee0ff22,#9b7bff22);border:1px solid #3ee0ff44;box-shadow:0 0 24px #3ee0ff22}
.title{font-size:20px;font-weight:650;letter-spacing:-.01em}
.grow{flex:1;min-width:0}
.chip{display:inline-flex;align-items:center;gap:7px;padding:6px 11px;border-radius:999px;font-size:12px;font-weight:600;border:1px solid var(--line);background:#0b1220;white-space:nowrap}
.dot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 10px var(--green)}
.dot.warn{background:var(--amber);box-shadow:0 0 10px var(--amber)} .dot.bad{background:var(--red);box-shadow:0 0 10px var(--red)}
.pulse{animation:pulse 2.4s ease-in-out infinite}
@keyframes pulse{50%{opacity:.35}}
.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}
@container (max-width:900px){.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.cols{grid-template-columns:1fr!important}}
@container (max-width:460px){.kpis{grid-template-columns:1fr}}
.ringrow{display:flex;align-items:center;gap:14px}
.ring{position:relative;width:92px;height:92px;flex:none}
.ring svg{width:100%;height:100%;transform:rotate(-90deg)}
.ring .v{position:absolute;inset:0;display:grid;place-items:center;text-align:center;line-height:1.05}
.ring .v b{font-size:24px;font-weight:700} .ring .v span{font-size:10px;color:var(--dim);letter-spacing:.08em;text-transform:uppercase}
.arc{transition:stroke-dashoffset 1s cubic-bezier(.2,.8,.2,1)}
.legend{display:grid;gap:6px;font-size:12px}
.legend i{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:7px;vertical-align:middle}
.big{font-size:26px;font-weight:700;letter-spacing:-.02em} .unit{font-size:12px;color:var(--dim);margin-left:3px;font-weight:500}
.tp{display:flex;gap:18px;align-items:baseline;margin-bottom:6px}
.tp .lab{font-size:10px;letter-spacing:.12em;color:var(--dim);text-transform:uppercase;display:block;margin-bottom:2px}
svg.spark{width:100%;height:64px;display:block;overflow:visible}
.bar{height:8px;border-radius:99px;background:#1a2438;overflow:hidden}
.bar>i{display:block;height:100%;border-radius:99px;transition:width .8s}
.poe{display:grid;gap:10px}
.poe .row{display:grid;gap:5px}
.poe .row div:first-child{display:flex;justify-content:space-between;font-size:12px}
.mapwrap{overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:thin}
.map{width:100%;display:block}
.map .node rect{fill:#0d1626;stroke:var(--line)}
.map .node.off rect{stroke:var(--red)}
.map .node .ic{color:var(--cyan)} .map .node.ap .ic{color:var(--violet)} .map .node.gw .ic{color:var(--amber)}
.map text{fill:var(--text);font-size:12px} .map text.sub{fill:var(--dim);font-size:10.5px}
.map .link{fill:none;stroke:#3ee0ff55;stroke-width:1.6}
.map .flow{fill:none;stroke:var(--cyan);stroke-width:2;stroke-dasharray:4 14;animation:flow 1.6s linear infinite;filter:drop-shadow(0 0 3px #3ee0ff)}
.map .link.down{stroke:var(--red);stroke-dasharray:4 4}
.map .lt{fill:var(--dim);font-size:10px}
.map .cl circle{fill:#9b7bff22;stroke:#9b7bff88}
.map .cl text{fill:var(--violet);font-size:11px;font-weight:700}
@keyframes flow{to{stroke-dashoffset:-36}}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.ap{display:grid;gap:9px;padding:10px 0;border-top:1px solid var(--line)} .ap:first-of-type{border-top:0;padding-top:0}
.ap .t{display:flex;align-items:center;gap:9px}
.ap .t .ic{color:var(--violet);display:flex}
.radio{display:grid;grid-template-columns:62px 1fr 44px;gap:10px;align-items:center;font-size:12px}
.radio .meta{font-size:10.5px;color:var(--dim)}
.sw{padding:10px 0;border-top:1px solid var(--line)} .sw:first-of-type{border-top:0;padding-top:0}
.sw .t{display:flex;align-items:center;gap:9px;margin-bottom:9px} .sw .t .ic{color:var(--cyan);display:flex}
.ports{display:grid;grid-template-columns:repeat(auto-fill,minmax(30px,1fr));gap:6px}
.port{height:30px;border-radius:7px;border:1px solid var(--line);background:#0a111e;display:grid;place-items:center;font-size:10px;color:var(--dim);position:relative;cursor:default}
.port.up{border-color:#3dffa288;color:var(--text);background:linear-gradient(180deg,#3dffa21f,#3dffa208)}
.port.up.s100{border-color:#ffc24a88;background:linear-gradient(180deg,#ffc24a1f,#ffc24a08)}
.port.uplink{border-color:var(--cyan);box-shadow:0 0 10px #3ee0ff44 inset}
.port .bolt{position:absolute;top:1px;right:3px;font-size:8px;color:var(--amber)}
.plegend{display:flex;gap:12px;flex-wrap:wrap;font-size:11px;color:var(--dim);margin-top:10px}
.plegend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:-1px;border:1px solid}
.talk{display:grid;grid-template-columns:22px minmax(0,1.3fr) minmax(0,1fr) 92px;gap:10px;align-items:center;padding:7px 0;border-top:1px solid var(--line);font-size:13px}
.talk:first-of-type{border-top:0}
.talk .ic{color:var(--dim);display:flex} .talk .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.talk .r{text-align:right}
.empty{padding:28px;text-align:center;color:var(--dim)}
`;

class InstantOnCard extends HTMLElement {
  static getStubConfig() { return {}; }
  static getConfigElement() { return null; }

  setConfig(config) {
    this._config = { sections: ALL_SECTIONS, ...config };
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card><div class="wrap"><div class="empty">Loading Instant On…</div></div></ha-card>`;
    }
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._refresh();
  }

  connectedCallback() {
    this._timer = setInterval(() => this._refresh(), REFRESH_MS);
    this._tick = setInterval(() => this._updateAgo(), 5000);
    if (this._hass) this._refresh();
  }
  disconnectedCallback() { clearInterval(this._timer); clearInterval(this._tick); }
  getCardSize() { return 14; }
  getGridOptions() { return { columns: "full", min_columns: 6 }; }

  async _refresh() {
    if (!this._hass || this._busy) return;
    this._busy = true;
    try {
      const data = await this._hass.callWS({ type: "instant_on/overview" });
      const want = this._config.site;
      const site = (data.sites || []).find((s) => !want || s.name === want || s.id === String(want)) || (data.sites || [])[0];
      this._site = site;
      if (site && (!this._histAt || Date.now() - this._histAt > HISTORY_MS)) await this._loadHistory(site);
      this._render();
    } catch (e) {
      this._error = e && (e.message || e.code) ? `${e.code || ""} ${e.message || ""}`.trim() : String(e);
      this._render();
    } finally {
      this._busy = false;
    }
  }

  async _loadHistory(site) {
    const ids = Object.values(site.entities || {}).filter(Boolean);
    if (!ids.length) return;
    const end = new Date(), start = new Date(end - 24 * 3600 * 1000);
    try {
      const h = await this._hass.callWS({
        type: "history/history_during_period", start_time: start.toISOString(), end_time: end.toISOString(),
        entity_ids: ids, minimal_response: true, no_attributes: true, significant_changes_only: false,
      });
      const series = {};
      for (const [key, id] of Object.entries(site.entities)) {
        series[key] = (h[id] || []).map((p) => [(p.lu ?? p.lc) * 1000, parseFloat(p.s)]).filter((p) => !isNaN(p[1]));
      }
      this._hist = series;
      this._histAt = Date.now();
    } catch (e) { /* history is optional */ }
  }

  _updateAgo() {
    const el = this.shadowRoot && this.shadowRoot.getElementById("ago");
    if (el && this._site) el.textContent = `updated ${ago(this._site.updated)}`;
  }

  _render() {
    const root = this.shadowRoot.querySelector(".wrap");
    const s = this._site;
    if (!s) {
      root.innerHTML = `<div class="empty">${this._error ? `Couldn't load Instant On data: ${esc(this._error)}` : "No Instant On site found. Is the integration set up?"}</div>`;
      return;
    }
    const parts = { header: () => this._header(s), kpis: () => this._kpis(s), map: () => this._map(s), aps: null, switches: null, talkers: () => this._talkers(s) };
    const secs = this._config.sections;
    let html = "";
    for (let i = 0; i < secs.length; i++) {
      const k = secs[i];
      // Put APs and switches side by side when both are shown next to each other.
      if ((k === "aps" && secs[i + 1] === "switches") || (k === "switches" && secs[i + 1] === "aps")) {
        html += `<div class="cols">${this._aps(s)}${this._switches(s)}</div>`;
        i++;
      } else if (k === "aps") html += this._aps(s);
      else if (k === "switches") html += this._switches(s);
      else if (parts[k]) html += parts[k]();
    }
    root.innerHTML = html;
    // Animate rings from empty on first paint.
    requestAnimationFrame(() => root.querySelectorAll(".arc[data-off]").forEach((a) => a.setAttribute("stroke-dashoffset", a.dataset.off)));
  }

  _status(s) {
    const offline = s.devices.filter((d) => !d.online).length;
    if (s.alerts.major || offline) return ["bad", offline ? `${offline} device${offline > 1 ? "s" : ""} offline` : `${s.alerts.major} major alert${s.alerts.major > 1 ? "s" : ""}`];
    if (s.alerts.total) return ["warn", `${s.alerts.total} active alert${s.alerts.total > 1 ? "s" : ""}`];
    return ["ok", "All systems nominal"];
  }

  _header(s) {
    const [cls, text] = this._status(s);
    const fw = s.devices.filter((d) => d.up_to_date === false).length;
    return `<div class="head">
      <div class="logo">${icon("accessPoint", 24)}</div>
      <div class="grow"><div class="title">Instant On · ${esc(s.name)}</div>
        <div class="small dim mono"><span id="ago">updated ${ago(s.updated)}</span> · ${s.devices.length} devices${s.gateway ? ` · via ${esc(s.gateway)}` : ""}${fw ? ` · ${fw} firmware update${fw > 1 ? "s" : ""}` : ""}</div></div>
      <span class="chip"><span class="dot ${cls === "ok" ? "" : cls} pulse"></span>${esc(text)}</span>
    </div>`;
  }

  _ring(segments, center, label, size = 92) {
    const r = 40, c = 2 * Math.PI * r;
    let acc = 0, arcs = "";
    for (const [frac, color] of segments) {
      const len = Math.max(0, Math.min(1, frac)) * c;
      arcs += `<circle class="arc" cx="50" cy="50" r="${r}" fill="none" stroke="${color}" stroke-width="9" stroke-linecap="round"
        stroke-dasharray="${len} ${c}" stroke-dashoffset="${-acc}" style="filter:drop-shadow(0 0 4px ${color})"/>`;
      acc += len;
    }
    return `<div class="ring" style="width:${size}px;height:${size}px"><svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="${r}" fill="none" stroke="#1a2438" stroke-width="9"/>${arcs}</svg>
      <div class="v"><div><b class="mono">${center}</b><br><span>${label}</span></div></div></div>`;
  }

  _spark(points, color, id, fill = true, h = 64) {
    if (!points || points.length < 2) return `<svg class="spark" viewBox="0 0 300 ${h}"><text x="0" y="${h / 2}" fill="#7f8da8" font-size="11">collecting history…</text></svg>`;
    const t0 = points[0][0], t1 = Date.now(), max = Math.max(...points.map((p) => p[1]), 0.001) * 1.15;
    const X = (t) => ((t - t0) / (t1 - t0 || 1)) * 300, Y = (v) => h - (v / max) * (h - 4) - 2;
    let d = "";
    points.forEach((p, i) => { d += `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`; });
    d += `L300,${Y(points[points.length - 1][1]).toFixed(1)}`;
    return `<svg class="spark" viewBox="0 0 300 ${h}" preserveAspectRatio="none">
      <defs><linearGradient id="g${id}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${color}" stop-opacity=".35"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>
      ${fill ? `<path d="${d}L300,${h}L0,${h}Z" fill="url(#g${id})"/>` : ""}
      <path d="${d}" fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke" style="filter:drop-shadow(0 0 3px ${color})"/></svg>`;
  }

  _kpis(s) {
    const H = this._hist || {};
    const score = s.score ?? 0;
    const scoreColor = score >= 80 ? "var(--green)" : score >= 50 ? "var(--amber)" : "var(--red)";
    const c = s.clients, tot = Math.max(c.total, 1);
    const [dn, dnu] = fmtRate(s.throughput.down), [up, upu] = fmtRate(s.throughput.up);
    const sw = s.devices.filter((d) => d.poe);
    const used = sw.reduce((a, d) => a + d.poe.used, 0), budget = sw.reduce((a, d) => a + d.poe.budget, 0);
    const online = s.devices.filter((d) => d.online).length;
    return `<div class="kpis">
      <div class="panel"><h3>Site health <span class="mono">${online}/${s.devices.length} up</span></h3><div class="ringrow">
        ${this._ring([[score / 100, scoreColor]], score, "score")}
        <div class="legend"><div><i style="background:${scoreColor}"></i>${esc((s.health || "").replace(/^\w/, (m) => m.toUpperCase()))}</div>
          <div class="dim small">${esc((s.health_reason || "").replace(/([A-Z])/g, " $1").toLowerCase())}</div>
          <div class="small"><span class="mono">${s.alerts.total}</span> <span class="dim">active alerts</span></div></div></div>
        ${this._spark(H.health_score, "#3dffa2", "hs", false, 34)}</div>
      <div class="panel"><h3>Clients <span class="mono">${c.total}</span></h3><div class="ringrow">
        ${this._ring([[c.wireless / tot, "var(--violet)"], [c.wired / tot, "var(--cyan)"]], c.total, "online")}
        <div class="legend"><div><i style="background:var(--violet)"></i><span class="mono">${c.wireless}</span> wireless</div>
          <div><i style="background:var(--cyan)"></i><span class="mono">${c.wired}</span> wired</div>
          <div class="dim small mono">${Object.entries(c.bands).filter(([, n]) => n).map(([b, n]) => `${band(b)} ${n}`).join(" · ")}</div></div></div>
        ${this._spark(H.clients, "#9b7bff", "cl", false, 34)}</div>
      <div class="panel"><h3>Throughput <span>24 h</span></h3>
        <div class="tp"><div><span class="lab">↓ Down</span><span class="big mono" style="color:var(--green)">${dn}</span><span class="unit">${dnu}</span></div>
          <div><span class="lab">↑ Up</span><span class="big mono" style="color:var(--violet)">${up}</span><span class="unit">${upu}</span></div></div>
        <div style="position:relative">${this._spark(H.throughput_down, "#3dffa2", "dn")}<div style="position:absolute;inset:0">${this._spark(H.throughput_up, "#9b7bff", "up", false)}</div></div></div>
      <div class="panel"><h3>PoE budget <span class="mono">${used} / ${budget} W</span></h3><div class="poe">
        ${sw.length ? sw.map((d) => { const p = Math.round((d.poe.used / d.poe.budget) * 100); return `<div class="row"><div><span>${esc(d.name)}</span><span class="mono dim">${d.poe.used} W · ${p}%</span></div>
          <div class="bar"><i style="width:${p}%;background:linear-gradient(90deg,var(--amber),${p > 80 ? "var(--red)" : "#ffde8a"})"></i></div></div>`; }).join("") : `<div class="dim small">No PoE switches</div>`}
        </div></div>
    </div>`;
  }

  _map(s) {
    const devs = s.devices, ids = new Set(devs.map((d) => d.id));
    const kids = {};
    const GW = "__gw__";
    for (const d of devs) {
      const p = d.uplink && ids.has(d.uplink) ? d.uplink : GW;
      (kids[p] = kids[p] || []).push(d);
    }
    for (const k in kids) kids[k].sort((a, b) => (a.type === b.type ? (a.name || "").localeCompare(b.name || "") : a.type === "switch" ? -1 : 1));
    // Tidy-tree layout: leaves get consecutive rows, parents centre on their children.
    const pos = {}, ROW = 66, COLW = 250, NODE_W = 196, NODE_H = 46;
    let row = 0, maxDepth = 0;
    const place = (id, depth) => {
      maxDepth = Math.max(maxDepth, depth);
      const ch = kids[id] || [];
      if (!ch.length) { pos[id] = { x: depth, y: row++ }; return; }
      ch.forEach((c) => place(c.id, depth + 1));
      pos[id] = { x: depth, y: (pos[ch[0].id].y + pos[ch[ch.length - 1].id].y) / 2 };
    };
    place(GW, 0);
    const W = (maxDepth + 1) * COLW + 70, H = Math.max(row, 1) * ROW + 10;
    const px = (p) => 10 + p.x * COLW, py = (p) => 10 + p.y * ROW;
    let links = "", nodes = "";
    const byId = Object.fromEntries(devs.map((d) => [d.id, d]));
    for (const d of devs) {
      const parentId = d.uplink && ids.has(d.uplink) ? d.uplink : GW;
      const a = pos[parentId], b = pos[d.id];
      const x1 = px(a) + NODE_W, y1 = py(a) + NODE_H / 2, x2 = px(b), y2 = py(b) + NODE_H / 2, mx = (x1 + x2) / 2;
      const path = `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
      const parent = byId[parentId];
      const port = parent && (parent.ports || []).find((p) => p.peer === d.name);
      links += `<path class="link ${d.online ? "" : "down"}" d="${path}"/>${d.online ? `<path class="flow" d="${path}" style="animation-duration:${(1.2 + Math.random() * 1.2).toFixed(2)}s"/>` : ""}`;
      if (port) links += `<text class="lt mono" x="${x2 - 6}" y="${y2 - 6}" text-anchor="end">${port.n ? `p${port.n} · ` : ""}${speed(port.speed)}</text>`;
    }
    const node = (id, kind, name, sub, online = true, clients = null) => {
      const p = pos[id], x = px(p), y = py(p), parent = (kids[id] || []).length > 0;
      // Parents show their client count in the subtitle so nothing sits on the links.
      if (clients && parent) sub += ` · ${clients} clients`;
      let n = `<g class="node ${kind === "accessPoint" ? "ap" : kind === "gateway" ? "gw" : ""} ${online ? "" : "off"}" transform="translate(${x},${y})">
        <rect width="${NODE_W}" height="${NODE_H}" rx="11"/><g class="ic" transform="translate(11,12)">${icon(kind, 22)}</g>
        <text x="42" y="20">${esc((name || "").length > 24 ? name.slice(0, 23) + "…" : name || "")}</text><text class="sub mono" x="42" y="35">${esc(sub)}</text>
        <circle cx="${NODE_W - 12}" cy="12" r="3.5" fill="${online ? "var(--green)" : "var(--red)"}" style="filter:drop-shadow(0 0 4px ${online ? "#3dffa2" : "#ff5c7a"})"/></g>`;
      if (clients && !parent) {
        const cx = x + NODE_W + 34, cy = y + NODE_H / 2, r = Math.min(20, 11 + Math.sqrt(clients) * 1.6);
        n += `<path class="link" d="M${x + NODE_W},${cy} L${cx - r},${cy}" style="stroke-dasharray:2 3"/><g class="cl"><circle cx="${cx}" cy="${cy}" r="${r}"/>
          <text x="${cx}" y="${cy + 4}" text-anchor="middle" class="mono">${clients}</text></g>`;
      }
      return n;
    };
    nodes += node(GW, "gateway", s.gateway || "Gateway", "internet uplink");
    for (const d of devs) {
      const sub = d.type === "accessPoint" && d.radios ? d.radios.map((r) => `ch ${r.channel}`).join(" · ") : `${d.model || ""}${d.ports ? ` · ${d.ports.filter((p) => p.up).length}/${d.ports.length} up` : ""}`;
      nodes += node(d.id, d.type, d.name, sub, d.online, d.clients);
    }
    return `<div class="panel"><h3>Network map <span>${devs.filter((d) => d.type === "switch").length} switches · ${devs.filter((d) => d.type === "accessPoint").length} access points</span></h3>
      <div class="mapwrap"><svg class="map" viewBox="0 0 ${W} ${H}" style="max-height:${H * 1.15}px;min-width:${Math.round(W * 0.72)}px">${links}${nodes}</svg></div></div>`;
  }

  _aps(s) {
    const aps = s.devices.filter((d) => d.type === "accessPoint");
    if (!aps.length) return "";
    return `<div class="panel"><h3>Access points <span class="mono">${aps.reduce((a, d) => a + d.clients, 0)} clients</span></h3>
      ${aps.map((d) => `<div class="ap"><div class="t"><span class="ic">${icon("accessPoint", 18)}</span><b class="grow">${esc(d.name)}</b>
        <span class="small dim mono">${esc(d.model || "")} · up ${fmtUptime(d.uptime)}</span><span class="dot ${d.online ? "" : "bad"}"></span></div>
        ${(d.radios || []).map((r) => `<div class="radio"><div><b>${band(r.band)}</b><div class="meta mono">ch ${r.channel} · ${String(r.width || "").replace("mhz", "")}</div></div>
          <div><div class="bar"><i style="width:${Math.max(2, r.util || 0)}%;background:${utilColor(r.util || 0)};box-shadow:0 0 8px ${utilColor(r.util || 0)}"></i></div>
          <div class="meta mono" style="margin-top:4px">${r.util ?? 0}% airtime · ${r.clients ?? 0} clients${r.power ? ` · ${r.power} dBm` : ""}</div></div>
          <div class="mono" style="text-align:right;font-size:15px;font-weight:700">${r.clients ?? 0}</div></div>`).join("")}</div>`).join("")}</div>`;
  }

  _switches(s) {
    const sws = s.devices.filter((d) => d.type === "switch");
    if (!sws.length) return "";
    return `<div class="panel"><h3>Switches <span class="mono">${sws.reduce((a, d) => a + (d.ports || []).filter((p) => p.up).length, 0)} links up</span></h3>
      ${sws.map((d) => `<div class="sw"><div class="t"><span class="ic">${icon("switch", 18)}</span><b class="grow">${esc(d.name)}</b>
        <span class="small dim mono">${esc(d.model || "")}${d.poe ? ` · ${d.poe.used} W` : ""} · up ${fmtUptime(d.uptime)}</span><span class="dot ${d.online ? "" : "bad"}"></span></div>
        <div class="ports">${(d.ports || []).map((p) => {
          const tip = [`Port ${p.n}`, p.up ? `${speed(p.speed)} link` : "no link", p.peer, p.poe_mw ? `PoE ${(p.poe_mw / 1000).toFixed(1)} W` : "", p.up && (p.down || p.up_bps) ? `↓${rate(p.down)} ↑${rate(p.up_bps)}` : ""].filter(Boolean).join(" · ");
          return `<div class="port ${p.up ? "up" : ""} ${p.speed === "mbps100" || p.speed === "mbps10" ? "s100" : ""} ${p.uplink ? "uplink" : ""}" title="${esc(tip)}">${p.poe_mw ? '<span class="bolt">⚡</span>' : ""}<span class="mono">${p.n}</span></div>`;
        }).join("")}</div></div>`).join("")}
      <div class="plegend"><span><i style="border-color:#3dffa2;background:#3dffa21f"></i>1 Gb+</span><span><i style="border-color:#ffc24a;background:#ffc24a1f"></i>100 Mb</span>
        <span><i style="border-color:var(--cyan)"></i>uplink</span><span>⚡ PoE</span><span><i style="border-color:var(--line)"></i>no link</span></div></div>`;
  }

  _talkers(s) {
    const t = (s.top_clients || []).filter((c) => c.down + c.up > 0);
    if (!t.length) return "";
    const max = Math.max(...t.map((c) => c.down + c.up), 1);
    return `<div class="panel"><h3>Top talkers <span>right now</span></h3>
      ${t.map((c) => `<div class="talk"><span class="ic">${icon(c.type === "wireless" ? "client" : "switch", 16)}</span>
        <div class="nm">${esc(c.name)}${c.others ? ` <span class="dim">+${c.others} on port</span>` : ""}<div class="small dim">${esc(c.via || "")}${c.port ? ` · port ${c.port}` : ""}${c.band ? ` · ${band(c.band)}` : ""}</div></div>
        <div><div class="bar" style="height:6px"><i style="width:${((c.down + c.up) / max) * 100}%;background:linear-gradient(90deg,var(--green),var(--cyan))"></i></div></div>
        <div class="r mono small"><span style="color:var(--green)">↓ ${rate(c.down)}</span><br><span style="color:var(--violet)">↑ ${rate(c.up)}</span></div></div>`).join("")}</div>`;
  }
}

if (!customElements.get("instant-on-card")) {
  customElements.define("instant-on-card", InstantOnCard);
  window.customCards = window.customCards || [];
  window.customCards.push({ type: "instant-on-card", name: "Instant On", description: "Mission-control view of your HPE Instant On network", preview: true });
  console.info(`%c INSTANT-ON-CARD %c ${VERSION} `, "background:#3ee0ff;color:#070b14;font-weight:700", "background:#0e1524;color:#3ee0ff");
}
