# import os
# import torch
# import wandb
# import argparse
# import typing as t
# from torch import nn
# from time import time
# from shutil import rmtree
# from einops import rearrange
# from datetime import datetime
# from torch.cuda.amp import GradScaler
# from torch.utils.data import DataLoader


# import submission
# import train as trainer
# from v1t import losses, data
# from v1t.models.utils import ELU1
# from v1t.utils.logger import Logger
# from v1t.utils import utils, tensorboard
# from v1t.utils.scheduler import Scheduler
# from v1t.models import Model, get_model_info


# class Args:
#     def __init__(self, args, output_dir: str):
#         self.device = args.device
#         self.output_dir = output_dir


# class OutputModule(nn.Module):
#     """
#     ensemble mode:
#         0 - average the outputs of the ensemble models
#         1 - linear layer to connect the outputs from the ensemble models
#         2 - separate linear layer per animal
#     """

#     def __init__(self, args: t.Any, in_features: int):
#         super(OutputModule, self).__init__()
#         self.in_features = in_features
#         self.output_shapes = args.output_shapes
#         self.ensemble_mode = args.ensemble_mode
#         assert self.ensemble_mode in (0, 1, 2)
#         if self.ensemble_mode == 1:
#             self.linear = nn.Linear(in_features=in_features, out_features=1)
#         elif self.ensemble_mode == 2:
#             self.linear = nn.ModuleDict(
#                 {
#                     mouse_id: nn.Linear(in_features=in_features, out_features=1)
#                     for mouse_id in self.output_shapes.keys()
#                 }
#             )
#         self.activation = ELU1()

#         self.apply(self.init_weight)

#     @staticmethod
#     def init_weight(m: nn.Module):
#         if isinstance(m, nn.Linear):
#             nn.init.trunc_normal_(m.weight, std=0.02)
#             if m.bias is not None:
#                 nn.init.constant_(m.bias, 0)
#         elif isinstance(m, nn.LayerNorm):
#             nn.init.constant_(m.bias, 0)
#             nn.init.constant_(m.weight, 1.0)

#     def forward(self, inputs: torch.Tensor, mouse_id: str):
#         match self.ensemble_mode:
#             case 0:
#                 outputs = torch.mean(inputs, dim=-1)
#             case 1:
#                 outputs = self.linear(inputs)
#                 outputs = rearrange(outputs, "b d 1 -> b d")
#             case 2:
#                 outputs = self.linear[mouse_id](inputs)
#                 outputs = rearrange(outputs, "b d 1 -> b d")
#             case _:
#                 NotImplementedError(
#                     f"--ensemble_model {self.ensemble_mode} not supported."
#                 )
#         outputs = self.activation(outputs)
#         return outputs


# class EnsembleModel(nn.Module):
#     def __init__(
#         self,
#         args: t.Any,
#         saved_models: t.Dict[str, str],
#         ds: t.Dict[str, DataLoader],
#     ):
#         super(EnsembleModel, self).__init__()
#         self.verbose = args.verbose
#         self.input_shape = args.input_shape
#         self.output_shapes = args.output_shapes
#         self.ensemble = nn.ModuleDict()
#         for name, output_dir in saved_models.items():
#             model_args = Args(args, output_dir)
#             utils.load_args(model_args)
#             model = Model(args=model_args, ds=ds)
#             self.load_model_state(model, output_dir=model_args.output_dir)
#             self.ensemble[name] = model
#         self.ensemble.requires_grad_(False)
#         self.output_module = OutputModule(args, in_features=len(saved_models))

#     def load_model_state(
#         self,
#         model: nn.Module,
#         output_dir: str,
#         device: torch.device = torch.device("cpu"),
#     ):
#         filename = os.path.join(output_dir, "ckpt", "model_state.pt")
#         assert os.path.exists(filename), f"Cannot find {filename}."
#         ckpt = torch.load(filename, map_location=device)
#         # it is possible that the checkpoint only contains part of a model
#         # hence we update the current state_dict of the model instead of
#         # directly calling model.load_state_dict(ckpt['model'])
#         state_dict = model.state_dict()
#         state_dict.update(ckpt["model"])
#         model.load_state_dict(state_dict)
#         if self.verbose:
#             print(
#                 f"Loaded checkpoint from {output_dir} "
#                 f"(correlation: {ckpt['value']:.04f})."
#             )

#     def regularizer(self, mouse_id: str):
#         return torch.tensor(0.0)

#     def forward(
#         self,
#         inputs: torch.Tensor,
#         mouse_id: str,
#         behaviors: torch.Tensor,
#         pupil_centers: torch.Tensor,
#     ):
#         ensemble = []
#         for name in self.ensemble.keys():
#             outputs, _, _ = self.ensemble[name](
#                 inputs,
#                 mouse_id=mouse_id,
#                 behaviors=behaviors,
#                 pupil_centers=pupil_centers,
#                 activate=False,
#             )
#             outputs = rearrange(outputs, "b d -> b d 1")
#             ensemble.append(outputs)
#         ensemble = torch.cat(ensemble, dim=-1)
#         ensemble = self.output_module(ensemble, mouse_id=mouse_id)
#         return ensemble, None, None  # match output signature of Model


# def fit_ensemble(
#     args,
#     model: EnsembleModel,
#     optimizer: torch.optim.Optimizer,
#     criterion: losses.Loss,
#     scaler: GradScaler,
#     scheduler: Scheduler,
#     train_ds: t.Dict[str, DataLoader],
#     val_ds: t.Dict[str, DataLoader],
#     test_ds: t.Dict[str, DataLoader],
# ):
#     summary = tensorboard.Summary(args)

#     epoch = scheduler.restore()

#     while (epoch := epoch + 1) < args.epochs + 1:
#         if args.verbose:
#             print(f"\nEpoch {epoch:03d}/{args.epochs:03d}")

#         start = time()
#         train_result = trainer.train(
#             args,
#             ds=train_ds,
#             model=model,
#             optimizer=optimizer,
#             criterion=criterion,
#             scaler=scaler,
#             epoch=epoch,
#             summary=summary,
#         )
#         val_result = trainer.validate(
#             args,
#             ds=val_ds,
#             model=model,
#             criterion=criterion,
#             scaler=scaler,
#             epoch=epoch,
#             summary=summary,
#         )
#         elapse = time() - start

#         summary.scalar("model/elapse", value=elapse, step=epoch, mode=0)
#         summary.scalar(
#             "model/learning_rate",
#             value=optimizer.param_groups[0]["lr"],
#             step=epoch,
#             mode=0,
#         )
#         if args.verbose:
#             print(
#                 f'Train\t\t\tloss: {train_result["loss"]:.04f}\t\t'
#                 f'correlation: {train_result["single_trial_correlation"]:.04f}\n'
#                 f'Validation\t\tloss: {val_result["loss"]:.04f}\t\t'
#                 f'correlation: {val_result["single_trial_correlation"]:.04f}\n'
#                 f"Elapse: {elapse:.02f}s"
#             )
#         early_stop = scheduler.step(val_result["single_trial_correlation"], epoch=epoch)
#         if args.use_wandb:
#             wandb.log(
#                 {
#                     "train_loss": train_result["loss"],
#                     "train_corr": train_result["single_trial_correlation"],
#                     "val_loss": val_result["loss"],
#                     "val_corr": val_result["single_trial_correlation"],
#                     "best_corr": scheduler.best_value,
#                     "elapse": elapse,
#                 },
#                 step=epoch,
#             )
#         if early_stop:
#             break

#     scheduler.restore()
#     eval_result = utils.evaluate(
#         args,
#         ds=test_ds,
#         model=model,
#         epoch=epoch,
#         summary=summary,
#         mode=2,
#         print_result=True,
#         save_result=args.output_dir,
#     )
#     if args.use_wandb:
#         wandb.log({"test_corr": eval_result["single_trial_correlation"]}, step=epoch)


# def main(args):
#     if args.clear_output_dir and os.path.isdir(args.output_dir):
#         rmtree(args.output_dir)
#     if not os.path.isdir(args.output_dir):
#         os.makedirs(args.output_dir)

#     Logger(args)
#     utils.get_device(args)
#     utils.set_random_seed(seed=args.seed)

#     data.get_mouse_ids(args)

#     args.micro_batch_size = args.batch_size
#     train_ds, val_ds, test_ds = data.get_training_ds(
#         args,
#         data_dir=args.dataset,
#         mouse_ids=args.mouse_ids,
#         batch_size=args.batch_size,
#         device=args.device,
#     )

#     if args.use_wandb:
#         os.environ["WANDB_SILENT"] = "true"
#         try:
#             wandb.init(
#                 config=args,
#                 dir=os.path.join(args.output_dir, "wandb"),
#                 project="sensorium",
#                 entity="bryanlimy",
#                 group=args.wandb_group,
#                 name=os.path.basename(args.output_dir),
#             )
#         except AssertionError as e:
#             print(f"wandb.init error: {e}\n")
#             args.use_wandb = False

#     # pretrained model to load
#     args.saved_models = {}
#     assert hasattr(args, "saved_models") and args.saved_models

#     model = EnsembleModel(args, saved_models=args.saved_models, ds=train_ds)

#     # get model info
#     mouse_id = args.mouse_ids[0]
#     batch_size = args.micro_batch_size
#     random_input = lambda size: torch.rand(*size)
#     model_info = get_model_info(
#         model=model,
#         input_data={
#             "inputs": random_input((batch_size, *model.input_shape)),
#             "behaviors": random_input((batch_size, 3)),
#             "pupil_centers": random_input((batch_size, 2)),
#         },
#         mouse_id=mouse_id,
#         filename=os.path.join(args.output_dir, "model.txt"),
#     )
#     if args.verbose > 2:
#         print(str(model_info))
#     if args.use_wandb:
#         wandb.log({"trainable_params": model_info.trainable_params}, step=0)

#     model.to(args.device)

#     utils.save_args(args)

#     if args.ensemble_mode == 0 and args.train:
#         print(f"Cannot train ensemble model with average outputs")

#     criterion = losses.get_criterion(args, ds=train_ds)
#     scaler = GradScaler(enabled=args.amp)
#     if args.amp and args.verbose:
#         print(f"Enable automatic mixed precision training.")
#     if args.ensemble_mode:
#         optimizer = torch.optim.AdamW(
#             params=[
#                 {
#                     "params": model.parameters(),
#                     "lr": args.lr,
#                     "name": "model",
#                 }
#             ],
#             lr=args.lr,
#             betas=(args.adam_beta1, args.adam_beta2),
#             eps=args.adam_eps,
#             weight_decay=args.weight_decay,
#         )
#         scheduler = Scheduler(
#             args,
#             model=model,
#             optimizer=optimizer,
#             scaler=scaler,
#             mode="max",
#             module_names=["output_module"],
#         )
#         if args.train:
#             fit_ensemble(
#                 args,
#                 model=model,
#                 optimizer=optimizer,
#                 criterion=criterion,
#                 scaler=scaler,
#                 scheduler=scheduler,
#                 train_ds=train_ds,
#                 val_ds=val_ds,
#                 test_ds=test_ds,
#             )
#         else:
#             scheduler.restore()
#     else:
#         epoch = 0
#         val_result = trainer.validate(
#             args,
#             ds=val_ds,
#             model=model,
#             criterion=criterion,
#             scaler=scaler,
#             epoch=epoch,
#         )
#         if args.verbose:
#             print(
#                 f'Validation\t\tloss: {val_result["loss"]:.04f}\t\t'
#                 f'correlation: {val_result["single_trial_correlation"]:.04f}\n'
#             )
#         if args.use_wandb:
#             wandb.log(
#                 {
#                     "val_loss": val_result["loss"],
#                     "val_corr": val_result["single_trial_correlation"],
#                     "best_corr": val_result["single_trial_correlation"],
#                 },
#                 step=epoch,
#             )

#     test_ds, final_test_ds = data.get_submission_ds(
#         args,
#         data_dir=args.dataset,
#         batch_size=args.batch_size,
#         device=args.device,
#     )

#     # create CSV dir to save results with timestamp Year-Month-Day-Hour-Minute
#     timestamp = f"{datetime.now():%Y-%m-%d-%Hh%Mm}"
#     csv_dir = os.path.join(args.output_dir, "submissions", timestamp)

#     eval_result = utils.evaluate(
#         args, ds=test_ds, model=model, print_result=True, save_result=csv_dir
#     )
#     if args.use_wandb:
#         wandb.log({"test_corr": eval_result["single_trial_correlation"]}, step=0)

#     if "sensorium" in args.dataset:
#         if "S0" in test_ds:  # Sensorium challenge
#             submission.generate_submission(
#                 args,
#                 mouse_id="S0",
#                 test_ds=test_ds,
#                 final_test_ds=final_test_ds,
#                 model=model,
#                 csv_dir=os.path.join(csv_dir, "sensorium"),
#             )
#         if "S1" in test_ds:  # Sensorium+ challenge
#             submission.generate_submission(
#                 args,
#                 mouse_id="S1",
#                 test_ds=test_ds,
#                 final_test_ds=final_test_ds,
#                 model=model,
#                 csv_dir=os.path.join(csv_dir, "sensorium+"),
#             )

#     print(f"\nSubmission results saved to {csv_dir}.")


# if __name__ == "__main__":
#     parser = argparse.ArgumentParser()
#     # dataset settings
#     parser.add_argument(
#         "--dataset",
#         type=str,
#         default="data/sensorium",
#         help="path to directory where the compressed dataset is stored.",
#     )
#     parser.add_argument("--output_dir", type=str, required=True)
#     parser.add_argument(
#         "--mouse_ids",
#         nargs="+",
#         type=int,
#         default=None,
#         help="Mouse to use for training.",
#     )
#     parser.add_argument(
#         "--behavior_mode",
#         required=True,
#         type=int,
#         choices=[0, 1, 2, 3, 4],
#         help="behavior mode:"
#         "0: do not include behavior"
#         "1: concat behavior with natural image"
#         "2: add latent behavior variables to each ViT block"
#         "3: add latent behavior + pupil centers to each ViT block"
#         "4: separate BehaviorMLP for each animal",
#     )
#     parser.add_argument(
#         "--gray_scale", action="store_true", help="convert colored image to gray-scale"
#     )
#     parser.add_argument(
#         "--num_workers",
#         default=2,
#         type=int,
#         help="number of works for DataLoader.",
#     )

#     # training settings
#     parser.add_argument(
#         "--epochs",
#         default=200,
#         type=int,
#         help="maximum epochs to train the model.",
#     )
#     parser.add_argument("--batch_size", default=4, type=int)
#     parser.add_argument(
#         "--device",
#         type=str,
#         choices=["cpu", "cuda", "mps"],
#         default="",
#         help="Device to use for computation. "
#         "Use the best available device if --device is not specified.",
#     )
#     parser.add_argument("--seed", type=int, default=1234)
#     parser.add_argument(
#         "--amp", action="store_true", help="automatic mixed precision training"
#     )
#     parser.add_argument(
#         "--ensemble_mode",
#         type=int,
#         required=True,
#         choices=[0, 1, 2],
#         help="ensemble method: "
#         "0 - average the outputs of the ensemble models, "
#         "1 - linear layer to connect the outputs from the ensemble models"
#         "2 - separate linear layer per animal",
#     )

#     parser.add_argument(
#         "--train",
#         action="store_true",
#         help="train ensemble model before inference.",
#     )

#     # optimizer settings
#     parser.add_argument("--adam_beta1", type=float, default=0.9)
#     parser.add_argument("--adam_beta2", type=float, default=0.9999)
#     parser.add_argument("--adam_eps", type=float, default=1e-8)
#     parser.add_argument("--lr", type=float, default=0.001)
#     parser.add_argument(
#         "--weight_decay",
#         type=float,
#         default=0.01,
#         help="L2 weight decay coefficient",
#     )
#     parser.add_argument(
#         "--criterion",
#         type=str,
#         default="poisson",
#         help="criterion (loss function) to use.",
#     )
#     parser.add_argument(
#         "--ds_scale",
#         action="store_true",
#         help="scale loss by the size of the dataset",
#     )

#     # plot settings
#     parser.add_argument(
#         "--save_plots", action="store_true", help="save plots to --output_dir"
#     )
#     parser.add_argument(
#         "--dpi",
#         type=int,
#         default=120,
#         help="matplotlib figure DPI",
#     )
#     parser.add_argument(
#         "--format",
#         type=str,
#         default="svg",
#         choices=["pdf", "svg", "png"],
#         help="file format when --save_plots",
#     )

#     # wandb settings
#     parser.add_argument("--use_wandb", action="store_true")
#     parser.add_argument("--wandb_group", type=str, default="")

#     # misc
#     parser.add_argument(
#         "--clear_output_dir",
#         action="store_true",
#         help="overwrite content in --output_dir",
#     )
#     parser.add_argument("--verbose", type=int, default=2, choices=[0, 1, 2, 3])

#     main(parser.parse_args())

import os
import torch
import wandb
import argparse
import typing as t
from torch import nn
from time import time
from shutil import rmtree
from einops import rearrange
from datetime import datetime
from torch.cuda.amp import GradScaler
from torch.utils.data import DataLoader

import submission
import train as trainer
from v1t import losses, data
from v1t.models.utils import ELU1
from v1t.utils.logger import Logger
from v1t.utils import utils, tensorboard
from v1t.utils.scheduler import Scheduler
from v1t.models import Model, get_model_info


class Args:
    """
    A class to load and store arguments for each model.
    """

    def __init__(self, base_args, output_dir: str):
        # Load the arguments from the saved model
        self.output_dir = output_dir
        args_file = os.path.join(output_dir, "args.yaml")
        if os.path.exists(args_file):
            saved_args = torch.load(args_file)
            self.__dict__.update(saved_args.__dict__)
        else:
            raise FileNotFoundError(f"No saved args in {args_file}")
        # Override any arguments as needed
        self.device = base_args.device
        # Add any other attributes from base_args if necessary
        # For example, you might want to set self.verbose = base_args.verbose


class OutputModule(nn.Module):
    """
    OutputModule combines the outputs from different models in the ensemble.
    Ensemble modes:
        0 - Average the outputs of the ensemble models.
        1 - Learn a linear combination of the outputs.
        2 - Separate linear layer per mouse_id.
    """

    def __init__(self, args: t.Any, num_models: int):
        super(OutputModule, self).__init__()
        self.ensemble_mode = args.ensemble_mode
        self.activation = ELU1()

        if self.ensemble_mode == 1:
            # Learnable weights to combine models
            self.weights = nn.Parameter(torch.ones(num_models) / num_models)
        elif self.ensemble_mode == 2:
            # Implement per-mouse linear layers if needed
            self.linear = nn.ModuleDict(
                {
                    mouse_id: nn.Linear(num_models, 1)
                    for mouse_id in args.mouse_ids
                }
            )

    def forward(self, inputs: torch.Tensor, mouse_id: str = None):
        # inputs shape: (batch_size, num_neurons, num_models)
        if self.ensemble_mode == 0:
            # Average the outputs
            outputs = torch.mean(inputs, dim=-1)
        elif self.ensemble_mode == 1:
            # Weighted sum
            outputs = torch.einsum('bnd,d->bn', inputs, self.weights)
        elif self.ensemble_mode == 2:
            # Per-mouse linear combination
            outputs = self.linear[mouse_id](inputs.permute(0, 2, 1)).squeeze(-1)
        else:
            raise NotImplementedError(f"Ensemble mode {self.ensemble_mode} not supported.")
        outputs = self.activation(outputs)
        return outputs


class EnsembleModel(nn.Module):
    """
    EnsembleModel handles multiple models with different configurations.
    It loads each model with its own saved arguments and combines their outputs.
    """

    def __init__(
        self,
        base_args: t.Any,
        saved_models: t.Dict[str, str],
        ds: t.Dict[str, DataLoader],
    ):
        super(EnsembleModel, self).__init__()
        self.verbose = base_args.verbose
        self.ensemble = nn.ModuleDict()
        self.input_shapes = {}
        self.behavior_modes = {}
        self.attention_types = {}
        self.use_MLP_flags = {}
        self.use_BMLP_flags = {}
        self.num_models = len(saved_models)

        for name, output_dir in saved_models.items():
            model_args = Args(base_args, output_dir)
            # Ensure that device is correctly set
            model_args.device = base_args.device
            model_args.output_dir = output_dir
            # Load the model
            model = Model(args=model_args, ds=ds)
            self.load_model_state(model, output_dir=model_args.output_dir)
            self.ensemble[name] = model
            self.input_shapes[name] = model_args.input_shape
            self.behavior_modes[name] = model_args.behavior_mode
            self.attention_types[name] = model_args.attention_type
            self.use_MLP_flags[name] = model_args.use_MLP
            self.use_BMLP_flags[name] = model_args.use_BMLP

        self.ensemble.requires_grad_(False)
        self.output_module = OutputModule(base_args, num_models=self.num_models)

    def load_model_state(
        self,
        model: nn.Module,
        output_dir: str,
        device: torch.device = torch.device("cpu"),
    ):
        filename = os.path.join(output_dir, "ckpt", "model_state.pt")
        assert os.path.exists(filename), f"Cannot find {filename}."
        ckpt = torch.load(filename, map_location=device)
        state_dict = model.state_dict()
        state_dict.update(ckpt["model"])
        model.load_state_dict(state_dict)
        if self.verbose:
            print(
                f"Loaded checkpoint from {output_dir} "
                f"(correlation: {ckpt['value']:.04f})."
            )

    def preprocess_input(self, inputs: torch.Tensor, target_shape: t.Tuple[int, ...]):
        # Implement resizing or other preprocessing as needed
        # For simplicity, assuming inputs are already in the correct shape
        return inputs  # Placeholder

    def adjust_behavior(self, behaviors: torch.Tensor, behavior_mode: int):
        # Adjust behaviors based on behavior_mode
        if behavior_mode == 0:
            return None  # No behavior input
        else:
            # Adjust behaviors accordingly
            return behaviors  # Placeholder

    def forward(
        self,
        inputs: torch.Tensor,
        mouse_id: str,
        behaviors: torch.Tensor,
        pupil_centers: torch.Tensor,
    ):
        ensemble_outputs = []
        for name, model in self.ensemble.items():
            model_input = self.preprocess_input(inputs, self.input_shapes[name])
            behavior_input = self.adjust_behavior(behaviors, self.behavior_modes[name])
            # Some models might not use pupil_centers
            # Adjust inputs as necessary
            outputs, _, _ = model(
                model_input,
                mouse_id=mouse_id,
                behaviors=behavior_input,
                pupil_centers=pupil_centers,
                activate=False,
            )
            ensemble_outputs.append(outputs)
        # Align outputs if necessary
        ensemble_outputs = self.align_outputs(ensemble_outputs)
        # Combine outputs
        ensemble = self.combine_outputs(ensemble_outputs, mouse_id)
        return ensemble, None, None

    def align_outputs(self, outputs_list: t.List[torch.Tensor]):
        # Implement alignment logic if outputs have different shapes
        # For simplicity, assuming outputs have the same shape
        return outputs_list  # Placeholder

    def combine_outputs(self, outputs_list: t.List[torch.Tensor], mouse_id: str):
        # Stack outputs along a new dimension
        outputs_stack = torch.stack(outputs_list, dim=-1)  # Shape: (batch_size, num_neurons, num_models)
        # Apply output module
        ensemble_output = self.output_module(outputs_stack, mouse_id=mouse_id)
        return ensemble_output

    def regularizer(self, mouse_id: str):
        return torch.tensor(0.0)


def fit_ensemble(
    args,
    model: EnsembleModel,
    optimizer: torch.optim.Optimizer,
    criterion: losses.Loss,
    scaler: GradScaler,
    scheduler: Scheduler,
    train_ds: t.Dict[str, DataLoader],
    val_ds: t.Dict[str, DataLoader],
    test_ds: t.Dict[str, DataLoader],
):
    summary = tensorboard.Summary(args)

    epoch = scheduler.restore()

    while (epoch := epoch + 1) < args.epochs + 1:
        if args.verbose:
            print(f"\nEpoch {epoch:03d}/{args.epochs:03d}")

        start = time()
        train_result = trainer.train(
            args,
            ds=train_ds,
            model=model,
            optimizer=optimizer,
            criterion=criterion,
            scaler=scaler,
            epoch=epoch,
            summary=summary,
        )
        val_result = trainer.validate(
            args,
            ds=val_ds,
            model=model,
            criterion=criterion,
            scaler=scaler,
            epoch=epoch,
            summary=summary,
        )
        elapse = time() - start

        summary.scalar("model/elapse", value=elapse, step=epoch, mode=0)
        summary.scalar(
            "model/learning_rate",
            value=optimizer.param_groups[0]["lr"],
            step=epoch,
            mode=0,
        )
        if args.verbose:
            print(
                f'Train\t\tloss: {train_result["loss"]:.04f}\t'
                f'correlation: {train_result["single_trial_correlation"]:.04f}\n'
                f'Validation\tloss: {val_result["loss"]:.04f}\t'
                f'correlation: {val_result["single_trial_correlation"]:.04f}\n'
                f"Elapse: {elapse:.02f}s"
            )
        early_stop = scheduler.step(val_result["single_trial_correlation"], epoch=epoch)
        if args.use_wandb:
            wandb.log(
                {
                    "train_loss": train_result["loss"],
                    "train_corr": train_result["single_trial_correlation"],
                    "val_loss": val_result["loss"],
                    "val_corr": val_result["single_trial_correlation"],
                    "best_corr": scheduler.best_value,
                    "elapse": elapse,
                },
                step=epoch,
            )
        if early_stop:
            break

    scheduler.restore()
    eval_result = utils.evaluate(
        args,
        ds=test_ds,
        model=model,
        epoch=epoch,
        summary=summary,
        mode=2,
        print_result=True,
        save_result=args.output_dir,
    )
    if args.use_wandb:
        wandb.log({"test_corr": eval_result["single_trial_correlation"]}, step=epoch)


def main(args):
    if args.clear_output_dir and os.path.isdir(args.output_dir):
        rmtree(args.output_dir)
    if not os.path.isdir(args.output_dir):
        os.makedirs(args.output_dir)

    Logger(args)
    utils.get_device(args)
    utils.set_random_seed(seed=args.seed)

    data.get_mouse_ids(args)

    args.micro_batch_size = args.batch_size
    train_ds, val_ds, test_ds = data.get_training_ds(
        args,
        data_dir=args.dataset,
        mouse_ids=args.mouse_ids,
        batch_size=args.batch_size,
        device=args.device,
    )

    if args.use_wandb:
        os.environ["WANDB_SILENT"] = "true"
        try:
            wandb.init(
                config=args,
                dir=os.path.join(args.output_dir, "wandb"),
                project="V1T",
                entity="7wikd",  # Replace with your WandB entity
                group=args.wandb_group,
                name=os.path.basename(args.output_dir),
            )
        except AssertionError as e:
            print(f"wandb.init error: {e}\n")
            args.use_wandb = False

    # Ensure args.saved_models is a dictionary mapping model names to output directories
    assert hasattr(args, "saved_models") and args.saved_models, "You must provide saved_models mapping"

    model = EnsembleModel(args, saved_models=args.saved_models, ds=train_ds)

    # Get model info
    mouse_id = args.mouse_ids[0]
    batch_size = args.micro_batch_size
    random_input = lambda size: torch.rand(*size)
    model_info = get_model_info(
        model=model,
        input_data={
            "inputs": random_input((batch_size, *next(iter(model.input_shapes.values())))),
            "behaviors": random_input((batch_size, 3)),
            "pupil_centers": random_input((batch_size, 2)),
        },
        mouse_id=mouse_id,
        filename=os.path.join(args.output_dir, "model.txt"),
    )
    if args.verbose > 2:
        print(str(model_info))
    if args.use_wandb:
        wandb.log({"trainable_params": model_info.trainable_params}, step=0)

    model.to(args.device)

    utils.save_args(args)

    if args.ensemble_mode == 0 and args.train:
        print(f"Cannot train ensemble model with average outputs")
        args.train = False  # Prevent training if ensemble_mode is 0

    criterion = losses.get_criterion(args, ds=train_ds)
    scaler = GradScaler(enabled=args.amp)
    if args.amp and args.verbose:
        print(f"Enable automatic mixed precision training.")
    if args.ensemble_mode:
        optimizer = torch.optim.AdamW(
            params=model.output_module.parameters(),
            lr=args.lr,
            betas=(args.adam_beta1, args.adam_beta2),
            eps=args.adam_eps,
            weight_decay=args.weight_decay,
        )
        scheduler = Scheduler(
            args,
            model=model,
            optimizer=optimizer,
            scaler=scaler,
            mode="max",
            module_names=["output_module"],
        )
        if args.train:
            fit_ensemble(
                args,
                model=model,
                optimizer=optimizer,
                criterion=criterion,
                scaler=scaler,
                scheduler=scheduler,
                train_ds=train_ds,
                val_ds=val_ds,
                test_ds=test_ds,
            )
        else:
            scheduler.restore()
    else:
        epoch = 0
        val_result = trainer.validate(
            args,
            ds=val_ds,
            model=model,
            criterion=criterion,
            scaler=scaler,
            epoch=epoch,
        )
        if args.verbose:
            print(
                f'Validation\tloss: {val_result["loss"]:.04f}\t'
                f'correlation: {val_result["single_trial_correlation"]:.04f}\n'
            )
        if args.use_wandb:
            wandb.log(
                {
                    "val_loss": val_result["loss"],
                    "val_corr": val_result["single_trial_correlation"],
                    "best_corr": val_result["single_trial_correlation"],
                },
                step=epoch,
            )

    test_ds, final_test_ds = data.get_submission_ds(
        args,
        data_dir=args.dataset,
        batch_size=args.batch_size,
        device=args.device,
    )

    # Create CSV dir to save results with timestamp Year-Month-Day-Hour-Minute
    timestamp = f"{datetime.now():%Y-%m-%d-%Hh%Mm}"
    csv_dir = os.path.join(args.output_dir, "submissions", timestamp)

    eval_result = utils.evaluate(
        args, ds=test_ds, model=model, print_result=True, save_result=csv_dir
    )
    if args.use_wandb:
        wandb.log({"test_corr": eval_result["single_trial_correlation"]}, step=0)

    if "sensorium" in args.dataset:
        if "S0" in test_ds:  # Sensorium challenge
            submission.generate_submission(
                args,
                mouse_id="S0",
                test_ds=test_ds,
                final_test_ds=final_test_ds,
                model=model,
                csv_dir=os.path.join(csv_dir, "sensorium"),
            )
        if "S1" in test_ds:  # Sensorium+ challenge
            submission.generate_submission(
                args,
                mouse_id="S1",
                test_ds=test_ds,
                final_test_ds=final_test_ds,
                model=model,
                csv_dir=os.path.join(csv_dir, "sensorium+"),
            )

    print(f"\nSubmission results saved to {csv_dir}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    # Dataset settings
    parser.add_argument(
        "--dataset",
        type=str,
        default="data/sensorium",
        help="Path to directory where the compressed dataset is stored.",
    )
    parser.add_argument("--output_dir", type=str, required=True)
    parser.add_argument(
        "--mouse_ids",
        nargs="+",
        type=str,
        default=None,
        help="Mouse IDs to use for training.",
    )
    parser.add_argument(
        "--behavior_mode",
        required=True,
        type=int,
        choices=[0, 1, 2, 3, 4],
        help="Behavior mode:"
        "0: do not include behavior"
        "1: concat behavior with natural image"
        "2: add latent behavior variables to each ViT block"
        "3: add latent behavior + pupil centers to each ViT block"
        "4: separate BehaviorMLP for each animal",
    )
    parser.add_argument(
        "--gray_scale", action="store_true", help="Convert colored image to gray-scale."
    )
    parser.add_argument(
        "--num_workers",
        default=2,
        type=int,
        help="Number of workers for DataLoader.",
    )

    # Training settings
    parser.add_argument(
        "--epochs",
        default=200,
        type=int,
        help="Maximum epochs to train the model.",
    )
    parser.add_argument("--batch_size", default=4, type=int)
    parser.add_argument(
        "--device",
        type=str,
        choices=["cpu", "cuda", "mps"],
        default="",
        help="Device to use for computation. "
        "Use the best available device if --device is not specified.",
    )
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument(
        "--amp", action="store_true", help="Automatic mixed precision training."
    )
    parser.add_argument(
        "--ensemble_mode",
        type=int,
        required=True,
        choices=[0, 1, 2],
        help="Ensemble method: "
        "0 - average the outputs of the ensemble models, "
        "1 - linear layer to connect the outputs from the ensemble models, "
        "2 - separate linear layer per animal.",
    )
    parser.add_argument(
        "--train",
        action="store_true",
        help="Train ensemble model before inference.",
    )

    # Optimizer settings
    parser.add_argument("--adam_beta1", type=float, default=0.9)
    parser.add_argument("--adam_beta2", type=float, default=0.9999)
    parser.add_argument("--adam_eps", type=float, default=1e-8)
    parser.add_argument("--lr", type=float, default=0.001)
    parser.add_argument(
        "--weight_decay",
        type=float,
        default=0.01,
        help="L2 weight decay coefficient.",
    )
    parser.add_argument(
        "--criterion",
        type=str,
        default="poisson",
        help="Criterion (loss function) to use.",
    )
    parser.add_argument(
        "--ds_scale",
        action="store_true",
        help="Scale loss by the size of the dataset.",
    )

    # Plot settings
    parser.add_argument(
        "--save_plots", action="store_true", help="Save plots to --output_dir."
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=120,
        help="Matplotlib figure DPI.",
    )
    parser.add_argument(
        "--format",
        type=str,
        default="svg",
        choices=["pdf", "svg", "png"],
        help="File format when --save_plots.",
    )

    # WandB settings
    parser.add_argument("--use_wandb", action="store_true")
    parser.add_argument("--wandb_group", type=str, default="")

    # Miscellaneous
    parser.add_argument(
        "--clear_output_dir",
        action="store_true",
        help="Overwrite content in --output_dir.",
    )
    parser.add_argument("--verbose", type=int, default=2, choices=[0, 1, 2, 3])

    # Additional arguments for saved models
    parser.add_argument(
        "--saved_models",
        type=str,
        nargs='+',
        required=True,
        help="List of paths to saved model directories.",
    )

    args = parser.parse_args()

    # Convert saved_models list to a dictionary
    # Assuming model names are the directory names
    args.saved_models = {os.path.basename(path): path for path in args.saved_models}

    main(args)
