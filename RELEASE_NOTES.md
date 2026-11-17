## [0.1.31] - 2026-11-17

### Houdini
- **Mono Anim Loader** node put down by hand: **Shot** is a menu of the project's shots (shots with no anim say so), and changing the shot moves the same character to the newest anim there, or picks that shot's newest version with no file yet, instead of keeping the old shot's version ("anim v001 missing on disk"). While nothing is picked, Status says just the next step: outside a project, where to set one (Project Root under Advanced, or the manager's Project box); then pick a shot, "sh030 has no anim publish yet", pick an anim file.