import logging
import re

import torch

from .full_image import attach_full_image_sampling, feather_region_mask

MAX_REGIONS = 10

# Keep in sync with REGION_COLORS in js/regional_painter.js
REGION_COLORS = [
    (0.133, 0.588, 0.953),  # 1 blue
    (0.298, 0.686, 0.314),  # 2 green
    (0.957, 0.263, 0.212),  # 3 red
    (1.000, 0.922, 0.231),  # 4 yellow
    (0.878, 0.251, 0.984),  # 5 magenta
    (0.000, 0.737, 0.831),  # 6 cyan
    (1.000, 0.596, 0.000),  # 7 orange
    (0.612, 0.153, 0.690),  # 8 purple
    (0.804, 0.863, 0.224),  # 9 lime
    (1.000, 0.502, 0.671),  # 10 pink
]

_BREAK_RE = re.compile(r"\bBREAK\b", re.IGNORECASE)
_UNPAINTED_DIST_SQ = 0.15
# mask bounds: the last 60% of the steps re-render the whole image with the complete prompt to merge the regions.
_MASK_BOUNDS_MERGE = 0.6


def split_prompt_breaks(prompt):
    parts = []
    for part in _BREAK_RE.split(prompt):
        part = part.strip()
        if part:
            parts.append(part)
    return parts


def region_ids_from_map(region_map, num_regions):
    flat = region_map.reshape(-1, 3)
    best_dist = torch.full((flat.shape[0],), float("inf"), dtype=torch.float32, device=region_map.device)
    best_id = torch.zeros((flat.shape[0],), dtype=torch.long, device=region_map.device)
    # Match the full palette so leftover paint of removed regions can't snap to a kept color.
    for i, rgb in enumerate(REGION_COLORS):
        color = torch.tensor(rgb, dtype=region_map.dtype, device=region_map.device)
        dist = (flat - color).pow(2).sum(-1)
        closer = dist < best_dist
        best_id[closer] = i + 1
        best_dist[closer] = dist[closer]
    best_id[(best_dist > _UNPAINTED_DIST_SQ) | (best_id > num_regions)] = 0
    return best_id.reshape(region_map.shape[0], region_map.shape[1])


class RegionalPrompter:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clip": ("CLIP",),
                "positive_prompt": ("STRING", {
                    "forceInput": True,
                    "multiline": True,
                    "tooltip": "Prompt with BREAK-separated regions.",
                }),
                "prepend_base_to_regions": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "First BREAK section is prepended to every region prompt.",
                }),
                "regions": ("INT", {
                    "forceInput": True,
                    "tooltip": "Region count from the RegionalPainter 'regions' output.",
                }),
                "strength": ("FLOAT", {
                    "default": 0.5,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.05,
                    "tooltip": "Region strength: 1.0 = only the region prompt inside a region; lower values blend the base prompt back in. Ignored when there is no base prompt.",
                }),
                "cond_area": (["mask bounds", "full image"], {
                    "tooltip": "mask bounds (default): samples each region as a crop of one image (faster); the last 60% of the steps merge the regions with the complete prompt. full image: generates every region as a complete image, fits it into its region, then re-renders the whole image, keeping region centers and redrawing their edges and the background.",
                }),
            },
            "optional": {
                "negative_prompt": ("STRING", {
                    "forceInput": True,
                    "multiline": True,
                    "tooltip": "Optional negative prompt; BREAK gives it the same regions.",
                }),
                "region_map": ("IMAGE", {
                    "tooltip": "Region map from the RegionalPainter or an editor.",
                }),
            },
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING")
    RETURN_NAMES = ("positive", "negative")
    FUNCTION = "encode"
    CATEGORY = "EimissLoaders/universal regional prompter"

    def encode(self, clip, positive_prompt, prepend_base_to_regions, regions, strength, cond_area,
               negative_prompt="", region_map=None):
        positive_prompt = (positive_prompt or "").strip()
        if not positive_prompt:
            raise ValueError("RegionalPrompter: connect a positive prompt from another node.")
        if region_map is None:
            raise ValueError(
                "RegionalPrompter: no region map connected. Paint the regions in the RegionalPainter node "
                "(or an external editor) and connect its image output here."
            )

        negative_prompt = (negative_prompt or "").strip()
        ids = region_ids_from_map(region_map[0], regions)
        set_area_to_bounds = cond_area == "mask bounds"
        # full image does its own re-render instead of the merge.
        merge = _MASK_BOUNDS_MERGE if set_area_to_bounds else 0.0

        positive, region_conds = self._encode_prompt(clip, positive_prompt, prepend_base_to_regions, regions, strength,
                                                     merge, set_area_to_bounds, ids)
        negative, _ = self._encode_prompt(clip, negative_prompt, prepend_base_to_regions, regions, strength, merge,
                                          set_area_to_bounds, ids)
        if not set_area_to_bounds and region_conds:
            negative_base = [c for c in negative if c[1].get("default")]
            positive = attach_full_image_sampling(positive, negative_base, region_conds)
        return (positive, negative)

    def _encode_prompt(self, clip, prompt, prepend_base, regions, strength, merge, set_area_to_bounds, ids):
        parts = split_prompt_breaks(prompt)
        if len(parts) <= 1:
            return self._add_values(clip, ", ".join(parts), {"default": True}), []
        if prepend_base:
            base_text = parts[0]
            region_texts = parts[1:]
        else:
            base_text = ""
            region_texts = parts
        if not region_texts:
            raise ValueError("RegionalPrompter: no region prompts found. Add BREAK separated prompts.")
        if len(region_texts) != regions:
            base_note = " (the first BREAK section is the base prompt while prepend_base_to_regions is on)" if prepend_base else ""
            raise ValueError(
                f"RegionalPrompter: prompt has {len(region_texts)} regions{base_note} but the painter has {regions}. "
                "Set the painter's region count to match, or add/remove BREAK sections."
            )

        # The base prompt covers the unpainted areas; inside a region it is prepended
        # to that region's prompt instead, since the sampler cancels the base there.
        # Without a base prompt there is nothing to blend, so `strength` is ignored.
        base_values = {"default": True}
        region_values = {"mask_strength": strength if base_text else 1.0, "set_area_to_bounds": set_area_to_bounds}
        merge_from = 1.0 - merge
        if merge > 0.0:
            # Regions and base stop at merge_from; from there on the whole prompt takes
            # over and re-renders the image as one, like a KSampler denoise pass.
            base_values["end_percent"] = merge_from
            region_values["end_percent"] = merge_from
        cond = self._add_values(clip, base_text, base_values)
        region_conds = []
        for i, text in enumerate(region_texts, start=1):
            mask = (ids == i).to(torch.float32).unsqueeze(0)
            if torch.max(mask) == 0.0:
                logging.warning(f"RegionalPrompter: region {i} has no painted pixels, skipping its prompt.")
                continue
            region_prompt = f"{base_text}, {text}" if base_text else text
            region = self._add_values(clip, region_prompt, {})
            cond_mask = feather_region_mask(mask) if set_area_to_bounds else mask
            cond.extend([[emb, {**extra, **region_values, "mask": cond_mask}] for emb, extra in region])
            region_conds.append((region, mask))
        if merge > 0.0:
            cond.extend(self._add_values(clip, ", ".join(parts), {"start_percent": merge_from}))
        return cond, region_conds

    # Keeps every entry returned by the text encoder (some models schedule several)
    # and adds the extra conditioning values to each of them.
    def _add_values(self, clip, text, values):
        return [[emb, {**extra, **values}] for emb, extra in clip.encode_from_tokens_scheduled(clip.tokenize(text))]