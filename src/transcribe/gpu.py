"""GPU 記憶體管理工具。

8GB VRAM 下，轉錄模型、對齊模型、pyannote 分辨模型無法同時常駐，
每個階段用完都要顯式釋放，否則下一階段會 CUDA OOM。
"""

from __future__ import annotations

import gc


def ensure_cuda(device: str) -> None:
    """device 指定為 cuda 時，確認 torch 真的有 CUDA，否則給友善錯誤。

    避免裝到 CPU 版 torch 時拋出難懂的 ``AssertionError: Torch not compiled
    with CUDA enabled`` 深層 traceback。
    """
    if not device.startswith("cuda"):
        return
    from .errors import CudaUnavailableError, ToolMissingError

    try:
        import torch
    except ImportError as exc:  # pragma: no cover
        raise ToolMissingError(
            "torch is not installed",
            hint="尚未安裝 torch，請依 README 安裝相依。",
        ) from exc

    if not torch.cuda.is_available():
        raise CudaUnavailableError(
            f"CUDA not available (torch={torch.__version__})",
            hint=(
                "torch 偵測不到 CUDA。多半是裝到 CPU 版 torch。請重裝 CUDA 版："
                "uv pip install --reinstall-package torch --reinstall-package torchaudio "
                "torch torchaudio --torch-backend=auto；或改用 --device cpu（會很慢）。"
            ),
        )


def free_gpu(*objs: object) -> None:
    """刪除傳入的模型物件並清空 CUDA 快取。

    用法：``free_gpu(model, align_model)``。即使 torch 未安裝（測試環境）
    也不會出錯，方便離線 mock 測試。
    """
    for obj in objs:
        del obj
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass
