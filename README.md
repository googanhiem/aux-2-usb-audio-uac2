# AUX-2 USB Audio: UAC 2.0 prototype

Test firmware configs for the Home Assistant Connect AUX-2 (ESP32-S3) that send the AUX-2's audio mixer to a USB DAC on its USB host port.

ESPHome's `usb_audio` component (esphome/esphome#11728) is built on Espressif's `usb_host_uac`, which only accepts USB Audio Class 1.0 devices. This repo has a prototype `usb_audio` that adds a build option to use the MIT-licensed UAC 2.0 host driver [`averyy/usb_host_uac2`](https://github.com/Averyy/esp-uac2-host) instead. UAC 2.0 runs fine at full speed: 48 kHz, 16-bit stereo is 192 bytes per 1 ms frame.

**Status:** untested prototype, not yet compiled. Speaker (playback) only.

## Configs

| File | Driver | For |
|---|---|---|
| `aux-2-usb-audio-uac2.yaml` | `usb_host_uac2` 0.2.0 | UAC 2.0 devices: Creative SXFI AMP (`041e:6007`), Apple USB-C to 3.5 mm adapter (`05ac:110a`) |
| `aux-2-usb-audio-uac1.yaml` | `usb_host_uac` 1.5.0, patched | UAC 1.0 devices; regression check with the Sound BlasterX G6 (`041e:3256`) |

Both configs:
- pull the upstream AUX-2 package (`NabuCasa/aux-2`, pinned commit);
- point the mixer at the USB speaker (48 kHz, 16-bit, stereo);
- keep everything else from the AUX-2 package, including Sendspin: the hub, the Sendspin media source and its switches, all on by default. Sendspin and media-player audio go through the mixer to the USB speaker. The 16-bit USB speaker makes the whole chain 16-bit;
- remove Bluetooth (proxy, BLE stack, its switch, BLE Improv) and every USB device except the speaker (ZWA-2 Z-Wave proxy, ZBT-2 Zigbee proxy, CH343 USB RS-485/Modbus proxy) via `trim.yaml`. The onboard RS-232 proxies stay;
- add Improv over USB serial and provisioning in place of the factory package, which needs signing keys.

A UAC2 build ignores UAC 1.0 devices and a UAC1 build ignores UAC 2.0 devices.

## Build

The configs need ESPHome `dev` (2026.11.0-dev or later). The AUX-2 package requires 2026.10.2.

```bash
python3 -m venv venv
```

```bash
venv/bin/pip install "esphome @ git+https://github.com/esphome/esphome.git@dev"
```

```bash
venv/bin/esphome compile aux-2-usb-audio-uac2.yaml
```

The firmware lands in `.esphome/build/connect-aux-2/build/`:
- `firmware.factory.bin` for a first flash over USB (web.esphome.io or `esptool`)
- `firmware.ota.bin` for OTA
- `firmware.elf` for decoding crash backtraces

Or flash and follow logs in one step:

```bash
venv/bin/esphome run aux-2-usb-audio-uac2.yaml
```

The UAC2 build logs the device's descriptor dump when it opens the speaker. On start it logs the alternate setting the driver chose, its sync type and its feedback endpoint (`usb_audio` tag). If the format is missing, it lists every alternate setting and clock range.

## Repo layout

- `components/usb_audio/`: ESPHome `usb_audio` from `dev` `0240f5706`, plus `usb_audio: driver: uac1 | uac2` (default `uac1`, the upstream behaviour). Loaded through `external_components`.
- `idf_components/usb_host_uac/`: Espressif `usb_host_uac` 1.5.0 with a fix for a NULL dereference in `uac_host_device_open()`'s `fail:` path. It crashed and boot-looped whenever a device was rejected. Used by the UAC1 config only.
- `patches/usb_audio-uac2.patch`: the `usb_audio` change as a diff against ESPHome.
- `docs/UAC2-PROTOTYPE.md`: approach, API mapping, USB host channel budget, open questions.

## USB host channels

With `trim.yaml` the USB host port is left to the speaker (and a hub, if you use one), so channels are not a constraint for these test builds. A UAC2 speaker uses at most 3 of the 8 channels, and a hub adds 2. The limit below applies to the stock AUX-2 firmware.


The ESP32-S3 has 8 USB host channels, and every endpoint pipe in use holds one, including each device's EP0. A hub, a ZWA-2 and a CH343 already use all 8, so with those three attached no audio device can enumerate.

A UAC2 asynchronous speaker uses 3 channels while streaming (EP0, audio OUT, feedback IN). Hub + ZWA-2 + UAC2 speaker fits exactly. See `docs/UAC2-PROTOTYPE.md`.

## Licenses

- `components/usb_audio` is derived from ESPHome: C++ under GPL-3.0, Python under MIT (see esphome/esphome).
- `idf_components/usb_host_uac` is Espressif's, Apache-2.0 (its `LICENSE` is included), with the local fix above.
- `usb_host_uac2` is fetched from the ESP component registry at build time (MIT).
