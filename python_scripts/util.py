import json
import numpy as np
import pandas as pd
import plotly.express as px
from operator import methodcaller
import os
from sklearn import linear_model
import math
from scipy.stats import pearsonr

def unit_vector(vector):
    """ Returns the unit vector of the vector.  """
    return vector / np.linalg.norm(vector)

def angle_between(v1, v2):
    """ Returns the angle in radians between vectors 'v1' and 'v2'::

            >>> angle_between((1, 0, 0), (0, 1, 0))
            1.5707963267948966
            >>> angle_between((1, 0, 0), (1, 0, 0))
            0.0
            >>> angle_between((1, 0, 0), (-1, 0, 0))
            3.141592653589793
    """
    v1_u = unit_vector(v1)
    v2_u = unit_vector(v2)
    rads = np.arccos(np.clip(np.dot(v1_u, v2_u), -1.0, 1.0))
    return math.degrees(rads)

def regression_models(shifted_df):
    indexExpStarts = 0
    for index, row in shifted_df.iterrows():
        if row['PathIDX'] != 99:
            indexExpStarts = index
            break

    indexExpStarts = max(0, indexExpStarts-500)
    shifted_df = shifted_df.drop(range(indexExpStarts))
    shifted_df = shifted_df[shifted_df["left_right_eye_is_blinking"] == False]
    shifted_df = shifted_df[shifted_df["PathIDX"].astype(int) != 99]
    
    shifted_df.index = np.arange(0, len(shifted_df))

    X1 = shifted_df[['gaze_vis_x','gaze_vis_y']]
    y1 = shifted_df['target_vis_x']

    X2 = shifted_df[['gaze_vis_x','gaze_vis_y']]
    y2 = shifted_df['target_vis_y']
    x_regr = linear_model.LinearRegression()
    x_regr.fit(X1.values, y1.values)
    
    y_regr = linear_model.LinearRegression()
    y_regr.fit(X2.values, y2.values)

    return  [x_regr, y_regr]

def clean_df(df, remove_static):
    indexExpStarts = 0
    for index, row in df.iterrows():
        if row['PathIDX'] != 99:
            indexExpStarts = index
            break

    indexExpStarts = max(0, indexExpStarts-200)
    df = df.drop(range(indexExpStarts))
    df["left_right_eye_is_blinking"] = df["left_right_eye_is_blinking"].apply(lambda x: True if "True" in x else False)        
    # We recorded the moving target segments with PathIDX>0 and with PathIDX<0 for static data segments. Except for the calibration task which is positive for static targets.
    # Thus, for calculations regarding the moving target category we flag the static data points with '99' denoting the dummy category. And vice-versa for static category. 
    # This is our DUAL DATA CAPTURE strategy that allowed for capturing the datasets from both the categories in the same session. 
    if remove_static:
        df["PathIDX"] = df["PathIDX"].apply(lambda x: 99 if x < 0 else x)
    else:        
        df["PathIDX"] = df["PathIDX"].apply(lambda x: 99 if x > 0 else x) 
    # df = df.rename(columns={"left_right_eye_is_blinking": "left_right_eye_is_blinking"})
    # df = df.rename(columns={"PathIDX": "PathIDX"})
    df['seconds'] = df['seconds'].apply(lambda x: x-df['seconds'].iat[0])
    df['frame'] = df['frame'].apply(lambda x: x-df['frame'].iat[0])
    df = df.fillna(0)
    df.index = np.arange(0, len(df))
    return df

def shifted_euc_error_h(df, shift):
    error = 0
    count = 0
    data = df[:-shift]
    if shift == 0:
        data = df

    for index, row in data.iterrows():
        if row['PathIDX']==99 or row['left_right_eye_is_blinking']:
            continue
        error += abs(row['target_vis_x'] - df.iloc[index + shift]['gaze_vis_x'])
        error += abs(row['target_vis_y'] - df.iloc[index + shift]['gaze_vis_y'])
        count+=1
    return error/count

def shifted_df(df):
    min_error = float('inf')
    idx = 0

    for shift in range(30):
        e_after_shift = shifted_euc_error_h(df,shift)
        if min_error > e_after_shift:
            min_error = e_after_shift
            idx = shift

    if idx == 0:
        return [df, idx]

    shifted_df = df.copy(deep=True)
    shifted_df = shifted_df[:-idx]
    shifted_df['gaze_vis_x'] = df['gaze_vis_x'][idx:].values 
    shifted_df['gaze_vis_y'] = df['gaze_vis_y'][idx:].values
    return [shifted_df, idx]

#Horizontal Error: This is the average tracking error strictly along the X-axis (left-to-right drift). 
def spatial_euc_error_h(df):
    #Calibrated error
    error1 = 0
    count = 0
    for index, row in df.iterrows():
        if row['PathIDX']==99 or row['left_right_eye_is_blinking']:
            continue
        count += 1
        error1 += abs(row['target_vis_x'] - row['gaze_x_recal'])
    #Uncalibrated error
    error2 = 0
    count = 0
    for index, row in df.iterrows():
        if row['PathIDX']==99 or row['left_right_eye_is_blinking']:
            continue
        count += 1
        error2 += abs(row['target_vis_x'] - row['gaze_vis_x'])
    return [error1/count, error2/count]

#Vertical Error: This is the average tracking error strictly along the Y-axis (up-and-down drift). 
def spatial_euc_error_v(df):
    #Calibrated error
    error1 = 0
    count = 0
    for index, row in df.iterrows():
        if row['PathIDX']==99 or row['left_right_eye_is_blinking']:
            continue
        count += 1
        error1 += abs(row['target_vis_y'] - row['gaze_y_recal'])
    #Uncalibrated error
    error2 = 0
    count = 0
    for index, row in df.iterrows():
        if row['PathIDX']==99 or row['left_right_eye_is_blinking']:
            continue
        count += 1
        error2 += abs(row['target_vis_y'] - row['gaze_vis_y'])
    return [error1/count, error2/count]

#Combined / Vector Error): This is the total 2D or 3D straight-line distance error. It uses the Pythagorean theorem to combine both horizontal and vertical deviations into a single accuracy score.
def spatial_euc_error_c(df):
    #Calibrated error
    error1 = 0
    count = 0
    for index, row in df.iterrows():
        if row['PathIDX']==99 or row['left_right_eye_is_blinking']:
            continue
        count += 1
        p = [row['target_vis_x'], row['target_vis_y']]
        q = [row['gaze_x_recal'],row['gaze_y_recal']]
        error1 += math.dist(p, q)
    #Uncalibrated error
    error2 = 0
    count = 0
    for index, row in df.iterrows():
        if row['PathIDX']==99 or row['left_right_eye_is_blinking']:
            continue
        count += 1
        p = [row['target_vis_x'], row['target_vis_y']]
        q = [row['gaze_vis_x'],row['gaze_vis_y']]
        error2 += math.dist(p, q)
    return [error1/count, error2/count]

def spatial_vec_errors(df):
    error = 0
    count = 0
    for index, row in df.iterrows():
        if row['PathIDX']==99 or row['left_right_eye_is_blinking']:
            continue
        count += 1
        p = row['gaze_vector']
        q = row['target_vector']
        if isinstance(p, str):
            p = json.loads(p)
            q = json.loads(q)

        error += angle_between(p,q)
    return error/len(df.index)

def spatial_euc_errors(df):
    e_h = spatial_euc_error_h(df)
    e_v = spatial_euc_error_v(df)
    e_c = spatial_euc_error_c(df)
    return [e_c, e_h, e_v]

def pearsonr_from_df(df):
    """Calculates Pearson correlation coefficients for gaze tracking offsets.

    Computes the statistical correlation between horizontal (X) and vertical (Y)
    gaze tracking errors relative to the target. It calculates this relationship
    separately for both the raw (original) gaze data and the recalibrated gaze data
    to assess calibration impact.

    Data is automatically cleaned by filtering out static calibration markers (99)
    and any non-positive tracking indices. Missing values are filled with 0.0.

    Args:
        df (pandas.DataFrame): Eye-tracking dataset containing the columns:
            'PathIDX', 'gaze_vis_x', 'gaze_vis_y', 'gaze_x_recal', 'gaze_y_recal',
            'target_vis_x', and 'target_vis_y'.

    Returns:
        list of list: A nested list structured as:
            [
                [original_r_coefficient, original_p_value],
                [recalibrated_r_coefficient, recalibrated_p_value]
            ]
    """
    # Filter out invalid flagged points (99) and when user left_right_eye_is_blinking
    df = df[(df.PathIDX != 99) & (~df.left_right_eye_is_blinking)]
    
    # Extract, convert to float, and handle NaN values for X-axis
    x_g = df.gaze_vis_x.astype(float).fillna(0.0)
    x_g_recal = df.gaze_x_recal.astype(float).fillna(0.0)
    x_t = df.target_vis_x.astype(float).fillna(0.0)
    
    # Calculate horizontal gaze tracking errors (raw vs recalibrated)
    x_offset = np.subtract(x_g,x_t)
    x_offset_recal = np.subtract(x_g_recal,x_t)
    
    # Extract, convert to float, and handle NaN values for Y-axis
    y_g = df.gaze_vis_y.astype(float).fillna(0.0)
    y_g_recal = df.gaze_y_recal.astype(float).fillna(0.0)
    y_t = df.target_vis_y.astype(float).fillna(0.0)
    
    # Calculate vertical gaze tracking errors (raw vs recalibrated)
    y_offset = np.subtract(y_g,y_t)
    y_offset_recal = np.subtract(y_g_recal,y_t)
    
    # Compute Pearson correlation (r, p-value) between X and Y drift
    pr = pearsonr(x_offset, y_offset)
    pr_recal = pearsonr(x_offset_recal, y_offset_recal)

    # Return nested list: [[raw_r, raw_p], [recal_r, recal_p]]
    return [[pr[0], pr[1]], [pr_recal[0], pr_recal[1]]]

def generate_recalibrated_file(raw_file_path, recal_file_path, x_regr, y_regr, remove_static):
    """
    Reads raw task data, predicts calibrated gaze points using high-speed
    vectorized operations instead of an apply loop, and outputs to CSV.
    """
    df = pd.read_csv(raw_file_path)
    df = clean_df(df, remove_static)
    df, idx = shifted_df(df)
    
    # HIGH-SPEED VECTORIZATION: Pass the entire matrix at once instead of looping row-by-row
    # We extract the underlying NumPy array using .values for raw processing speed
    coordinates_matrix = df[['gaze_vis_x', 'gaze_vis_y']].values
    
    df['gaze_x_recal'] = x_regr.predict(coordinates_matrix)
    df['gaze_y_recal'] = y_regr.predict(coordinates_matrix)
    
    # Vectorized string replacements across the entire series sequence
    gaze_vec = df['gaze_vector'].str.replace('_', ',', regex=False).str.replace('(', '[', regex=False).str.replace(')', ']', regex=False).apply(json.loads)
    target_vec = df['target_vector'].str.replace('_', ',', regex=False).str.replace('(', '[', regex=False).str.replace(')', ']', regex=False).apply(json.loads)

    df['gaze_vector'] = gaze_vec
    df['target_vector'] = target_vec
    df["correction_index"] = idx

    # Select required columns
    columns = [
        "frame",
        "PathIDX",
        # "timestamp",
        "seconds",
        # "gaze_confidence",
        # "gaze_pos",
        # "target_pos",
        "gaze_vector",
        "target_vector",
        "gaze_vis_x",
        "gaze_vis_y",
        "target_vis_x",
        "target_vis_y",
        "left_right_eye_is_blinking",
        "gaze_x_recal",
        "gaze_y_recal",
        "correction_index"
    ]

    df = df[columns].copy()

    df.to_csv(recal_file_path, index=False)

def compute_task_errors(calibrated_task_csv_path, errors_for_task, base_name):
    df_recal = pd.read_csv(calibrated_task_csv_path)

    # Simple fallback index detection safely handling empty edge conditions
    first_idx = df_recal['correction_index'].iloc[0] if not df_recal.empty else np.nan

    if 'w1' in base_name:
        errors_for_task['w1_euc'] = spatial_euc_errors(df_recal)
        errors_for_task['w1_vec'] = spatial_vec_errors(df_recal)
        errors_for_task['w1_index'] = first_idx
    elif 'w2' in base_name:
        errors_for_task['w2_euc'] = spatial_euc_errors(df_recal)
        errors_for_task['w2_vec'] = spatial_vec_errors(df_recal)
        errors_for_task['w2_index'] = first_idx
    elif 'w3' in base_name:
        errors_for_task['w3_euc'] = spatial_euc_errors(df_recal)
        errors_for_task['w3_vec'] = spatial_vec_errors(df_recal)
        errors_for_task['w3_index'] = first_idx
    elif 's4' in base_name:
        errors_for_task['s4_euc'] = spatial_euc_errors(df_recal)
        errors_for_task['s4_vec'] = spatial_vec_errors(df_recal)
        errors_for_task['s4_index'] = first_idx
    elif 'b5' in base_name:
        errors_for_task['b5_euc'] = spatial_euc_errors(df_recal)
        errors_for_task['b5_vec'] = spatial_vec_errors(df_recal)
        errors_for_task['b5_index'] = first_idx
    elif 'cal' in base_name:
        errors_for_task['callibrate_euc'] = spatial_euc_errors(df_recal)
        errors_for_task['callibrate_vec'] = spatial_vec_errors(df_recal)
        errors_for_task['callibrate_index'] = first_idx
        errors_for_task['callibrate_pearsonr'] = pearsonr_from_df(df_recal)[0]
        errors_for_task['callibrate_pearsonr_recal'] = pearsonr_from_df(df_recal)[1]

    return errors_for_task

def get_recalibrated_data_dir(target_type, calibrate_with):
    if calibrate_with == 'cal':
        return os.path.join(os.getcwd(), '..', 'recalibrated_data', f"{target_type}_target")
    return os.path.join(os.getcwd(), '..', 'recalibrated_data_others', calibrate_with, f"{target_type}_target")

def get_raw_data_directory():
    return os.path.abspath(os.path.join(os.getcwd(), '..', 'participant-data'))

def get_all_participants():
    participant_data = get_raw_data_directory()
    
    if not os.path.exists(participant_data):
        raise FileNotFoundError(f"The directory '{participant_data}' does not exist.")
        
    # Combine the prefix check and exclusion filter into a single step
    exclusions = {'data_validate', 'recalibrated_data_moving', 'recalibrated_data_static', 'pilot_testing'}    
    active_folders = [
        f.name for f in os.scandir(participant_data)
        if f.is_dir() and f.name.startswith("participant-") and f.name not in exclusions
    ]
    
    return active_folders

def get_participant_raw_files(participant):
    files_path = os.path.join(get_raw_data_directory(), participant)
    all_raw_files = [
        f
        for f in os.listdir(files_path)
        if os.path.isfile(os.path.join(files_path, f))
    ]

    tasks = ["w1","w2","w3","s4","b5","cal"]
    tasks_file_dir = {}
    for t in tasks:
        matches = [f for f in all_raw_files if t in f]
        tasks_file_dir[t] = os.path.join(files_path, matches[0]) if matches else None
    
    return tasks_file_dir