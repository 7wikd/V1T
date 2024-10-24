import os
import time
import torch
import wandb
import argparse
from functools import partial
from datetime import datetime

import train as trainer


class Args:
    def __init__(
        self,
        id: str,
        config: wandb.Config,
        dataset: str,
        num_workers: int = 2,
        verbose: int = 1,
    ):
        self.dataset = dataset
        output_dir = getattr(config, 'output_dir', 'runs/')
        self.output_dir = os.path.join(
            output_dir, f"{datetime.now():%Y%m%d-%Hh%Mm}-{id}"
        )
        self.num_workers = num_workers
        self.device = ""
        self.mouse_ids = None
        self.seed = 1234
        self.save_plots = False
        self.dpi = 120
        self.format = "svg"
        self.clear_output_dir = False
        self.amp = False
        self.backend = None
        self.deterministic = False
        self.grad_checkpointing = None
        self.gray_scale = False
        self.verbose = verbose
        self.use_wandb = True
        for key, value in config.items():
            if not hasattr(self, key):
                setattr(self, key, value)


def main(wandb_group: str, dataset: str, num_workers: int = 2):
    run = wandb.init(group=wandb_group)
    config = run.config
    run.name = run.id
    args = Args(
        id=run.id,
        config=config,
        dataset=dataset,
        num_workers=num_workers,
    )
    trainer.main(args, wandb_sweep=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=str,
        default="data/sensorium",
        help="path to directory where the dataset is stored.",
    )
    parser.add_argument("--num_workers", type=int, default=4)
    parser.add_argument("--sweep_id", type=str, required=True)
    parser.add_argument("--wandb_group", type=str, required=True)
    parser.add_argument("--num_trials", type=int, default=1)
    parser.add_argument("--verbose", type=int, default=1, choices=[0, 1, 2])
    params = parser.parse_args()

    for i in range(params.num_trials):
        wandb.agent(
            sweep_id=f"7wikd/V1T/{params.sweep_id}",
            function=partial(
                main,
                wandb_group=params.wandb_group,
                dataset=params.dataset,
                num_workers=params.num_workers,
            ),
            count=1,
        )
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        if i < params.num_trials - 1:
            time.sleep(5)
