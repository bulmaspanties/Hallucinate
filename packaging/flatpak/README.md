# Flatpak and Flathub

`io.github.bulmaspanties.Hallucinate.yml` builds Hallucinate on the KDE 6.11 runtime with the
[PySide BaseApp](https://github.com/flathub/io.qt.PySide.BaseApp) (PySide6 and numpy). The remaining
Python dependencies are pinned with checksums in `python3-requirements.yaml`, so the build needs no
network access, as Flathub requires. CI builds this manifest, launches the result offscreen, and runs
the Flathub linter on every pull request.

## Build locally
```sh
flatpak remote-add --user --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak-builder --user --install --force-clean --install-deps-from=flathub build-dir \
  packaging/flatpak/io.github.bulmaspanties.Hallucinate.yml
flatpak run io.github.bulmaspanties.Hallucinate
```
Check the result with the same linter Flathub uses:
```sh
flatpak install --user flathub org.flatpak.Builder
flatpak run --command=flatpak-builder-lint org.flatpak.Builder manifest packaging/flatpak/io.github.bulmaspanties.Hallucinate.yml
```
Linting a locally built repo (`... repo <repo-dir>`) reports `appstream-external-screenshot-url` and
`appstream-screenshots-not-mirrored-in-ostree`; that is expected, because Flathub's build service mirrors the
screenshots. Any other error needs fixing before submission.
Before submitting, play an MP3 and an AAC file in the built Flatpak: codec support comes from the runtime,
and the CI launch test does not exercise decoding.

## Submitting to Flathub
Submission happens from your own GitHub account; see the
[Flathub submission guide](https://docs.flathub.org/docs/for-app-authors/submission).

1. Make sure the release you are submitting is tagged (for example `v0.3.2`) and that its
   `<release>` entry is in `io.github.bulmaspanties.Hallucinate.metainfo.xml`.
2. Fork [flathub/flathub](https://github.com/flathub/flathub) and create a branch from its
   `new-pr` branch.
3. Copy `io.github.bulmaspanties.Hallucinate.yml` and `python3-requirements.yaml` into the fork's root.
4. In the copied manifest, replace the `type: dir` source with the tagged release:
   ```yaml
   - type: git
     url: https://github.com/bulmaspanties/Hallucinate.git
     tag: v0.3.2
     commit: <full commit hash of that tag>   # git rev-parse v0.3.2^{commit}
   ```
5. Open a pull request against `new-pr` titled `Add io.github.bulmaspanties.Hallucinate`. Reviewers
   build it with `bot, build`. Expect questions about `--talk-name=org.freedesktop.Notifications` and the
   Discord socket, which are commented in the manifest.
6. After it is merged, Flathub creates `flathub/io.github.bulmaspanties.Hallucinate`; future releases
   are pull requests there that bump `tag`/`commit` (and `python3-requirements.yaml` when dependencies
   change).

The `io.github.bulmaspanties` app ID is verified through the GitHub account that owns this repository.

## Updating dependencies
`python3-requirements.yaml` explains how to regenerate it with
[flatpak-pip-generator](https://github.com/flatpak/flatpak-builder-tools/tree/master/pip). When moving to a
newer BaseApp, bump `runtime-version` and `base-version` together; they must match.
