# mod-upload

Holds only the latest BlackHawk mod JAR. Each push here runs `.github/workflows/publish-mod.yml`,
which uploads the JAR to the `pack-current` release as `bh-<sha256>` and updates the
`mods/blackhawk-1.0.0.jar` entry of `manifest.json` (old manifest kept as `manifest.previous-*.json`).
