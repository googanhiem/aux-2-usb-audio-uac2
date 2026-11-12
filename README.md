# AUX-2 USB Audio: UAC 2.0 prototype

Test firmware configs for the Home Assistant Connect AUX-2 (ESP32-S3) that add a USB audio device on its USB host port: a third audio output next to the analog DAC and TOSLink, the device's input as a Sendspin source, and sensors for connection and levels.

ESPHome's `usb_audio` component (esphome/esphome#11728) is built on Espressif's `usb_host_uac`, which only accepts USB Audio Class 1.0 devices. This repo has a prototype `usb_audio` that adds a build option to use the MIT-licensed UAC 2.0 host driver [`averyy/usb_host_uac2`](https://github.com/Averyy/esp-uac2-host) instead. UAC 2.0 runs fine at full speed: 48 kHz, 16-bit stereo is 192 bytes per 1 ms frame.

**Status:** prototype. USB output on the UAC2 build plays through the Apple USB-C adapter. USB input, the sensors and the UAC1 build are untested on hardware.

## Configs

| File | Driver | For |
|---|---|---|
| `aux-2-usb-audio-uac2.yaml` | `usb_host_uac2` 0.2.0 | UAC 2.0 devices. Works: Apple USB-C to 3.5 mm adapter (`05ac:110a`) |
| `aux-2-usb-audio-uac1.yaml` | `usb_host_uac` 1.5.0, patched | UAC 1.0 devices; regression check with the Sound BlasterX G6 (`041e:3256`) |

Both pull the upstream AUX-2 package (`NabuCasa/aux-2`, pinned commit) and add two local packages:

- `trim.yaml` removes Bluetooth (proxy, BLE stack, its switch, BLE Improv) and the ZWA-2, ZBT-2 and CH343 USB RS-485 (Modbus) support. It also removes the core package's output router and selector, which `usb-audio.yaml` replaces. The onboard RS-232 proxies stay.
- `usb-audio.yaml` adds the USB audio features below.

Improv over USB serial and provisioning replace the factory package, which needs signing keys. A UAC2 build ignores UAC 1.0 devices, and a UAC1 build ignores UAC 2.0 devices.

### Audio output

The **Audio Output** selector has three options: **Analog** (PCM5122 DAC), **Digital** (TOSLink) and **USB**.

- Everything the AUX-2 plays goes mixer → router → the selected output. That covers Sendspin, the media player and announcements.
- The router runs at 24-bit. The USB speaker converts that to the 16-bit stereo 48 kHz stream the USB device gets.
- If the USB device is missing or can't stream, only the USB output is silent; Analog and Digital keep working.
- The jack-detect automation (`Automatic output mode selection`) still switches between Analog and Digital when a plug goes in. Turn it off if you want USB to stay selected.

### USB input as a Sendspin source

The USB device's capture interface is the AUX-2's Sendspin **source**. That can be a headset mic or line in through a TRRS splitter on the Apple adapter. Sendspin gets 48 kHz, 16-bit **stereo**, so a server such as Music Assistant can use it as an input.

The device itself captures mono (the Apple adapter's jack has a single mic contact), and the USB microphone copies that channel to left and right (`usb_num_channels: 1` with `num_channels: 2`). The input is mic-level with bias power on the mic line: a line-level source probably needs an attenuator.

The UAC2 build enables duplex in the driver (`CONFIG_UAC2_ALLOW_DUPLEX`). `usb_host` splits the USB FIFO between playback and capture.

### Sensors (any USB audio device)

| Entity | What it shows |
|---|---|
| USB Audio Output / Input Connected | The device's playback / capture interface is open |
| USB Audio Output / Input Status | Device name and the format it streams, or why it could not start |
| USB Audio Output Playing | The USB output is streaming |
| USB Audio Input Signal | Input above -60 dBFS RMS (held 2 s) |
| USB Audio Output / Input Level, Peak | RMS and peak in dBFS over the last second |
| USB Audio Input Monitor (switch) | Keeps the input running so its sensors work without a Sendspin server; on by default |

Levels are computed on the AUX-2 from the PCM it sends and receives, so they work with any device. They read *unknown* while nothing streams.

### Devices that can't work at full speed

The ESP32-S3's USB host is full-speed: one packet per 1 ms frame. Some high-speed devices keep their high-speed packet sizes, meant for 125 µs microframes, when attached at full speed. The Creative SXFI AMP (`041e:6007`) is one: its 2-channel 16-bit alt allows 64-byte packets, and 48 kHz stereo needs 192.

No host-side setting can fix that. The status sensor reports it as "endpoint too small at full speed".

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

- `components/usb_audio/`: ESPHome `usb_audio` from `dev` `0240f5706`, loaded through `external_components`. Changes:
  - `usb_audio: driver: uac1 | uac2` (default `uac1`, the upstream behaviour);
  - the speaker accepts 16- to 32-bit input and converts it to the USB stream's width;
  - RMS/peak level meters on the speaker and microphone (`take_level()`);
  - `is_connected()` and `get_status()` on the hub.
- `idf_components/usb_host_uac/`: Espressif `usb_host_uac` 1.5.0 with a fix for a NULL dereference in `uac_host_device_open()`'s `fail:` path. It crashed and boot-looped whenever a device was rejected. Used by the UAC1 config only.
- `patches/usb_audio-uac2.patch`: the `usb_audio` changes as a diff against ESPHome `0240f5706`.
- `docs/UAC2-PROTOTYPE.md`: approach, API mapping, USB host channel budget, open questions.

## USB host channels

With `trim.yaml` the USB host port is left to the audio device (and a hub, if you use one), so channels are not a constraint for these test builds. A UAC2 device streaming both ways uses 4 of the 8 channels (EP0, audio OUT, feedback IN, capture IN), and a hub adds 2. The limit below applies to the stock AUX-2 firmware.

The ESP32-S3 has 8 USB host channels, and every endpoint pipe in use holds one, including each device's EP0. A hub, a ZWA-2 and a CH343 already use all 8, so with those three attached no audio device can enumerate.

A UAC2 asynchronous speaker uses 3 channels while streaming (EP0, audio OUT, feedback IN). Hub + ZWA-2 + UAC2 speaker fits exactly. See `docs/UAC2-PROTOTYPE.md`.

## Licenses

- `components/usb_audio` is derived from ESPHome: C++ under GPL-3.0, Python under MIT (see esphome/esphome).
- `idf_components/usb_host_uac` is Espressif's, Apache-2.0 (its `LICENSE` is included), with the local fix above.
- `usb_host_uac2` is fetched from the ESP component registry at build time (MIT).
