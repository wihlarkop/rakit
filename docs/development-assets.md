# Rakit web assets

Rakit ships its generated admin stylesheet in `rakit_web/static/rakit.css`.
Normal Python users need neither Bun nor any frontend build tooling: wheels and
source distributions include the committed generated CSS.

Maintainers changing Rakit-owned templates or frontend styling use Bun:

```powershell
bun install
bun run css:build
bun run css:watch
```

Commit both the Tailwind source at `packages/rakit-web/src/rakit_web/assets/rakit.css`
and the regenerated static asset. `uv build --all-packages -o dist` consumes
that committed asset and never invokes Bun.

To verify generated CSS is current, run `bun run css:build` and confirm
`git diff --exit-code -- packages/rakit-web/src/rakit_web/static/rakit.css`.
