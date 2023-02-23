from .core import register, Core

import torch
import typing as t
from torch import nn

from v1t.models import utils


@register("conv")
class ConvCore(Core):
    def __init__(
        self,
        args,
        input_shape: t.Tuple[int, int, int],
        kernel_size: int = 3,
        stride: int = 2,
        name: str = "ConvCore",
    ):
        super(ConvCore, self).__init__(args, input_shape=input_shape, name=name)
        self.register_buffer("reg_scale", torch.tensor(args.core_reg_scale))

        output_shape = input_shape
        self.conv_block1 = nn.Sequential(
            nn.Conv2d(
                in_channels=input_shape[0],
                out_channels=args.num_filters,
                kernel_size=kernel_size,
                stride=stride,
            ),
            nn.InstanceNorm2d(num_features=args.num_filters),
            nn.GELU(),
            nn.Dropout2d(p=args.dropout),
        )
        output_shape = utils.conv2d_shape(
            output_shape,
            num_filters=args.num_filters,
            kernel_size=kernel_size,
            stride=stride,
        )

        stride = 1
        self.conv_block2 = nn.Sequential(
            nn.Conv2d(
                in_channels=output_shape[0],
                out_channels=args.num_filters * 2,
                kernel_size=kernel_size,
                stride=stride,
            ),
            nn.InstanceNorm2d(num_features=args.num_filters),
            nn.GELU(),
            nn.Dropout2d(p=args.dropout),
        )
        output_shape = utils.conv2d_shape(
            output_shape,
            num_filters=args.num_filters * 2,
            kernel_size=kernel_size,
            stride=stride,
        )

        self.conv_block3 = nn.Sequential(
            nn.Conv2d(
                in_channels=output_shape[0],
                out_channels=args.num_filters * 3,
                kernel_size=kernel_size,
                stride=stride,
            ),
            nn.InstanceNorm2d(num_features=args.num_filters),
            nn.GELU(),
            nn.Dropout2d(p=args.dropout),
        )
        output_shape = utils.conv2d_shape(
            output_shape,
            num_filters=args.num_filters * 3,
            kernel_size=kernel_size,
            stride=stride,
        )

        self.output_shape = output_shape

    def regularizer(self):
        """L1 regularization"""
        return self.reg_scale * sum(p.abs().sum() for p in self.parameters())

    def forward(self, inputs: torch.Tensor):
        outputs = self.conv_block1(inputs)
        outputs = self.conv_block2(outputs)
        outputs = self.conv_block3(outputs)
        return outputs