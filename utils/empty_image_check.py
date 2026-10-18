class EmptyImageCheck:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "optional": {
                "images1": ("IMAGE",),
                "images2": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "emptyImageCheck"
    CATEGORY = "EimissLoaders/utils"
    DESCRIPTION = "images1 and images2 are both optional: returns images1 when it is not empty, otherwise returns images2."
    OUTPUT_NODE = True

    def emptyImageCheck(self, images1=None, images2=None):
        if images1 is not None:
            return (images1,)
        elif images2 is not None:
            return (images2,)
        else:
            return (None,)