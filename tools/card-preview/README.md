# Card preview

Work on `instant-on-card` in a normal browser, without Home Assistant. The page loads the card straight from
`custom_components/instant_on/frontend/`, gives it a fake `hass` object that returns a snapshot, and makes up 24 hours of history.

## Run it

From the repository root:

```bash
python3 -m http.server 8000
```

Then open <http://localhost:8000/tools/card-preview/>. Edit the card, then reload the page to see the change. The slider changes the card's width, so you
can check the phone layout.

## Use your own network's data

`sample-overview.json` is made-up data. To preview your own network:

1. Open any Home Assistant page in your browser, open the browser's developer tools (F12), and run this in the **Console** tab:

   ```js
   copy(JSON.stringify(await document.querySelector("home-assistant").hass.callWS({ type: "instant_on/overview" })))
   ```

2. Paste the result into `tools/card-preview/overview.json`.
3. Pick **overview.json** at the top of the preview page.

`overview.json` holds your device names, client names and network layout. It's listed in `.gitignore`; **don't commit it**.

## Screenshots without a desktop browser

On a headless machine with Docker:

```bash
docker run --rm --network host -v "$PWD:/repo:ro" zenika/alpine-chrome:124 --no-sandbox --hide-scrollbars --window-size=1330,1500 --screenshot=/tmp/s.png http://localhost:8000/tools/card-preview/
```

(The screenshot is written inside the container; add `-v /some/dir:/tmp` to keep it.)
