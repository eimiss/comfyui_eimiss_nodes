import comfy.sd
import folder_paths


class UniversalModelLoader:

    @classmethod
    def INPUT_TYPES(cls):
        checkpoints = folder_paths.get_filename_list("checkpoints")
        clips = folder_paths.get_filename_list("clip")
        vaes = folder_paths.get_filename_list("vae")
        return {
            "required": {
                "checkpoint": (
                    checkpoints,
                ),
            },
            "optional": {
                "clip_override": (
                    ["None"] + clips,
                ),
                "vae_override": (
                    ["None"] + vaes,
                ),
            }
        }

    RETURN_TYPES = ("MODEL", "CLIP", "VAE")
    RETURN_NAMES = ("model", "clip", "vae")
    FUNCTION = "load"
    CATEGORY = "EimissLoaders"


    def load(self, checkpoint, clip_override="None", vae_override="None"):
        ckpt_path = folder_paths.get_full_path("checkpoints", checkpoint)

        # Load checkpoint
        model, clip, vae, _ = comfy.sd.load_checkpoint_guess_config(ckpt_path, output_vae=True, output_clip=True)

        # Replace CLIP if selected
        if clip_override != "None":
            clip_path = folder_paths.get_full_path("clip", clip_override)
            # Match the text encoder type to the checkpoint's model family, like CLIPLoader's "type".
            image_model = model.model.model_config.unet_config.get("image_model", "")
            clip_type = getattr(comfy.sd.CLIPType, image_model.upper(), comfy.sd.CLIPType.STABLE_DIFFUSION)
            clip = comfy.sd.load_clip(ckpt_paths=[clip_path], embedding_directory=folder_paths.get_folder_paths("embeddings"), clip_type=clip_type)

        # Replace VAE if selected
        if vae_override != "None":
            vae_path = folder_paths.get_full_path("vae", vae_override)
            sd = comfy.utils.load_torch_file(vae_path)
            vae = comfy.sd.VAE(sd=sd)
        return (model, clip, vae)
