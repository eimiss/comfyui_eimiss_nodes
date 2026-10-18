import math

import torch

import comfy.sample
import comfy.sampler_helpers
import comfy.samplers
import comfy.utils

# Region denoise: 1.0 at the edge, down by _BAND_STEP per band over the outer _FADE_DEPTH of its depth, then _CORE_DENOISE.
_CORE_DENOISE = 0.5
_BAND_STEP = 0.1
_FADE_DEPTH = 0.5
_LEVELS = round((1.0 - _CORE_DENOISE) / _BAND_STEP)
# Neighbouring region prompts blend across a border over this many outer bands on each side.
_BLEND_BANDS = 2
_PLAN_KEY = "eimiss_full_image"


def _latent_box(mask, height, width):
    # (y, x, h, w) of the mask's bounding box in latent pixels.
    rows = mask[0].any(dim=1).nonzero()
    cols = mask[0].any(dim=0).nonzero()
    mask_h, mask_w = mask.shape[-2:]
    y0 = int(rows[0]) * height // mask_h
    x0 = int(cols[0]) * width // mask_w
    y1 = -(-(int(rows[-1]) + 1) * height // mask_h)
    x1 = -(-(int(cols[-1]) + 1) * width // mask_w)
    return y0, x0, y1 - y0, x1 - x0


def _full_size(box_h, box_w, height, width):
    # The box's aspect ratio at the pixel count of the whole latent, in multiples of 8.
    scale = math.sqrt(height * width / (box_h * box_w))
    return max(8, round(box_h * scale / 8) * 8), max(8, round(box_w * scale / 8) * 8)


def _edge_distance(mask):
    # Pixels from each masked pixel to the region's edge (1 on the edge, 0 outside); image borders are not edges.
    inside = mask > 0.5
    distance = torch.zeros(mask.shape)
    while inside.any():
        distance += inside
        inside = -torch.nn.functional.max_pool2d(-inside.float(), 3, stride=1, padding=1) > 0.5
    return distance


def _region_denoise(distance, band):
    stepped = (1.0 - _BAND_STEP * torch.floor((distance - 1) / band)).clamp(min=_CORE_DENOISE)
    return torch.where(distance > 0, stepped, 1.0)


def _band(distance):
    return _FADE_DEPTH * float(distance.max()) / _LEVELS


def _feather(mask, band):
    # 0.5 on the region's edge, ramping to 1 inside and 0 outside over _BLEND_BANDS bands; image borders stay hard.
    radius = max(1, round(_BLEND_BANDS * band))
    return torch.nn.functional.avg_pool2d((mask > 0.5).float(), 2 * radius + 1, stride=1, padding=radius, count_include_pad=False)


def feather_region_mask(mask):
    # Mask bounds: the region mask at 1/8 size (about latent size), feathered so neighbouring crops overlap and blend.
    small = torch.nn.functional.avg_pool2d(mask.unsqueeze(1), 8)
    return _feather(small, _band(_edge_distance(small)))[0]


def attach_full_image_sampling(positive, negative, regions):
    # A plain cond value instead of a cond hook: hooks make ComfyUI drop the dynamic VRAM model.
    plan = (negative, regions)
    return [[emb, {**extra, _PLAN_KEY: plan}] for emb, extra in positive]


def _sample_full_image(outer_sample, guider, plan, noise, latent_image, sampler, sigmas, denoise_mask, callback,
                       disable_pbar, seed, latent_shapes):
    # Region images fitted into their regions, then a full re-render that is held back at region centers.
    negative, regions = plan
    regional = guider.conds
    steps = len(sigmas) - 1
    # The passes run up to where region centers get released; ending on 0 returns a clean, shrinkable image.
    pass_sigmas = sigmas[:steps - round(steps * _CORE_DENOISE) + 1].clone()
    pass_sigmas[-1] = 0.0

    def sample(cond, noise, latent, mask, shapes):
        guider.conds = {"positive": comfy.sampler_helpers.convert_cond(cond),
                        "negative": comfy.sampler_helpers.convert_cond(negative)}
        return outer_sample(noise, latent, sampler, pass_sigmas, mask, callback, disable_pbar, seed, latent_shapes=shapes)

    # The background starts from full noise in the re-render, so the regions are fitted onto the input latent.
    out = latent_image.clone()
    height, width = out.shape[-2:]
    strength = torch.ones((1, 1, height, width))
    feathered = {}
    for i, (cond, mask) in enumerate(regions, start=1):
        y, x, box_h, box_w = _latent_box(mask, height, width)
        shape = noise.shape[:-2] + _full_size(box_h, box_w, height, width)
        empty = torch.zeros(shape)
        image = sample(cond, comfy.sample.prepare_noise(empty, seed + i), empty, None, [shape])
        image = comfy.utils.common_upscale(image, box_w, box_h, "area", "disabled")
        weight = comfy.utils.common_upscale(mask.unsqueeze(1), width, height, "bilinear", "disabled")
        distance = _edge_distance(weight)
        band = _band(distance)
        strength = torch.minimum(strength, _region_denoise(distance, band))
        feathered[id(mask)] = _feather(weight, band)[0]
        weight = weight[..., y:y + box_h, x:x + box_w].reshape((1,) * (out.ndim - 2) + (box_h, box_w))
        target = out[..., y:y + box_h, x:x + box_w]
        target.lerp_(image.to(target), weight.to(target))

    strength = strength.reshape((1,) * (out.ndim - 2) + (height, width)).to(guider.model_patcher.load_device)
    if denoise_mask is not None:
        strength = strength * denoise_mask
    schedule = sigmas.tolist()

    def release(sigma, mask, extra_options):
        # A pixel stays on the fitted image until the schedule reaches its own denoise.
        step = min(range(steps + 1), key=lambda i: abs(schedule[i] - float(sigma[0])))
        return (mask >= (steps - step - 0.5) / steps).to(mask.dtype)

    guider.model_options["denoise_mask_function"] = release
    # Region prompts cross-fade over each border instead of switching at a hard line.
    guider.conds = {k: [{**c, "mask": feathered[id(c["mask"])]} if id(c.get("mask")) in feathered else c for c in v]
                    for k, v in regional.items()}
    return outer_sample(noise, out, sampler, sigmas, strength, callback, disable_pbar, seed, latent_shapes=latent_shapes)


# Runs the full image plan in any guider whose positive conditioning carries it; other samplings are untouched.
def apply_full_image_patch():
    original = comfy.samplers.CFGGuider.outer_sample
    if getattr(original, "_eimiss_full_image_patch", False):
        return

    def outer_sample(self, noise, latent_image, sampler, sigmas, denoise_mask=None, callback=None, disable_pbar=False,
                     seed=None, latent_shapes=None):
        plan = next((c[_PLAN_KEY] for c in self.conds.get("positive", []) if _PLAN_KEY in c), None)
        # Partial denoise (img2img, detailers): only the regional conditioning applies.
        if plan is None or float(sigmas[0]) < float(self.model_patcher.get_model_object("model_sampling").sigma_max) * (1 - 1e-5):
            return original(self, noise, latent_image, sampler, sigmas, denoise_mask, callback, disable_pbar, seed,
                            latent_shapes=latent_shapes)
        return _sample_full_image(original.__get__(self), self, plan, noise, latent_image, sampler, sigmas, denoise_mask,
                                  callback, disable_pbar, seed, latent_shapes)

    outer_sample._eimiss_full_image_patch = True
    comfy.samplers.CFGGuider.outer_sample = outer_sample
