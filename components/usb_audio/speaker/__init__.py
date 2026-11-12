import esphome.codegen as cg
from esphome.components import audio, speaker
import esphome.config_validation as cv
from esphome.const import CONF_BUFFER_SIZE, CONF_ID, CONF_NUM_CHANNELS, CONF_SAMPLE_RATE
from esphome.types import ConfigType

from .. import (
    CONF_USB_AUDIO_ID,
    apply_buffer_size,
    bytes_per_frame,
    final_validate_one_per_hub,
    request_speaker_fifo,
    stream_info,
    stream_schema,
    usb_audio_ns,
)

USBAudioSpeaker = usb_audio_ns.class_("USBAudioSpeaker", speaker.Speaker, cg.Component)

CONF_WRITE_TIMEOUT = "write_timeout"

# Keep in sync with the driver default of CONFIG_UAC_NUM_PACKETS_PER_URB / CONFIG_UAC2_NUM_PACKETS_PER_URB (both 3)
PACKETS_PER_TRANSFER = 3


def set_speaker_input_limits(config: ConfigType) -> ConfigType:
    """Accept 16- to 32-bit input at the stream's rate and channel count; the speaker converts it to bits_per_sample.

    So the speaker can sit behind a router or mixer whose format (e.g. 24-bit for an I2S DAC) differs from what the USB
    device streams.
    """
    audio.set_stream_limits(
        min_bits_per_sample=16,
        max_bits_per_sample=32,
        min_channels=config[CONF_NUM_CHANNELS],
        max_channels=config[CONF_NUM_CHANNELS],
        min_sample_rate=config[CONF_SAMPLE_RATE],
        max_sample_rate=config[CONF_SAMPLE_RATE],
    )(config)
    return config


def validate_buffer_size(config: ConfigType) -> ConfigType:
    """The driver only sends complete transfers, so the buffer must hold two of them to keep audio flowing."""
    frames_per_packet = -(-config[CONF_SAMPLE_RATE] // 1000)
    transfer_size = PACKETS_PER_TRANSFER * frames_per_packet * bytes_per_frame(config)
    return apply_buffer_size(config, 2 * transfer_size, "two USB transfers")


CONFIG_SCHEMA = cv.All(
    speaker.SPEAKER_SCHEMA.extend(stream_schema(48000, 2)).extend(
        {
            cv.GenerateID(): cv.declare_id(USBAudioSpeaker),
            cv.Optional(
                CONF_WRITE_TIMEOUT, default="20ms"
            ): cv.positive_time_period_milliseconds,
        }
    ),
    set_speaker_input_limits,
    validate_buffer_size,
    request_speaker_fifo,
)

FINAL_VALIDATE_SCHEMA = final_validate_one_per_hub("speaker")


async def to_code(config: ConfigType) -> None:
    var = cg.new_Pvariable(
        config[CONF_ID],
        stream_info(config),
        config[CONF_BUFFER_SIZE],
        config[CONF_WRITE_TIMEOUT].total_milliseconds,
    )
    await cg.register_component(var, config)
    await speaker.register_speaker(var, config)
    hub = await cg.get_variable(config[CONF_USB_AUDIO_ID])
    await cg.register_parented(var, hub)
    cg.add(hub.register_speaker(var))
