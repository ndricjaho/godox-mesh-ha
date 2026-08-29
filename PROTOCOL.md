# Godox Vendor Model Protocol

Technical notes on the reverse-engineered command set, for anyone wanting to add
more commands (effects, CCT, fan control, etc.) or port this to another language.

## Transport

Standard Bluetooth SIG Mesh, GATT Proxy bearer. The light exposes the standard
Mesh Proxy Service (`00001828-...`) with the standard Data In (`00002add-...`) and
Data Out (`00002ade-...`) characteristics. No vendor-specific GATT UUIDs are
involved at the transport level — only the Access-layer opcode is vendor-specific.

Provisioning uses No-OOB authentication (no PIN/confirmation step), standard
FIPS P-256 ECDH. This is what makes provisioning your own device trivial via any
standard mesh provisioner app (nRF Mesh, etc.) — there's nothing Godox-specific
about the provisioning process itself.

## Vendor model

- Company ID: `0x0211` (Telink Semiconductor Co., Ltd — this is Telink's real,
  Bluetooth-SIG-assigned company identifier, not something Godox-specific)
- Model ID: `0x0000` — full Vendor Model ID as shown by mesh tools: `0x02110000`
- All commands observed use outer vendor opcode **`0xF0`**, sent
  **unacknowledged**. (The app's code briefly appears to reference `0xF1` as well,
  in an argument that turns out to be the *expected status/reply opcode* for a
  request-response exchange, not an actual outgoing command opcode — sending a
  real command with opcode `0xF1` produces no response from the light.)

## Inner packet formats

There are **two** Godox-specific inner wire formats, both wrapped inside the
same outer vendor opcode `0xF0`, and both CRC8-checksummed with the same
table -- but structured differently. Which one a given command uses depends
on whether the decompiled code builds it via `sendAgreementDataV2()` (fixed
length) or `sendAgreementDataV3()` (variable length).

### "V2" format (fixed 8 bytes) -- on/off, HSI, CCT

```
[0]     sub-command byte (identifies which command this is)
[1..5]  5 bytes of command-specific data
[6]     1 more byte of command-specific data
[7]     CRC8 checksum of bytes [0..6]
```

### "V3" format (variable length) -- most lighting effects

```
[0]        sub-command byte
[1]        total packet length (= len(data) + 3, i.e. the packet's own total byte count)
[2..N+1]   N bytes of command-specific data
[N+2]      CRC8 checksum of bytes [0..N+1]
```

`build_v3_packet(subcmd, data)` in [`godox_commands.py`](./custom_components/godox_mesh/mesh/godox_commands.py)
implements this framing (fully confirmed from the decompiled
`sendAgreementDataV3()`), ready to use once a given effect's sub-command byte
and data layout are worked out.

### CRC8

Table-driven CRC8, extracted directly from the Godox app
(`com.godox.agm.CRC8Util`). See [`crc8_table.py`](./custom_components/godox_mesh/mesh/crc8_table.py)
for the full 256-entry table. Algorithm:

```python
def crc8(data: bytes) -> int:
    crc = 0
    for b in data:
        crc = CRC8_TABLE[(crc ^ b) & 0xFF]
    return crc & 0xFF
```

### Known / implemented sub-commands ("V2" format)

| Sub-command | Purpose | Status |
|---|---|---|
| `0xFE` | On/Off | **CONFIRMED** — verified live against a real TL120 |
| `0xF1` | HSI color | **CONFIRMED** — verified live against a real TL120 |
| `0xF0` | CCT (color temperature) | EXPERIMENTAL — structure confirmed from decompiled code, temperature/tint byte encoding NOT verified live. See `build_cct()`'s docstring for the (unconfirmed) scaling guess in use. |
| `0xF2` | RGBW | Not traced — not reachable from any TL120 UI screen (only found via what looks like an exported third-party SDK surface; TL120 uses HSI, not RGBW channels) |
| `0xF3` | `changeLightFX` (generic effect) | Not traced |
| `0xF4` | `changeLightCard` | Not traced |
| `0xF5` | `changeElectricFan` | Not applicable — different Godox product line (fans), not present on TL120 |
| `0xFC` | `changeBrightnessOffset` | Marked `@Deprecated` in the app itself ("no effect") — skip this one |

Confirmed payload layouts:

- **On/off**: `data = [onoff (0x00=ON, 0x01=OFF, inverted!), 0xFF, 0xFF, 0xFF, 0xFF]`, trailing byte `0xFF`.
- **HSI**: `data = [brightness_int, hue_low, hue_high, saturation, 0x02]`, trailing byte = `brightness_decimal` (one digit, 0-9). Hue is 0-360 as little-endian 16-bit across bytes 2-3; saturation is 0-100; brightness is split into an integer part (0-100) and a one-digit decimal part, matching how the app's UI displays brightness as e.g. "55.3%".

### What's NOT yet figured out, and why

Most of the lighting-effect commands (fire, candle, police car, TV, music,
SOS, welding, cloudy, explosion, lightning, laser, various "pixel" and
"chase" effects, XY color, RGBW variants, a couple of card-related commands)
use the V3 format above -- confirmed as *framing*, but their per-effect
sub-command byte and data layout are not traced.

Unlike the V2-format methods (where each named method has an inline `const`
literal for its sub-command byte, trivially greppable), most V3-format
effect methods **don't have a hardcoded sub-command constant findable by
static search** — it appears to be supplied dynamically (very possibly as
one of the method's own parameters, shared across a family of effects rather
than baked into each named wrapper). Working these out requires the same
full caller-tracing approach used for `changeLightSwitch` and
`changeLightHSI` (find the method in `GodoxCommandApi.smali`, find where
it's actually called from a real UI screen, work out which caller register
maps to which real-world parameter) — done per-effect, individually. That's
real, one-at-a-time work, not a quick sweep, which is why it isn't done
here yet. Contributions welcome.

Two effect methods DID yield a findable sub-command byte from a quick sweep
(worth a head start if anyone picks this up): `changeLightFXRGBChase` and
`changeLightFXRGBFlow` both appear to use `0xF7`; `changeLightRGBWEx2`
appears to use `0xF9`. None of these three have been traced further
(payload layout, live verification) — treat as a lead, not a confirmed
result.

The following methods exist in `GodoxCommandApi` but are for different Godox
product lines entirely (motorized gimbals, selfie ring lights, fans) and
don't apply to a TL120 at all: `changeElectricFan`, `changeElectricFanV2`,
`changeMotionPitchAxisAngle`, `changeMotionPitchAxisDemarcate`,
`changeMotionPitchAxisSmoothness`, `changeMotionSoftLightParam`,
`changeSelfieModeParam`, `changeSmoothnessParam`, `changeControlModeParam`.

## How this was found

1. Bluetooth HCI snoop capture of the *provisioning* handshake (not useful for
   decrypting ongoing traffic — passive capture of a genuine ECDH exchange
   doesn't yield the session key — but confirmed No-OOB and the exact
   provisioning message sequence).
2. Attempts to control the light via the standard SIG models (Generic OnOff,
   Generic Level, Light Lightness) all failed silently — the physical LED isn't
   wired to those models' state at all.
3. Static analysis (decompiling the Godox Android APK with `apktool`, reading the
   resulting Smali) of `com.godox.agm.GodoxCommandApi` revealed the actual vendor
   command construction, including the CRC8 implementation.
4. Verified live against a real TL120 provisioned into an independent nRF Mesh
   network (i.e. not Godox's own network or keys).
