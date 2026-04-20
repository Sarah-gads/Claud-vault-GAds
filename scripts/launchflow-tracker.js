#!/usr/bin/env node
/**
 * LaunchFlow Work Tracker — Claude Code hook
 *
 * Auto-registers MSP Launchpad Claude Code sessions to the Live Work tab
 * in LaunchFlow via direct HTTPS to Supabase's `ob_live_work` table.
 *
 * No Python required. No manual registration. Runs in all modes including
 * --dangerously-skip-permissions (hooks fire via the harness, not via
 * permission checks).
 *
 * Invoked as a hook with one positional arg identifying the event:
 *   node launchflow-tracker.js session-start
 *   node launchflow-tracker.js user-prompt
 *   node launchflow-tracker.js post-tool-use
 *   node launchflow-tracker.js stop
 *   node launchflow-tracker.js session-end
 *
 * Or as a CLI:
 *   node launchflow-tracker.js retro   # backfill currently-open Claude sessions
 *   node launchflow-tracker.js whoami  # diagnose config resolution
 *
 * Config (first non-empty wins):
 *   process.env.*
 *   <cwd>/.env and every parent up to drive root
 *   ~/.launchflow/.env
 *   ~/launchpad-labs/.env
 *
 * Keys recognised:
 *   LAUNCHFLOW_SUPABASE_URL         (fallback: SUPABASE_TEAM_OPS_URL)
 *   LAUNCHFLOW_SUPABASE_SERVICE_KEY (fallback: SUPABASE_TEAM_OPS_SERVICE_KEY)
 *   LAUNCHFLOW_MEMBER_NAME
 *   LAUNCHFLOW_SKIP=1               (opt out of current session)
 *   LAUNCHFLOW_DEBUG=1              (log to ~/.launchflow/hook-debug.log)
 *
 * Silent-fail by design: never blocks Claude Code. Failures go to the debug
 * log, never to stderr.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');
const https = require('https');
const { URL } = require('url');

const HOME = os.homedir();
const STATE_DIR = path.join(HOME, '.launchflow');
const STATE_FILE = path.join(STATE_DIR, 'hook-state.json');
const CATALOG_FILE = path.join(STATE_DIR, 'catalog.json');
const DEBUG_LOG = path.join(STATE_DIR, 'hook-debug.log');
const HEARTBEAT_INTERVAL_MS = 10 * 60 * 1000;
const CATALOG_STALE_MS = 60 * 60 * 1000; // refresh hourly
const STDIN_TIMEOUT_MS = 2000;
const MATCH_MIN_TOKENS = 2;   // need at least 2 distinctive tokens overlapping
const MATCH_MIN_SCORE = 0.5;  // at least half of candidate tokens found

const HOOK_MODE = (process.argv[2] || 'unknown').toLowerCase();

// ─── Logging ─────────────────────────────────────────────────────────────────

function log(msg) {
  if (process.env.LAUNCHFLOW_DEBUG !== '1') return;
  try {
    if (!fs.existsSync(STATE_DIR)) fs.mkdirSync(STATE_DIR, { recursive: true });
    fs.appendFileSync(DEBUG_LOG, `[${new Date().toISOString()}] [${HOOK_MODE}] ${msg}\n`);
  } catch (_) { /* swallow */ }
}

// ─── Env / config ────────────────────────────────────────────────────────────

function parseEnvFile(filepath) {
  const env = {};
  try {
    const content = fs.readFileSync(filepath, 'utf8');
    for (const raw of content.split(/\r?\n/)) {
      const line = raw.trim();
      if (!line || line.startsWith('#')) continue;
      const eq = line.indexOf('=');
      if (eq < 0) continue;
      const key = line.slice(0, eq).trim();
      let value = line.slice(eq + 1).trim();
      if ((value.startsWith('"') && value.endsWith('"')) ||
          (value.startsWith("'") && value.endsWith("'"))) {
        value = value.slice(1, -1);
      }
      env[key] = value;
    }
  } catch (_) { /* not readable — ignore */ }
  return env;
}

function candidateEnvFiles(cwd) {
  const out = [];
  let dir = cwd;
  for (let i = 0; i < 20 && dir; i++) {
    out.push(path.join(dir, '.env'));
    // Also probe a sibling msp-launchpad/.env so running from the workspace root still finds creds
    out.push(path.join(dir, 'msp-launchpad', '.env'));
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  out.push(path.join(HOME, '.launchflow', '.env'));
  out.push(path.join(HOME, 'launchpad-labs', '.env'));
  out.push(path.join(HOME, '.launchpad-labs', '.env'));
  return out;
}

function loadConfig(cwd) {
  const files = candidateEnvFiles(cwd);
  // Merge in reverse so earlier files (closer to cwd) win
  const merged = {};
  for (const f of files.slice().reverse()) Object.assign(merged, parseEnvFile(f));

  const pick = (...keys) => {
    for (const k of keys) {
      if (process.env[k]) return process.env[k];
      if (merged[k]) return merged[k];
    }
    return null;
  };

  return {
    url: pick('LAUNCHFLOW_SUPABASE_URL', 'SUPABASE_TEAM_OPS_URL'),
    serviceKey: pick('LAUNCHFLOW_SUPABASE_SERVICE_KEY', 'SUPABASE_TEAM_OPS_SERVICE_KEY'),
    memberName: pick('LAUNCHFLOW_MEMBER_NAME'),
    envFilesChecked: files,
  };
}

// ─── Context detection ───────────────────────────────────────────────────────

function isMspLaunchpadContext(cwd) {
  if (process.env.LAUNCHFLOW_SKIP === '1') return false;
  if (!cwd) return false;
  const normalized = cwd.replace(/\\/g, '/').toLowerCase();
  // Fast path — any CWD under the workspace root counts
  if (normalized.includes('/claude code') || normalized.includes('/msp-launchpad')) return true;
  // Fallback — walk up looking for a CLAUDE.md that mentions MSP Launchpad
  let dir = cwd;
  for (let i = 0; i < 6 && dir; i++) {
    const claudeMd = path.join(dir, 'CLAUDE.md');
    if (fs.existsSync(claudeMd)) {
      try {
        const content = fs.readFileSync(claudeMd, 'utf8');
        if (/msp\s*launchpad/i.test(content)) return true;
      } catch (_) { /* ignore */ }
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return false;
}

// ─── State ───────────────────────────────────────────────────────────────────

function loadState() {
  try { return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8')); } catch (_) { return {}; }
}

function saveState(state) {
  try {
    if (!fs.existsSync(STATE_DIR)) fs.mkdirSync(STATE_DIR, { recursive: true });
    fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
  } catch (e) { log(`saveState err: ${e.message}`); }
}

// ─── Supabase client ─────────────────────────────────────────────────────────

function supabaseRequest(cfg, method, query, body) {
  return new Promise((resolve, reject) => {
    let parsed;
    try { parsed = new URL(cfg.url); } catch (e) { return reject(e); }
    const data = body ? JSON.stringify(body) : null;
    const options = {
      hostname: parsed.hostname,
      port: parsed.port || 443,
      path: `/rest/v1/ob_live_work${query ? '?' + query : ''}`,
      method,
      headers: {
        apikey: cfg.serviceKey,
        Authorization: `Bearer ${cfg.serviceKey}`,
        'Content-Type': 'application/json',
        Prefer: 'return=representation',
      },
      timeout: 10000,
    };
    if (data) options.headers['Content-Length'] = Buffer.byteLength(data);

    const req = https.request(options, (res) => {
      let raw = '';
      res.on('data', (c) => { raw += c; });
      res.on('end', () => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          try { resolve(raw ? JSON.parse(raw) : null); }
          catch (_) { resolve(null); }
        } else {
          log(`HTTP ${res.statusCode}: ${raw.slice(0, 300)}`);
          reject(new Error(`HTTP ${res.statusCode}`));
        }
      });
    });
    req.on('error', (e) => { log(`req err: ${e.message}`); reject(e); });
    req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
    if (data) req.write(data);
    req.end();
  });
}

// ─── Catalog (projects known to LaunchFlow) ──────────────────────────────────
//
// We keep a cached list of known project/tool/bounty names so the hook can
// upgrade a "new input" row to a real project label once the conversation
// gives enough signal. Cache lives at ~/.launchflow/catalog.json and is
// refreshed hourly (or on demand via `refresh-catalog`).

const CATALOG_SOURCES = [
  { table: 'systems',              select: 'name,project_dir',       kind: 'system',     pathField: 'project_dir' },
  { table: 'ob_automation_builds', select: 'name',                   kind: 'build' },
  { table: 'ob_tools',             select: 'name,slug,category',     kind: 'tool' },
  { table: 'ob_deliverables',      select: 'name,code',              kind: 'deliverable' },
  { table: 'event_bounties',       select: 'title',                  kind: 'bounty',     nameField: 'title' },
];

// Also harvest project names actually used in the Live Work tab in the last
// 30 days. This captures project labels the team uses but that don't exist
// in any catalog table — e.g. "The Heart", "Zhero Design Gen v2.5", "Kavira".
// Whatever someone has manually tracked becomes the catalog for auto-matching.
async function fetchLiveWorkHistory(cfg) {
  const cutoff = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString();
  try {
    const rows = await supabaseRequestTable(
      cfg, 'ob_live_work',
      `select=${encodeURIComponent('project_name')}&started_at=gte.${encodeURIComponent(cutoff)}&limit=500`,
    );
    const seen = new Set();
    const items = [];
    for (const r of rows) {
      const n = String(r.project_name || '').trim();
      if (!n) continue;
      const key = n.toLowerCase();
      if (seen.has(key)) continue;
      if (/^(new input|new session|claude code workspace|claude code session|session [a-f0-9]{6,})$/i.test(n)) continue;
      seen.add(key);
      items.push({ name: n, kind: 'live_history', projectDir: null });
    }
    return items;
  } catch (e) { log(`live-work harvest failed: ${e.message}`); return []; }
}

async function fetchAllCatalog(cfg) {
  const items = [];
  for (const src of CATALOG_SOURCES) {
    try {
      const rows = await supabaseRequestTable(cfg, src.table, `select=${encodeURIComponent(src.select)}&limit=500`);
      for (const r of rows) {
        const name = (src.nameField ? r[src.nameField] : r.name) || null;
        if (!name) continue;
        items.push({
          name: String(name).trim(),
          kind: src.kind,
          projectDir: src.pathField ? (r[src.pathField] || null) : null,
        });
      }
    } catch (e) { log(`catalog fetch ${src.table} failed: ${e.message}`); }
  }
  // Merge in project names actually used on the Live Work tab recently
  const liveHistory = await fetchLiveWorkHistory(cfg);
  for (const h of liveHistory) items.push(h);
  return items;
}

// Variant of supabaseRequest that hits an arbitrary table (our main helper is
// hard-coded to ob_live_work for safety).
function supabaseRequestTable(cfg, table, query) {
  return new Promise((resolve, reject) => {
    let parsed;
    try { parsed = new URL(cfg.url); } catch (e) { return reject(e); }
    const options = {
      hostname: parsed.hostname,
      port: parsed.port || 443,
      path: `/rest/v1/${table}${query ? '?' + query : ''}`,
      method: 'GET',
      headers: {
        apikey: cfg.serviceKey,
        Authorization: `Bearer ${cfg.serviceKey}`,
        Accept: 'application/json',
      },
      timeout: 10000,
    };
    const req = https.request(options, (res) => {
      let raw = '';
      res.on('data', (c) => { raw += c; });
      res.on('end', () => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          try { resolve(raw ? JSON.parse(raw) : []); } catch (_) { resolve([]); }
        } else { reject(new Error(`HTTP ${res.statusCode}`)); }
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
    req.end();
  });
}

function loadCatalogCache() {
  try {
    const raw = JSON.parse(fs.readFileSync(CATALOG_FILE, 'utf8'));
    return raw && Array.isArray(raw.items) ? raw : null;
  } catch (_) { return null; }
}

function saveCatalogCache(items) {
  try {
    if (!fs.existsSync(STATE_DIR)) fs.mkdirSync(STATE_DIR, { recursive: true });
    fs.writeFileSync(CATALOG_FILE, JSON.stringify({ fetchedAt: Date.now(), items }, null, 2));
  } catch (e) { log(`catalog save err: ${e.message}`); }
}

// Non-blocking background refresh. Writes the updated cache whenever it
// completes; current hook invocation uses whatever was on disk.
function maybeRefreshCatalogInBackground(cfg) {
  const cached = loadCatalogCache();
  const stale = !cached || (Date.now() - cached.fetchedAt) > CATALOG_STALE_MS;
  if (!stale) return;
  // Spawn a detached node subprocess so the parent hook can exit immediately.
  try {
    const { spawn } = require('child_process');
    const child = spawn(process.execPath, [__filename, 'refresh-catalog'], {
      detached: true, stdio: 'ignore',
      env: { ...process.env, LAUNCHFLOW_SUPABASE_URL: cfg.url, LAUNCHFLOW_SUPABASE_SERVICE_KEY: cfg.serviceKey },
    });
    child.unref();
  } catch (_) { /* swallow */ }
}

// Stopwords are generic project words that shouldn't count as a "distinctive"
// overlap. "Pipeline" by itself doesn't identify any specific project because
// half of LaunchFlow is pipelines.
const MATCH_STOPWORDS = new Set([
  'the','a','an','of','for','and','or','to','with','in','on','at','by','as','is',
  'pipeline','automation','system','tool','generator','builder','engine','manager',
  'content','client','clients','portal','dashboard','report','reports','form','forms',
  'new','old','data','setup','project','projects','workflow','workflows','section',
  'tracker','handler','config','page','pages','site','sites','post','posts','flow',
  'gen','v1','v2','v3','v4','v5','phase','plan','brief',
]);

function tokensOf(text) {
  if (!text) return new Set();
  return new Set(
    String(text).toLowerCase().split(/[^a-z0-9]+/)
      .filter((w) => w.length >= 3 && !MATCH_STOPWORDS.has(w)),
  );
}

// Try to match a catalog item to (text, cwd). Returns the best match (if any).
function matchCatalog(items, text, cwd) {
  if (!items || items.length === 0) return null;
  const cwdNorm = (cwd || '').replace(/\\/g, '/').toLowerCase();

  // Pass A — direct CWD ↔ project_dir match (strongest signal)
  for (const it of items) {
    if (!it.projectDir) continue;
    const dir = String(it.projectDir).replace(/\\/g, '/').toLowerCase().replace(/\/+$/, '');
    if (!dir) continue;
    if (cwdNorm === dir || cwdNorm.startsWith(dir + '/')) {
      return { name: it.name, kind: it.kind, confidence: 1.0, reason: 'cwd→project_dir' };
    }
  }

  // Pass B — keyword match between catalog name and text tokens
  const textTokens = tokensOf(text);
  if (textTokens.size === 0) return null;
  let best = null;
  for (const it of items) {
    const nameTokens = tokensOf(it.name);
    if (nameTokens.size === 0) continue;
    let hits = 0;
    for (const t of nameTokens) if (textTokens.has(t)) hits++;
    if (hits === 0) continue;
    // Special case: names with only ONE distinctive token (e.g. "The Heart"
    // → {heart}, "Kavira" → {kavira}) can match on a single token hit IF
    // that token is specific enough (>=5 chars). This avoids requiring 2
    // tokens when the project name only has one.
    const singleTokenMatch = nameTokens.size === 1 && hits === 1 && [...nameTokens][0].length >= 5;
    if (!singleTokenMatch && hits < MATCH_MIN_TOKENS) continue;
    const score = hits / nameTokens.size;
    if (score < MATCH_MIN_SCORE) continue;
    if (!best || score > best.score || (score === best.score && nameTokens.size > best.tokenCount)) {
      best = { name: it.name, kind: it.kind, score, tokenCount: nameTokens.size, hits };
    }
  }
  if (!best) return null;
  return { name: best.name, kind: best.kind, confidence: best.score, reason: `keyword (${best.hits}/${best.tokenCount})` };
}

async function handleRefreshCatalog() {
  const cfg = loadConfig(process.cwd());
  if (!cfg.url || !cfg.serviceKey) { console.log('Missing config.'); return; }
  const items = await fetchAllCatalog(cfg);
  saveCatalogCache(items);
  console.log(`Catalog refreshed: ${items.length} items across ${CATALOG_SOURCES.length} tables → ${CATALOG_FILE}`);
  const byKind = items.reduce((acc, it) => (acc[it.kind] = (acc[it.kind] || 0) + 1, acc), {});
  for (const [k, n] of Object.entries(byKind)) console.log(`  ${k.padEnd(12)} ${n}`);
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const now = () => new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');

function truncate(str, n) {
  if (!str) return '';
  const clean = String(str).replace(/\s+/g, ' ').trim();
  return clean.length > n ? clean.slice(0, n - 1) + '…' : clean;
}

function cleanPromptText(prompt) {
  if (!prompt) return '';
  // Strip system-reminder blocks, command-caveat, command-* tags
  return String(prompt)
    .replace(/<system-reminder>[\s\S]*?<\/system-reminder>/g, '')
    .replace(/<local-command-[^>]*>[\s\S]*?<\/local-command-[^>]*>/g, '')
    .replace(/<command-[^>]*>[\s\S]*?<\/command-[^>]*>/g, '')
    .trim();
}

function firstMeaningfulLine(prompt) {
  const cleaned = cleanPromptText(prompt);
  for (const line of cleaned.split(/\r?\n/)) {
    const t = line.trim();
    if (t && t.length >= 4) return t;
  }
  return cleaned.slice(0, 200);
}

function humanize(slug) {
  return String(slug)
    .split(/[-_]/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

// Parse Lodewijk's standard resume-prompt format:
//   "2. The Heart — Phase 3 / Plan 03-05 Transcripts — 4146ca45 (17:58)"
//   returns { projectName: "The Heart", description: "Phase 3 / Plan 03-05 Transcripts" }
// Handles em-dash (—), en-dash (–), and plain hyphen with spaces.
function parseResumePrompt(text) {
  if (!text) return null;
  const firstLine = text.split(/\r?\n/).map((l) => l.trim()).find(Boolean);
  if (!firstLine) return null;
  const m = firstLine.match(/^\s*(?:[*•\-]|\d+[.)])\s*([^—–]+?)\s*[—–]\s*(.+?)\s*$/);
  if (!m) return null;
  let project = m[1].trim();
  let desc = m[2].trim();
  // Strip trailing " — <hex id> (<timestamp>)" if present
  desc = desc.replace(/\s*[—–]\s*[a-f0-9]{6,}\s*(?:\([^)]+\))?\s*$/i, '').trim();
  if (project.length < 2 || project.length > 60) return null;
  return { projectName: project, description: desc };
}

// Derive from CWD only — returns null if CWD doesn't yield a useful name.
function deriveFromCwd(cwd) {
  if (!cwd) return null;
  const segs = cwd.replace(/\\/g, '/').split('/').filter(Boolean);
  const idx = segs.findIndex((s) => s.toLowerCase() === 'projects');
  if (idx >= 0 && segs[idx + 1]) return humanize(segs[idx + 1]);
  return null;
}

// Short label for a session when we can't determine the project yet.
// Deliberately human-friendly — signals "we don't know yet, stand by" rather
// than leaking a session UUID. As the conversation produces more signal
// (longer prompts, file edits, catalog matches), the row can be upgraded.
function fallbackLabel(_sessionId) {
  return 'new input';
}

function deriveProjectName(cwd, sessionId, firstPrompt) {
  if (firstPrompt) {
    const parsed = parseResumePrompt(firstPrompt);
    if (parsed) return parsed.projectName;
  }
  const fromCwd = deriveFromCwd(cwd);
  if (fromCwd) return fromCwd;
  return fallbackLabel(sessionId);
}

function slugCwd(cwd) {
  // Match Claude Code's project directory naming: every `\ / :` or whitespace → `-`
  return cwd.replace(/[\\/:\s]/g, '-');
}

// ─── Session ops ─────────────────────────────────────────────────────────────

async function findSession(cfg, sessionId) {
  const rows = await supabaseRequest(
    cfg, 'GET',
    `session_id=eq.${encodeURIComponent(sessionId)}&status=in.(active,paused,blocked)&order=last_heartbeat.desc&limit=1`,
  );
  return Array.isArray(rows) && rows.length > 0 ? rows[0] : null;
}

async function createSession(cfg, { sessionId, projectName, description, cwd }) {
  const ts = now();
  const row = {
    project_name: projectName,
    description,
    status: 'active',
    // Intentionally NOT auto-setting terminal_label — that's what created the
    // noisy "CLAUDE CODE" tag. Python tracker sets it only when --label is passed.
    terminal_label: null,
    session_id: sessionId,
    started_at: ts,
    last_heartbeat: ts,
    metadata: { source: 'claude-code-hook', cwd, member_name: cfg.memberName || null },
  };
  if (cfg.memberName) row.member_name = cfg.memberName;
  await supabaseRequest(cfg, 'POST', '', row);
  log(`created ${sessionId.slice(0, 8)} for "${projectName}"`);
}

async function patchSession(cfg, sessionId, patch) {
  const body = { ...patch, last_heartbeat: now() };
  await supabaseRequest(
    cfg, 'PATCH',
    `session_id=eq.${encodeURIComponent(sessionId)}&status=in.(active,paused)`,
    body,
  );
}

async function completeSession(cfg, sessionId, note) {
  const ts = now();
  await supabaseRequest(
    cfg, 'PATCH',
    `session_id=eq.${encodeURIComponent(sessionId)}&status=in.(active,paused,blocked)`,
    { status: 'completed', completed_at: ts, last_heartbeat: ts, progress_notes: note || null },
  );
  log(`completed ${sessionId.slice(0, 8)}`);
}

// ─── Stdin reader ────────────────────────────────────────────────────────────

function readStdin() {
  return new Promise((resolve) => {
    if (process.stdin.isTTY) return resolve(null);
    let data = '';
    let done = false;
    const finalize = () => {
      if (done) return;
      done = true;
      if (!data) return resolve(null);
      try { resolve(JSON.parse(data)); } catch (_) { resolve(null); }
    };
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (c) => { data += c; });
    process.stdin.on('end', finalize);
    process.stdin.on('error', finalize);
    setTimeout(finalize, STDIN_TIMEOUT_MS);
  });
}

// ─── Hook handlers ───────────────────────────────────────────────────────────

// A row is "hook-owned" if we created it (metadata.source === 'claude-code-hook').
// Rows created by the Python work-tracker or other means are "foreign" and we
// only heartbeat them — never overwrite their project_name or description.
function isHookOwned(row) {
  return row && row.metadata && row.metadata.source === 'claude-code-hook';
}

// Set of session_ids known to Claude Code's live-process registry.
// A hook row whose session_id is NOT in here is dangling — typically from
// a /clear inside a still-running Claude Code process (Claude Code generates
// a new session_id on /clear but doesn't fire SessionEnd for the old one).
function liveClaudeSessionIds() {
  const dir = path.join(HOME, '.claude', 'sessions');
  if (!fs.existsSync(dir)) return new Set();
  const ids = new Set();
  for (const f of fs.readdirSync(dir).filter((n) => n.endsWith('.json'))) {
    try {
      const d = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
      if (d.sessionId) ids.add(d.sessionId);
    } catch (_) { /* ignore */ }
  }
  return ids;
}

// Auto-retire hook rows for this member whose session_id doesn't match any
// live Claude Code process and whose heartbeat is stale. Throttled to at most
// once every 15 minutes via state file so we don't hammer Supabase.
async function autoRetireStaleRows(cfg, state) {
  if (!cfg.memberName) return;
  const throttleKey = '__lastAutoRetire';
  const lastRun = state[throttleKey] || 0;
  if (Date.now() - lastRun < 15 * 60 * 1000) return;

  try {
    const rows = await supabaseRequest(
      cfg, 'GET',
      `member_name=eq.${encodeURIComponent(cfg.memberName)}&status=in.(active,paused)&select=id,session_id,metadata,last_heartbeat&limit=100`,
    );
    if (!Array.isArray(rows) || rows.length === 0) {
      state[throttleKey] = Date.now();
      return;
    }
    const liveIds = liveClaudeSessionIds();
    const nowMs = Date.now();
    const STALE_MS = 5 * 60 * 1000; // 5 minutes of no heartbeat
    let retired = 0;
    for (const r of rows) {
      if (!isHookOwned(r)) continue; // leave foreign rows alone
      if (!r.session_id || liveIds.has(r.session_id)) continue; // still alive
      const age = nowMs - new Date(r.last_heartbeat).getTime();
      if (age < STALE_MS) continue; // might be about to register
      await supabaseRequest(
        cfg, 'PATCH',
        `id=eq.${r.id}&status=in.(active,paused)`,
        { status: 'completed', completed_at: now(), last_heartbeat: now(), progress_notes: 'Auto-retired: no live Claude Code process for this session_id' },
      );
      retired++;
      log(`auto-retired dangling row ${r.session_id.slice(0, 8)} (age ${Math.round(age/60000)}min)`);
    }
    state[throttleKey] = Date.now();
    if (retired > 0) log(`auto-retire: retired ${retired} dangling row(s)`);
  } catch (e) {
    log(`auto-retire failed: ${e.message}`);
  }
}

async function handleSessionStart({ sessionId, cwd, cfg, state }) {
  // Self-heal: retire any hook rows for this member whose session_id doesn't
  // match a live Claude Code process. Throttled internally.
  await autoRetireStaleRows(cfg, state);

  const existing = await findSession(cfg, sessionId).catch(() => null);
  if (existing) {
    log(`already exists ${sessionId.slice(0, 8)} (hookOwned=${isHookOwned(existing)}) → heartbeat only`);
    state[sessionId] = {
      ...(state[sessionId] || {}),
      exists: true,
      rowId: existing.id,
      hookOwned: isHookOwned(existing),
      projectName: existing.project_name,
      descriptionLocked: !isHookOwned(existing), // foreign rows: don't touch description ever
    };
    saveState(state);
    return;
  }
  // Fresh row — use fallback label so team members see "Session abc12345"
  // instead of the useless "Claude Code Workspace". The first user prompt
  // will upgrade this within seconds.
  await createSession(cfg, {
    sessionId,
    projectName: deriveProjectName(cwd, sessionId, null),
    description: 'Starting session…',
    cwd,
  });
  state[sessionId] = {
    exists: true,
    createdAt: Date.now(),
    hookOwned: true,
    descriptionLocked: false,
  };
  saveState(state);
}

async function handleUserPrompt({ sessionId, cwd, cfg, state, hookData }) {
  const rawPrompt = hookData.prompt || '';
  const cleaned = cleanPromptText(rawPrompt);
  if (!cleaned) return;

  let sState = state[sessionId] || {};

  // If we missed SessionStart, look up existing row
  if (!sState.exists) {
    const existing = await findSession(cfg, sessionId).catch(() => null);
    if (existing) {
      sState = {
        exists: true,
        rowId: existing.id,
        hookOwned: isHookOwned(existing),
        projectName: existing.project_name,
        descriptionLocked: !isHookOwned(existing),
      };
    }
  }

  // Foreign row (Python tracker or otherwise) → heartbeat only, NEVER overwrite
  if (sState.exists && sState.descriptionLocked) {
    await patchSession(cfg, sessionId, {});
    state[sessionId] = { ...sState, lastHeartbeat: Date.now() };
    saveState(state);
    return;
  }

  // Kick off a background catalog refresh if cache is stale. We use whatever
  // is currently on disk for this invocation.
  maybeRefreshCatalogInBackground(cfg);
  const catalog = loadCatalogCache();
  const catalogItems = catalog ? catalog.items : [];

  // First prompt: set initial project + description
  if (!sState.initialDescriptionSet) {
    const parsed = parseResumePrompt(cleaned);
    let projectName, description;

    if (parsed) {
      // Lodewijk's "N. Project — Phase X" resume format: use both parts
      projectName = parsed.projectName;
      description = truncate(parsed.description, 120);
    } else {
      // Try catalog match against prompt + CWD. Falls back to "new input"
      // if nothing lines up.
      const match = matchCatalog(catalogItems, cleaned, cwd);
      projectName = match ? match.name : deriveProjectName(cwd, sessionId, cleaned);
      description = truncate(firstMeaningfulLine(cleaned), 120);
      if (match) log(`catalog matched: "${match.name}" (${match.reason}, conf=${match.confidence.toFixed(2)})`);
    }

    if (!sState.exists) {
      await createSession(cfg, { sessionId, projectName, description, cwd });
      sState = { exists: true, createdAt: Date.now(), hookOwned: true };
    } else if (sState.hookOwned !== false) {
      await patchSession(cfg, sessionId, { project_name: projectName, description });
    }
    sState.initialDescriptionSet = true;
    sState.projectName = projectName;
    sState.initialDescription = description;
    state[sessionId] = sState;
    saveState(state);
    return;
  }

  // Subsequent prompts: if the current label is still generic ("new input"),
  // try again — the conversation may now have enough signal to match a
  // catalog item. Never rename away from a real project label.
  if (sState.hookOwned !== false && looksGeneric(sState.projectName)) {
    const match = matchCatalog(catalogItems, cleaned + ' ' + (sState.initialDescription || ''), cwd);
    if (match) {
      await patchSession(cfg, sessionId, { project_name: match.name });
      sState.projectName = match.name;
      state[sessionId] = sState;
      log(`upgraded generic → "${match.name}" (${match.reason})`);
      saveState(state);
      return;
    }
  }

  // Otherwise just heartbeat — never overwrite description on later prompts
  await patchSession(cfg, sessionId, {});
  state[sessionId] = { ...sState, lastHeartbeat: Date.now() };
  saveState(state);
}

async function handlePostToolUse({ sessionId, cfg, state, hookData }) {
  const sState = state[sessionId];
  if (!sState || !sState.exists) return;

  const toolName = hookData.tool_name || '';
  const toolInput = hookData.tool_input || {};
  const filePath = toolInput.file_path || null;
  const isFileEdit = ['Write', 'Edit', 'NotebookEdit'].includes(toolName) && filePath;

  // Upgrade generic names based on file-edit activity. If Claude is writing
  // into a system's project_dir, that's a stronger signal than prompt text.
  if (isFileEdit && sState.hookOwned !== false && looksGeneric(sState.projectName)) {
    const catalog = loadCatalogCache();
    const items = catalog ? catalog.items : [];
    const match = matchCatalog(items, '', filePath);
    if (match) {
      await patchSession(cfg, sessionId, { project_name: match.name });
      sState.projectName = match.name;
      state[sessionId] = sState;
      saveState(state);
      log(`upgraded via file-edit: "${match.name}" (${match.reason})`);
      return;
    }
  }

  // Otherwise throttled heartbeat only. No "now: editing X" noise — the tab
  // is for at-a-glance status, not a live log.
  const nowMs = Date.now();
  const last = sState.lastHeartbeat || 0;
  if ((nowMs - last) <= HEARTBEAT_INTERVAL_MS) return;

  await patchSession(cfg, sessionId, {});
  state[sessionId] = { ...sState, lastHeartbeat: nowMs };
  saveState(state);
}

async function handleStop({ sessionId, cfg, state }) {
  const sState = state[sessionId];
  if (!sState || !sState.exists) return;
  // Stop fires every turn — just heartbeat, don't complete
  await patchSession(cfg, sessionId, {});
}

async function handleSessionEnd({ sessionId, cfg, state }) {
  const sState = state[sessionId];
  if (!sState || !sState.exists) return;
  await completeSession(cfg, sessionId, 'Session ended');
  delete state[sessionId];
  saveState(state);
}

// ─── Retro backfill ──────────────────────────────────────────────────────────

function listClaudeSessions() {
  const dir = path.join(HOME, '.claude', 'sessions');
  if (!fs.existsSync(dir)) return [];
  const out = [];
  for (const f of fs.readdirSync(dir).filter((n) => n.endsWith('.json'))) {
    try {
      const data = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
      out.push(data);
    } catch (_) { /* ignore */ }
  }
  return out;
}

function firstUserPromptFromTranscript(cwd, sessionId) {
  const transcript = path.join(HOME, '.claude', 'projects', slugCwd(cwd), `${sessionId}.jsonl`);
  if (!fs.existsSync(transcript)) return null;
  try {
    const content = fs.readFileSync(transcript, 'utf8');
    for (const line of content.split('\n')) {
      if (!line.trim()) continue;
      try {
        const j = JSON.parse(line);
        if (j.type !== 'user' || !j.message) continue;
        const c = j.message.content;
        let text = '';
        if (typeof c === 'string') text = c;
        else if (Array.isArray(c)) text = c.filter((b) => b.type === 'text').map((b) => b.text).join(' ');
        const cleaned = firstMeaningfulLine(text);
        if (cleaned && cleaned.length >= 10) return cleaned;
      } catch (_) { /* ignore bad line */ }
    }
  } catch (_) { /* ignore */ }
  return null;
}

async function handleRetro() {
  const sessions = listClaudeSessions();
  if (sessions.length === 0) { console.log('No active Claude Code sessions found.'); return; }

  // Use the first interactive session's cwd for config resolution (they usually share one)
  const firstCwd = sessions.find((s) => s.kind === 'interactive')?.cwd || process.cwd();
  const cfg = loadConfig(firstCwd);
  if (!cfg.url || !cfg.serviceKey) {
    console.log('Missing LAUNCHFLOW_SUPABASE_URL / LAUNCHFLOW_SUPABASE_SERVICE_KEY.');
    console.log('Run: node launchflow-tracker.js whoami');
    return;
  }

  let checked = 0, skipped = 0, alreadyThere = 0, backfilled = 0, failed = 0;
  for (const s of sessions) {
    if (s.kind !== 'interactive') { skipped++; continue; }
    const sid = s.sessionId || s.session_id;
    const scwd = s.cwd;
    if (!sid || !scwd) { skipped++; continue; }
    if (!isMspLaunchpadContext(scwd)) { skipped++; continue; }
    checked++;
    try {
      const existing = await findSession(cfg, sid);
      if (existing) { alreadyThere++; continue; }
      const firstPrompt = firstUserPromptFromTranscript(scwd, sid);
      const parsed = firstPrompt ? parseResumePrompt(firstPrompt) : null;
      const projectName = parsed ? parsed.projectName : deriveProjectName(scwd, sid, firstPrompt);
      const description = parsed
        ? truncate(parsed.description, 120)
        : truncate(firstPrompt || 'Backfilled session', 120);
      await createSession(cfg, { sessionId: sid, projectName, description, cwd: scwd });
      backfilled++;
      console.log(`  backfilled ${sid.slice(0, 8)} — ${projectName} — ${truncate(description, 60)}`);
    } catch (e) {
      failed++;
      console.log(`  failed    ${sid.slice(0, 8)} — ${e.message}`);
    }
  }
  console.log(`\nDone. checked=${checked} already=${alreadyThere} backfilled=${backfilled} failed=${failed} skipped=${skipped}`);
}

// ─── Cleanup ─────────────────────────────────────────────────────────────────

// Normalise a project name for fuzzy matching:
//   "The Heart" → "heart"
//   "Zhero Design Gen v2.3.2" → "zherodesigngenv232"
function normalizeProject(name) {
  return String(name || '')
    .toLowerCase()
    .replace(/^the\s+/, '')
    .replace(/\s+/g, '')
    .replace(/[^\w]/g, '');
}

function looksGeneric(name) {
  if (!name) return true;
  const n = name.toLowerCase();
  return n === 'new input'
    || n === 'new session'
    || n.startsWith('session ')
    || n === 'claude code workspace'
    || n === 'claude code session';
}

async function handleCleanup() {
  const cfg = loadConfig(process.cwd());
  if (!cfg.url || !cfg.serviceKey) { console.log('Missing config. Run whoami.'); return; }

  // All active/paused rows
  const rows = await supabaseRequest(cfg, 'GET', 'status=in.(active,paused)&order=last_heartbeat.desc&limit=200');
  if (!Array.isArray(rows) || rows.length === 0) { console.log('Nothing active.'); return; }

  let fixedNames = 0, dedupedHookDupes = 0, normalized = 0, catalogMatched = 0;

  const catalog = loadCatalogCache();
  const catalogItems = catalog ? catalog.items : [];

  // Pass 1 — fix hook-owned rows whose description is a resume-pattern prompt
  // (re-parse to extract a proper project_name + short description)
  for (const r of rows) {
    if (!isHookOwned(r)) continue;
    if (!looksGeneric(r.project_name)) continue;
    const parsed = parseResumePrompt(r.description || '');
    if (!parsed) continue;
    console.log(`  rename  ${r.session_id.slice(0, 8)}  "${r.project_name}" → "${parsed.projectName}"`);
    await supabaseRequest(
      cfg, 'PATCH',
      `id=eq.${r.id}`,
      { project_name: parsed.projectName, description: truncate(parsed.description, 120), last_heartbeat: now() },
    );
    r.project_name = parsed.projectName;
    r.description = parsed.description;
    fixedNames++;
  }

  // Pass 1b — for generic hook rows, try to catalog-match on the description.
  // This upgrades old "Claude Code Workspace" / "Session xxxxx" rows to real
  // project names when the first prompt text hints at a known project.
  for (const r of rows) {
    if (!isHookOwned(r)) continue;
    if (!looksGeneric(r.project_name)) continue;
    const cwd = (r.metadata && r.metadata.cwd) || '';
    const match = matchCatalog(catalogItems, r.description || '', cwd);
    if (!match) continue;
    console.log(`  match   ${r.session_id.slice(0, 8)}  "${r.project_name}" → "${match.name}" (${match.reason})`);
    await supabaseRequest(
      cfg, 'PATCH',
      `id=eq.${r.id}`,
      { project_name: match.name, last_heartbeat: now() },
    );
    r.project_name = match.name;
    catalogMatched++;
  }

  // Pass 1c — any remaining hook rows with old generic labels get normalised
  // to "new input" so the tab uses a consistent placeholder.
  for (const r of rows) {
    if (!isHookOwned(r)) continue;
    if (r.project_name === 'new input') continue;
    if (!looksGeneric(r.project_name)) continue;
    console.log(`  relabel ${r.session_id.slice(0, 8)}  "${r.project_name}" → "new input"`);
    await supabaseRequest(
      cfg, 'PATCH',
      `id=eq.${r.id}`,
      { project_name: 'new input', last_heartbeat: now() },
    );
    r.project_name = 'new input';
    normalized++;
  }

  // Pass 2 — for every pair where a hook-owned row has the same member + same
  // normalised project name as a foreign (Python-tracker) row, complete the
  // OLDER/STALER one. Earlier we preferred foreign, which erased live hook
  // sessions whose session_id was still alive. New rule:
  //   • If the hook row's session_id is in the live process registry,
  //     the hook row IS the live representation — keep it, expire the foreign.
  //   • Otherwise (hook session dead, foreign alive), complete the hook row.
  const liveIdsSet = liveClaudeSessionIds();
  const groups = new Map();
  for (const r of rows) {
    const key = `${(r.member_name || '').toLowerCase()}|${normalizeProject(r.project_name)}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(r);
  }
  for (const [_key, group] of groups) {
    if (group.length < 2) continue;
    const foreign = group.filter((g) => !isHookOwned(g));
    const hookOwned = group.filter((g) => isHookOwned(g));
    if (foreign.length === 0 || hookOwned.length === 0) continue;

    const hookLive = hookOwned.filter((g) => liveIdsSet.has(g.session_id));
    if (hookLive.length > 0) {
      // Hook row represents a live session → it wins. Complete foreign rows.
      for (const f of foreign) {
        console.log(`  dedupe  ${(f.session_id || '').slice(0, 8)}  foreign "${f.project_name}" → superseded by live hook session`);
        await supabaseRequest(
          cfg, 'PATCH',
          `id=eq.${f.id}&status=in.(active,paused)`,
          { status: 'completed', completed_at: now(), last_heartbeat: now(), progress_notes: 'Auto-deduped: live Claude Code hook session is now authoritative' },
        );
        dedupedHookDupes++;
      }
    } else {
      // No live hook session → Python-tracker row is authoritative, hook row is orphan
      for (const dup of hookOwned) {
        console.log(`  dedupe  ${dup.session_id.slice(0, 8)}  hook (dead) "${dup.project_name}" → superseded by foreign row`);
        await supabaseRequest(
          cfg, 'PATCH',
          `id=eq.${dup.id}`,
          { status: 'completed', completed_at: now(), last_heartbeat: now(), progress_notes: 'Auto-deduped: same project tracked manually via work-tracker.py' },
        );
        dedupedHookDupes++;
      }
    }
  }

  // Pass 3 — multiple hook-owned rows with the same NON-GENERIC normalised
  // name (e.g. two terminals both auto-tracked "The Heart"). Skip generic
  // names like "Claude Code Workspace" / "Session xyz" — those legitimately
  // represent different unrelated sessions that just happen to share a
  // fallback label.
  for (const [key, group] of groups) {
    const hookOwned = group.filter((g) => isHookOwned(g));
    if (hookOwned.length < 2) continue;
    if (hookOwned.every((g) => looksGeneric(g.project_name))) continue;
    hookOwned.sort((a, b) => new Date(b.last_heartbeat) - new Date(a.last_heartbeat));
    const keep = hookOwned[0];
    for (const dup of hookOwned.slice(1)) {
      console.log(`  dedupe  ${dup.session_id.slice(0, 8)}  (keeping freshest hook row for "${keep.project_name}")`);
      await supabaseRequest(
        cfg, 'PATCH',
        `id=eq.${dup.id}&status=in.(active,paused)`,
        { status: 'completed', completed_at: now(), last_heartbeat: now(), progress_notes: 'Auto-deduped: duplicate hook session for same project' },
      );
      dedupedHookDupes++;
    }
  }

  // Pass 4 — retire dangling hook rows (session_id not in live process registry)
  let retiredDangling = 0;
  const liveIds = liveClaudeSessionIds();
  for (const r of rows) {
    if (!isHookOwned(r)) continue;
    if (!r.session_id || liveIds.has(r.session_id)) continue;
    const age = Date.now() - new Date(r.last_heartbeat).getTime();
    if (age < 5 * 60 * 1000) continue; // give recent ones a grace window
    console.log(`  retire  ${r.session_id.slice(0, 8)}  (no live Claude process, ${Math.round(age/60000)}min stale) — "${r.project_name}"`);
    await supabaseRequest(
      cfg, 'PATCH',
      `id=eq.${r.id}&status=in.(active,paused)`,
      { status: 'completed', completed_at: now(), last_heartbeat: now(), progress_notes: 'Auto-retired: no live Claude Code process' },
    );
    retiredDangling++;
  }

  // Pass 5 — expire foreign rows (Python tracker) whose heartbeat is >2h old.
  // These are manual `start`s that the user forgot to `complete`. The UI
  // already hides them, but marking them completed keeps the DB honest.
  let expiredForeign = 0;
  for (const r of rows) {
    if (isHookOwned(r)) continue;
    const age = Date.now() - new Date(r.last_heartbeat).getTime();
    if (age < 2 * 60 * 60 * 1000) continue; // under 2h — still fresh
    console.log(`  expire  ${r.session_id ? r.session_id.slice(0, 8) : '(no sid)'}  (manual, ${Math.round(age/60000)}min stale) — "${r.project_name}"`);
    await supabaseRequest(
      cfg, 'PATCH',
      `id=eq.${r.id}&status=in.(active,paused)`,
      { status: 'completed', completed_at: now(), last_heartbeat: now(), progress_notes: 'Auto-expired: heartbeat > 2h stale' },
    );
    expiredForeign++;
  }

  console.log(`\nDone. renamed=${fixedNames} catalog-matched=${catalogMatched} relabelled=${normalized} deduped=${dedupedHookDupes} retired=${retiredDangling} expired=${expiredForeign}`);
}

// ─── Whoami diagnostic ───────────────────────────────────────────────────────

async function handleWhoami() {
  const cwd = process.cwd();
  const cfg = loadConfig(cwd);
  const mspCtx = isMspLaunchpadContext(cwd);
  console.log('LaunchFlow tracker — config resolution');
  console.log(`  cwd                : ${cwd}`);
  console.log(`  MSP Launchpad ctx? : ${mspCtx ? 'YES' : 'NO (would skip)'}`);
  console.log(`  supabase url       : ${cfg.url || '(MISSING)'}`);
  console.log(`  service key        : ${cfg.serviceKey ? 'set' : '(MISSING)'}`);
  console.log(`  member name        : ${cfg.memberName || '(MISSING — set LAUNCHFLOW_MEMBER_NAME)'}`);
  console.log(`  state file         : ${STATE_FILE}`);
  console.log(`  env files checked  :`);
  for (const f of cfg.envFilesChecked) {
    const found = fs.existsSync(f) ? 'found' : '    -';
    console.log(`    ${found}  ${f}`);
  }

  // Network probe — confirm the key actually authenticates against Supabase
  // and that the narrow grants are in place. SELECT with limit=0 is the
  // cheapest read; PostgREST returns [] on success, 401/403 on auth failure.
  if (!cfg.url || !cfg.serviceKey) {
    console.log('  key probe          : SKIPPED (missing url or key)');
    process.exitCode = 1;
    return;
  }
  try {
    await supabaseRequest(cfg, 'GET', 'select=id&limit=0');
    console.log('  key probe          : ok (auth + ob_live_work read OK)');
  } catch (e) {
    console.log(`  key probe          : FAIL (${e.message})`);
    console.log('                       Key is missing, expired, revoked, or lacks RLS grant.');
    process.exitCode = 1;
  }
}

// ─── Main ────────────────────────────────────────────────────────────────────

async function main() {
  try {
    // CLI commands — no stdin
    if (HOOK_MODE === 'retro') { await handleRetro(); return; }
    if (HOOK_MODE === 'cleanup' || HOOK_MODE === 'dedup') { await handleCleanup(); return; }
    if (HOOK_MODE === 'refresh-catalog' || HOOK_MODE === 'catalog') { await handleRefreshCatalog(); return; }
    if (HOOK_MODE === 'whoami') { await handleWhoami(); return; }

    // Hook commands — read stdin JSON
    const hookData = await readStdin();
    if (!hookData) { log('no hook data'); return; }

    const sessionId = hookData.session_id || hookData.sessionId;
    const cwd = hookData.cwd || process.cwd();
    if (!sessionId) { log('no sessionId in hook data'); return; }

    if (!isMspLaunchpadContext(cwd)) { log(`skip: non-MSP cwd (${cwd})`); return; }

    const cfg = loadConfig(cwd);
    if (!cfg.url || !cfg.serviceKey) { log('missing supabase config'); return; }

    const state = loadState();

    switch (HOOK_MODE) {
      case 'session-start':
        await handleSessionStart({ sessionId, cwd, cfg, state });
        break;
      case 'user-prompt':
        await handleUserPrompt({ sessionId, cwd, cfg, state, hookData });
        break;
      case 'post-tool-use':
        await handlePostToolUse({ sessionId, cfg, state, hookData });
        break;
      case 'stop':
        await handleStop({ sessionId, cfg, state });
        break;
      case 'session-end':
        await handleSessionEnd({ sessionId, cfg, state });
        break;
      default:
        log(`unknown hook mode: ${HOOK_MODE}`);
    }
  } catch (e) {
    log(`fatal: ${e.message}\n${e.stack || ''}`);
    // silent fail — never block Claude
  }
}

main();
