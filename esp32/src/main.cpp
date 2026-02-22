#include <WiFi.h>
#include <PubSubClient.h>
#include <Preferences.h>
#include <esp_system.h>
#include "credentials.h"
#include "ldr.h"
#include "oled.h"

// LDR pin
const int LDR_PIN = 34;

// ---- Status LEDs + Button ----
static const int LED_WIFI = 25;
static const int LED_MQTT = 26;
static const int LED_OFFLINE = 27;
static const int LED_POWER = 32;
static const int BTN_TOGGLE = 14; // wired to GND, using INPUT_PULLUP

static bool systemEnabled = true;

// debounce
static uint32_t lastBtnChangeMs = 0;
static int lastBtnRead = HIGH;
static int stableBtn = HIGH;

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

unsigned long lastSendMs = 0;
unsigned long lastReconnectAttemptMs = 0;

uint32_t reconnectDelayMs = 3000;
uint32_t wifiFailCount = 0;

Preferences prefs;
uint32_t bootCount = 0;
int resetReason = 0;
bool bootInfoSent = false;

static uint32_t lastUiMs = 0;
static bool isDay = true;

// crude calibration: you WILL adjust after observing real values
static int ldrMin = 300;  // brightest
static int ldrMax = 3000; // darkest

static int clampi(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }
static int ldrPctFromRaw(int raw)
{
  int rc = clampi(raw, ldrMin, ldrMax);
  return (int)((rc - ldrMin) * 100L / (ldrMax - ldrMin));
}

// ---- WiFi ----
bool connectWiFi(uint32_t timeoutMs = 20000)
{
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false); // reduce random drops on ESP32
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("WiFi connecting");
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && (millis() - start) < timeoutMs)
  {
    delay(500);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED)
  {
    wifiFailCount = 0;
    Serial.print("WiFi OK, IP: ");
    Serial.println(WiFi.localIP());
    Serial.print("Gateway: ");
    Serial.println(WiFi.gatewayIP());
    Serial.print("DNS: ");
    Serial.println(WiFi.dnsIP());
    Serial.print("RSSI: ");
    Serial.println(WiFi.RSSI());
    return true;
  }

  wifiFailCount++;
  Serial.println("WiFi FAIL (timeout)");
  return false;
}

// ---- MQTT ----
bool connectMQTT()
{
  // Unique clientId prevents session clashes
  String clientId = "esp32-" + String((uint32_t)ESP.getEfuseMac(), HEX);

  Serial.print("MQTT connecting to ");
  Serial.print(TB_HOST);
  Serial.print(":");
  Serial.println(TB_PORT);

  // ThingsBoard: username = device access token, password empty
  bool ok = mqtt.connect(clientId.c_str());

  if (ok)
  {
    Serial.print("MQTT OK, clientId=");
    Serial.println(clientId);

    // Optional: "boot marker" as telemetry (not attributes)
    if (!bootInfoSent)
    {
      String bootPayload = "{";
      bootPayload += "\"boot_count\":" + String(bootCount) + ",";
      bootPayload += "\"reset_reason\":" + String(resetReason);
      bootPayload += "}";

      mqtt.publish("devices/esp32/telemetry", bootPayload.c_str());
      bootInfoSent = true;
    }
  }
  else
  {
    Serial.print("MQTT FAIL, state=");
    Serial.println(mqtt.state());
    Serial.print("WiFi.status=");
    Serial.println(WiFi.status());
    Serial.print("RSSI=");
    Serial.println(WiFi.RSSI());
  }

  return ok;
}

void sendTelemetry()
{
  unsigned long now = millis();

  String payload = "{";
  // payload += "\"hb\":1,";
  payload += "\"uptime_ms\":" + String(now) + ",";
  payload += "\"rssi_dbm\":" + String(WiFi.RSSI());
  auto r = ldrGet();
  payload += ",\"ldr_raw\":" + String(r.raw);
  payload += ",\"ldr_v\":" + String(r.volts, 3);
  payload += "}";

  Serial.print("Publishing: ");
  Serial.println(payload);

  bool ok = mqtt.publish("devices/esp32/telemetry", payload.c_str());
  Serial.print("publish() => ");
  Serial.println(ok ? "OK" : "FAIL");

  if (!ok)
  {
    Serial.print("mqtt.state() = ");
    Serial.println(mqtt.state());
  }
}

void initIo()
{
  pinMode(LED_WIFI, OUTPUT);
  pinMode(LED_MQTT, OUTPUT);
  pinMode(LED_OFFLINE, OUTPUT);
  pinMode(LED_POWER, OUTPUT);

  pinMode(BTN_TOGGLE, INPUT_PULLUP);

  // default OFF until loop updates
  digitalWrite(LED_WIFI, LOW);
  digitalWrite(LED_MQTT, LOW);
  digitalWrite(LED_OFFLINE, LOW);
  digitalWrite(LED_POWER, LOW);
}

void buttonTick()
{
  const uint32_t now = millis();
  const int reading = digitalRead(BTN_TOGGLE);

  if (reading != lastBtnRead)
  {
    lastBtnRead = reading;
    lastBtnChangeMs = now;
  }

  // 40ms debounce
  if (now - lastBtnChangeMs >= 40)
  {
    if (stableBtn != reading)
    {
      stableBtn = reading;

      // detect press (HIGH -> LOW) because pull-up
      if (stableBtn == LOW)
      {
        systemEnabled = !systemEnabled;
        Serial.printf("systemEnabled=%s\n", systemEnabled ? "true" : "false");
      }
    }
  }
}

void ledsUpdate()
{
  const bool wifiOk = (WiFi.status() == WL_CONNECTED);
  const bool mqttOk = mqtt.connected();

  digitalWrite(LED_POWER, systemEnabled ? HIGH : LOW);

  if (!systemEnabled)
  {
    // when "off", everything else off
    digitalWrite(LED_WIFI, LOW);
    digitalWrite(LED_MQTT, LOW);
    digitalWrite(LED_OFFLINE, LOW);
    return;
  }

  digitalWrite(LED_WIFI, wifiOk ? HIGH : LOW);
  digitalWrite(LED_MQTT, mqttOk ? HIGH : LOW);

  // Offline LED = "system enabled but not fully connected"
  const bool offline = !(wifiOk && mqttOk);
  digitalWrite(LED_OFFLINE, offline ? HIGH : LOW);
}

void setup()
{
  Serial.begin(115200);
  ldrInit(LDR_PIN);
  initIo();
  delay(200);
  resetReason = (int)esp_reset_reason();

  prefs.begin("sys", false);
  bootCount = prefs.getUInt("boot_count", 0) + 1;
  prefs.putUInt("boot_count", bootCount);
  prefs.end();

  Serial.print("boot_count: ");
  Serial.println(bootCount);
  Serial.print("reset_reason: ");
  Serial.println(resetReason);

  // MQTT client configuration BEFORE first connect attempt
  mqtt.setServer(TB_HOST, TB_PORT);
  mqtt.setBufferSize(1024);
  mqtt.setKeepAlive(30);
  mqtt.setSocketTimeout(5);

  // Bring WiFi up (non-blocking with timeout)
  connectWiFi();

  // Try MQTT once (loop handles retries/backoff)
  if (WiFi.status() == WL_CONNECTED)
  {
    connectMQTT();
  }

  // Debug info (optional)
  Serial.printf("Chip model: %s\n", ESP.getChipModel());
  Serial.printf("Chip revision: %d\n", ESP.getChipRevision());
  Serial.printf("Chip cores: %d\n", ESP.getChipCores());
  Serial.printf("Flash size: %u\n", ESP.getFlashChipSize());
  Serial.printf("SDK version: %s\n", ESP.getSdkVersion());

  bool ok = oledInit(21, 22, 0x3C);
  Serial.printf("OLED init: %s\n", ok ? "OK" : "FAIL");
}

void loop()
{
  // 1) Ensure WiFi
  if (WiFi.status() != WL_CONNECTED)
  {
    Serial.println("WiFi lost. Reconnecting...");
    bool ok = connectWiFi();

    // If WiFi keeps failing, you can restart after N fails (optional)
    if (!ok && wifiFailCount >= 10)
    {
      Serial.println("WiFi failed too many times. Restarting...");
      delay(200);
      ESP.restart();
    }

    // Force quick MQTT retry after WiFi returns
    lastReconnectAttemptMs = 0;
    reconnectDelayMs = 3000;
  }

  // 2) Ensure MQTT
  if (WiFi.status() == WL_CONNECTED)
  {
    if (!mqtt.connected())
    {
      unsigned long now = millis();
      if (now - lastReconnectAttemptMs > reconnectDelayMs)
      {
        lastReconnectAttemptMs = now;

        if (connectMQTT())
        {
          reconnectDelayMs = 3000U;
        }
        else
        {
          reconnectDelayMs = reconnectDelayMs * 2U;
          if (reconnectDelayMs > 60000U)
            reconnectDelayMs = 60000U;
        }
      }
    }
    else
    {
      mqtt.loop();
    }
  }

  // 3) Send telemetry on schedule (only when connected)
  unsigned long now = millis();
  if (systemEnabled && mqtt.connected() && (now - lastSendMs > 30000))
  {
    lastSendMs = now;
    sendTelemetry();
  }

  delay(10);

  if (systemEnabled && ldrTick(500))
  {
    auto r = ldrGet();
    Serial.printf("LDR raw=%d volts=%.3f\n", r.raw, r.volts);
  }

  // Update OLED every 500ms
  uint32_t now2 = millis();
  if (now2 - lastUiMs >= 500)
  {
    lastUiMs = now2;

    auto r = ldrGet();
    int pct = ldrPctFromRaw(r.raw);
    pct = 100 - pct; // invert: 0%=dark, 100%=bright

    // hysteresis so it doesn't flicker
    const int DAY_ON = 65;
    const int DAY_OFF = 45;
    if (!isDay && pct >= DAY_ON)
      isDay = true;
    if (isDay && pct <= DAY_OFF)
      isDay = false;

    OledStatus s;
    s.mqttConnected = mqtt.connected();
    s.rssiDbm = WiFi.RSSI();
    s.ldrRaw = r.raw;
    s.ldrPct = pct;
    s.isDay = isDay;

    oledRender(s);
  }

  buttonTick();
  ledsUpdate();
}