class EmptyConditioningCheck:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "optional": {
                "conditioning1": ("CONDITIONING",),
                "conditioning2": ("CONDITIONING",),
            },
        }

    RETURN_TYPES = ("CONDITIONING",)
    RETURN_NAMES = ("conditioning",)
    FUNCTION = "emptyConditioningCheck"
    CATEGORY = "EimissLoaders/utils"
    DESCRIPTION = "conditioning1 and conditioning2 are both optional: returns conditioning1 when it is not empty, otherwise returns conditioning2."
    OUTPUT_NODE = True

    def emptyConditioningCheck(self, conditioning1=None, conditioning2=None):
        if conditioning1 is not None:
            return (conditioning1,)
        elif conditioning2 is not None:
            return (conditioning2,)
        else:
            return (None,)