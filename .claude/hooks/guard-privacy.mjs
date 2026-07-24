#!/usr/bin/env node
// PreToolUse(Bash): block `git commit` while git tracks a private file
// (.env, resume, db/, config.yaml). PRINCIPLES #12 is a red line, and CI only
// catches a leak after it is already pushed. tools/check_privacy.mjs owns the
// rules — this just runs it at the last moment where the leak is still local.
import { execFileSync } from "node:child_process";

const stdin = await new Promise((r) => {
  let s = "";
  process.stdin.on("data", (c) => (s += c)).on("end", () => r(s));
});

let cmd = "";
try {
  cmd = JSON.parse(stdin)?.tool_input?.command ?? "";
} catch {
  process.exit(0); // unparseable payload is not our problem — let it through
}
if (!/\bgit\s+commit\b/.test(cmd)) process.exit(0);

const root = process.env.CLAUDE_PROJECT_DIR ?? process.cwd();
try {
  execFileSync("node", [`${root}/tools/check_privacy.mjs`], { stdio: "pipe" });
} catch (e) {
  const reason = `Blocked — git tracks a private file (PRINCIPLES #12):\n${
    e.stdout?.toString() ?? ""
  }${e.stderr?.toString() ?? ""}`.trim();
  process.stdout.write(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: reason,
      },
    }),
  );
}
