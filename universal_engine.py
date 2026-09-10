import os
import json
import time
import traceback
import numpy as np
import pandas as pd
import xgboost as xgb
import tensorflow as tf
from tensorflow import keras
import joblib
import matplotlib.pyplot as plt
import seaborn as sns
import matplotlib.gridspec as gridspec
import warnings

# Suppress verbose terminal warnings for a clean production log
warnings.filterwarnings('ignore')
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

class StructuralAnomalyEngine:
    """
    Universal Master Pipeline for Structural Anomaly Detection.
    Handles I/O validation, buffering, deep learning/machine learning fusion,
    scientific visualization, and continuous CSV logging.
    """
    def __init__(self, model_dir='models', log_file='public/telemetry_log.csv'):
        print("[INIT] Booting Universal Structural Anomaly Engine...")
        self.model_dir = model_dir
        self.log_file = log_file
        
        # Buffer Settings
        self.dl_window = 24
        self.ml_window = 10
        self.master_buffer = pd.DataFrame()
        
        # Analytical History Tracker
        self.history = {
            'step': [], 'tilt_x': [], 'roof_dist': [], 
            'lstm_mse': [], 'gru_error': [], 'risk_score': []
        }
        self.step_counter = 0
        
        # Ensure output directories exist
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
        
        self._load_models()
        print("[INIT] Engine Ready. Awaiting telemetry stream.")

    def _load_models(self):
        """Loads all Keras and XGBoost artifacts with strict error handling."""
        try:
            class Sampling(keras.layers.Layer):
                def call(self, inputs):
                    z_mean, z_log_var = inputs
                    batch = tf.shape(z_mean)[0]
                    dim = tf.shape(z_mean)[1]
                    epsilon = tf.keras.backend.random_normal(shape=(batch, dim))
                    return z_mean + tf.exp(0.5 * z_log_var) * epsilon

            # 1. Deep Learning Architecture
            self.lstm = keras.models.load_model(f'{self.model_dir}/lstm_autoencoder_final.keras')
            self.lstm_meta = joblib.load(f'{self.model_dir}/anomaly_metadata.pkl')
            
            self.vae = keras.models.load_model(f'{self.model_dir}/vae_final.keras', custom_objects={'Sampling': Sampling})
            self.vae_meta = joblib.load(f'{self.model_dir}/vae_metadata.pkl')
            
            self.gru = keras.models.load_model(f'{self.model_dir}/gru_forecaster.keras')
            self.gru_meta = joblib.load(f'{self.model_dir}/gru_metadata.pkl')
            
            self.dl_fusion_xgb = xgb.XGBClassifier()
            self.dl_fusion_xgb.load_model(f'{self.model_dir}/xgboost_production_ensemble.json')
            
            # 2. Statistical Machine Learning Architecture
            self.ml_detector_xgb = xgb.XGBClassifier()
            self.ml_detector_xgb.load_model(f'{self.model_dir}/xgboost_statistical_detector.json')
            
        except Exception as e:
            print(f"[CRITICAL ERROR] Failed to load models from '{self.model_dir}/'.")
            print(traceback.format_exc())
            raise

    def _validate_and_fill_inputs(self, raw_data):
        """
        UNIVERSAL INGESTION: Automatically detects missing sensors (e.g., Strain, Temp) 
        and injects safe baselines to prevent pipeline crashes during live demos.
        """
        required_keys = {
            'rotation_x': 1.1, 'rotation_y': 5.5, 'rotation_z': 77.7,
            'acceleration_x': 0.01, 'acceleration_y': 0.01, 'acceleration_z': 0.06,
            'raindrop': 0.0, 'vibration': 0.0, 'soil20cm': 100.0, 
            'soil40cm': 100.0, 'soil60cm': 100.0, 'temperature': 25.0, 'humidity': 70.0,
            'Accel_X (m/s^2)': 0.1, 'Accel_Y (m/s^2)': 0.0, 'Accel_Z (m/s^2)': 9.8,
            'Strain (με)': 110.0, 'Temp (°C)': 25.0, 'roof_convergence_cm': 300.0
        }
        
        safe_data = {}
        for key, default_val in required_keys.items():
            val = raw_data.get(key, default_val)
            safe_data[key] = float(val) if val is not None else default_val
            
        return safe_data

    def _calculate_dl_features(self, current_tick, previous_tick):
        """Calculates internal derivatives and gradients dynamically."""
        tick = current_tick.copy()
        
        tick['acceleration_x_filtered'] = tick['acceleration_x'] * 0.9
        tick['acceleration_y_filtered'] = tick['acceleration_y'] * 0.9
        tick['acceleration_z_filtered'] = tick['acceleration_z'] * 0.9
        tick['acceleration_magnitude'] = np.sqrt(tick['acceleration_x']**2 + tick['acceleration_y']**2 + tick['acceleration_z']**2)
        tick['soil_mean'] = (tick['soil20cm'] + tick['soil40cm'] + tick['soil60cm']) / 3.0
        tick['soil_gradient'] = 0.0 
        
        if previous_tick is None:
            for diff_key in ['rotation_x_change', 'rotation_y_change', 'rotation_z_change', 
                             'acceleration_magnitude_change', 'soil_change', 'soil_mean_change', 
                             'temperature_change', 'humidity_change']:
                tick[diff_key] = 0.0
        else:
            tick['rotation_x_change'] = tick['rotation_x'] - previous_tick['rotation_x']
            tick['rotation_y_change'] = tick['rotation_y'] - previous_tick['rotation_y']
            tick['rotation_z_change'] = tick['rotation_z'] - previous_tick['rotation_z']
            prev_mag = np.sqrt(previous_tick['acceleration_x']**2 + previous_tick['acceleration_y']**2 + previous_tick['acceleration_z']**2)
            tick['acceleration_magnitude_change'] = tick['acceleration_magnitude'] - prev_mag
            tick['soil_change'] = tick['soil20cm'] - previous_tick['soil20cm']
            prev_soil_mean = (previous_tick['soil20cm'] + previous_tick['soil40cm'] + previous_tick['soil60cm']) / 3.0
            tick['soil_mean_change'] = tick['soil_mean'] - prev_soil_mean
            tick['temperature_change'] = tick['temperature'] - previous_tick['temperature']
            tick['humidity_change'] = tick['humidity'] - previous_tick['humidity']
            
        return tick

    def process_tick(self, raw_sensor_data, auto_render_graph=False):
        """
        Main Execution Loop. 
        Pass auto_render_graph=True to automatically overwrite the dashboard PNG every tick.
        """
        try:
            self.step_counter += 1
            validated_data = self._validate_and_fill_inputs(raw_sensor_data)
            
            previous_tick = self.master_buffer.iloc[-1].to_dict() if not self.master_buffer.empty else None
            processed_tick = self._calculate_dl_features(validated_data, previous_tick)
            
            # Maintain sliding window buffer
            self.master_buffer = pd.concat([self.master_buffer, pd.DataFrame([processed_tick])], ignore_index=True)
            if len(self.master_buffer) > self.dl_window:
                self.master_buffer = self.master_buffer.iloc[-self.dl_window:].reset_index(drop=True)
                
            if len(self.master_buffer) < self.dl_window:
                return {"status": "BUFFERING", "ready_pct": round((len(self.master_buffer)/self.dl_window)*100)}

            # ==========================================
            # 1. DEEP LEARNING TRACK (LSTM/VAE/GRU)
            # ==========================================
            ae_cols = ['rotation_x', 'rotation_y', 'rotation_z', 'acceleration_x', 'acceleration_y', 'acceleration_z', 'raindrop', 'vibration', 'soil20cm', 'soil40cm', 'soil60cm', 'temperature', 'humidity', 'acceleration_x_filtered', 'acceleration_y_filtered', 'acceleration_z_filtered', 'acceleration_magnitude', 'rotation_x_change', 'rotation_y_change', 'rotation_z_change', 'soil_mean', 'soil_gradient', 'soil_change', 'acceleration_magnitude_change', 'soil_mean_change', 'temperature_change', 'humidity_change']
            
            X_ae_seq = np.expand_dims(self.lstm_meta['scaler'].transform(self.master_buffer[ae_cols].values), axis=0)
            lstm_mse = float(np.mean(np.square(X_ae_seq - self.lstm.predict(X_ae_seq, verbose=0))))
            vae_mse = float(np.mean(np.square(X_ae_seq - self.vae.predict(X_ae_seq, verbose=0))))
            
            gru_cols = ['rotation_x', 'rotation_y', 'rotation_z', 'acceleration_x', 'acceleration_y', 'acceleration_z']
            X_gru_raw = self.master_buffer[gru_cols].values
            X_gru_seq = np.expand_dims(self.gru_meta['scaler_X'].transform(X_gru_raw), axis=0)
            gru_pred = self.gru.predict(X_gru_seq, verbose=0)
            y_true = self.gru_meta['scaler_y'].transform([X_gru_raw[-1, :3]])
            gru_error = float(np.mean(np.abs(y_true - gru_pred)))

            # DL Fusion Meta-Learner
            ctx = X_ae_seq[:, -1, :9][0]
            fusion_df = pd.DataFrame([ctx], columns=['rotation_x', 'rotation_y', 'rotation_z', 'acceleration_x', 'acceleration_y', 'acceleration_z', 'raindrop', 'vibration', 'soil20cm'])
            fusion_df['lstm_mse'] = lstm_mse
            fusion_df['lstm_flag'] = int(lstm_mse > self.lstm_meta['selected_threshold'])
            fusion_df['vae_mse'] = vae_mse
            fusion_df['vae_flag'] = int(vae_mse > self.vae_meta['selected_threshold'])
            fusion_df['gru_trajectory_error'] = gru_error
            dl_risk = int(self.dl_fusion_xgb.predict(fusion_df)[0])

            # ==========================================
            # 2. MACHINE LEARNING TRACK (Statistical)
            # ==========================================
            ml_buffer = self.master_buffer.iloc[-self.ml_window:]
            ml_cols = ['Accel_X (m/s^2)', 'Accel_Y (m/s^2)', 'Accel_Z (m/s^2)', 'Strain (με)', 'Temp (°C)', 'roof_convergence_cm']
            ml_features = {}
            for col in ml_cols:
                ml_features[f'{col}_live'] = float(ml_buffer[col].iloc[-1])
                ml_features[f'{col}_mean'] = float(ml_buffer[col].mean())
                ml_features[f'{col}_std']  = float(ml_buffer[col].std())
                ml_features[f'{col}_max']  = float(ml_buffer[col].max())
                
            ml_risk = int(self.ml_detector_xgb.predict(pd.DataFrame([ml_features]))[0])

            # ==========================================
            # 3. DETERMINISTIC DECISION MATRIX
            # ==========================================
            ultimate_score = 2 if (ml_risk == 2 or (dl_risk == 1 and ml_risk == 1)) else 1 if (dl_risk == 1 or ml_risk == 1) else 0
            status_text = "CRITICAL COLLAPSE" if ultimate_score == 2 else "WARNING" if ultimate_score == 1 else "SAFE"

            # Update Internal Scientist History
            tilt_val = float(processed_tick['rotation_x'])
            roof_val = ml_features['roof_convergence_cm_live']
            
            self.history['step'].append(self.step_counter)
            self.history['tilt_x'].append(tilt_val)
            self.history['roof_dist'].append(roof_val)
            self.history['lstm_mse'].append(lstm_mse)
            self.history['gru_error'].append(gru_error)
            self.history['risk_score'].append(ultimate_score)

            # Continuous CSV Logging
            log_data = pd.DataFrame([{
                'step': self.step_counter,
                'status': status_text,
                'tilt_x': tilt_val,
                'roof_convergence': roof_val,
                'lstm_mse': lstm_mse,
                'gru_error': gru_error
            }])
            # Write header if file doesn't exist, otherwise append
            log_data.to_csv(self.log_file, mode='a', header=not os.path.exists(self.log_file), index=False)

            # Auto-Render Scientific Dashboard if requested
            if auto_render_graph and len(self.history['step']) > 1:
                self.generate_dashboard()

            # Return Clean JSON Payload for the Web Developers
            return {
                "status": "ACTIVE",
                "ultimate_decision": {"score": ultimate_score, "status_text": status_text},
                "telemetry": {
                    "lstm_mse": round(lstm_mse, 4),
                    "vae_mse": round(vae_mse, 4),
                    "gru_error": round(gru_error, 4),
                    "tilt_x": round(tilt_val, 2),
                    "roof_convergence": round(roof_val, 1)
                }
            }
            
        except Exception as e:
            print(f"[PIPELINE ERROR] {str(e)}")
            return {"status": "ERROR", "message": str(e)}

    def generate_dashboard(self, save_path='public/scientific_dashboard.png'):
        """
        Renders a high-resolution, analytical Matplotlib grid for scientific review.
        """
        if len(self.history['step']) < 2: 
            return False
            
        try:
            df_hist = pd.DataFrame(self.history)
            plt.style.use('seaborn-v0_8-whitegrid')
            fig = plt.figure(figsize=(16, 10))
            gs = gridspec.GridSpec(2, 3, height_ratios=[1, 1])

            colors = {0: '#2ca02c', 1: '#ff7f0e', 2: '#d62728'}
            scatter_colors = df_hist['risk_score'].map(colors)

            # Panel 1: Kinematics
            ax1 = plt.subplot(gs[0, 0])
            ax1.plot(df_hist['step'], df_hist['tilt_x'], color='#1f77b4', lw=2)
            ax1.scatter(df_hist['step'], df_hist['tilt_x'], c=scatter_colors, zorder=5)
            ax1.set_title('Structural Tilt Kinematics (Rotation X)', fontweight='bold')
            ax1.set_ylabel('Degrees')

            # Panel 2: Time-of-Flight Physics
            ax2 = plt.subplot(gs[0, 1])
            ax2.plot(df_hist['step'], df_hist['roof_dist'], color='#8c564b', lw=2)
            ax2.scatter(df_hist['step'], df_hist['roof_dist'], c=scatter_colors, zorder=5)
            ax2.axhline(300, color='gray', ls='--', alpha=0.5, label='Nominal')
            ax2.axhline(285, color='#ff7f0e', ls='--', alpha=0.5, label='Sag Limit')
            ax2.axhline(250, color='#d62728', ls='--', alpha=0.5, label='Critical Floor')
            ax2.set_title('Roof Convergence (ToF Displacement)', fontweight='bold')
            ax2.set_ylabel('Centimeters')
            ax2.legend(loc='lower left', fontsize='small')

            # Panel 3: Temporal Anomaly (LSTM)
            ax3 = plt.subplot(gs[1, 0])
            ax3.plot(df_hist['step'], df_hist['lstm_mse'], color='#ff7f0e', lw=2)
            ax3.set_yscale('log')
            ax3.set_title('LSTM-AE Reconstruction Error', fontweight='bold')
            ax3.set_ylabel('MSE (Log Scale)')
            ax3.set_xlabel('Time (Ticks)')

            # Panel 4: Trajectory Deviation (GRU)
            ax4 = plt.subplot(gs[1, 1])
            ax4.plot(df_hist['step'], df_hist['gru_error'], color='#d62728', lw=2)
            ax4.set_title('GRU Prediction Deviation', fontweight='bold')
            ax4.set_ylabel('Absolute Error')
            ax4.set_xlabel('Time (Ticks)')

            # Panel 5: Distribution Analysis
            ax5 = plt.subplot(gs[:, 2])
            safe_data = df_hist[df_hist['risk_score'] == 0]['lstm_mse']
            crit_data = df_hist[df_hist['risk_score'] == 2]['lstm_mse']
            if not safe_data.empty: 
                sns.kdeplot(safe_data, fill=True, color='#2ca02c', ax=ax5, label='Safe State')
            if not crit_data.empty: 
                sns.kdeplot(crit_data, fill=True, color='#d62728', ax=ax5, label='Critical State')
            ax5.set_title('Density Distribution Analysis', fontweight='bold')
            ax5.set_xlabel('LSTM MSE Density')
            ax5.legend()

            plt.tight_layout()
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            plt.savefig(save_path, dpi=150)
            plt.close(fig) # Prevent memory leaks
            return True
            
        except Exception as e:
            print(f"[GRAPHICS ERROR] {str(e)}")
            return False

# ============================================================
# EXECUTION TEST BLOCK
# ============================================================
if __name__ == "__main__":
    engine = StructuralAnomalyEngine()
    