#pragma once
#include <Arduino.h>

struct OledStatus {
  bool mqttConnected;
  int rssiDbm;
  int ldrRaw;
  int ldrPct;
  bool isDay;
};

bool oledInit(int sdaPin = 21, int sclPin = 22, uint8_t addr = 0x3C);
void oledRender(const OledStatus& s);
