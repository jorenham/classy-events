__all__ = ["TypeMROMap"]

import collections
import typing

KT_co = typing.TypeVar("KT_co", covariant=True)
VT = typing.TypeVar("VT")


class TypeMROMap(
    typing.Generic[KT_co, VT],
    collections.defaultdict,
    typing.Mapping[typing.Type[KT_co], typing.Mapping[str, VT]],
):
    """
    A defaultdict of chainmaps where the keys are types. The default value is
    a chainmap child of the closest mro parent of the type, or a new chainmap.

    Assumes that the types (i.e. keys) are inserted in reverse mro order.
    """

    def __init__(self, **kwargs):
        super().__init__(collections.ChainMap, **kwargs)

    def __missing__(self, cls: typing.Type[KT_co]):
        for base in cls.mro()[1:]:
            if base in self:
                self[cls] = self[base].new_child()
                break
        else:
            self[cls] = collections.ChainMap()

        return self[cls]
