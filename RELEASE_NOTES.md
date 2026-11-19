## [0.1.39] - 2026-11-19

### Houdini
- **MonoFX Loader**: opening a scene whose loaders have newer publishes shows a small prompt listing them (which part, from which version to which), with **Open manager** and **Update**. It stacks above the heavy-shot prompt. **Don't show again for these versions** keeps it quiet for that scene until something newer is published.
- **MonoFX Loader**: an Update made outside the manager (from that prompt) refreshes the open manager; before, it still said "2 behind".