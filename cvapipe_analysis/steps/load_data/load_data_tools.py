import os
import uuid
import quilt3
import pandas as pd
from tqdm import tqdm
from pathlib import Path

from cvapipe_analysis.tools import io

class DataLoader(io.LocalStagingIO):
    """
    Functionalities for downloading the variance
    dataset used in the paper or load a custom
    dataset specified as an input csv file.

    WARNING: All classes are assumed to know the whole
    structure of directories inside the local_staging
    folder and this is hard coded. Therefore, classes
    may break if you move saved files from the places
    their are saved.
    """

    package_name = "aics/hipsc_single_cell_image_dataset"
    registry = "s3://allencell"
    subfolder = 'loaddata'
    required_df_columns = [
        'CellId',
        'structure_name',
        'crop_seg_fms_id',
        'crop_raw_fms_id',
    ]
    extra_columns = [
        'roi',
        'volume',
        'centroid_x',
        'centroid_y',
        'centroid_z',
        'track_id',
        'label_img',
        'is_outlier',
        'index_sequence',
        'raw_full_zstack_fms_id',
        'seg_full_zstack_fms_id',
    ]

    def __init__(self, control):
        super().__init__(control)

    def load(self, parameters):
        if any(p in parameters for p in ["csv", "fmsid"]):
            return self.download_local_data(parameters)
        return self.download_quilt_data('test' in parameters)

    def download_quilt_data(self, test=False):
        pkg = quilt3.Package.browse(self.package_name, self.registry)
        df_meta = pkg["metadata.csv"]()
        if test:
            print('Downloading test dataset with 12 interphase cell images per structure.')
            df_meta = self.get_interphase_test_set(df_meta)
        path = self.control.get_staging()/self.subfolder
        for i, row in df_meta.iterrows():
            pkg[row["crop_raw"]].fetch(path/row["crop_raw"])
            pkg[row["crop_seg"]].fetch(path/row["crop_seg"])
        return df_meta

    def download_local_data(self, parameters):
        use_fms = use_fms="fmsid" in parameters
        df = self.load_data_from_csv(parameters, use_fms)
        self.is_dataframe_valid(df)
        cols = self.required_df_columns + self.extra_columns
        df = df[[c for c in cols if c in df.columns]].set_index('CellId', drop=True)
        if not use_fms:
            self.create_symlinks(df)
        return df

    def is_dataframe_valid(self, df):
        for col in self.required_df_columns:
            if col not in df.columns:
                raise ValueError(f"Input CSV is missing column: {col}.")
        return

    def create_symlinks(self, df, use_fms=False):
        for col in ['crop_raw', 'crop_seg']:
            abs_path_data_folder = self.control.get_staging()/f"{self.subfolder}"
            (abs_path_data_folder/col).mkdir(parents=True, exist_ok=True)
        get_path = self.get_direct_path_from_column
        if use_fms:
            get_path = self.get_path_from_fms_id
        for index, row in tqdm(df.iterrows(), total=len(df)):
            idx = str(uuid.uuid4())[:8]
            for col in ['crop_raw', 'crop_seg']:
                src = get_path(row, col)
                dst = abs_path_data_folder/f"{col}/{src.stem}_{idx}{src.suffix}"
                os.symlink(src, dst)
                df.loc[index, col] = dst
        return df

    @staticmethod
    def get_interphase_test_set(df):
        df_test = pd.DataFrame([])
        df = df.loc[df.cell_stage=='M0']# M0 = interphase
        for _, df_struct in df.groupby('structure_name'):
            df_test = df_test.append(df_struct.sample(n=12, random_state=666, replace=False))
        return df_test.copy()
