import esphome.codegen as cg
from esphome.components import microphone
import esphome.config_validation as cv
from esphome.const import CONF_BUFFER_SIZE, CONF_ID, CONF_NUM_CHANNELS, CONF_SAMPLE_RATE
from esphome.types import ConfigType

from .. import (
    CONF_USB_AUDIO_ID,
    apply_buffer_size,
    bytes_per_frame,
    final_validate_one_per_hub,
    request_microphone_fifo,
    set_stream_limits,
    stream_info,
    stream_schema,
    usb_audio_ns,
)

USBAudioMicrophone = usb_audio_ns.class_(
    "USBAudioMicrophone", microphone.Microphone, cg.Component
)

# Keep in sync with USBAudioMicrophone::READ_TIMEOUT_MS in usb_audio_microphone.h
READ_PERIOD_MS = 20

# Channels the USB device captures, when fewer than num_channels (the channels the microphone publishes): a mono
# capture is copied to both channels of a stereo stream.
CONF_USB_NUM_CHANNELS = "usb_num_channels"


def _usb_config(config: ConfigType) -> ConfigType:
    """The platform config as the USB stream sees it: usb_num_channels in place of num_channels."""
    return {
        **config,
        CONF_NUM_CHANNELS: config.get(CONF_USB_NUM_CHANNELS, config[CONF_NUM_CHANNELS]),
    }


def _read_size(config: ConfigType) -> int:
    """Bytes of USB audio in two read periods."""
    usb = _usb_config(config)
    return usb[CONF_SAMPLE_RATE] * bytes_per_frame(usb) * 2 * READ_PERIOD_MS // 1000


def _upmix_size(config: ConfigType) -> int:
    """Bytes of published audio for one read, when the USB stream has fewer channels; 0 otherwise."""
    usb_channels = config.get(CONF_USB_NUM_CHANNELS, config[CONF_NUM_CHANNELS])
    if usb_channels == config[CONF_NUM_CHANNELS]:
        return 0
    return _read_size(config) // usb_channels * config[CONF_NUM_CHANNELS]


def validate_usb_channels(config: ConfigType) -> ConfigType:
    usb_channels = config.get(CONF_USB_NUM_CHANNELS)
    if usb_channels is not None and usb_channels > config[CONF_NUM_CHANNELS]:
        raise cv.Invalid(
            f"{CONF_USB_NUM_CHANNELS} cannot be more than {CONF_NUM_CHANNELS}",
            path=[CONF_USB_NUM_CHANNELS],
        )
    return config


def validate_buffer_size(config: ConfigType) -> ConfigType:
    """The driver buffer must hold the audio that arrives between two reads, with room to spare."""
    return apply_buffer_size(
        config, _read_size(config), f"{2 * READ_PERIOD_MS} ms of audio"
    )


def _request_fifo(config: ConfigType) -> ConfigType:
    request_microphone_fifo(_usb_config(config))
    return config


CONFIG_SCHEMA = cv.All(
    microphone.MICROPHONE_SCHEMA.extend(stream_schema(16000, 1)).extend(
        {
            cv.GenerateID(): cv.declare_id(USBAudioMicrophone),
            cv.Optional(CONF_USB_NUM_CHANNELS): cv.int_range(min=1, max=2),
        }
    ),
    validate_usb_channels,
    set_stream_limits,
    validate_buffer_size,
    _request_fifo,
)

FINAL_VALIDATE_SCHEMA = final_validate_one_per_hub("microphone")


async def to_code(config: ConfigType) -> None:
    upmix_size = _upmix_size(config)
    var = cg.new_Pvariable(
        config[CONF_ID],
        stream_info(config),
        stream_info(_usb_config(config)),
        config[CONF_BUFFER_SIZE],
        cg.static_buffer(config[CONF_ID], cg.uint8, _read_size(config)),
    )
    if upmix_size:
        upmix_id = cv.declare_id(cg.uint8)(f"{config[CONF_ID].id}_upmix")
        cg.add(
            var.set_upmix_buffer(cg.static_buffer(upmix_id, cg.uint8, upmix_size))
        )
    await cg.register_component(var, config)
    await microphone.register_microphone(var, config)
    hub = await cg.get_variable(config[CONF_USB_AUDIO_ID])
    await cg.register_parented(var, hub)
    cg.add(hub.register_microphone(var))
