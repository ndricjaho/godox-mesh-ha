# Godox Mesh Light for Home Assistant

Control Godox TL-series RGB lights (TL120 confirmed; likely other Telink-mesh-based
Godox lights too — TL60, TL30, etc.) directly from Home Assistant over Bluetooth,
**without the Godox Light app, without rooting anything, and without cracking
Godox's own encryption keys.**

## Why this exists / how it works

Godox's lights speak standard **Bluetooth SIG Mesh** (via a Telink chipset), not a
simple point-to-point BLE protocol. The Godox app's own network keys are generated
per-install and never leave your phone in a form you can recover without root
access. Instead of fighting that, this project takes a different approach:

1. Factory-reset the light so it forgets Godox's network entirely.
2. Re-provision it into **your own** Bluetooth Mesh network using Nordic's free,
   official **nRF Mesh** app — this generates a fresh Network Key and Application
   Key that *you* control.
3. This integration talks directly to the light using those keys, implementing
   the real Bluetooth Mesh network + application encryption layers itself (no
   dependency on Godox's app, ever again).

The trade-off: once re-provisioned this way, the light **leaves Godox's network**
and the Godox app can no longer control it, until/unless you factory-reset and
re-add it there instead. For Home-Assistant-only use, that's the point.

The actual on/off, brightness, and color commands were reverse-engineered from the
Godox Android app's decompiled source and verified live against a real TL120 —
see [`PROTOCOL.md`](./PROTOCOL.md) for the full technical writeup if you're curious
or want to extend this to more commands (effects, CCT, etc.).

## What you need

- A Godox TL-series light with only Bluetooth connectivity (no WiFi/DMX needed)
- An Android or iOS phone/tablet
- **nRF Mesh** app (free, by Nordic Semiconductor — search your app store)
- Home Assistant with a working Bluetooth adapter reachable by the host running it
  (if you're on Docker, this means `network_mode: host` and the D-Bus socket
  mounted in — see Home Assistant's own Bluetooth integration docs if this isn't
  already working)

## Step 1: Factory-reset the light

Power-cycle the light following the manual's reset sequence (short on/off cycles,
then a couple of longer ones), **or**, if it's currently added in the Godox Light
app, use that app's "remove device" option first.

## Step 2: Provision it with nRF Mesh

1. Install and open **nRF Mesh**. On first launch it silently creates a default
   network for you (auto-generated Network Key) — that's normal.
2. Tap **Add Node**, scan, and select the light (it'll show as an unprovisioned
   device, often named `GD_LED`).
3. Tap **Identify** to confirm it's the right physical light (it'll blink), then
   **Provision**. Wait for it to complete — it'll be assigned a unicast address
   like `0x0002`.
4. Go to **Settings → Manage App Keys → Add App Key** if none exists yet.
5. Back in the light's node page: add that App Key to the node (under "App Keys"),
   then open **Element (the one with ~13 models) → Generic On Off Server** (or any
   model) and **Bind Key** to the same App Key.
6. Also bind the App Key to the model named **"Vendor Model"** (Vendor Model ID
   `0x02110000`) on the same element — this is the one that actually drives the
   LED hardware; the standard SIG models are present for certification but don't
   control the light.

## Step 3: Export your network's keys

In nRF Mesh: **Settings → your network → Export** (usually a share/export icon).
This produces a Mesh Configuration Database JSON file containing your Network Key,
Application Key, and the light's unicast address. You'll need three values out of
it for the next step:

- `netKeys[0].key` — your **Network Key**
- `appKeys[0].key` — your **Application Key**
- The light's node `unicastAddress` (e.g. `"0002"`)

## Step 4: Add the light in Home Assistant

Install this integration via HACS (or manually, see below), then:

**Settings → Devices & Services → Add Integration → Godox Mesh Light**, and fill in:

| Field | Where to find it |
|---|---|
| Bluetooth MAC address | nRF Connect (Nordic's separate scanner app) while the light is advertising, or check My Files logs from the original provisioning |
| Unicast address | From the exported JSON, e.g. `0x0002` |
| Provisioner address | Usually `0x0001` (nRF Mesh's own address in the network) — check the exported JSON's provisioner node if unsure |
| Network Key | From the exported JSON |
| Application Key | From the exported JSON |

Repeat for each additional light — same Network Key and Application Key each
time (they're all on the same mesh network), just a different MAC and unicast
address per light.

## Manual installation (without HACS)

Copy `custom_components/godox_mesh/` into your Home Assistant config directory's
`custom_components/` folder, then restart Home Assistant. The Godox logo
(`custom_components/godox_mesh/brand/`) will show up automatically in the
integrations UI on Home Assistant 2026.3 or newer — no extra setup needed.

## Installing via HACS

Add this repository as a custom repository in HACS (category: Integration), then
install normally, then restart Home Assistant.

## Known limitations

- **No real status feedback.** The light doesn't send back a usable status reply
  over the command set this integration uses, so Home Assistant's shown state is
  optimistic (whatever we last successfully told the light to do), not a live
  read of the light's actual state. If a command silently fails to reach the
  light, the displayed state can drift from reality.
- **On/off and HSI color are confirmed working** (verified live against a real
  TL120). **CCT (color temperature) is implemented but experimental** — the
  wire structure is right, but the exact byte encoding for temperature/tint
  wasn't fully pinned down from static analysis alone and hasn't been verified
  live; it's available at the Python API level (`GodoxMeshLight.set_cct()`) for
  testing, but deliberately not wired into the light entity's UI. **The various
  lighting effects (fire, candle, police car, TV, music, SOS, etc.) are
  documented but not implemented** — see [`PROTOCOL.md`](./PROTOCOL.md) for
  exactly what's confirmed vs. what still needs tracing, and how to trace it.
  PRs welcome.
- **One light per BLE connection at a time**, and only a few simultaneous
  connections are supported by the light's firmware — this shouldn't matter for
  normal on/off/color use (each command connects, sends, disconnects quickly),
  but very rapid back-to-back commands to many lights at once may see occasional
  connection contention.

## Credits

Protocol reverse-engineered via Bluetooth HCI snoop capture analysis and static
analysis of the decompiled Godox Light Android app. Not affiliated with Godox or
Telink Semiconductor.
