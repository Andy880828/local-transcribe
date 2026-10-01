#!/usr/bin/env node
// docs-sync v1.1.0 (andy-init)
// Claude Code Stop hook：本輪有「程式變更」就擋下一次，要求依 project-docs 的更新時機表同步文件。
// 由 /andy-init:project-docs 複製進專案；要改行為請改 andy-claude-kit 裡的原檔再 audit，不要只改這份。
//
// 判斷規則：
// - stop_hook_active 為 true（本來就是因為被擋而繼續）→ 放行，避免無限迴圈
// - 非 git repo、git 失敗 → 放行（錯誤寫 stderr；hook 故障不能卡住 session）
// - 程式變更 = 工作區變更 + 上次記錄的 HEAD 之後的 commit，排除 docs/**、根目錄 *.md、.claude/**
// - 同一批變更（路徑＋內容指紋相同）只擋一次
// - 環境變數 DOCS_SYNC_DISABLE=1 → 放行

'use strict';

const { execFileSync } = require('node:child_process');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const STATE_FILE = path.join('.claude', '.docs-sync-state.json');
const MAX_LISTED = 10;
const MAX_HASH_BYTES = 1024 * 1024;
const GIT_TIMEOUT_MS = 8000; // hook 的 timeout 是 15 秒，git 要先放棄才來得及放行
const SPINE_DOCS = ['docs/PROGRESS.md', 'AGENTS.md', 'docs/ARCHITECTURE.md', 'docs/ROADMAP.md', 'docs/PRD.md'];

// repo 設定檔的變動不影響文件內容（例如安裝本 hook 時會改 .gitignore）。
const META_FILES = new Set(['.gitignore', '.gitattributes']);

function isDocOrMeta(file) {
  const base = file.split('/').pop();
  return (
    file.startsWith('docs/') ||
    file.startsWith('.claude/') ||
    META_FILES.has(base) ||
    (!file.includes('/') && file.toLowerCase().endsWith('.md'))
  );
}

// 非 ASCII 路徑（中文檔名）在非 -z 輸出會被寫成 "docs/\344\270..."。所有列檔指令都用 -z（不跳脫），
// core.quotepath=false 是保險：日後若有人加了不帶 -z 的呼叫也不會壞。
// --no-optional-locks：status 不去搶 index.lock，避免和同時執行的 git 指令衝突。
function git(args, cwd) {
  return execFileSync('git', ['--no-optional-locks', '-c', 'core.quotepath=false', ...args], {
    cwd,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
    timeout: GIT_TIMEOUT_MS,
  });
}

function workingTreeChanges(root) {
  const out = git(['status', '--porcelain', '-z', '--untracked-files=all'], root);
  const entries = out.split('\0').filter(Boolean);
  const files = [];
  for (let i = 0; i < entries.length; i++) {
    const status = entries[i].slice(0, 2);
    files.push(entries[i].slice(3));
    if (status.includes('R') || status.includes('C')) i++; // rename/copy 的下一筆是原路徑
  }
  return files;
}

/** 上次記錄的 HEAD 之後、由「自己」提交的非 merge commit 所動到的檔案。pull 進來的別人的 commit 不算。 */
function committedChanges(root, fromHead, toHead) {
  if (!fromHead || fromHead === toHead) return [];
  try {
    git(['merge-base', '--is-ancestor', fromHead, toHead], root);
  } catch {
    return []; // 記錄的 HEAD 已不在歷史上（rebase / 換分支），只看工作區
  }
  let email = '';
  try {
    email = git(['config', 'user.email'], root).trim();
  } catch {
    // 沒設定 user.email 就不過濾作者
  }
  const args = ['log', '--no-merges', '--name-only', '-z', '--format=', `${fromHead}..${toHead}`];
  if (email) args.splice(1, 0, `--author=<${email}>`);
  return git(args, root).split('\0').map((f) => f.trim()).filter(Boolean);
}

// 大檔只取 size 與 mtime，避免 hook 在未忽略的建置產物上讀爆記憶體或逾時。
function contentKey(full) {
  try {
    const st = fs.statSync(full);
    if (!st.isFile()) return '<not-file>';
    if (st.size > MAX_HASH_BYTES) return `size:${st.size}:mtime:${st.mtimeMs}`;
    return crypto.createHash('sha256').update(fs.readFileSync(full)).digest('hex');
  } catch {
    return '<deleted>';
  }
}

function fingerprint(root, files) {
  const hash = crypto.createHash('sha256');
  for (const file of files) hash.update(file).update('\0').update(contentKey(path.join(root, file))).update('\n');
  return hash.digest('hex');
}

function readState(root) {
  try {
    return JSON.parse(fs.readFileSync(path.join(root, STATE_FILE), 'utf8'));
  } catch {
    return {};
  }
}

function writeState(root, state) {
  const file = path.join(root, STATE_FILE);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(state, null, 2) + '\n');
}

function buildReason(root, files) {
  const listed = files.slice(0, MAX_LISTED).map((f) => `  - ${f}`);
  if (files.length > MAX_LISTED) listed.push(`  - …另外 ${files.length - MAX_LISTED} 個`);
  const docs = SPINE_DOCS.filter((d) => fs.existsSync(path.join(root, d)));
  return [
    `[docs-sync] 本輪有 ${files.length} 個程式檔變更，結束前請依 project-docs 的「各文件的更新時機」檢查文件是否過期：`,
    ...listed,
    '',
    `要檢查的文件：${docs.length ? docs.join('、') : '（找不到骨幹文件，請先執行 /andy-init:project-docs）'}`,
    '- docs/PROGRESS.md：§0 接手速覽、最後更新日期、進度符號（⬜／🔄／✅／⛔）是否反映現況',
    '- AGENTS.md：本輪是否發現新陷阱、硬性約束或指令變更',
    '- ARCHITECTURE／ROADMAP／PRD：只有在更新時機表的觸發條件成立時才改',
    '不需要更新就回一句理由即可；同一批變更不會再被擋第二次。',
  ].join('\n');
}

/** 回傳 { block: boolean, reason?: string }。純邏輯，方便測試。 */
function decide(input, env) {
  if (env.DOCS_SYNC_DISABLE === '1' || input.stop_hook_active === true) return { block: false };

  const cwd = input.cwd || env.CLAUDE_PROJECT_DIR || process.cwd();
  let root;
  try {
    root = git(['rev-parse', '--show-toplevel'], cwd).trim();
  } catch {
    return { block: false };
  }

  let head = null;
  try {
    head = git(['rev-parse', 'HEAD'], root).trim();
  } catch {
    // 還沒有任何 commit
  }

  const state = readState(root);
  const changed = [...new Set([...workingTreeChanges(root), ...committedChanges(root, state.head, head)])]
    .filter((f) => !isDocOrMeta(f))
    .sort();

  if (!changed.length) {
    writeState(root, { ...state, head });
    return { block: false };
  }

  const fp = fingerprint(root, changed);
  if (fp === state.fingerprint) {
    writeState(root, { ...state, head });
    return { block: false };
  }

  writeState(root, { head, fingerprint: fp, blockedAt: new Date().toISOString() });
  return { block: true, reason: buildReason(root, changed) };
}

function main() {
  let input = {};
  try {
    const raw = fs.readFileSync(0, 'utf8');
    input = raw.trim() ? JSON.parse(raw) : {};
  } catch (err) {
    process.stderr.write(`[docs-sync] 無法解析 hook 輸入，放行：${err.message}\n`);
    return;
  }
  try {
    const result = decide(input, process.env);
    if (result.block) process.stdout.write(JSON.stringify({ decision: 'block', reason: result.reason }));
  } catch (err) {
    process.stderr.write(`[docs-sync] 執行失敗，放行：${err.stack || err}\n`);
  }
}

if (require.main === module) main();

module.exports = { decide, isDocOrMeta };
