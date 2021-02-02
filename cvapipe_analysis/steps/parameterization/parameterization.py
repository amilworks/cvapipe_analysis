#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import logging
from pathlib import Path
from typing import NamedTuple, Optional, Union, List, Dict

import pandas as pd
from tqdm import tqdm
from datastep import Step, log_run_params
from aics_dask_utils import DistributedHandler
from .parameterization_tools import parameterize

###############################################################################

log = logging.getLogger(__name__)

###############################################################################

class DatasetFields:
    CellId = "CellId"
    CellIndex = "CellIndex"
    FOVId = "FOVId"
    CellRepresentationPath = "CellRepresentationPath"

class SingleCellParameterizationResult(NamedTuple):
    cell_id: Union[int, str]
    path: Path


class SingleCellParameterizationError(NamedTuple):
    cell_id: int
    error: str

class Parameterization(Step):

    def __init__(
        self,
        direct_upstream_tasks: List["Step"] = [],
        config: Optional[Union[str, Path, Dict[str, str]]] = None,
    ):
        super().__init__(direct_upstream_tasks=direct_upstream_tasks, config=config)

    @staticmethod
    def _single_cell_parameterization(
        row_index: int,
        row: pd.Series,
        save_dir: Path,
        load_data_dir: Path,
        overwrite: bool,
    ) -> Union[SingleCellParameterizationResult, SingleCellParameterizationError]:

        # Get the ultimate end save path for this cell
        save_path = save_dir / f"{row_index}.tif"

        # Check skip
        if not overwrite and save_path.is_file():
            log.info(f"Skipping cell parameterization for Cell Id: {row_index}")
            return SingleCellParameterizationResult(row_index, save_path)

        # Overwrite or didn't exist
        log.info(f"Beginning cell parameterization for CellId: {row_index}")

        # Wrap errors for debugging later
        try:
            parameterize(
                data_folder = load_data_dir,
                row = row.to_dict(),
                save_as = save_path
            )
            
            log.info(f"Completed cell parameterization for CellId: {row_index}")
            return SingleCellParameterizationResult(row_index, save_path)

        # Catch and return error
        except Exception as e:
            log.info(
                f"Failed cell parameterization for CellId: {row_index}. Error: {e}"
            )
            return SingleCellParameterizationError(row_index, str(e))

    @log_run_params
    def run(
        self,
        debug=False,
        distributed_executor_address: Optional[str] = None,
        overwrite: bool = False,
        **kwargs):

        # For parameterization we need to load the single cell
        # metadata dataframe and the single cell feature dataframe

        # Load manifest from load_data step
        df = pd.read_csv(
            self.project_local_staging_dir/'loaddata/manifest.csv',
            index_col = 'CellId'
        )
        
        # Keep only the columns that will be used from now on
        columns_to_keep = ['crop_raw', 'crop_seg', 'name_dict']
        df = df[columns_to_keep]
        
        # Load manifest from feature calculation step
        df_features = pd.read_csv(
            self.project_local_staging_dir/'computefeatures/manifest.csv',
            index_col = 'CellId'
        )
                
        # Merge the two dataframes
        df = df.join(df_features, how='inner')
        
        # Folder for storing the parameterized intensity representations
        save_dir = self.step_local_staging_dir/'representations'
        save_dir.mkdir(parents=True, exist_ok=True)

        # Data folder
        load_data_dir = self.project_local_staging_dir/'loaddata'
        
        '''
        # Run parameterization sequentially
        for index in tqdm(df.index):
            parameterize(
                data_folder = load_data_dir,
                row = df.loc[index].to_dict(),
                save_as = save_dir / f'{index}.tif'
            )
        '''
        
        # Process each row
        with DistributedHandler(distributed_executor_address) as handler:
            # Start processing
            results = handler.batched_map(
                self._single_cell_parameterization,
                # Convert dataframe iterrows into two lists of items to iterate over
                # One list will be row index
                # One list will be the pandas series of every row
                *zip(*list(df.iterrows())),
                # Pass the other parameters as list of the same thing for each
                # mapped function call
                [save_dir for i in range(len(df))],
                [load_data_dir for i in range(len(df))],
                [overwrite for i in range(len(df))]
            )

        # Generate features paths rows
        cell_parameterization_dataset = []
        errors = []
        for result in results:
            if isinstance(result, SingleCellParameterizationResult):
                cell_parameterization_dataset.append(
                    {
                        DatasetFields.CellId: result.cell_id,
                        DatasetFields.CellRepresentationPath: result.path,
                    }
                )
            else:
                errors.append(
                    {DatasetFields.CellId: result.cell_id, "Error": result.error}
                )
        
        self.manifest = cell_parameterization_dataset
        manifest_save_path = self.step_local_staging_dir / "manifest.csv"
        self.manifest.to_csv(manifest_save_path)
            
        return manifest_save_path
