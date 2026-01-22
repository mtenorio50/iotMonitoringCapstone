#pragma once
#include <Arduino.h>

struct LdrReading {
  int raw;
  float volts;
};

void ldrInit(int pin);
bool ldrTick(uint32_t intervalMs);   // returns true when updated
LdrReading ldrGet();
