"""Export-only MHA implementation with dynamic source/target sequence lengths.

The pinned VietOCR uses torch.nn.MultiheadAttention in PyTorch's
nn.Transformer. Legacy torch.onnx.export may specialize internal attention
Reshape nodes to the sample sequence length even when dynamic_axes is set.
This module replaces attention *only in a deepcopy used for ONNX export*.

Scope: eval-only, batch-first=False, same-size Q/K/V embeddings, no
key-padding mask, 2D additive self-attention mask or no attention mask,
need_weights=False, no extra K/V bias or zero-attention. Exact Unicode
output parity is still checked by check_vietocr_onnx_parity.py.
"""
from __future__ import annotations

import math

import torch
from torch import nn
from torch.nn import functional as F


class DynamicSequenceAttention(nn.Module):
    """Reference-weight attention with ONNX-traceable, dynamic Reshape."""

    def __init__(self, original: nn.MultiheadAttention) -> None:
        super().__init__()
        if (
            not original._qkv_same_embed_dim
            or original.batch_first
            or original.bias_k is not None
            or original.bias_v is not None
            or original.add_zero_attn
            or original.in_proj_weight is None
            or original.in_proj_bias is None
            or original.embed_dim != original.kdim
            or original.embed_dim != original.vdim
        ):
            raise ValueError("Unsupported MHA configuration; refuse ONNX export")
        # Preserve the exact pretrained/fine-tuned Parameter objects from the
        # export copy. Never initialize a new projection.
        # nn.TransformerEncoder/Decoder inspect these attributes before
        # calling the attention module, even in their non-fastpath branches.
        self.batch_first = original.batch_first
        self._qkv_same_embed_dim = original._qkv_same_embed_dim
        self.in_proj_weight = original.in_proj_weight
        self.in_proj_bias = original.in_proj_bias
        self.out_proj = original.out_proj
        self.embed_dim = original.embed_dim
        self.num_heads = original.num_heads
        self.head_dim = original.head_dim
        self.scale = 1.0 / math.sqrt(self.head_dim)

    def forward(
        self,
        query,
        key,
        value,
        key_padding_mask=None,
        need_weights=False,
        attn_mask=None,
        average_attn_weights=True,
        is_causal=False,
    ):
        if key_padding_mask is not None:
            raise ValueError("ONNX export refuses key_padding_mask")
        if need_weights:
            raise ValueError("ONNX export refuses need_weights=True")
        if is_causal and attn_mask is None:
            raise ValueError("ONNX export refuses implicit causal mask")
        if attn_mask is not None and (attn_mask.ndim != 2 or not attn_mask.is_floating_point()):
            raise ValueError("ONNX export only accepts a 2D additive attention mask")

        wq, wk, wv = self.in_proj_weight.chunk(3, dim=0)
        bq, bk, bv = self.in_proj_bias.chunk(3, dim=0)

        def split_heads(x, weight, bias):
            projected = F.linear(x, weight, bias)
            # x.shape[0] and x.shape[1] are symbolic to ONNX tracing.
            # Do not cast sequence length to Python int; that was the cause
            # of the fixed sequence Reshape encountered on Windows.
            return projected.reshape(
                projected.shape[0], projected.shape[1], self.num_heads, self.head_dim
            ).permute(1, 2, 0, 3)

        q = split_heads(query, wq, bq)
        k = split_heads(key, wk, bk)
        v = split_heads(value, wv, bv)

        attention = torch.matmul(q, k.transpose(2, 3)) * self.scale
        if attn_mask is not None:
            attention = attention + attn_mask.unsqueeze(0).unsqueeze(0)
        attention = torch.softmax(attention, dim=-1)
        context = torch.matmul(attention, v)
        context = context.permute(2, 0, 1, 3).reshape(
            query.shape[0], query.shape[1], self.embed_dim
        )
        return self.out_proj(context), None


def replace_attention_for_export(module: nn.Module) -> int:
    """Replace MHA recursively in an export copy; return replacement count."""
    count = 0
    for name, child in list(module.named_children()):
        if isinstance(child, nn.MultiheadAttention):
            module.add_module(name, DynamicSequenceAttention(child))
            count += 1
        else:
            count += replace_attention_for_export(child)
    return count
