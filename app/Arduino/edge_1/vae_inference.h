#pragma once
#include <Arduino.h>
#include "buffer_stage_3.h"

// Manual inference for the trained 24x27 convolutional VAE.
// The embedded path uses z_mean (deterministic inference) rather than random
// Sampling epsilon. This makes the anomaly score stable on the ESP32.
bool runVAE(const FeatureBuffer &buffer, float reconstruction[24][27]);
float calculateVAE_MSE(const FeatureBuffer &buffer, const float reconstruction[24][27]);
