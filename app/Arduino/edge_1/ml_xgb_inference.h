#pragma once
#include <Arduino.h>

// ============================================================
// XGBOOST STATISTICAL DETECTOR 2.0 - ESP32-S3 INFERENCE
// Generated directly from:
// xgboost_statistical_detector_2.0(3).json
//
// Model:
//   objective : multi:softprob
//   classes   : 3
//   trees     : 450
//   features  : 24
//   nodes     : 1960
//
// IMPORTANT:
// This is a 3-class model. The returned predictionClass is
// 0, 1, or 2. Do NOT map these to the 2-bit ML flag until the
// training label meaning is confirmed.
// ============================================================

#define ML_XGB_FEATURES 24
#define ML_XGB_TREES 450
#define ML_XGB_CLASSES 3
#define ML_XGB_NODES 1960

struct MLXGBResult
{
    float probability[ML_XGB_CLASSES];
    float margin[ML_XGB_CLASSES];
    uint8_t predictionClass;
};

// Run exact embedded XGBoost inference.
// Input order must exactly match the 24 trained features.
bool runMLXGB(
    const float features[ML_XGB_FEATURES],
    MLXGBResult &result
);

// Optional helper for serial diagnostics.
void printMLXGBInput(
    const float features[ML_XGB_FEATURES]
);
