#include <WiFi.h>
#include <PubSubClient.h>
#include "credentials.h"

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

unsigned long lastSendMs = 0;
unsigned long lastReconnectAttemptMs = 0;

void connectWiFi()
{
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("WiFi connecting");
  while (WiFi.status() != WL_CONNECTED)
  {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("WiFi OK, IP: ");
  Serial.println(WiFi.localIP());
}

bool connectMQTT()
{
  mqtt.setServer(TB_HOST, TB_PORT);

  Serial.print("MQTT connecting to ");
  Serial.print(TB_HOST);
  Serial.print(":");
  Serial.println(TB_PORT);

  // ThingsBoard: username = device access token, password empty
  bool ok = mqtt.connect("esp32", TB_TOKEN, nullptr);
  Serial.println(ok ? "MQTT OK" : "MQTT FAIL");
  return ok;
}

void sendTelemetry()
{
  unsigned long now = millis();

  String payload = "{";
  payload += "\"hb\":1,";
  payload += "\"uptime_ms\":" + String(now) + ",";
  payload += "\"rssi_dbm\":" + String(WiFi.RSSI());
  payload += "}";

  Serial.print("Publishing: ");
  Serial.println(payload);

  bool ok = mqtt.publish("v1/devices/me/telemetry", payload.c_str());
  Serial.print("publish() => ");
  Serial.println(ok ? "OK" : "FAIL");

  if (!ok)
  {
    Serial.print("mqtt.state() = ");
    Serial.println(mqtt.state()); // 0 = connected, negatives = error
  }
}

void setup()
{
  Serial.begin(115200);
  delay(200);

  connectWiFi();
  mqtt.setBufferSize(1024);
  connectMQTT();
}

void loop()
{
  if (WiFi.status() != WL_CONNECTED)
  {
    Serial.println("WiFi lost. Reconnecting...");
    connectWiFi();
  }

  if (!mqtt.connected())
  {
    unsigned long now = millis();
    if (now - lastReconnectAttemptMs > 3000)
    {
      lastReconnectAttemptMs = now;
      connectMQTT();
    }
  }
  else
  {
    mqtt.loop();
  }

  unsigned long now = millis();
  if (mqtt.connected() && (now - lastSendMs > 30000))
  { // every 30s
    lastSendMs = now;
    sendTelemetry();
  }

  delay(10);
}
