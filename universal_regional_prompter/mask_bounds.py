import comfy.samplers


def _dim_fractions(mask, num_dims):
    # Fractional (offset, size) of the mask's non-empty area for each spatial dim.
    spatial = mask if mask.ndim == num_dims else mask[0]
    fractions = []
    for d in range(num_dims):
        reduce_dims = tuple(j for j in range(spatial.ndim) if j != d)
        projection = spatial != 0
        if reduce_dims:
            projection = projection.any(dim=reduce_dims)
        indices = projection.flatten().nonzero()
        if indices.numel() == 0:
            return None
        low = int(indices.min())
        high = int(indices.max())
        denom = max(1, spatial.shape[d])
        fractions.append((low / denom, (high - low + 1) / denom))
    return fractions


def _area_from_mask(cond, num_dims):
    fractions = _dim_fractions(cond["mask"], num_dims)
    if fractions is None:
        cond["area"] = ("percentage",) + (0.0,) * num_dims * 2
    else:
        cond["area"] = ("percentage",) + tuple(size for _, size in fractions) + tuple(offset for offset, _ in fractions)
    cond["set_area_to_bounds"] = False


# ComfyUI implements "mask bounds" only for 2D latents
# and crashes for 3D-latent models like Wan/anima. This turns the mask into a
# percentage area for those ranks, so the same mask-bounds behavior works there too.
def apply_mask_bounds_patch():
    original = comfy.samplers.resolve_areas_and_cond_masks_multidim
    if getattr(original, "_eimiss_multidim_patch", False):
        return

    def resolve_areas_and_cond_masks_multidim(conditions, dims, device):
        if len(dims) != 2:
            for cond in conditions:
                if cond.get("set_area_to_bounds", False) and "mask" in cond:
                    _area_from_mask(cond, len(dims))
        return original(conditions, dims, device)

    resolve_areas_and_cond_masks_multidim._eimiss_multidim_patch = True
    comfy.samplers.resolve_areas_and_cond_masks_multidim = resolve_areas_and_cond_masks_multidim
