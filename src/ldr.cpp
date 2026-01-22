#include "ldr.h"

static int g_pin = -1;
static uint32_t g_lastMs = 0;
static LdrReading g_r {0, 0.0f};

static int readAvg(int pin, int samples) {
  long sum = 0;
  for (int i = 0; i < samples; i++) {
    sum += analogRead(pin);
    delay(2); // small; ok at low frequency
  }
  return (int)(sum / samples);
}

void ldrInit(int pin) {
  g_pin = pin;
  analogReadResolution(12);  // 0..4095
  g_lastMs = 0;
  g_r = {0, 0.0f};
}

bool ldrTick(uint32_t intervalMs) {
  if (g_pin < 0) return false;

  uint32_t now = millis();
  if (now - g_lastMs < intervalMs) return false;

  g_lastMs = now;
  g_r.raw = readAvg(g_pin, 10);
  g_r.volts = (g_r.raw / 4095.0f) * 3.3f;
  return true;
}

LdrReading ldrGet() {
  return g_r;
}
