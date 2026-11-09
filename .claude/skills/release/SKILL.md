---
name: release
description: Release MonoFX Suite (version bump, changelog, installer build, git tag, GitHub Release with MonoFXSuite_Setup.exe and the Blender add-on ZIP). Use when the user asks to release, publish a version, ship, make a new build for others, or "push, release".
---

# Release MonoFX Suite

A release is: the changes since the last tag written up in `docs/changelog.md`, `VERSION` bumped, the
installer and the Blender ZIP built from `main`, a tag `vX.Y.Z` on `main`, and a GitHub Release
carrying both files. `release.ps1` at the repo root does the mechanical part in two steps and checks
everything before it acts; this skill is the part a script cannot do (the notes) and the order.

## 1. See what changed

```bash
git fetch origin --tags
git describe --tags --abbrev=0 origin/main          # last release, e.g. v0.1.24
git log --oneline <last-tag>..HEAD                   # on the branch going to main
```

Read the commits (and the diff where a subject is vague). Nothing since the last tag: say so and stop.

## 2. Write the notes under `## [Unreleased]` in `docs/changelog.md`

Follow the earlier sections in that file:
- Grouped by `### Houdini`, `### Blender`, `### Maya`, `### Installer`, `### Shared / tests` (only the groups that have something).
- One bullet per change a user notices, starting with the tool in bold: `- **Auto Material**: ...`.
  Say what the user can now do or what no longer goes wrong, in their words, not the code's.
  Numbers when they matter ("16 materials ~1 s instead of ~110 s").
- Internal refactors, docs and test-only commits go under `### Shared / tests` in one line, or nowhere.
- Leave `## [Unreleased]` as the heading; `release.ps1 prepare` moves the body into the new version.

Version: `patch` unless the user says otherwise (every release so far has been a patch).

## 3. Prepare (on the branch that goes to main)

```powershell
.\release.ps1 prepare            # or -Bump minor / major
```

It refuses when the tree is dirty, the tests fail or `[Unreleased]` is empty. It commits
`docs: release vX.Y.Z` (VERSION, changelog, RELEASE_NOTES.md) and pushes nothing. Then push the branch
and open the PR as usual, the release commit in it.

## 4. Merge

Merging into `main` is the user's call: the auto-mode classifier blocks `gh pr merge` on an unreviewed
PR until the user says to merge. Ask once ("Merge PR #N and publish vX.Y.Z?"); after their yes, merge
with `gh pr merge <N> --merge` (merge commits, like the earlier releases).

## 5. Publish (from main exactly as on origin)

```powershell
git fetch origin
git switch --detach origin/main     # works in a worktree, where main is checked out elsewhere
.\release.ps1 publish -DryRun       # checks + tests + build, no tag
.\release.ps1 publish
```

`publish` stops before acting when: HEAD is not `origin/main`, the tree is dirty, the changelog has no
section for `VERSION`, the tag or the GitHub Release already exists, gh is logged out, Inno Setup is
missing, tests fail, or the build did not produce a fresh installer and ZIP. It builds before tagging,
so a failed build leaves no tag. Then: tag `vX.Y.Z` at HEAD, push the tag, `publish_release.ps1`
(notes from `RELEASE_NOTES.md`, assets `MonoFXSuite_Setup.exe` + newest `monofx_pipeline_blender_v*.zip`).

Run `publish` in the background (it builds and uploads for a minute or two). If `publish_release.ps1`
fails after the tag is pushed, fix the cause and run `.\publish_release.ps1` alone: do not re-tag.

## 6. Report

```bash
gh release view vX.Y.Z --json url,isDraft,assets --jq '{url, isDraft, assets: [.assets[].name]}'
```

Tell the user the release link, the tag, the two assets, and that other machines get the change by
installing `MonoFXSuite_Setup.exe`. A copy patched by hand into `Documents/houdiniXX.X/monofx` is not
replaced by a release; say so if this session patched one.

## Notes

- Build outputs (`build/output`, the Blender `releases/` ZIP) are git-ignored; nothing to commit after a build.
- A new file the installer must ship needs a line in `build/installer/MonoFXSuite.iss` (`[Files]`) in
  the same change, or the release goes out without it.
- Never push to `main` directly, never move or delete a published tag, never `gh release delete`
  without the user asking.
