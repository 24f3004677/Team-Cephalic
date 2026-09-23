#include "gru_inference.h"
#include <math.h>

static inline float sigmoidGRU(float x)
{
    if (x >= 0.0f) {
        float e = expf(-x);
        return 1.0f / (1.0f + e);
    } else {
        float e = expf(x);
        return e / (1.0f + e);
    }
}

static void runGRULayer(
    const float *input, int inputDim, int timesteps,
    const float *kernel, const float *recurrent, const float *bias,
    int units, bool returnSequences, float *output)
{
    // Keras GRU(reset_after=True) gate order: [update(z), reset(r), candidate(h)].
    // Bias has shape (2, 3*units): input bias followed by recurrent bias.
    float h[32] = {0.0f};
    float z[32], r[32], hh[32];

    for (int t = 0; t < timesteps; ++t)
    {
        const float *x = input + t * inputDim;
        for (int u = 0; u < units; ++u)
        {
            float az = bias[u];
            float ar = bias[units + u];
            float ah = bias[2 * units + u];

            // kernel is [inputDim, 3*units]
            for (int i = 0; i < inputDim; ++i) {
                const float xi = x[i];
                az += xi * kernel[i * (3 * units) + u];
                ar += xi * kernel[i * (3 * units) + units + u];
                ah += xi * kernel[i * (3 * units) + 2 * units + u];
            }

            // recurrent kernel is [units, 3*units]
            float rz = bias[3 * units + u];
            float rr = bias[4 * units + u];
            float rh = bias[5 * units + u];

            for (int j = 0; j < units; ++j) {
                const float hj = h[j];
                rz += hj * recurrent[j * (3 * units) + u];
                rr += hj * recurrent[j * (3 * units) + units + u];
                rh += hj * recurrent[j * (3 * units) + 2 * units + u];
            }

            z[u] = sigmoidGRU(az + rz);
            r[u] = sigmoidGRU(ar + rr);

            // Keras reset_after=True:
            // candidate = tanh(input_candidate + r * recurrent_candidate)
            hh[u] = tanhf(ah + r[u] * rh);
        }

        // Keras GRU state update:
        // h_new = z*h_old + (1-z)*candidate
        for (int u = 0; u < units; ++u) {
            h[u] = z[u] * h[u] + (1.0f - z[u]) * hh[u];
        }

        if (returnSequences) {
            float *y = output + t * units;
            for (int u = 0; u < units; ++u) y[u] = h[u];
        }
    }

    if (!returnSequences) {
        for (int u = 0; u < units; ++u) output[u] = h[u];
    }
}

int runGRUForecast(const float inputRaw[GRU_SEQ][GRU_INPUT_FEATURES],
                   float predictionScaled[GRU_OUTPUTS])
{
    if (!inputRaw || !predictionScaled) return 1;

    static float xScaled[GRU_SEQ][GRU_INPUT_FEATURES];
    static float gru1Out[GRU_SEQ][GRU_HIDDEN1];
    static float gru2Out[GRU_HIDDEN2];

    for (int t = 0; t < GRU_SEQ; ++t) {
        for (int f = 0; f < GRU_INPUT_FEATURES; ++f) {
            xScaled[t][f] =
                (inputRaw[t][f] - GRU_X_MEAN[f]) / GRU_X_SCALE[f];
        }
    }

    runGRULayer(
        &xScaled[0][0], GRU_INPUT_FEATURES, GRU_SEQ,
        GRU1_KERNEL, GRU1_RECURRENT, GRU1_BIAS,
        GRU_HIDDEN1, true, &gru1Out[0][0]
    );

    runGRULayer(
        &gru1Out[0][0], GRU_HIDDEN1, GRU_SEQ,
        GRU2_KERNEL, GRU2_RECURRENT, GRU2_BIAS,
        GRU_HIDDEN2, false, gru2Out
    );

    // Dense(16 -> 3), linear activation.
    for (int o = 0; o < GRU_OUTPUTS; ++o) {
        float v = DENSE_BIAS[o];
        for (int i = 0; i < GRU_HIDDEN2; ++i) {
            v += gru2Out[i] * DENSE_KERNEL[i * GRU_OUTPUTS + o];
        }
        predictionScaled[o] = v;
    }

    return 0;
}

float calculateGRUTrajectoryError(
    const float predictionScaled[GRU_OUTPUTS],
    const float lastRotationRaw[GRU_OUTPUTS])
{
    float error = 0.0f;

    for (int i = 0; i < GRU_OUTPUTS; ++i) {
        const float yTrueScaled =
            (lastRotationRaw[i] - GRU_Y_MEAN[i]) / GRU_Y_SCALE[i];

        error += fabsf(yTrueScaled - predictionScaled[i]);
    }

    return error / (float)GRU_OUTPUTS;
}
