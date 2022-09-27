from .readout import register, Readout

import torch
import numpy as np
from torch import nn
from torch.utils.data import DataLoader


@register("linear")
class LinearReadout(Readout):
    def __init__(
        self,
        input_shape: tuple,
        output_shape: tuple,
        ds: DataLoader,
        name: str = "LinearReadout",
    ):
        super(LinearReadout, self).__init__(
            input_shape=input_shape, output_shape=output_shape, ds=ds, name=name
        )

        self.linear = nn.Sequential(
            nn.Flatten(),
            nn.Linear(
                in_features=int(np.prod(input_shape)), out_features=self.num_neurons
            ),
        )

    def forward(self, inputs: torch.Tensor):
        return self.linear(inputs)