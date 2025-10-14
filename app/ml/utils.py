from __future__ import annotations

from typing import Dict, Iterable, Sequence, Any, Optional, Union
import numpy as np
import pandas as pd


def ensure_2d_frame(
    x: Union[float, int, Sequence[Any], np.ndarray, pd.Series, Dict[str, Any], pd.DataFrame],
    feature_order: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """
    Coerce many input shapes into a single-row DataFrame in the correct column order.

    Accepts:
      - scalar (float/int)
      - list/tuple
      - np.ndarray
      - pd.Series
      - dict[str, Any]
      - pd.DataFrame

    Returns:
      pd.DataFrame with shape (1, n_features)
    """
    if isinstance(x, pd.DataFrame):
        df = x
    elif isinstance(x, pd.Series):
        df = x.to_frame().T
    elif isinstance(x, dict):
        # Order keys by feature_order if provided; otherwise keep dict order
        if feature_order is None:
            df = pd.DataFrame([x])
        else:
            df = pd.DataFrame([[x.get(k, np.nan) for k in feature_order]], columns=list(feature_order))
    else:
        # Scalars / lists / arrays
        arr = np.asarray(x)
        if arr.ndim == 0:
            arr = arr.reshape(1, 1)
        elif arr.ndim == 1:
            arr = arr.reshape(1, -1)
        # If we know the order, apply column names
        if feature_order is None:
            cols = [f"f{i}" for i in range(arr.shape[1])]
        else:
            # If total size matches, reshape to (1, n_features)
            if arr.size == len(feature_order) and arr.shape[1] != len(feature_order):
                arr = arr.reshape(1, len(feature_order))
            cols = list(feature_order)
        df = pd.DataFrame(arr, columns=cols)

    # Reorder columns to feature_order if provided
    if feature_order is not None:
        # Insert any missing columns as NaN, keep order strict
        for col in feature_order:
            if col not in df.columns:
                df[col] = np.nan
        df = df.loc[:, list(feature_order)]

    return df
