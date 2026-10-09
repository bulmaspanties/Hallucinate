# AUR packages

- `hallucinate/` — stable, builds the tagged GitHub release tarball.
- `hallucinate-git/` — tracks `main`.

## Releasing a new version
1. Bump `version` in `pyproject.toml` and `CHANGELOG.md`, commit, tag `vX.Y.Z`, push the tag.
2. In `hallucinate/PKGBUILD` set `pkgver`, `pkgrel=1`, then `updpkgsums`.
3. `makepkg --printsrcinfo > .SRCINFO` and test with `makepkg -f` (ideally `extra-x86_64-build` from `devtools`; `namcap PKGBUILD *.pkg.tar.zst`).

## First submission (do this with your own AUR account + SSH key)
Add your SSH public key at <https://aur.archlinux.org/account>, then for each package:
```sh
git clone ssh://aur@aur.archlinux.org/hallucinate.git aur-hallucinate   # empty repo on first clone
cp packaging/aur/hallucinate/{PKGBUILD,.SRCINFO} aur-hallucinate/
cd aur-hallucinate && git add PKGBUILD .SRCINFO
git commit -m "Initial import: hallucinate 0.1.0"
git push origin HEAD:master
```
Repeat with `hallucinate-git`. AUR branches must be named `master`.
