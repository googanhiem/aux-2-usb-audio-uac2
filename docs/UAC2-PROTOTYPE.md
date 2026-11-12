# UAC 2.0 playback for ESPHome `usb_audio`: prototype notes

Base: esphome `dev` at `0240f5706` (it contains the usb_audio merge `1dc4006`, esphome/esphome#11728).
Driver: `averyy/usb_host_uac2` 0.2.0 (MIT, https://github.com/Averyy/esp-uac2-host). It needs ESP-IDF 5.4 or later; ESPHome builds with 5.5.6.

## Approach

This first step is a build option. It swaps the whole component from `espressif/usb_host_uac` to `usb_host_uac2`:

```yaml
usb_audio:
  driver: uac2   # default uac1 = upstream behaviour, unchanged
```

- The change is an `external_components` override, `components/usb_audio` in this repo. The diff against ESPHome `dev` `0240f5706` is in `patches/usb_audio-uac2.patch`.
- Speaker (playback) only. The microphone platform compiles against UAC2 but is untested. The driver also refuses capture while playback runs on the S3 unless `CONFIG_UAC2_ALLOW_DUPLEX` is set.
- A UAC2 build streams only to UAC2 devices, and a UAC1 build only to UAC1 devices. Doing both at runtime is the next step; see the last section.

## API mapping (`uac_host_*` to `uac2_host_*`)

| usb_audio use | UAC1 (`usb_host_uac` 1.5.0) | UAC2 (`usb_host_uac2` 0.2.0) | Notes |
|---|---|---|---|
| install / uninstall | `uac_host_install(&cfg)` / `uac_host_uninstall()` | `uac2_host_install` / `uac2_host_uninstall` | Config struct has the same fields (background task, priority, stack, core, callback). |
| connect event | `UAC_HOST_DRIVER_EVENT_TX/RX_CONNECTED (addr, iface)` | `UAC2_HOST_DRIVER_EVENT_TX/RX_CONNECTED` | Same shape. UAC2 also reports devices that were already attached at install. |
| disconnect | device cb `UAC_HOST_DRIVER_EVENT_DISCONNECTED` | device cb `UAC2_HOST_DEVICE_EVENT_DISCONNECTED` | Close from a non-callback context, as before. |
| open / close | `uac_host_device_open/close` | `uac2_host_device_open/close` | Same config fields. A failed close keeps the handle valid, so the existing retry logic fits. |
| choose format | `uac_host_get_device_info` + `get_device_alt_param`, then a pre-check of the subframe size | `uac2_host_device_start()` picks the alt itself (best first). It also sets the clock source or selector and starts the feedback EP. | After start, `uac2_host_device_get_stream_info()` is checked. A `sub_slot_size*8 != bits` result is stopped and rejected, the same rule as UAC1. |
| start / suspend / resume / stop | `uac_host_device_start/suspend/resume/stop` | `uac2_host_device_*` | Same semantics: suspend discards the ring and keeps the alt. |
| write | `uac_host_device_write(h, data, len, ticks)` | `uac2_host_device_write(h, data, len, ms)` | Timeout is in ms, not ticks. A write is all-or-nothing. |
| read | `uac_host_device_read(..., ticks)` | `uac2_host_device_read(..., ms)` | |
| volume | `uac_host_device_set_volume(h, percent)` | `uac2_host_device_set_volume_percent(h, ch, %)` | Sets master channel 0. If that fails, sets each stream channel instead; doing both would attenuate twice. |
| mute | `uac_host_device_set_mute(h, bool)` | `uac2_host_device_set_mute_all_channels(h, bool)` | |
| TX_DONE | after every transfer while ring ≤ threshold | once when ring < threshold, re-armed by the next write | UAC2 uses it only as a wakeup (threshold = buffer/2). |
| transfer error | `TRANSFER_ERROR` | `TRANSFER_ERROR`, plus `STREAM_ERROR` (stream dead after 10 consecutive errors) | New STREAM_DEAD event: STOP op, platform gets FAILED, next start() starts afresh. |
| ring fill | (not exposed; the speaker mirrors it) | `uac2_host_device_get_buffer_status()` | See speaker changes. |

## What changed

`__init__.py`
- New `driver: uac1|uac2` option. `uac2` adds IDF component `averyy/usb_host_uac2@0.2.0`, sets `CONFIG_UAC2_NUM_ISOC_URBS=6` (18 ms in flight, the same as the UAC1 path) and defines `USE_USB_AUDIO_UAC2`.

`usb_audio.h/.cpp` (hub)
- `DeviceHandle` typedef and `#ifdef` per driver call.
- `start_uac2_()` lets the driver choose the alt and logs the alt, sync type and feedback EP the driver picked. On a format miss it logs all alts and the clock's rate ranges. `uac2_host_device_print_info()` runs on open, for device bring-up.
- `speaker_ring_bytes()` reads the driver's ring fill.
- STREAM_DEAD event and STOP op.

`speaker/usb_audio_speaker.*`
- The UAC1 driver parks a transfer until the ring holds all of it, so the upstream speaker mirrors that exactly: packet sizing, tail padding and transfer accounting. UAC2 behaves differently. It drains the ring 1 ms packet by packet, at the rate the device's feedback EP reports, and fills any shortfall with silence, so mirroring is impossible.
- Under UAC2 the speaker:
  - reads the ring fill back from the driver for back-pressure;
  - skips tail padding and silence padding;
  - finishes once the ring is empty and the in-flight transfers (18 ms) have played;
  - reports played frames from `loop()` as `written - ring` bytes, about every 10 ms, with a finish time of now + in-flight.
- The loop stays enabled while the stream runs.

## USB host channel budget (ESP32-S3: 8 host channels)

ESP-IDF allocates a host channel when it allocates a pipe (`hcd_pipe_alloc()`, `hcd_dwc.c`, IDF 5.5) and holds it until the pipe is freed. Every enumerated device holds one for EP0, so a device that finds no free channel cannot even enumerate.

| Device | Pipes (channels) |
|---|---|
| Hub | EP0 + interrupt IN = 2 |
| ZWA-2 (CDC-ACM, comm interface unclaimed) | EP0 + bulk IN + bulk OUT = 3 |
| CH343 | EP0 + bulk IN + bulk OUT = 3 |
| UAC1 speaker (G6), streaming | EP0 + iso OUT = 2 (1 while idle) |
| UAC2 async speaker with explicit feedback, streaming | EP0 + iso OUT + **iso IN feedback** = 3 (1 while idle) |
| UAC2 adaptive/sync speaker, streaming | EP0 + iso OUT = 2 |

What this means:
- Hub + ZWA-2 + CH343 already uses 8/8, so with all three attached no audio device can enumerate. That holds for UAC1 too, not just UAC2.
- Without the CH343: hub + ZWA-2 + UAC2 async = 2 + 3 + 3 = **8/8, which fits exactly**. UAC1 would use 7/8.
- Without the ZWA-2: hub + CH343 + UAC2 async = 8/8, which also fits.
- The extra feedback channel matters only for async endpoints. The start log line (`sync async, feedback EP 0x8x`) shows which kind each device is.
- The UAC2 driver allocates the feedback pipe on start(). If no channel is free, that alt is refused, the driver tries the next one, and start() returns NOT_SUPPORTED. That counts as `rejected` (logged once until replug).

USB FIFO: the speaker asks `usb_host` for the iso OUT size (196 B at 48 kHz/16-bit/stereo), which forces a custom split:
- RX keeps its minimum of 34 lines, so IN endpoints up to 128 B fit. The 3–4 byte feedback IN and the 64-byte bulk INs fit there, so `usb_host` needs no change.
- PTX gets the rest, 150 lines = 600 B. An alt with a larger `wMaxPacketSize` is refused by the host, and the driver moves on to the next alt.

## Untested / open

- Nothing has run on hardware. Also not yet compiled (see the build section).
- SXFI AMP (041e:6007) and Apple dongle (05ac:110a, config 1 UAC2): which alt and sync type is chosen. Whether 16-bit/48 kHz is offered. Volume/mute through the feature unit. Hot-unplug during playback.
- The Apple dongle's 24-bit alt probably uses 3-byte slots (works if configured as 24bit). 4-byte slots are rejected, as in UAC1.
- G6 regression: a UAC2 build ignores UAC1 devices by design (the uac2 driver only reports bInterfaceProtocol 0x20). Regression-check the G6 with the UAC1 build (`aux-2-usb-audio-uac1.yaml`). That path is byte-for-byte the upstream code apart from renames inside `#ifdef`.
- Timing reports (`audio_output_callback_`) are approximate under UAC2: ±1 loop iteration plus the 18 ms in-flight estimate. Sendspin sync accuracy is unverified.
- Feedback-driven packet sizing means the device clock sets the drain rate. If the mixer feeds slower or faster than the device clock over long runs, the ring buffer absorbs the drift until it underruns (silence) or back-pressures. That is the same as UAC1 but now visible as driver `underrun_bytes`, which is not logged yet.

## Next step: runtime UAC1 + UAC2

Install both drivers. The UAC1 connect callback also fires for UAC2 interfaces and its open then fails; that is the error path the local `usb_host_uac` patch fixes. So:
- tag each CONNECTED event with its driver;
- ignore UAC1 connects for devices whose bcdADC isn't 1.0, or let them fail quietly;
- keep a per-endpoint `uac2` flag selecting the driver calls and the speaker's buffering model.

USB host clients don't consume host channels, so two drivers cost no channels.
