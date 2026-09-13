// =====================================================
// ESP32-S3 ESP-NOW RECEIVER
// Compatible with older ESP32 Arduino core versions
// =====================================================

#include <WiFi.h>
#include <esp_now.h>
#include "esp_wifi.h"

// =====================================================
// ESP-NOW configuration
// Must match the transmitter
// =====================================================

#define ESPNOW_CHANNEL 1

// =====================================================
// Data structure
// This MUST exactly match the transmitter structure
// =====================================================

typedef struct struct_message {
  uint8_t node_id;

  float rotation_x;
  float rotation_y;
  float rotation_z;

  float accel_x;
  float accel_y;
  float accel_z;

  float roof_convergence_cm;

  float temperature;
  float humidity;

  uint32_t timestamp_ms;
} struct_message;

struct_message receivedData;

// =====================================================
// ESP-NOW receive callback
// Older ESP32 Arduino core format
// =====================================================

void OnDataRecv(
  const uint8_t *mac_addr,
  const uint8_t *incomingData,
  int len
) {
  Serial.println();
  Serial.println("====================================");
  Serial.println("ESP-NOW PACKET RECEIVED");
  Serial.println("====================================");

  Serial.print("Received packet size: ");
  Serial.println(len);

  Serial.print("Expected packet size: ");
  Serial.println(sizeof(struct_message));

  // Check packet size
  if (len != sizeof(struct_message)) {
    Serial.println("ERROR: Packet size does not match");
    return;
  }

  // Copy received packet
  memcpy(&receivedData, incomingData, sizeof(receivedData));

  // Print received data
  Serial.println();
  Serial.println("----- SENSOR DATA -----");

  Serial.print("Node ID: ");
  Serial.println(receivedData.node_id);

  Serial.print("Gyro X: ");
  Serial.print(receivedData.rotation_x, 2);
  Serial.println(" dps");

  Serial.print("Gyro Y: ");
  Serial.print(receivedData.rotation_y, 2);
  Serial.println(" dps");

  Serial.print("Gyro Z: ");
  Serial.print(receivedData.rotation_z, 2);
  Serial.println(" dps");

  Serial.print("Accel X: ");
  Serial.print(receivedData.accel_x, 2);
  Serial.println(" g");

  Serial.print("Accel Y: ");
  Serial.print(receivedData.accel_y, 2);
  Serial.println(" g");

  Serial.print("Accel Z: ");
  Serial.print(receivedData.accel_z, 2);
  Serial.println(" g");

  Serial.print("Roof convergence: ");
  Serial.print(receivedData.roof_convergence_cm, 2);
  Serial.println(" cm");

  Serial.print("Temperature: ");
  Serial.print(receivedData.temperature, 2);
  Serial.println(" C");

  Serial.print("Humidity: ");
  Serial.print(receivedData.humidity, 2);
  Serial.println(" %");

  Serial.print("Transmitter timestamp: ");
  Serial.print(receivedData.timestamp_ms);
  Serial.println(" ms");

  Serial.println("------------------------");
  Serial.println("DATA RECEIVED SUCCESSFULLY");
}

// =====================================================
// Setup
// =====================================================

void setup() {
  Serial.begin(115200);
  delay(1500);

  Serial.println();
  Serial.println("====================================");
  Serial.println("ESP32-S3 ESP-NOW RECEIVER");
  Serial.println("====================================");

  // Configure Wi-Fi station mode
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();

  // Set the same channel as the transmitter
  esp_wifi_set_channel(
    ESPNOW_CHANNEL,
    WIFI_SECOND_CHAN_NONE
  );

  Serial.print("Receiver MAC address: ");
  Serial.println(WiFi.macAddress());

  Serial.print("ESP-NOW channel: ");
  Serial.println(ESPNOW_CHANNEL);

  // Initialize ESP-NOW
  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW initialization failed");

    while (true) {
      delay(1000);
    }
  }

  Serial.println("ESP-NOW initialized successfully");

  // Register receive callback
  esp_now_register_recv_cb(OnDataRecv);

  Serial.println("Receiver callback registered");
  Serial.println("Receiver is ready");
  Serial.println("Waiting for transmitter data...");
}

// =====================================================
// Main loop
// =====================================================

void loop() {
  // Data is received automatically in OnDataRecv()
  delay(100);
}