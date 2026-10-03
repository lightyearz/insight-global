// Copies the deck's compositions/ and assets/ into video/ so the linear-video entry
// (video/index.html) mounts the same scene files as the slideshow deck.
// Plain copies (not symlinks): they work on Windows, with core.symlinks=false and in zip files.
// The copies are build output and are git-ignored; edit the deck folders, never video/*.
import { cpSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
for (const dir of ["compositions", "assets"]) {
  const dest = join(root, "video", dir);
  rmSync(dest, { recursive: true, force: true });
  cpSync(join(root, dir), dest, { recursive: true });
}
console.log("video/: compositions/ and assets/ synced from the deck");
