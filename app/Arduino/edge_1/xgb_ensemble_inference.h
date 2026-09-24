#pragma once

#include <Arduino.h>

// Exact embedded inference for xgboost_production_ensemble.json.
// Model: binary:logistic, 150 trees, 14 input features.
// Feature order is identical to the trained XGBoost model.

#define XGB_ENSEMBLE_FEATURES 14
#define XGB_ENSEMBLE_TREES 150

struct XGBEnsembleResult
{
    float margin;
    float probability;
    bool prediction;
};

// Normal XGBoost inference
bool runXGBEnsemble(
    const float features[XGB_ENSEMBLE_FEATURES],
    XGBEnsembleResult &result
);

// ============================================================
// DEBUG FUNCTION
// ============================================================
// Runs the same XGBoost tree traversal but prints:
// - tree number
// - global node
// - feature used by the split
// - feature value
// - split threshold
// - next node
// - final leaf weight
//
// This is ONLY for debugging.
// It does not modify the trained model.
// ============================================================

void runXGBTreeDebug(
    const float features[XGB_ENSEMBLE_FEATURES]
);