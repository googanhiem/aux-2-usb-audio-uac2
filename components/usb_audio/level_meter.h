#pragma once

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>

#include "freertos/FreeRTOS.h"

namespace esphome::usb_audio {

/// Peak and RMS of interleaved signed little-endian PCM (any channel count, 1-4 bytes per sample), collected on an
/// audio task and read out, then reset, by a sensor on the main loop. Format-agnostic, so it works for any USB device.
class LevelMeter {
 public:
  static constexpr float SILENCE_DBFS = -100.0f;

  void add(const uint8_t *data, size_t length, uint8_t bytes_per_sample) {
    if (bytes_per_sample == 0 || bytes_per_sample > 4) {
      return;
    }
    const size_t samples = length / bytes_per_sample;
    if (samples == 0) {
      return;
    }
    const int shift = 32 - 8 * bytes_per_sample;
    float sum_sq = 0.0f;
    uint32_t peak = 0;
    for (size_t i = 0; i < samples; i++) {
      const uint8_t *p = data + i * bytes_per_sample;
      uint32_t raw = 0;
      for (uint8_t b = 0; b < bytes_per_sample; b++) {
        raw |= static_cast<uint32_t>(p[b]) << (8 * b);
      }
      // Left-align to 32 bits, so the sign bit lands at bit 31 for every width.
      const int32_t value = static_cast<int32_t>(raw << shift);
      const uint32_t magnitude = value < 0 ? static_cast<uint32_t>(-(static_cast<int64_t>(value)))
                                           : static_cast<uint32_t>(value);
      if (magnitude > peak) {
        peak = magnitude;
      }
      const float normalized = static_cast<float>(value) * (1.0f / 2147483648.0f);
      sum_sq += normalized * normalized;
    }
    portENTER_CRITICAL(&this->lock_);
    this->sum_sq_ += sum_sq;
    this->count_ += samples;
    if (peak > this->peak_) {
      this->peak_ = peak;
    }
    portEXIT_CRITICAL(&this->lock_);
  }

  /// RMS and peak in dBFS since the last call; false when no audio arrived since then.
  bool take(float &rms_dbfs, float &peak_dbfs) {
    portENTER_CRITICAL(&this->lock_);
    const float sum_sq = this->sum_sq_;
    const uint32_t count = this->count_;
    const uint32_t peak = this->peak_;
    this->sum_sq_ = 0.0f;
    this->count_ = 0;
    this->peak_ = 0;
    portEXIT_CRITICAL(&this->lock_);
    if (count == 0) {
      return false;
    }
    rms_dbfs = to_dbfs(std::sqrt(sum_sq / static_cast<float>(count)));
    peak_dbfs = to_dbfs(static_cast<float>(peak) * (1.0f / 2147483648.0f));
    return true;
  }

 protected:
  static float to_dbfs(float amplitude) {
    if (amplitude <= 0.00001f) {
      return SILENCE_DBFS;
    }
    return std::max(SILENCE_DBFS, 20.0f * std::log10(amplitude));
  }

  portMUX_TYPE lock_ = portMUX_INITIALIZER_UNLOCKED;
  float sum_sq_{0.0f};
  uint32_t count_{0};
  uint32_t peak_{0};
};

}  // namespace esphome::usb_audio
