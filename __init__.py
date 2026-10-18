WEB_DIRECTORY = "./js"

from .universal_model_loader import UniversalModelLoader
from .utils.empty_image_check import EmptyImageCheck
from .utils.empty_conditioning_check import EmptyConditioningCheck
from .universal_regional_prompter.regional_prompter import RegionalPrompter
from .universal_regional_prompter.regional_painter import RegionalPainter
from .universal_regional_prompter.mask_bounds import apply_mask_bounds_patch
from .universal_regional_prompter.full_image import apply_full_image_patch

apply_mask_bounds_patch()
apply_full_image_patch()

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
]

NODE_CLASS_MAPPINGS = {
    "UniversalModelLoader": UniversalModelLoader,
    "EmptyImageChecker": EmptyImageCheck,
    "EmptyConditioningChecker": EmptyConditioningCheck,
    "RegionalPrompter": RegionalPrompter,
    "RegionalPainter": RegionalPainter,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "UniversalModelLoader": "Universal Model Loader",
    "EmptyImageChecker": "Empty Image Checker",
    "EmptyConditioningChecker": "Empty Conditioning Checker",
    "RegionalPrompter": "Regional Prompter",
    "RegionalPainter": "Regional Painter",
}