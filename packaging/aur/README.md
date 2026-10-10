# AUR packages

- `hallucinate/` — stable, builds the tagged GitHub release tarball.
- `hallucinate-git/` — tracks `main`.

CI builds the stable package in an Arch Linux container on every pull request. It checks that each
`.SRCINFO` matches its `PKGBUILD`, runs `namcap`, installs the package and launches it offscreen.

## Releasing a new version
1. Release `vX.Y.Z` as described in `CONTRIBUTING.md` (version bump PR, then the Release workflow).
2. In `hallucinate/PKGBUILD` set `pkgver`, `pkgrel=1`, then run `updpkgsums` (or put the
   `sha256sum` of `https://github.com/bulmaspanties/Hallucinate/archive/refs/tags/vX.Y.Z.tar.gz` in
   `sha256sums`).
3. `makepkg --printsrcinfo > .SRCINFO` (in both package directories if `hallucinate-git` changed) and
   test with `makepkg -f` (ideally `extra-x86_64-build` from `devtools`; `namcap PKGBUILD *.pkg.tar.zst`).
4. Commit the updated `PKGBUILD`/`.SRCINFO` here, then copy them into the AUR repository and push (below).

## First submission (do this with your own AUR account + SSH key)
Add your SSH public key at <https://aur.archlinux.org/account>, then for each package:
```sh
git clone ssh://aur@aur.archlinux.org/hallucinate.git aur-hallucinate   # empty repo on first clone
cp packaging/aur/hallucinate/{PKGBUILD,.SRCINFO} aur-hallucinate/
cd aur-hallucinate && git add PKGBUILD .SRCINFO
git commit -m "Initial import: hallucinate $(sed -n 's/^pkgver=//p' PKGBUILD)"
git push origin HEAD:master
```
Repeat with `hallucinate-git` (clone `ssh://aur@aur.archlinux.org/hallucinate-git.git`). AUR branches
must be named `master`. Later updates are the same copy, commit and push.
