#include "vae_inference.h"
#include "vae_weights.h"
#include <math.h>
#include <string.h>

static inline float relu(float x) { return x > 0.0f ? x : 0.0f; }

static void batchNorm(const float *in, float *out, int length, int channels,
                      const float *gamma, const float *beta,
                      const float *mean, const float *var) {
  for (int i = 0; i < length; ++i) {
    for (int c = 0; c < channels; ++c) {
      int p = i * channels + c;
      out[p] = gamma[c] * (in[p] - mean[c]) / sqrtf(var[c] + VAE_BN_EPS) + beta[c];
    }
  }
}

// Keras Conv1D, padding='same', stride=2, activation=relu.
// Weight layout: [kernel, input_channel, output_channel].
static void conv1dSameS2(const float *in, int inLen, int inCh,
                         const float *w, const float *b, int outCh,
                         float *out) {
  const int outLen = (inLen + 1) / 2;
  for (int o = 0; o < outLen; ++o) {
    const int base = o * 2; // SAME padding_before = 0 for L=24,k=3,s=2 and L=12,k=3,s=2
    for (int oc = 0; oc < outCh; ++oc) {
      float sum = b[oc];
      for (int k = 0; k < 3; ++k) {
        int ii = base + k;
        if (ii < 0 || ii >= inLen) continue;
        for (int ic = 0; ic < inCh; ++ic) {
          sum += in[ii * inCh + ic] * w[(k * inCh + ic) * outCh + oc];
        }
      }
      out[o * outCh + oc] = relu(sum);
    }
  }
}

// Keras Conv1DTranspose, padding='same', stride=2, kernel=3.
// For these exact shapes (6->12 and 12->24), TensorFlow SAME transpose
// corresponds to pad=1: each input position contributes to output i*2-1..i*2+1.
static void conv1dTransposeSame(const float *in, int inLen, int inCh,
                              const float *w, const float *b, int outCh, int stride,
                              float *out, bool useRelu) {
  const int outLen = inLen * stride;
  for (int i = 0; i < outLen * outCh; ++i) out[i] = 0.0f;

  for (int oc = 0; oc < outCh; ++oc) {
    for (int o = 0; o < outLen; ++o) out[o * outCh + oc] = b[oc];
  }

  for (int i = 0; i < inLen; ++i) {
    for (int k = 0; k < 3; ++k) {
      int o = i * stride + k - 1;
      if (o < 0 || o >= outLen) continue;
      for (int ic = 0; ic < inCh; ++ic) {
        float x = in[i * inCh + ic];
        for (int oc = 0; oc < outCh; ++oc) {
          out[o * outCh + oc] += x * w[(k * outCh + oc) * inCh + ic];
        }
      }
    }
  }

  if (useRelu) {
    for (int i = 0; i < outLen * outCh; ++i) out[i] = relu(out[i]);
  }
}

static void dense(const float *in, int inN, const float *w, const float *b,
                  int outN, float *out, bool useRelu) {
  for (int j = 0; j < outN; ++j) {
    float sum = b[j];
    for (int i = 0; i < inN; ++i) sum += in[i] * w[i * outN + j];
    out[j] = useRelu ? relu(sum) : sum;
  }
}

bool runVAE(const FeatureBuffer &buffer, float reconstruction[24][27]) {
  if (buffer.count < VAE_SEQ) return false;

  // Encoder: 24x27 -> 12x16 -> 6x32 -> 192 -> 4
  static float c1[12 * 16];
  static float bn1[12 * 16];
  static float c2[6 * 32];
  static float bn2[6 * 32];
  static float flat[192];
  static float zMean[4];
  static float zLogVar[4];

  // Decoder: 4 -> 192 -> 6x32 -> 12x32 -> 24x16 -> 24x27
  static float d0[192];
  static float d6[6 * 32];
  static float dt1[12 * 32];
  static float dbn1[12 * 32];
  static float dt2[24 * 16];
  static float dbn2[24 * 16];
  static float dt3[24 * 27];

  conv1dSameS2(&buffer.data[0][0], 24, 27, ENC_CONV1_W, ENC_CONV1_B, 16, c1);
  batchNorm(c1, bn1, 12, 16, ENC_BN1_G, ENC_BN1_B, ENC_BN1_M, ENC_BN1_V);

  conv1dSameS2(bn1, 12, 16, ENC_CONV2_W, ENC_CONV2_B, 32, c2);
  batchNorm(c2, bn2, 6, 32, ENC_BN2_G, ENC_BN2_B, ENC_BN2_M, ENC_BN2_V);

  memcpy(flat, bn2, sizeof(flat));
  dense(flat, 192, ZMEAN_W, ZMEAN_B, 4, zMean, false);
  dense(flat, 192, ZLOG_W, ZLOG_B, 4, zLogVar, false);

  // Deterministic embedded inference: z = z_mean.
  // zLogVar is still computed to keep the encoder path identical to the model.
  (void)zLogVar;

  dense(zMean, 4, DEC_DENSE_W, DEC_DENSE_B, 192, d0, true);
  memcpy(d6, d0, sizeof(d6));

  conv1dTransposeSame(d6, 6, 32, DEC_CONVT1_W, DEC_CONVT1_B, 32, 2, dt1, true);
  batchNorm(dt1, dbn1, 12, 32, DEC_BN1_G, DEC_BN1_B, DEC_BN1_M, DEC_BN1_V);

  conv1dTransposeSame(dbn1, 12, 32, DEC_CONVT2_W, DEC_CONVT2_B, 16, 2, dt2, true);
  batchNorm(dt2, dbn2, 24, 16, DEC_BN2_G, DEC_BN2_B, DEC_BN2_M, DEC_BN2_V);

  conv1dTransposeSame(dbn2, 24, 16, DEC_CONVT3_W, DEC_CONVT3_B, 27, 1, dt3, false);

  for (int t = 0; t < 24; ++t)
    for (int f = 0; f < 27; ++f)
      reconstruction[t][f] = dt3[t * 27 + f];

  return true;
}

float calculateVAE_MSE(const FeatureBuffer &buffer, const float reconstruction[24][27]) {
  if (buffer.count < VAE_SEQ) return NAN;
  double sum = 0.0;
  for (int t = 0; t < 24; ++t) {
    for (int f = 0; f < 27; ++f) {
      float d = buffer.data[t][f] - reconstruction[t][f];
      sum += (double)d * (double)d;
    }
  }
  return (float)(sum / (24.0 * 27.0));
}
