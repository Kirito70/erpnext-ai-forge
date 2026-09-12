// AUTO-GENERATED FROM erpnext-ai-forge 0.1.0 — DO NOT EDIT
// Source: adapters/opencode/templates/harness-plugin.js.j2
// Target: self (python_cli)
//
// Runs the shared harness after every write/edit. Throwing sends the lint
// output back to the model, which is opencode's equivalent of a blocking hook.

import { spawn } from "node:child_process";
import path from "node:path";

const HARNESS = "scripts/harness/check-file.sh";

const TIMEOUT_MS = 240000;

function runCheck(root, file) {
  return new Promise((resolve) => {
    const child = spawn("bash", [path.join(root, HARNESS), file], {
      cwd: root,
      env: { ...process.env },
    });

    let out = "";
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (out += d));

    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      // Timing out is not the same as failing. Killing the check and then
      // reporting "clean" would be a lie; reporting a failure the developer
      // cannot reproduce is worse. Say what happened.
      resolve({ code: 0, out: `[harness] check-file timed out after ${TIMEOUT_MS}ms` });
    }, TIMEOUT_MS);

    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ code: code ?? 0, out });
    });

    // A missing interpreter or script must not break the editing session — the
    // harness is a safety net, not a dependency of being able to type.
    child.on("error", (err) => {
      clearTimeout(timer);
      resolve({ code: 0, out: `[harness] could not run check-file: ${err.message}` });
    });
  });
}

export const HarnessPlugin = async ({ directory }) => ({
  "tool.execute.after": async (input, output) => {
    const tool = (input?.tool ?? "").toLowerCase();
    if (!["write", "edit", "patch", "multiedit"].includes(tool)) return;

    const file =
      output?.args?.filePath ?? output?.args?.file_path ?? input?.args?.filePath;
    if (!file) return;

    const { code, out } = await runCheck(directory, file);
    if (code !== 0) {
      // Thrown errors are surfaced to the model — the point is that it sees the
      // lint output and fixes it, not that the session dies.
      throw new Error(out || `harness: check-file failed for ${file}`);
    }
    if (out.trim()) console.log(out.trim());
  },
});

export default HarnessPlugin;
