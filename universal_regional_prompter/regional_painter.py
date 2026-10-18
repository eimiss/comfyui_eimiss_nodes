import base64
import binascii
import io

import numpy as np
import torch
from PIL import Image, UnidentifiedImageError

from .regional_prompter import MAX_REGIONS


def decode_paint_data(paint_data):
    if not paint_data:
        return None
    try:
        if "," in paint_data:
            paint_data = paint_data.split(",", 1)[1]
        img = Image.open(io.BytesIO(base64.b64decode(paint_data)))
        if img.mode != "RGB":
            img = img.convert("RGB")
        return torch.from_numpy(np.array(img)).float() / 255.0
    except (binascii.Error, UnidentifiedImageError, ValueError):
        raise ValueError("RegionalPainter: the painted canvas data is invalid. Repaint the regions in the canvas.")


class RegionalPainter:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "width": ("INT", {"default": 1024, "min": 64, "max": 2048, "step": 8}),
                "height": ("INT", {"default": 1024, "min": 64, "max": 2048, "step": 8}),
                "regions": ("INT", {"default": 2, "min": 2, "max": MAX_REGIONS, "step": 1}),
                "paint_data": ("STRING", {"default": "", "multiline": False}),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT")
    RETURN_NAMES = ("region_map", "regions")
    FUNCTION = "paint"
    CATEGORY = "EimissLoaders/universal regional prompter"

    def paint(self, width, height, regions, paint_data=""):
        img = decode_paint_data(paint_data)
        if img is None:
            img = torch.zeros((height, width, 3), dtype=torch.float32)
        elif img.shape[:2] != (height, width):
            img = torch.nn.functional.interpolate(
                img.permute(2, 0, 1).unsqueeze(0), size=(height, width), mode="nearest-exact"
            ).squeeze(0).permute(1, 2, 0)
        return (img.unsqueeze(0), regions)