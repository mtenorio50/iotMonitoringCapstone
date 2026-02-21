#include "oled.h"
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#define W 128
#define H 64

static Adafruit_SSD1306 display(W, H, &Wire, -1);
static bool g_ok = false;

static int clampi(int v, int lo, int hi){ return v < lo ? lo : (v > hi ? hi : v); }

static void drawBar(int x, int y, int w, int h, int pct){
  display.drawRect(x, y, w, h, SSD1306_WHITE);
  int fill = (w - 2) * pct / 100;
  display.fillRect(x + 1, y + 1, fill, h - 2, SSD1306_WHITE);
}

bool oledInit(int sdaPin, int sclPin, uint8_t addr) {
  Wire.begin(sdaPin, sclPin);
  g_ok = display.begin(SSD1306_SWITCHCAPVCC, addr);
  if (g_ok) {
    display.clearDisplay();
    display.display();
  }
  return g_ok;
}

void oledRender(const OledStatus& s) {
  if (!g_ok) return;

  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);

  display.setCursor(0,0);
  display.printf("LDR: %d (%d%%)", s.ldrRaw, s.ldrPct);

  display.setCursor(0,12);
  display.printf("State: %s", s.isDay ? "DAY" : "NIGHT");

  display.setCursor(0,24);
  display.printf("MQTT: %s  RSSI:%d", s.mqttConnected ? "OK" : "OFF", s.rssiDbm);

  drawBar(0, 40, 128, 12, s.ldrPct);

  display.display();
}
