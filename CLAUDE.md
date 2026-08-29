# CLAUDE.md

Context for Claude Code (or any AI assistant) working in this repository.

## What this is

A Home Assistant custom integration that controls Godox TL-series RGB lights
(TL120 confirmed) directly over Bluetooth Mesh, bypassing the Godox app and
Godox's own network entirely. The light is re-provisioned into an
independent Bluetooth Mesh network (via nRF Mesh) that the user fully
controls, and this integration implements the actual Mesh encryption layers
itself plus Godox's proprietary vendor-model command format.

Full background/history is in `README.md` (user-facing) and `PROTOCOL.md`
(technical protocol reference). Read `PROTOCOL.md` before touching anything
in `mesh/` — it documents exactly what's confirmed vs. experimental vs.
undocumented, which matters a lot here (see "Confidence levels" below).

## Architecture

```
custom_components/godox_mesh/
├── __init__.py          # HA integration setup, wires HA's Bluetooth
│                         # manager + persistent storage into mesh/
├── config_flow.py        # UI for adding a light (MAC, keys, addresses)
├── const.py
├── light.py               # The LightEntity HA shows in the UI
├── manifest.json
├── strings.json / translations/en.json
├── brand/                 # icon.png / logo.png (+@2x) for the HA UI
└── mesh/                  # Self-contained, NO homeassistant imports.
    ├── crypto.py           # s1/k1/k2/k4, AES-CMAC, AES-CCM, AES-ECB
    ├── network.py          # Network + Upper Transport PDU construction
    ├── proxy.py            # GATT Proxy PDU framing (SAR segmentation)
    ├── ble_client.py       # bleak + bleak-retry-connector transport
    ├── godox_commands.py   # Godox vendor command byte builders + CRC8
    ├── crc8_table.py       # 256-entry CRC8 table pulled from the Godox app
    └── seq.py              # Persistent sequence-number counter
tests/test_mesh.py         # Tests mesh/ only (no HA install needed)
```

**The `mesh/` subpackage is deliberately HA-independent.** It only imports
`bleak`, `bleak_retry_connector`, and `pycryptodome`. Keep it that way —
it's what lets `tests/test_mesh.py` run without a full Home Assistant
installation, and it's the part most likely to be reused/ported elsewhere.
HA-specific glue (config flow, entity, storage, the Bluetooth device lookup)
lives one level up and imports *into* `mesh/`, never the other way.

## Confidence levels — read this before changing `mesh/godox_commands.py`

This matters more here than in a typical codebase, because the "correctness"
of a command was established by testing it against real hardware the AI
assistant doesn't have access to. Don't upgrade something from experimental
to confirmed without the human actually testing it live and saying so.

- **`build_onoff()`, `build_hsi()`**: CONFIRMED. Verified live, byte-for-byte,
  against a real TL120 (see the hardcoded test vectors in `test_mesh.py` —
  those exact hex strings were sent to a real light and worked). Treat these
  as ground truth. If a future change to `network.py` or `crypto.py` ever
  makes these tests fail, that's a real regression, not a vector to update.
- **`build_cct()`**: EXPERIMENTAL. Structure is right, but the temperature/
  tint byte encoding is a documented guess, not a verified fact. Don't wire
  this into `light.py`'s UI-facing color modes until it's been tested live
  and confirmed. Test-only assertions for this function check internal
  consistency (CRC validity, right shape), not correctness against real
  hardware.
- **Lighting effects** (fire, candle, SOS, police car, TV, music, etc.):
  NOT IMPLEMENTED. `PROTOCOL.md` has the full reference of what's known
  (the V3 wire framing is confirmed) vs. not (per-effect sub-command bytes
  and payload layout). If asked to implement one of these, the correct
  approach is the same one used for everything else here: get the
  decompiled `GodoxCommandApi.smali` (not included in this repo — the user
  has it from the original reverse-engineering session, or it can be
  regenerated with `apktool d` on the Godox Light APK), trace the specific
  method to its real UI caller, work out the parameter mapping the same way
  `changeLightSwitch`/`changeLightHSI`/`changeLightCCT` were traced, and
  get it verified live by the user before calling it confirmed.

## Critical invariant: sequence numbers

`mesh/seq.py`'s `SequenceCounter` must never regress or reuse a value once
persisted. It's part of the AES-CCM nonce (see `network.py`) — reusing a
(source address, sequence number, IV index) triple breaks the encryption
scheme's security guarantees, not just correctness. If you touch storage
handling in `__init__.py` or the counter logic in `seq.py`, be paranoid
about this specifically. When in doubt, it's safer to skip sequence numbers
than to ever reuse one.

## Testing

```
pip install -r requirements-test.txt  # or: pip install pytest pycryptodome bleak
python -m pytest tests/ -v
```

17 tests as of this writing, all in `tests/test_mesh.py`, none requiring a
Home Assistant install or real hardware. They cover: RFC 4493 AES-CMAC
vectors (the one piece of crypto verified against a universally-published,
non-mesh-specific reference), the mesh key-derivation functions structurally,
full Network PDU construction (including a check that different sequence
numbers produce different ciphertext — a cheap sanity check against
accidental nonce reuse bugs), GATT Proxy PDU segmentation, and — most
importantly — that `build_onoff()`/`build_hsi()` produce the exact bytes
that were confirmed live against real hardware.

**There is no CI/hardware-in-the-loop testing.** Nothing here can verify a
change actually works against a physical light — that requires the user's
own TL120s. If you make a change to `mesh/ble_client.py`, `network.py`, or
`godox_commands.py`, say so clearly and ask the user to test live rather
than assuming correctness from the test suite passing.

## Known real-world gotchas (already solved once, don't reintroduce)

- **Connect via `bleak_retry_connector.establish_connection()` with a
  `BLEDevice` from `homeassistant.components.bluetooth.async_ble_device_from_address()`**,
  never a raw `BleakClient(mac_address)`. The latter bypasses HA's central
  Bluetooth adapter/connection-slot management and both logs a warning and
  produces unreliable connections in practice. This bit us once already
  (see git history).
- **`GodoxMeshLight` holds an `asyncio.Lock` per instance** to serialize
  connection attempts to the same device. BlueZ raises
  `org.bluez.Error.InProgress` if a second connect is issued to the same
  address while one is already underway. Don't remove this lock or add a
  code path that bypasses `_send_params()`'s locking.
- If BLE connections start failing with adapter/slot errors that restarting
  Bluetooth and Home Assistant doesn't fix, the actual light's own BLE stack
  can get stuck (observed once during development) — power-cycling the
  physical light itself resolved it when nothing server-side did. Worth
  remembering before assuming it's a code bug.

## Style / conventions

- Standard library + `bleak` + `bleak_retry_connector` + `pycryptodome` only
  in `mesh/`. Don't add new dependencies there without a good reason.
- Prefer explicit, spec-cited comments over clever code — this is
  implementing a security-sensitive protocol from a formal spec, and the
  next person (human or AI) reading it needs to be able to check the code
  against the spec section it claims to implement, not just trust it.
- When adding a new Godox command, follow the existing pattern in
  `godox_commands.py`: a `build_*()` function, a module-level `SUBCMD_*`
  constant, a docstring stating the confidence level plainly, and tests
  that check internal consistency at minimum (shape, CRC validity) plus
  exact-byte-match tests for anything actually verified live.
- Don't invent Bluetooth Mesh spec details (key derivation formulas, nonce
  construction, PDU layout) from memory without being confident, and say so
  explicitly when uncertain — this codebase already had one real bug from
  a misremembered test vector (see `crypto.py`'s comments on the self-test
  history); prefer citing a source or asking rather than repeating that.

## Things NOT yet done (real TODOs, not aspirational)

- Live verification of `build_cct()`'s temperature/tint encoding.
- Tracing any of the V3-format lighting effects (see `PROTOCOL.md`).
- No status/read-back support — entity state in `light.py` is optimistic
  only. A real status query would need tracing whatever `GET`-style vendor
  message the app uses (not investigated at all yet).
- Submitting this as a public HACS repository (currently private). The
  `your-github-username` placeholders in `manifest.json` and `hacs.json`
  need to be replaced with the real GitHub username/repo before that.
