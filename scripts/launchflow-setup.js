#!/usr/bin/env node
/**
 * LaunchFlow Tracker — One-time team onboarding installer
 *
 * Run once on a team member's machine. Does everything:
 *   1. Copies launchflow-tracker.js to ~/.claude/hooks/
 *   2. Patches ~/.claude/settings.json to wire the 5 hook events (idempotent)
 *   3. Writes ~/.launchflow/.env with the member's name + Supabase creds
 *   4. Runs a `whoami` diagnostic to verify everything resolves
 *
 * Usage:
 *   # Interactive (prompts for each value):
 *   node launchflow-setup.js
 *
 *   # One-shot (skip prompts):
 *   node launchflow-setup.js \
 *     --name "Thanh" \
 *     --url "https://<proj>.supabase.co" \
 *     --key "<service-role-jwt>"
 *
 * The tracker file is expected to live alongside this script
 * (msp-launchpad/scripts/launchflow-tracker.js). Adjust TRACKER_SRC
 * if you're distributing it differently.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');
const readline = require('readline');
const { spawnSync } = require('child_process');

const HOME = os.homedir();
const CLAUDE_DIR = path.join(HOME, '.claude');
const HOOKS_DIR = path.join(CLAUDE_DIR, 'hooks');
const SETTINGS_FILE = path.join(CLAUDE_DIR, 'settings.json');
const LAUNCHFLOW_DIR = path.join(HOME, '.launchflow');
const LAUNCHFLOW_ENV = path.join(LAUNCHFLOW_DIR, '.env');

const SCRIPT_DIR = __dirname;
const TRACKER_SRC = path.join(SCRIPT_DIR, 'launchflow-tracker.js');
const TRACKER_DEST = path.join(HOOKS_DIR, 'launchflow-tracker.js');
const TRACKER_CMD = `node "${TRACKER_DEST.replace(/\\/g, '/')}"`;

// Exactly what we want in settings.json.hooks
const HOOK_ENTRIES = {
  SessionStart: `${TRACKER_CMD} session-start`,
  UserPromptSubmit: `${TRACKER_CMD} user-prompt`,
  PostToolUse: `${TRACKER_CMD} post-tool-use`,
  Stop: `${TRACKER_CMD} stop`,
  SessionEnd: `${TRACKER_CMD} session-end`,
};

// ─── CLI args ────────────────────────────────────────────────────────────────

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--name') out.name = argv[++i];
    else if (a === '--url') out.url = argv[++i];
    else if (a === '--key') out.key = argv[++i];
    else if (a === '--yes' || a === '-y') out.yes = true;
  }
  return out;
}

function prompt(question, defaultValue) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  const label = defaultValue ? `${question} [${defaultValue}]: ` : `${question}: `;
  return new Promise((resolve) => {
    rl.question(label, (answer) => {
      rl.close();
      resolve(answer.trim() || defaultValue || '');
    });
  });
}

// ─── Settings.json patcher ───────────────────────────────────────────────────

function patchSettings() {
  let settings = {};
  if (fs.existsSync(SETTINGS_FILE)) {
    try {
      settings = JSON.parse(fs.readFileSync(SETTINGS_FILE, 'utf8'));
    } catch (e) {
      throw new Error(`Could not parse existing settings.json: ${e.message}`);
    }
  }
  if (!settings.hooks || typeof settings.hooks !== 'object') settings.hooks = {};

  let changed = false;
  for (const [event, command] of Object.entries(HOOK_ENTRIES)) {
    if (!Array.isArray(settings.hooks[event])) settings.hooks[event] = [];
    // Ensure at least one group
    if (settings.hooks[event].length === 0) {
      settings.hooks[event].push({ hooks: [] });
    }
    const group = settings.hooks[event][0];
    if (!Array.isArray(group.hooks)) group.hooks = [];
    // Idempotent: skip if our command is already present
    const already = group.hooks.some((h) => h.command === command);
    if (already) continue;
    group.hooks.push({ type: 'command', command });
    changed = true;
  }

  if (!changed) return { changed: false };

  // Back up first
  if (fs.existsSync(SETTINGS_FILE)) {
    const backup = `${SETTINGS_FILE}.backup-${new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)}`;
    fs.copyFileSync(SETTINGS_FILE, backup);
  }
  fs.writeFileSync(SETTINGS_FILE, JSON.stringify(settings, null, 2));
  return { changed: true };
}

// ─── .env writer ─────────────────────────────────────────────────────────────

function writeLaunchflowEnv({ name, url, key }) {
  if (!fs.existsSync(LAUNCHFLOW_DIR)) fs.mkdirSync(LAUNCHFLOW_DIR, { recursive: true });
  let existing = {};
  if (fs.existsSync(LAUNCHFLOW_ENV)) {
    for (const raw of fs.readFileSync(LAUNCHFLOW_ENV, 'utf8').split(/\r?\n/)) {
      const line = raw.trim();
      if (!line || line.startsWith('#')) continue;
      const eq = line.indexOf('=');
      if (eq < 0) continue;
      existing[line.slice(0, eq).trim()] = line.slice(eq + 1).trim();
    }
  }
  const merged = {
    ...existing,
    LAUNCHFLOW_MEMBER_NAME: name || existing.LAUNCHFLOW_MEMBER_NAME || '',
    LAUNCHFLOW_SUPABASE_URL: url || existing.LAUNCHFLOW_SUPABASE_URL || '',
    LAUNCHFLOW_SUPABASE_SERVICE_KEY: key || existing.LAUNCHFLOW_SUPABASE_SERVICE_KEY || '',
  };
  const lines = [
    '# LaunchFlow tracker config — written by launchflow-setup.js',
    `LAUNCHFLOW_MEMBER_NAME=${merged.LAUNCHFLOW_MEMBER_NAME}`,
    `LAUNCHFLOW_SUPABASE_URL=${merged.LAUNCHFLOW_SUPABASE_URL}`,
    `LAUNCHFLOW_SUPABASE_SERVICE_KEY=${merged.LAUNCHFLOW_SUPABASE_SERVICE_KEY}`,
    '',
  ];
  fs.writeFileSync(LAUNCHFLOW_ENV, lines.join('\n'));
}

// ─── Main ────────────────────────────────────────────────────────────────────

async function main() {
  const args = parseArgs(process.argv.slice(2));
  console.log('LaunchFlow Tracker — setup\n');

  // 1. Verify source file exists
  if (!fs.existsSync(TRACKER_SRC)) {
    console.error(`ERROR: ${TRACKER_SRC} not found.`);
    console.error('Make sure you ran this script from the directory containing launchflow-tracker.js.');
    process.exit(1);
  }

  // 2. Collect member name / creds
  let name = args.name;
  let url = args.url || process.env.LAUNCHFLOW_SUPABASE_URL || process.env.SUPABASE_TEAM_OPS_URL || '';
  let key = args.key || process.env.LAUNCHFLOW_SUPABASE_SERVICE_KEY || process.env.SUPABASE_TEAM_OPS_SERVICE_KEY || '';

  if (!name && !args.yes) name = await prompt('Your name (as shown on the Live Work tab)');
  if (!url && !args.yes) url = await prompt('LaunchFlow Supabase URL', 'https://ftzelkdvqsnaxajqyqui.supabase.co');
  if (!key && !args.yes) key = await prompt('LaunchFlow Supabase service role key');

  if (!name) { console.error('Missing --name'); process.exit(1); }
  if (!url)  { console.error('Missing --url');  process.exit(1); }
  if (!key)  { console.error('Missing --key');  process.exit(1); }

  // 3. Copy tracker to hooks dir
  if (!fs.existsSync(HOOKS_DIR)) fs.mkdirSync(HOOKS_DIR, { recursive: true });
  fs.copyFileSync(TRACKER_SRC, TRACKER_DEST);
  try { fs.chmodSync(TRACKER_DEST, 0o755); } catch (_) { /* Windows no-op */ }
  console.log(`  ✓ tracker installed  ${TRACKER_DEST}`);

  // 4. Write .env
  writeLaunchflowEnv({ name, url, key });
  console.log(`  ✓ config written     ${LAUNCHFLOW_ENV}`);

  // 5. Patch settings.json
  const patch = patchSettings();
  if (patch.changed) console.log(`  ✓ hooks wired        ${SETTINGS_FILE}`);
  else console.log(`  ✓ hooks already set  ${SETTINGS_FILE}`);

  // 6. Diagnostic
  console.log('\nRunning diagnostic…\n');
  const diag = spawnSync('node', [TRACKER_DEST, 'whoami'], { stdio: 'inherit' });
  if (diag.status !== 0) {
    console.error('\nDiagnostic failed. Check the output above.');
    process.exit(1);
  }

  // 7. Refresh catalog so matching works from the first session
  console.log('\nFetching project catalog…\n');
  spawnSync('node', [TRACKER_DEST, 'refresh-catalog'], { stdio: 'inherit' });

  console.log('\nAll set. Your Claude Code sessions inside MSP Launchpad directories');
  console.log('will now auto-register to the Live Work tab in LaunchFlow.');
  console.log('\nOptional: run this to backfill any currently-open sessions:');
  console.log(`  node "${TRACKER_DEST}" retro`);
}

main().catch((e) => { console.error('ERROR:', e.message); process.exit(1); });
