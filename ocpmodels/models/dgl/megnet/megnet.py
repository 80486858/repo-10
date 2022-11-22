"""
Implementation of MEGNet model.

Code attributions to https://github.com/materialsvirtuallab/m3gnet-dgl/tree/main/megnet,
along with contributions and modifications from Marcel Nassar, Santiago Miret, and Kelvin Lee
"""
from typing import Optional

import dgl
import torch
from torch import nn
from dgl.nn import Set2Set
from torch.nn import Dropout, Identity, Module, ModuleList, Softplus

from ocpmodels.models.dgl.megnet import MLP, MEGNetBlock, EdgeSet2Set


class MEGNet(Module):
    """
    DGL implementation of MEGNet.
    """

    def __init__(
        self,
        in_dim: int,
        num_blocks: int,
        hiddens: list[int],
        conv_hiddens: list[int],
        s2s_num_layers: int,
        s2s_num_iters: int,
        output_hiddens: list[int],
        is_classification: bool = True,
        node_embed: Optional[nn.Module] = None,
        edge_embed: Optional[nn.Module] = None,
        attr_embed: Optional[nn.Module] = None,
        dropout: Optional[float] = None,
    ) -> None:
        """
        TODO: Add docs.
        :param in_dim:
        :param num_blocks:
        :param hiddens:
        :param conv_hiddens:
        :param s2s_num_layers:
        :param s2s_num_iters:
        :param output_hiddens:
        :param is_classification:
        :param node_embed:
        :param edge_embed:
        :param attr_embed:
        :param dropout:
        """
        super().__init__()

        self.edge_embed = edge_embed if edge_embed else Identity()
        self.node_embed = node_embed if node_embed else Identity()
        self.attr_embed = attr_embed if attr_embed else Identity()

        dims = [in_dim] + hiddens
        self.edge_encoder = MLP(dims, Softplus(), activate_last=True)
        self.node_encoder = MLP(dims, Softplus(), activate_last=True)
        self.attr_encoder = MLP(dims, Softplus(), activate_last=True)

        blocks_in_dim = hiddens[-1]
        block_out_dim = conv_hiddens[-1]
        block_args = dict(conv_hiddens=conv_hiddens, dropout=dropout, skip=True)
        blocks = []
        from .layers import MEGNetBlock

        # first block
        blocks.append(MEGNetBlock(dims=[blocks_in_dim], **block_args))  # type: ignore
        # other blocks
        for _ in range(num_blocks - 1):
            blocks.append(MEGNetBlock(dims=[block_out_dim] + hiddens, **block_args))  # type: ignore
        self.blocks = ModuleList(blocks)

        s2s_kwargs = dict(n_iters=s2s_num_iters, n_layers=s2s_num_layers)
        self.edge_s2s = EdgeSet2Set(block_out_dim, **s2s_kwargs)
        self.node_s2s = Set2Set(block_out_dim, **s2s_kwargs)

        self.output_proj = MLP(
            # S2S cats q_star to output producing double the dim
            dims=[2 * 2 * block_out_dim + block_out_dim] + output_hiddens + [1],
            activation=Softplus(),
            activate_last=False,
        )

        self.dropout = Dropout(dropout) if dropout else None
        # TODO(marcel): should this be an 1D dropout

        self.is_classification = is_classification

    def forward(
        self,
        graph: dgl.DGLGraph,
        edge_feat: torch.Tensor,
        node_feat: torch.Tensor,
        graph_attr: torch.Tensor,
    ) -> None:
        """
        TODO: Add docs.
        :param graph:
        :param edge_feat:
        :param node_feat:
        :param graph_attr:
        :return:
        """

        edge_feat = self.edge_encoder(self.edge_embed(edge_feat))
        node_feat = self.node_encoder(self.node_embed(node_feat))
        graph_attr = self.attr_encoder(self.attr_embed(graph_attr))

        for block in self.blocks:
            output = block(graph, edge_feat, node_feat, graph_attr)
            edge_feat, node_feat, graph_attr = output

        node_vec = self.node_s2s(graph, node_feat)
        edge_vec = self.edge_s2s(graph, edge_feat)

        vec = torch.hstack([node_vec, edge_vec, graph_attr])

        if self.dropout:
            vec = self.dropout(vec)  # pylint: disable=E1102

        output = self.output_proj(vec)
        if self.is_classification:
            output = torch.sigmoid(output)

        return output
