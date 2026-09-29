'use strict';
const fsp = require('node:fs/promises');
const path = require('node:path');
const { parsePatch, applyPatch } = require('diff');

const stripPrefix = (name) => name.replace(/^[ab]\//, '');

/**
 * Applies a `git diff` style patch to the files under `rootDir` without needing Git.
 * All results are computed in memory first, so a patch that does not apply leaves the tree untouched.
 * Returns the number of files written.
 */
async function applyGitPatch(patchText, rootDir) {
  // The patch is stored with LF; a Windows checkout may have turned it into CRLF.
  const patches = parsePatch(patchText.replace(/\r\n/g, '\n'));
  const results = [];

  for (const p of patches) {
    const relative = stripPrefix(p.newFileName);
    const target = path.join(rootDir, relative);
    const isNew = p.oldFileName === '/dev/null';
    let source = '';
    if (!isNew) {
      try {
        source = await fsp.readFile(target, 'utf8');
      } catch {
        throw new Error(`patch target is missing: ${relative}`);
      }
    }
    const output = applyPatch(source, p);
    if (output === false) throw new Error(`patch does not apply cleanly to ${relative}`);
    results.push({ target, output });
  }

  for (const { target, output } of results) {
    await fsp.mkdir(path.dirname(target), { recursive: true });
    const temporary = `${target}.remiqora-patch-tmp`;
    await fsp.writeFile(temporary, output);
    await fsp.rename(temporary, target);
  }
  return results.length;
}

module.exports = { applyGitPatch };
