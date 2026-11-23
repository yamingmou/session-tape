// 用 pi 自己的解析器验收转换产物：能不能加载、能不能重建上下文、能不能被"最近的会话"找到。
const base = '/tmp/pi-proto/node_modules/@mariozechner/pi-coding-agent/dist/core/session-manager.js';
const m = await import(base);
const fs = await import('node:fs');

const file = fs.readFileSync('/tmp/pi-proto/out.txt', 'utf8').trim().replace(/^OUT=/, '');
console.log('目标文件:', file.split('/').slice(-1)[0]);

const entries = m.loadEntriesFromFile(file);
console.log('① loadEntriesFromFile → 条目数:', entries.length);
const kinds = {};
for (const e of entries) kinds[e.type] = (kinds[e.type] || 0) + 1;
console.log('   类型分布:', JSON.stringify(kinds));

const ctx = m.buildSessionContext(entries);
const msgs = ctx.messages ?? ctx;
console.log('② buildSessionContext → 消息数:', Array.isArray(msgs) ? msgs.length : '(非数组)');
if (Array.isArray(msgs)) {
  const seq = msgs.map(x => {
    const c = x.message?.content ?? x.content;
    const txt = typeof c === 'string' ? c : (Array.isArray(c) ? c.map(b => b.text ?? '').join('') : '');
    return `${x.message?.role ?? x.role}:${String(txt).slice(0, 18).replace(/\s+/g, ' ')}`;
  });
  seq.slice(0, 6).forEach((s, i) => console.log(`   [${i + 1}] ${s}`));
  if (seq.length > 6) console.log(`   … 共 ${seq.length} 条`);
}

const recent = m.findMostRecentSession('/tmp/pi-proto/agent');
console.log('③ findMostRecentSession →', recent ? (recent.split('/').pop()) : '(没找到)');
console.log('④ 会话版本:', m.CURRENT_SESSION_VERSION);
