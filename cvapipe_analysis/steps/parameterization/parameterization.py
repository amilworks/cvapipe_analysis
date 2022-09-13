#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import logging
from pathlib import Path
from datastep import Step, log_run_params
from typing import Dict, List, Optional, Union

import concurrent
from cvapipe_analysis.tools import io, general, cluster
from .parameterization_tools import Parameterizer

log = logging.getLogger(__name__)

class Parameterization(Step):
    def __init__(
        self,
        direct_upstream_tasks: List["Step"] = [],
        config: Optional[Union[str, Path, Dict[str, str]]] = None,
    ):
        super().__init__(direct_upstream_tasks=direct_upstream_tasks, config=config)

    @log_run_params
    def run(
        self,
        staging: Union[str, Path],
        verbose: Optional[bool]=False,
        distribute: Optional[bool]=False,
        **kwargs):

        with general.configuration(staging) as control:

            step_folder = control.create_step_dirs(self.step_name, ["representations"])

            device = io.LocalStagingIO(control)
            df = device.load_step_manifest("preprocessing")
            log.info(f"Manifest: {df.shape}")

            if distribute:

                distributor = cluster.ParameterizationDistributor(self, control)
                distributor.set_data(df)
                distributor.distribute()
                log.info(f"Multiple jobs have been launched. Please come back when the calculation is complete.")
                
                return None

            parameterizer = Parameterizer(control)
            if verbose:
                parameterizer.set_verbose_mode_on()
            with concurrent.futures.ProcessPoolExecutor(control.get_ncores()) as executor:
                executor.map(parameterizer.execute, [row for _,row in df.iterrows()])
