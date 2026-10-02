/* LoW Draftboard frontend. Vanilla JS, no build step.
   The server owns the truth (F-44): every command goes to /api/command, every
   mutation returns the new state, and all views poll /api/state every 3 s,
   re-rendering only when `rev` changed. The DOM is built with textContent only
   (data never goes in as HTML strings) and board cards are keyed by player id, so an
   update never reloads images. */
"use strict";

const $ = s => document.querySelector(s);
const ESPN_CDN = id => `https://a.espncdn.com/i/headshots/nba/players/full/${encodeURIComponent(id)}.png`;
const POLL_MS = 3000, FADE_MS = 420;

let PLAYERS = [], BY_ID = new Map(), PLAYERS_REV = null;
let CATEGORIES = ["PTS","TPM","REB","AST","STL","BLK","FG","FT"];   // active, config order
let STATE = null;
let view = "board", sortBy = "espn", layout = "cards";
const fading = new Set();          // just-taken player ids, still shown while they fade out
const cardEls = new Map(), rowEls = new Map(), logEls = new Map();

/* ---------------------------------------------------------------- DOM helper */
function h(tag, attrs, ...kids){
  const el = document.createElement(tag);
  for(const [k,v] of Object.entries(attrs||{})){
    if(v == null || v === false) continue;
    if(k === "class") el.className = v;
    else if(k === "text") el.textContent = v;
    else if(k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if(k in el && k !== "list") el[k] = v;
    else el.setAttribute(k, v);
  }
  for(const c of kids.flat()){
    if(c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
const money = v => (v == null || v === "") ? "–" : "$" + Math.round(v);
const initials = n => (n||"?").split(/\s+/).filter(Boolean).map(w => w[0]).slice(0,2).join("").toUpperCase();

/* Headshots (F-15): local cache, then the ESPN CDN, then initials. */
function photo(id, name, cls){
  const img = h("img", {class: cls, alt: "", loading: "lazy", decoding: "async"});
  let step = 0;
  img.addEventListener("error", () => {
    step++;
    if(step === 1){ img.src = ESPN_CDN(id); return; }
    img.replaceWith(h("div", {class: cls.replace("ph","ini"), text: initials(name), "aria-hidden": "true"}));
  });
  img.src = `/headshots/${encodeURIComponent(id)}.png`;
  return img;
}

/* ---------------------------------------------------------------- matching for the live filter
   Only used to filter the board while typing (F-31). The server parser decides. */
const norm = s => (s||"").normalize("NFKD").replace(/[̀-ͯ]/g,"").toLowerCase()
  .replace(/['’`.]/g,"").replace(/[^a-z0-9]+/g," ").replace(/\b(jr|sr|ii|iii|iv)\b/g," ")
  .replace(/\s+/g," ").trim();
/* Same wake-word pattern as app/parser.py WAKE_CORE. */
const WAKE = /^(?:(?:hey|ok|okay|okey|okee|okie|oki|uh|um|so)\s+)*(?:draft\s?bot|(?:ok(?:ay|ey|ee|ie|i)?\s?)?ban+[aei]+n+[aei]*s?)\b\s*/;
function bigrams(s){ const t = " "+s+" ", o = []; for(let i=0;i<t.length-1;i++) o.push(t.slice(i,i+2)); return o; }
function dice(a,b){
  if(!a || !b) return 0; if(a === b) return 1;
  const A = bigrams(a), B = bigrams(b), m = new Map(); let hit = 0;
  A.forEach(g => m.set(g, (m.get(g)||0)+1));
  B.forEach(g => { const c = m.get(g); if(c > 0){ hit++; m.set(g, c-1); } });
  return 2*hit/(A.length+B.length);
}
const PHON = [["tch","ch"],["sch","sh"],["ch","c"],["ck","k"],["ph","f"],["kh","k"],["gh","g"],
  ["th","t"],["sh","s"],["ts","s"],["z","s"],["k","c"],["q","c"],["x","cs"],["y","i"],["w","v"]];
function phon(s){ s = (s||"").replace(/ /g,""); for(const [a,b] of PHON) s = s.split(a).join(b); return s.replace(/(.)\1+/g,"$1"); }
function keyOf(name){
  const n = norm(name), t = n.split(" ");
  const lasts = t.length > 1 ? [...t.slice(1), t.slice(1).join("")] : [n];
  return {n, lasts: [...new Set(lasts)], ph: phon(n)};
}
function score(q, k){
  const qc = q.replace(/ /g,""), qp = phon(q);
  let s = dice(q, k.n);
  for(const l of k.lasts) s = Math.max(s, .98*dice(q,l), .97*dice(qc,l), .95*dice(qp, phon(l)));
  s = Math.max(s, .96*dice(qp, k.ph));
  if(qc.length >= 3 && (k.n.startsWith(q) || k.lasts.some(l => l.startsWith(qc)))) s = Math.max(s, .8 + Math.min(qc.length,8)/40);
  return s;
}
/* The part before to/mine/for is the name, so the board filters mid-command.
   "nominate <player>" (or "nm") filters on the player; "sold to <team>" and the short
   "<team> for <amount>" name no player. Keywords as in app/parser.py parse_command. */
const NOMINATE = /^(?:nomin\w*|nm)\b\s*/;
function isTeamText(s){
  if(!STATE || !s) return false;
  const al = STATE.aliases || {};
  return STATE.teams.some(t => norm(t.name) === s || (al[t.name] || []).some(a => norm(a) === s));
}
function nameFragment(raw){
  let t = norm(String(raw||"").replace(/\$/g," ")).replace(WAKE,"").trim();
  if(/^(undo|skip|turn|clock|beurt|sold|soul|sol|sole|solde|pass|next|go back|back|previous|prev)\b/.test(t)) return "";
  t = t.replace(NOMINATE, "");
  const name = t.split(/\s+(?:to|mine|for|at)(?:\s+|$)/)[0].trim();
  return isTeamText(name) || isTeamText(name.replace(/\s+\d+$/, "")) ? "" : name;
}

/* ---------------------------------------------------------------- server */
async function api(url, body){
  const opt = body === undefined ? {cache: "no-store"} :
    {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)};
  let r;
  try { r = await fetch(url, opt); }
  catch(e){ say("Server unreachable. Retrying…", "err"); throw e; }
  let data = {};
  try { data = await r.json(); } catch(e){ data = {ok:false, kind:"error", message:`Server error ${r.status}.`}; }
  if(!r.ok && !data.message) data.message = data.detail ? String(data.detail) : `Error ${r.status}.`;
  if(!r.ok){ data.ok = false; data.kind = data.kind || "error"; }
  return data;
}

async function loadPlayers(){
  const d = await api("/api/players");
  PLAYERS = (d.players||[]).map(p => ({...p, _k: keyOf(p.name)}));
  BY_ID = new Map(PLAYERS.map(p => [String(p.id), p]));
  PLAYERS_REV = d.rev;
  if(Array.isArray(d.categories)) CATEGORIES = d.categories;
  cardEls.clear(); rowEls.clear();
  $("#board").replaceChildren(); $("#list tbody").replaceChildren();
}

async function poll(){
  try {
    const s = await api("/api/state");
    if(s.players_rev !== PLAYERS_REV) await loadPlayers();
    if(!STATE || s.rev !== STATE.rev || s.players_rev !== STATE.players_rev) applyState(s);
    else { STATE.voice = s.voice; renderVoice(); }   // "voice off" is time-based, no rev bump
    if($("#status").classList.contains("err") && $("#status").textContent.startsWith("Server unreachable")) say("");
  } catch(e){ /* message already shown */ }
}

/* New state from the server. Players that became taken fade out first (F-17),
   on every client, because this runs for polled state too. */
function applyState(s){
  if(!s || !s.teams) return;
  if(STATE){
    const before = new Set(STATE.picks.map(p => String(p.player_id)));
    for(const p of s.picks){
      const id = String(p.player_id);
      if(!before.has(id)){
        fading.add(id);
        setTimeout(() => { fading.delete(id); renderPlayers(); }, FADE_MS);
      }
    }
  }
  STATE = s;
  render();
}

/* ---------------------------------------------------------------- messages and prompts */
function say(msg, cls){ const s = $("#status"); s.textContent = msg || ""; s.className = cls || ""; }
function clearPrompt(){ const b = $("#prompt"); b.replaceChildren(); delete b.dataset.action; }

/* fromPrompt: a rejected pick keeps the prompt open so the entry can be corrected. */
function handle(res, fromPrompt = false){
  if(!res) return;
  if(fromPrompt && !res.ok && res.kind === "error"){
    say(res.message || "Pick rejected.", "err");
    const amt = document.querySelector("#prompt input");
    if(amt){ amt.focus(); amt.select(); }
    return;
  }
  clearPrompt();
  if(res.state) applyState(res.state);
  switch(res.kind){
    case "pick": say(res.message, "ok"); break;
    case "undo": case "turn": case "settings": case "reset": case "voice":
    case "nominate": case "unblock": say(res.message, "ok"); break;
    case "need_amount": say(res.message, "ask"); amountPrompt(res.player, res.team); break;
    case "ambiguous": say(res.message, "ask");
      candidatePrompt(res.candidates, res.team, res.amount, null, res.action); break;
    case "confirm_undo": confirmUndo(res.picks, {count: res.count}); break;
    case "search": case "empty": break;
    default:
      say(res.message || "Something went wrong.", "err");
      if(res.candidates && res.candidates.length) candidatePrompt(res.candidates, null, null, "Closest:", res.action);
      else if(res.team_candidates && res.team_candidates.length) teamPrompt(res.team_candidates, res.command, {expect_block: res.block_player_id, expect_player: res.player_id});
  }
}

/* Team not recognised: the closest teams as buttons. Each one runs the same command
   again with `team` set (no rebuilt text), so player and amount stay as typed. A failed
   "sold" also names the block player it was heard for (block_player_id, "" = nobody),
   a failed pick its heard player (player_id); sent back as expect_block/expect_player,
   the server refuses the click when that changed since (stale button, any screen). */
function teamButtons(cands, run){
  return cands.map(c => h("button", {type: "button", class: "cand", onclick: () => run(c)},
    c.team, " ", h("small", {text: `${Math.round(c.score*100)}%`})));
}
function teamPrompt(cands, command, pins){
  const box = $("#prompt");
  box.append(h("span", {class: "muted", text: "Team:"}),
    ...teamButtons(cands, async c => {
      const res = await api("/api/command", {text: command, team: c.team, ...pins, source: "click"});
      if(res.ok || ["need_amount", "ambiguous"].includes(res.kind)) $("#cmd").value = "";
      handle(res);
      renderPlayers();
    }),
    h("button", {type: "button", text: "Cancel", onclick: () => { clearPrompt(); say(""); }}));
}

/* action "nominate": a click puts that player on the block instead of picking him. */
function candidatePrompt(cands, team, amount, label, action){
  const box = $("#prompt");
  if(action === "nominate") box.dataset.action = "nominate";
  box.append(h("span", {class: "muted", text: label || (action === "nominate" ? "Nominate:" : "Pick one:")}));
  for(const c of cands){
    box.append(h("button", {type: "button", class: "cand", onclick: async () => {
        if(action === "nominate"){
          handle(await api("/api/nominate", {player_id: c.player.id, source: "click"}));
        }
        else if(team && amount != null){
          const res = await api("/api/pick", {player_id: c.player.id, team, price: amount, source: "click"});
          if(!res.ok && res.kind === "error"){ amountPrompt(c.player, team, amount); handle(res, true); }
          else handle(res);
        }
        else { clearPrompt(); amountPrompt(c.player, team); }
      }},
      c.player.name, " ", h("small", {text: `${Math.round(c.score*100)}%`})));
  }
  box.append(h("button", {type: "button", text: "Cancel", onclick: () => { clearPrompt(); say(""); }}));
}

/* Amount prompt, pre-filled with player and team; Enter confirms, Escape cancels.
   opts.source is stored with the pick; opts.onDone(res) runs after a stored pick. */
function amountPrompt(player, team, amount, opts = {}){
  clearPrompt();
  const sel = h("select", {"aria-label": "Team"},
    h("option", {value: "", text: "team…"}),
    (STATE ? STATE.teams : []).map(t => h("option", {value: t.name, disabled: t.full,
      text: `${t.name} (max ${t.max_bid})`})));
  sel.value = team || "";
  const amt = h("input", {type: "number", min: "1", step: "1", placeholder: "$", "aria-label": "Amount",
                          value: amount != null ? String(amount) : ""});
  const go = async () => {
    const price = parseInt(amt.value, 10);
    if(!sel.value){ sel.focus(); return; }
    if(!(price > 0)){ amt.focus(); return; }
    const res = await api("/api/pick", {player_id: player.id, team: sel.value, price,
                                        source: opts.source || "click"});
    handle(res, true);
    if(res.ok && opts.onDone) opts.onDone(res);
    if(!$("#prompt").children.length) $("#cmd").focus();
  };
  const cancel = () => { clearPrompt(); say(""); $("#cmd").focus(); };
  for(const el of [sel, amt]) el.addEventListener("keydown", e => {
    if(e.key === "Enter"){ e.preventDefault(); go(); }
    if(e.key === "Escape"){ e.preventDefault(); cancel(); }
  });
  $("#prompt").append(h("span", {class: "who", text: player.name}), h("span", {class: "muted", text: "to"}),
    sel, h("span", {class: "muted", text: "for $"}), amt,
    h("button", {type: "button", class: "primary", text: "Confirm", onclick: go}),
    h("button", {type: "button", text: "Cancel", onclick: cancel}));
  (team ? amt : sel).focus();
}

/* ---------------------------------------------------------------- dialogs */
function confirmDialog({title, body, ok = "OK", danger = false, requireText = null}){
  const dlg = $("#confirmDlg"), inp = $("#confirmInput"), okBtn = $("#confirmOk");
  $("#confirmTitle").textContent = title;
  $("#confirmBody").replaceChildren(...[].concat(body || []));
  okBtn.textContent = ok;
  okBtn.className = danger ? "danger" : "primary";
  inp.hidden = !requireText; inp.value = ""; inp.placeholder = requireText || "";
  okBtn.disabled = !!requireText;
  inp.oninput = () => { okBtn.disabled = requireText ? inp.value !== requireText : false; };
  return new Promise(resolve => {
    const done = v => { dlg.close(); okBtn.onclick = $("#confirmCancel").onclick = dlg.oncancel = null; resolve(v); };
    okBtn.onclick = () => done(requireText ? inp.value === requireText : true);
    $("#confirmCancel").onclick = () => done(false);
    dlg.oncancel = e => { e.preventDefault(); done(false); };
    inp.onkeydown = e => { if(e.key === "Enter"){ e.preventDefault(); if(!okBtn.disabled) okBtn.click(); } };
    dlg.showModal();
    (requireText ? inp : okBtn).focus();
  });
}

const pickLine = p => h("li", {text: `${p.name} → ${p.team}, $${p.price}`});

/* Multi-undo (`undo N` or "back to here"): one confirmation that lists the picks. */
async function confirmUndo(picks, target){
  const yes = await confirmDialog({
    title: `Remove ${picks.length} pick${picks.length === 1 ? "" : "s"}?`,
    body: [h("p", {text: "These picks are removed; turn and budgets go back to before the oldest one."}),
           h("ul", {}, picks.map(pickLine))],
    ok: `Remove ${picks.length}`, danger: true});
  if(!yes){ say("Nothing removed."); return; }
  handle(await api("/api/undo", target));
}

async function backToHere(seq){
  const res = await api("/api/undo/preview", {to_seq: seq});
  if(!res.ok){ say(res.message, "err"); return; }
  confirmUndo(res.picks, {to_seq: seq});
}

/* ---------------------------------------------------------------- voice
   The listener (voice/listen.py) posts "ok banana …" commands with source "voice"; the
   server keeps the latest result in STATE.voice.event, so this banner shows the same
   thing on every screen. A pending result (candidates or a missing amount; undo is
   never done by voice, the server rejects it)
   can be settled with one click on any screen; that marks it resolved everywhere. */
let voiceDismissed = null, voiceShown = null;

function renderVoice(){
  const v = STATE && STATE.voice;
  if(!v) return;
  const btn = $("#voiceBtn");
  btn.className = `voice ${v.status}`;
  btn.setAttribute("aria-pressed", String(!!v.muted));
  $("#voiceLabel").textContent = v.status === "off" ? (v.muted ? "voice off (muted)" : "voice off")
                               : v.status;
  btn.title = (v.status === "off"
      ? "Voice listener not running (py voice/listen.py)."
      : `Voice listener ${v.status}${v.model ? ` · ${v.model}` : ""}.`) +
    (v.muted ? " Click to unmute." : " Click to mute.");
  renderVoiceBar(v.event);
}

/* Marks the event settled on every screen and applies the returned state at once,
   so the banner drops its buttons here without waiting for the next poll. */
async function voiceResolve(ev, message){
  const res = await api("/api/voice/resolve", {id: ev.id, message});
  if(res.state) applyState(res.state);
}
/* Disables the banner's action buttons while a click is in flight (no double pick). */
const voiceLock = on => { for(const b of $("#voicebar").querySelectorAll("button:not(.x)")) b.disabled = on; };

function renderVoiceBar(ev){
  const bar = $("#voicebar");
  if(!ev || ev.id === voiceDismissed){ bar.hidden = true; bar.replaceChildren(); voiceShown = null; return; }
  const key = `${ev.id}|${ev.resolved || ""}`;
  if(key === voiceShown) return;             // unchanged: keep buttons and focus as they are
  voiceShown = key;
  const teamPick = !ev.resolved && !ev.ok && (ev.team_candidates || []).length > 0;
  const pending = teamPick || (!ev.resolved && ["ambiguous", "need_amount"].includes(ev.kind));
  // A team click the server refused settles the banner too, marked "Refused: ..."
  const refused = !!ev.resolved && ev.resolved.startsWith("Refused: ");
  const cls = refused ? "err" : ev.resolved || ev.ok ? "ok" : pending ? "ask" : "err";
  const kids = [h("span", {class: "vtag", text: "Voice"}),
                h("q", {class: "heard", text: ev.heard || ""}),
                h("span", {class: `vres ${cls}`, text: ev.resolved ? (refused ? ev.resolved : `Done: ${ev.resolved}`) : (ev.message || "")})];
  if(teamPick){
    // A click runs the heard command with that team; a follow-up prompt (which player,
    // how much) continues in the command bar, and the banner is settled on every screen.
    kids.push(...teamButtons(ev.team_candidates, async c => {
      voiceLock(true);
      const res = await api("/api/command", {text: ev.command, team: c.team, expect_block: ev.block_player_id,
                                        expect_player: ev.player_id, source: "voice-click"});
      handle(res);
      if(res.ok) await voiceResolve(ev, res.message);
      else if(["ambiguous", "need_amount"].includes(res.kind)) await voiceResolve(ev, `${c.team}: continue in the command bar.`);
      // refused (block or player changed, team renamed): the buttons can never work
      // again, so settle the banner on every screen instead of leaving them hanging
      else await voiceResolve(ev, `Refused: ${res.message || "not done."}`);
    }));
  }
  if(pending && ev.kind === "ambiguous"){
    for(const c of ev.candidates || []) kids.push(h("button", {type: "button", class: "cand",
      onclick: async () => {
        const done = res => { voiceLock(true); return voiceResolve(ev, res.message); };
        if(ev.action === "nominate"){
          voiceLock(true);
          const res = await api("/api/nominate", {player_id: c.player.id, source: "voice"});
          handle(res);
          if(res.ok) await done(res); else voiceLock(false);
        }
        else if(ev.team && ev.amount != null){
          voiceLock(true);
          const res = await api("/api/pick", {player_id: c.player.id, team: ev.team, price: ev.amount, source: "voice"});
          if(res.ok){ handle(res); await done(res); }
          else { voiceLock(false); amountPrompt(c.player, ev.team, ev.amount, {source: "voice", onDone: done}); handle(res, true); }
        } else amountPrompt(c.player, ev.team, null, {source: "voice", onDone: done});
      }}, c.player.name, " ", h("small", {text: `${Math.round(c.score*100)}%`})));
  }
  if(pending && ev.kind === "need_amount" && ev.player){
    kids.push(h("button", {type: "button", class: "primary",
      text: `Enter amount: ${ev.player.name} → ${ev.team}`,
      onclick: () => {
        say(`${ev.player.name} to ${ev.team}: enter the amount.`, "ask");
        amountPrompt(ev.player, ev.team, null, {source: "voice", onDone: res => { voiceLock(true); return voiceResolve(ev, res.message); }});
      }}));
  }
  kids.push(h("button", {type: "button", class: "x", text: "×", title: "Hide on this screen",
    "aria-label": "Dismiss", onclick: () => { voiceDismissed = ev.id; renderVoiceBar(ev); }}));
  bar.className = cls;
  bar.replaceChildren(...kids);
  bar.hidden = false;
}

/* ---------------------------------------------------------------- rendering */
function render(){
  if(!STATE) return;
  document.documentElement.style.setProperty("--nteams", STATE.teams.length || 12);
  const banner = $("#banner");
  banner.hidden = !STATE.error;
  banner.textContent = STATE.error || "";
  renderVoice();
  renderBlock();
  renderHistory();
  if(view === "board"){ renderClock(); renderBudgets(); renderPlayers(); }
  else renderRosters();
}

/* The block (nominated, not yet sold): big on every view, with last season's actual
   stats and the projection per game in the active categories, so the room sees what
   the player is worth. Static per nomination: rebuilt only when the player, the
   nominator or the player pool changes (no headshot reload on every poll). */
const STAT_LABEL = {TPM: "3PM", FG: "FG%", FT: "FT%"};
const LAST_LABEL = "2025-26", PROJ_LABEL = "2026-27p";
const fmtStat = v => (v == null || v === "" || !isFinite(v)) ? "–" : Number(v).toFixed(1);
const fmtPct = v => (v == null || v === "" || !isFinite(v)) ? "–" : Number(v).toFixed(3).replace(/^0(?=\.)/, "");
function statCells(src, pct){
  /* src: {GP, PTS, TPM, ...} per game; pct: {FG, FT}. Null src → all "–". */
  const cells = [src ? (src.GP == null ? "–" : String(Math.round(src.GP))) : "–"];
  for(const c of CATEGORIES){
    if(c === "FG" || c === "FT") cells.push(fmtPct(src ? pct[c] : null));
    else cells.push(fmtStat(src ? src[c] : null));
  }
  return cells;
}
function blockStats(id){
  const pl = BY_ID.get(String(id));
  if(!pl) return h("div", {class: "bstats", hidden: true});
  const last = pl.last || null, pg = pl.pg || null;
  const row = (label, cells, cls) => h("tr", {class: cls},
    h("th", {scope: "row", text: label}), ...cells.map(v => h("td", {text: v})));
  return h("table", {class: "bstats"},
    h("thead", {}, h("tr", {}, h("th", {}), h("th", {scope: "col", text: "GP"}),
      ...CATEGORIES.map(c => h("th", {scope: "col", text: STAT_LABEL[c] || c})))),
    h("tbody", {},
      row(LAST_LABEL, statCells(last, last ? {FG: last.fg_pct, FT: last.ft_pct} : {}), last ? "" : "none"),
      row(PROJ_LABEL, statCells(pg, {FG: pl.fg_pct, FT: pl.ft_pct}), "proj")));
}
let blockShown = null;
function renderBlock(){
  const el = $("#block"), b = STATE.block;
  if(!b){ el.hidden = true; el.replaceChildren(); blockShown = null; return; }
  const key = `${b.player.id}|${b.nominator}|${PLAYERS_REV}`;
  if(key !== blockShown){
    blockShown = key;
    const p = b.player;
    const meta = [(p.pos||"").split("/")[0], p.team, p.value != null ? `value ${money(p.value)}` : null,
                  b.nominator ? `nominated by ${b.nominator}` : null].filter(Boolean).join(" · ");
    el.replaceChildren(
      photo(p.id, p.name, "ph"),
      h("div", {class: "bwho"},
        h("span", {class: "flabel", text: "On the block"}),
        h("strong", {class: "bname", text: p.name, title: p.name}),
        h("span", {class: "muted", text: meta})),
      h("div", {class: "bstatwrap"}, blockStats(p.id)),
      h("div", {class: "bact"},
        h("button", {type: "button", class: "primary", text: "Sold…", title: "Choose the team and amount",
          onclick: () => { say(`${p.name} sold: choose the team and amount.`, "ask"); amountPrompt(p, null); }}),
        h("button", {type: "button", text: "Clear", title: "Take the player off the block (no pick is removed)",
          onclick: async () => handle(await api("/api/block/clear", {}))})));
    el.hidden = false;
  }
}

function takenIds(){ return new Set((STATE ? STATE.picks : []).map(p => String(p.player_id))); }

function visiblePlayers(){
  const taken = takenIds();
  const pool = PLAYERS.filter(p => !taken.has(String(p.id)) || fading.has(String(p.id)));
  const q = nameFragment($("#cmd").value);
  if(q) return pool.map(p => [score(q, p._k), p]).filter(x => x[0] > 0.4)
                   .sort((a,b) => b[0]-a[0]).map(x => x[1]);
  return pool.slice().sort((a,b) => sortBy === "espn"
    ? a.espn_rank - b.espn_rank
    : (b.value||0) - (a.value||0) || a.espn_rank - b.espn_rank);
}

/* Keyed reconcile: reuses elements, moves only what is out of place. */
function reconcile(parent, items, cache, keyFn, make, update){
  const want = new Set(items.map(keyFn));
  for(const el of [...parent.children]) if(!want.has(el.dataset.key)) el.remove();
  let prev = null;
  for(const it of items){
    const k = keyFn(it);
    let el = cache.get(k);
    if(!el){ el = make(it); el.dataset.key = k; cache.set(k, el); }
    if(update) update(el, it);
    const expected = prev ? prev.nextElementSibling : parent.firstElementChild;
    if(el !== expected) parent.insertBefore(el, expected);
    prev = el;
  }
}

function makeCard(p){
  const inj = p.inj && p.inj !== "ACTIVE";
  return h("div", {class: "card" + (inj ? " inj" : ""), tabIndex: 0,
      title: `${p.name} · ${p.pos||""} · ${p.team||""} · ADP ${p.adp||"–"} · z ${p.z_total ?? "–"} · risk ${p.risk ?? "–"}${inj ? " · " + p.inj : ""}`,
      onclick: () => onPlayerClick(p),
      onkeydown: e => { if(e.key === "Enter") onPlayerClick(p); }},
    h("span", {class: "rk", text: p.espn_rank}),      // ESPN rank in every sort (F-18)
    photo(p.id, p.name, "ph"),
    h("div", {class: "nm", text: p.name}),
    h("div", {class: "mt"}, h("span", {text: `${(p.pos||"").split("/")[0]} ${p.team||""}`}),
      h("span", {class: "val", text: money(p.value)})));
}

function makeRow(p){
  return h("tr", {onclick: () => onPlayerClick(p), title: p.name},
    h("td", {class: "muted", text: p.espn_rank}), h("td", {text: p.name}),
    h("td", {text: p.pos || ""}), h("td", {text: p.team || ""}),
    h("td", {class: "val", text: money(p.value)}), h("td", {text: money(p.market_value)}),
    h("td", {text: p.adp || "–"}), h("td", {text: p.z_total ?? "–"}), h("td", {text: p.risk ?? "–"}));
}

const markGone = (el, p) => el.classList.toggle("gone", fading.has(String(p.id)));

function renderPlayers(){
  if(!STATE || view !== "board") return;
  const list = visiblePlayers();
  $("#availCount").textContent = `${STATE.available_count} available`;
  $("#cardsWrap").hidden = layout !== "cards";
  $("#listWrap").hidden = layout !== "list";
  if(layout === "cards") reconcile($("#board"), list, cardEls, p => String(p.id), makeCard, markGone);
  else reconcile($("#list tbody"), list, rowEls, p => String(p.id), makeRow, markGone);
}

/* A nominate under way (typed in the bar, or its candidate row open): a click on the
   board nominates that player instead of opening the pick prompt. */
function nominating(){
  return $("#prompt").dataset.action === "nominate" ||
    NOMINATE.test(norm($("#cmd").value).replace(WAKE,"").trim());
}

async function onPlayerClick(p){
  if(fading.has(String(p.id))) return;
  if(nominating()){
    const res = await api("/api/nominate", {player_id: p.id, source: "click"});
    if(res.ok){ $("#cmd").value = ""; renderPlayers(); }
    handle(res);
    return;
  }
  say(`${p.name}: choose the team and amount.`, "ask");
  amountPrompt(p, null);
}

function renderClock(){
  const slots = STATE.league.roster_spots;
  const t = STATE.teams.find(x => x.on_clock);
  $("#clockTeam").textContent = STATE.on_the_clock || "–";
  $("#clockMeta").textContent = t ? `$${t.remaining} left · ${t.count}/${slots} · max bid ${t.max_bid}`
                                  : (STATE.picks.length ? "every roster is full" : "");
}

function renderBudgets(){
  const {budget, roster_spots: slots} = STATE.league;
  $("#budgets").replaceChildren(...STATE.teams.map(t =>
    h("div", {class: `team${t.full ? " full" : ""}${t.on_clock ? " clock" : ""}${t.is_me ? " me" : ""}`,
              title: `${t.name}: $${t.remaining} left, ${t.count}/${slots}, max bid $${t.max_bid}`},
      h("b", {text: t.name}),
      h("span", {class: "n"}, h("span", {text: `$${t.remaining} · ${t.count}/${slots}`}),
        h("span", {class: "mx", text: `max ${t.max_bid}`})),
      h("div", {class: "bar"}, h("i", {style: `width:${Math.min(100, 100*t.spent/budget)}%`})))));
}

/* Pick history on the left, newest on top (F-27), latest highlighted (F-28). */
function renderHistory(){
  const picks = STATE.picks;
  $("#pickCount").textContent = picks.length ? String(picks.length) : "";
  const log = $("#log");
  if(!picks.length){
    logEls.clear();
    log.replaceChildren(h("li", {class: "none", text: "No picks yet"}));
    return;
  }
  const num = new Map(picks.map((p,i) => [p.seq, i+1]));
  const latest = picks[picks.length-1].seq;
  reconcile(log, picks.slice().reverse(), logEls, p => String(p.seq), p =>
    h("li", {title: `#${num.get(p.seq)} ${p.name} · ${p.team} · $${p.price} · ${p.source}`},
      photo(p.player_id, p.name, "ph"),
      h("span", {}, h("div", {class: "hn", text: p.name}), h("div", {class: "ht", text: p.team})),
      h("span", {class: "hp"}, `$${p.price}`, h("small", {class: "no"})),
      h("button", {type: "button", class: "back", text: "back to here",
        title: "Remove every pick after this one", onclick: () => backToHere(p.seq)})),
    (el, p) => {
      el.classList.toggle("latest", p.seq === latest);
      el.querySelector(".no").textContent = `#${num.get(p.seq)}`;
      el.querySelector(".ht").textContent = p.team;       // follows a team rename
      el.querySelector(".back").hidden = p.seq === latest;
    });
}

/* Teams view (F-23..F-26): one column per team, one row per roster spot. */
function renderRosters(){
  const slots = STATE.league.roster_spots;
  $("#rosterGrid").replaceChildren(...STATE.teams.map(t => {
    const men = STATE.rosters[t.name] || [];
    const rows = Array.from({length: slots}, (_, i) => {
      const p = men[i];
      return p ? h("li", {title: `${p.name} · $${p.price}`},
                   h("span", {class: "pn", text: p.name, "data-full": p.name}),
                   h("span", {class: "pp", text: `$${p.price}`}))
               : h("li", {class: "empty"}, h("span", {class: "pn", text: "empty"}), h("span", {class: "pp", text: "–"}));
    });
    return h("div", {class: `rcol${t.on_clock ? " clock" : ""}${t.is_me ? " me" : ""}`},
      h("h3", {title: `${t.name}: $${t.remaining} left, max bid $${t.max_bid}`}, t.name,
        h("small", {text: `$${t.remaining} left`}),
        h("small", {class: "mx", text: `max $${t.max_bid}`})),
      h("ol", {}, rows));
  }));
  requestAnimationFrame(shortenNames);
}

/* Names that do not fit become "F. Lastname"; the full name stays in the tooltip. */
function shortName(n){
  const parts = n.split(" ");
  return parts.length < 2 ? n : `${parts[0][0]}. ${parts.slice(1).join(" ")}`;
}
function shortenNames(){
  for(const el of document.querySelectorAll("#rosterGrid .pn[data-full]")){
    el.textContent = el.dataset.full;
    if(el.scrollWidth > el.clientWidth) el.textContent = shortName(el.dataset.full);
  }
}

/* ---------------------------------------------------------------- settings */
let draftTeams = [], draftOrder = [], draftAliases = [];
function openSettings(){
  if(!STATE) return;
  draftTeams = STATE.teams.map(t => t.name);
  draftAliases = draftTeams.map(n => ((STATE.aliases || {})[n] || []).join(", "));
  draftOrder = STATE.nom_order.map(n => draftTeams.indexOf(n)).filter(i => i >= 0);
  $("#settingsErr").textContent = "";
  $("#setTeams").replaceChildren(...draftTeams.map((n, i) =>
    h("li", {class: "teamrow"},
      h("input", {value: n, maxLength: 40, "aria-label": `Team ${i+1}`,
        oninput: e => { draftTeams[i] = e.target.value; drawOrder(); drawMe(); }}),
      h("input", {value: draftAliases[i], maxLength: 160, placeholder: "also called…",
        "aria-label": `Nicknames of team ${i+1}`, title: "Nicknames, comma separated (max 5, for typing and voice)",
        oninput: e => { draftAliases[i] = e.target.value; }}))));
  drawOrder();
  drawMe(STATE.me);
  $("#settingsDlg").showModal();
}
function drawOrder(){
  $("#setOrder").replaceChildren(...draftOrder.map((ti, pos) => h("li", {},
    h("span", {text: draftTeams[ti] || `(team ${ti+1})`}),
    h("button", {type: "button", text: "↑", "aria-label": "Up", disabled: pos === 0,
      onclick: () => { [draftOrder[pos-1], draftOrder[pos]] = [draftOrder[pos], draftOrder[pos-1]]; drawOrder(); }}),
    h("button", {type: "button", text: "↓", "aria-label": "Down", disabled: pos === draftOrder.length-1,
      onclick: () => { [draftOrder[pos+1], draftOrder[pos]] = [draftOrder[pos], draftOrder[pos+1]]; drawOrder(); }}))));
}
function drawMe(selectName){
  const sel = $("#setMe");
  const cur = selectName != null ? draftTeams.indexOf(selectName) : sel.selectedIndex;
  sel.replaceChildren(...draftTeams.map((n, i) => h("option", {value: String(i), text: n || `(team ${i+1})`})));
  sel.selectedIndex = Math.max(0, cur);
}
async function saveSettings(){
  const teams = draftTeams.map(s => s.trim());
  const aliases = Object.fromEntries(teams.map((t, i) =>
    [t, draftAliases[i].split(",").map(s => s.trim()).filter(Boolean)]));
  const res = await api("/api/settings", {teams, nom_order: draftOrder.map(i => teams[i]),
                                          me: teams[$("#setMe").selectedIndex], aliases});
  if(!res.ok){ $("#settingsErr").textContent = res.message; return; }
  $("#settingsDlg").close();
  handle(res);
}
/* New draft: two separate confirmations, the second one typed. */
async function newDraft(){
  $("#settingsDlg").close();
  const n = STATE.picks.length;
  const one = await confirmDialog({title: "New draft", ok: "Continue", danger: true,
    body: h("p", {text: `Delete all ${n} pick${n === 1 ? "" : "s"}? Teams, nomination order and "me" are kept, and a backup is written first.`})});
  if(!one){ say("New draft cancelled."); return; }
  const two = await confirmDialog({title: "Type NEW DRAFT to confirm", ok: "Start new draft", danger: true,
    requireText: "NEW DRAFT", body: h("p", {text: "This clears the board for everyone."})});
  if(!two){ say("New draft cancelled; nothing changed."); return; }
  handle(await api("/api/reset", {confirm: "NEW DRAFT"}));
}

/* ---------------------------------------------------------------- view switching */
function setView(v, push = true){
  view = v;
  document.body.classList.toggle("teams", v === "teams");
  for(const b of $("#viewSeg").children) b.setAttribute("aria-pressed", String(b.dataset.view === v));
  $("#viewBoard").hidden = v !== "board";
  $("#viewTeams").hidden = v !== "teams";
  const path = v === "board" ? "/board" : "/teams";
  if(push && location.pathname !== path) history.pushState({v}, "", path);
  render();
}
const viewFromUrl = () => location.pathname.startsWith("/teams") ? "teams" : "board";

/* ---------------------------------------------------------------- events */
const cmd = $("#cmd");
let filterTimer = null;
cmd.addEventListener("input", () => { clearTimeout(filterTimer); filterTimer = setTimeout(renderPlayers, 60); });
cmd.addEventListener("keydown", async e => {
  if(e.key === "Escape"){ cmd.value = ""; clearPrompt(); say(""); renderPlayers(); }
  if(e.key === "Enter"){
    e.preventDefault();
    const text = cmd.value.trim();
    if(!text) return;
    const res = await api("/api/command", {text, source: "typed"});
    if(res.ok || ["need_amount","ambiguous","confirm_undo"].includes(res.kind)) cmd.value = "";
    handle(res);
    renderPlayers();
  }
});
for(const f of document.querySelectorAll("dialog form")) f.addEventListener("submit", e => e.preventDefault());
$("#undoBtn").onclick = async () => handle(await api("/api/undo", {count: 1}));
$("#skipBtn").onclick = async () => handle(await api("/api/turn", {}));
$("#backBtn").onclick = async () => handle(await api("/api/turn", {step: -1}));
$("#voiceBtn").onclick = async () => {
  if(!STATE || !STATE.voice) return;
  // Not through handle(): that clears the prompt, and an open amount prompt must stay.
  const res = await api("/api/voice/mute", {muted: !STATE.voice.muted});
  if(res.state) applyState(res.state);
  else say(res.message || "Could not change mute.", "err");
};
$("#settingsBtn").onclick = openSettings;
$("#settingsCancel").onclick = () => $("#settingsDlg").close();
$("#settingsSave").onclick = saveSettings;
$("#newDraftBtn").onclick = newDraft;
$("#viewSeg").addEventListener("click", e => { const b = e.target.closest("button"); if(b) setView(b.dataset.view); });
$("#sortSeg").addEventListener("click", e => {
  const b = e.target.closest("button"); if(!b) return;
  sortBy = b.dataset.sort;
  for(const x of $("#sortSeg").children) x.setAttribute("aria-pressed", String(x === b));
  renderPlayers();
});
$("#layoutBtn").onclick = () => {
  layout = layout === "cards" ? "list" : "cards";
  $("#layoutBtn").textContent = layout === "cards" ? "List" : "Cards";
  renderPlayers();
};
window.addEventListener("popstate", () => setView(viewFromUrl(), false));
let resizeTimer = null;
window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { if(view === "teams") shortenNames(); }, 120); });

(async function init(){
  view = viewFromUrl();
  document.body.classList.toggle("teams", view === "teams");
  for(;;){
    try { await loadPlayers(); break; } catch(e){ await new Promise(r => setTimeout(r, POLL_MS)); }
  }
  await poll();
  setView(view, false);
  cmd.focus();
  setInterval(poll, POLL_MS);   // every open view stays in sync (F-43)
})();
