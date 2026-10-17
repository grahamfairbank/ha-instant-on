# Contributing

Thanks for helping. This integration relies on an undocumented API, so **real-world payloads and bug reports are the most useful
contributions**.

## Reporting a bug

1. Turn on debug logging (see the [README](README.md#debug-logging)) and reproduce the problem.
2. Download diagnostics: integration card → three-dot menu → **Download diagnostics**. Personal fields are redacted, but check the file before sharing it.
3. Open a [bug report](../../issues/new?template=bug_report.yml) with the logs and diagnostics attached.

**Never post your password, bearer tokens or unredacted client lists.**

## Development setup

```bash
git clone https://github.com/grahamfairbank/ha-instant-on
cd ha-instant-on
python3 -m venv .venv && . .venv/bin/activate
pip install homeassistant pytest-homeassistant-custom-component ruff==0.14.0
```

To run it in a Home Assistant dev instance, symlink the component into your config directory:

```bash
ln -s "$PWD/custom_components/instant_on" /path/to/ha-config/custom_components/instant_on
```

### Trying the API without Home Assistant

`api.py` has no Home Assistant imports, so you can drive it directly:

```python
import asyncio, aiohttp
from custom_components.instant_on.api import InstantOnClient

async def main():
    async with aiohttp.ClientSession() as s:
        c = InstantOnClient(s, "user@example.com", "password")
        for site in await c.get_sites():
            print(site["name"], len(await c.get_clients(site["id"])))

asyncio.run(main())
```

(Importing `custom_components.instant_on.api` loads the package's `__init__.py`, which needs Home Assistant installed.)

## Working on the dashboard card

The card is one plain JavaScript file, `custom_components/instant_on/frontend/instant-on-card.js`. There's no framework or build step.

- **Without Home Assistant:** run the [card preview](tools/card-preview/README.md) (`python3 -m http.server 8000`, then open
  `/tools/card-preview/`). It loads the card file directly with sample data, and can also use a snapshot of your own network.
- **In Home Assistant:** copy the file over the installed one and hard-refresh the browser (Ctrl+Shift+R). Home Assistant serves the file
  from disk, so you don't need to restart for card-only changes. You do need to restart after changing any Python file.
- **Data:** the card draws only what `overview.build_site()` returns (documented in [ARCHITECTURE.md](docs/ARCHITECTURE.md#dashboard-card)).
  If the card needs a new field, add it there, not in the card.
- **The sidebar panel** (`instant-on-panel`) lives in the same file. Preview it with `tools/card-preview/panel.html`.
- **Register through `registerCard()`, never `customElements.define()` at load time.** Home Assistant loads the file before installing its own
  element registry; see [the registry quirk](docs/ARCHITECTURE.md#how-its-delivered).
- **Before opening a PR, check it at phone width** (the preview's width slider) and with Home Assistant's font. Text in Home Assistant runs slightly
  wider than in the preview.
- **Never commit real network data.** That means `tools/card-preview/overview.json` and any screenshot showing real device or client names.

## Code guidelines

- Follow the Home Assistant [integration quality guidelines](https://developers.home-assistant.io/docs/core/integration-quality-scale/).
- Keep `api.py` and `overview.py` free of Home Assistant imports.
- Entities read from the coordinator only; they never call the API.
- Access new API fields with `.get()`: the schema can change without warning.
- Document new fields or endpoints in [docs/API.md](docs/API.md).
- Run `ruff check .` before you open a PR (the rules are in `ruff.toml`; CI uses ruff 0.14.0). Without a local ruff:
  `docker run --rm -v "$PWD:/io" -w /io ghcr.io/astral-sh/ruff:0.14.0 check --no-cache .`

## Pull requests

- One change per PR, with a clear description and the Home Assistant version you tested with.
- Add an entry under **Unreleased** in [CHANGELOG.md](CHANGELOG.md).
- CI runs `hassfest` and the HACS validator. Both must pass.

## Releasing

1. Bump `version` in `custom_components/instant_on/manifest.json`, and `VERSION` at the top of `frontend/instant-on-card.js`.
2. Move the **Unreleased** changelog entries under the new version, and update the version badge in the README.
3. Commit and push, then tag and push the tag:

   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   ```

4. On GitHub: **Releases → Draft a new release**, choose the tag, set the title to the version, paste that version's changelog section, then **Publish release**.
   HACS offers the update to users from this release; a tag alone isn't enough.
